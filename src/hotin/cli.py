"""The command dispatcher and safe terminal renderers for hotin."""

import argparse
import contextlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from . import __version__, board, engine, health, render_board, schedule
from .cache import MemoryCache, open_cache
from .canonical import canonicalize
from .coerce import finite_float, finite_int
from .config import config_dir, env_path, load_config
from .render import color, hyperlink, sanitize
from .sources import (frontier, github, hfmodels, hfpapers, hn,
                      insiders, npm, trends, collections, reddit, smolai, youtube)


# Entities (the nouns, each self-ranked) + MANAGE verbs. The raw single-source
# feeds (hn/npm/stars/trending/reddit/youtube) are NOT commands — they are
# `repos --source <name>` values. `refresh` replaces the old ingest+update.
COMMANDS = {
    "repos": "trending AI repos — the flagship board (default)",
    "rising": "brand-new repos climbing fastest (velocity, not lifetime size)",
    "insiders": "repos the AI Insiders are backing (the smart-money signal)",
    "models": "AI models — frontier-lab press releases + trending model weights",
    "papers": "trending AI papers",
    "news": "recent AI news headlines",
    "brief": "a one-shot digest across every entity",
    "refresh": "refresh all sources, record a snapshot, report health (--quiet = headless)",
    "export": "write the board to docs/index.html + latest.json (the daily snapshot)",
    "setup": "check config, or schedule automatic refreshes (--schedule)",
    "search": "search cached tools",
    "show": "show one repo (owner/repo)",
    "about": "show project information",
}
_RETENTION_DAYS = 30.0
_INGEST_DEPTH = 100

_BADGE_COLORS = {"fresh": "32", "rising": "38;5;208", "viral": "38;5;198",
                 "smart-money": "38;5;220", "paper-backed": "38;5;45", "trending": "38;5;99"}
_ATTRIBUTION = "hotin · what's hot in AI · github.com/abe238/hotinai"
# `repos --source X` shows a single upstream feed instead of the fused board.
_REPO_SOURCE_ADAPTERS = {
    "stars": github, "trending": trends, "collections": collections,
    "hn": hn, "npm": npm, "reddit": reddit, "youtube": youtube,
}
_SOURCE_CHOICES = tuple(_REPO_SOURCE_ADAPTERS)
_FORMATS = ("text", "json", "md", "html")
# Commands that produce a ranked/list result and take --limit.
_LIST_COMMANDS = {"repos", "rising", "insiders", "models", "papers", "news", "search", "export"}
# Entity commands: (adapter, entity_type, metric weights for scoring, primary metric label).
# Models rank by HuggingFace's trendingScore (heat right now), NOT lifetime
# downloads — otherwise a hugely-adopted but old model (Kokoro-82M, ~10M
# downloads) outranks a genuinely surging new one. Downloads/likes stay as
# displayed context, not ranking weight.
_ENTITY_COMMANDS = {
    "models": (hfmodels, "model", {"model_trending_score": 1.0}),
    "papers": (hfpapers, "paper", {"paper_upvotes": 1.0}),
}


def _add_global_flags(
    parser: argparse.ArgumentParser, suppress_defaults: bool = False, include_limit: bool = True
) -> None:
    bdefault = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument("--format", choices=_FORMATS,
                        default=argparse.SUPPRESS if suppress_defaults else "text",
                        help="output format: text (default), json, md, html")
    parser.add_argument("--json", action="store_const", const="json", dest="format",
                        default=argparse.SUPPRESS, help="shorthand for --format json")
    parser.add_argument("--quiet", action="store_true", default=bdefault, help="reduce output")
    parser.add_argument("--verbose", action="store_true", default=bdefault, help="show scores and extra detail")
    if include_limit:
        parser.add_argument("--limit", type=int, default=argparse.SUPPRESS if suppress_defaults else None,
                            metavar="N", help="limit results (default 20)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hotin", description="What's hot in AI, from your terminal.")
    _add_global_flags(parser)
    subcommands = parser.add_subparsers(dest="command", title="subcommands")
    for command, description in COMMANDS.items():
        subparser = subcommands.add_parser(command, help=description, description=description)
        _add_global_flags(subparser, suppress_defaults=True, include_limit=(command in _LIST_COMMANDS))
        if command == "repos":
            subparser.add_argument("--source", choices=_SOURCE_CHOICES, default=None,
                                   help="show one upstream feed instead of the fused board")
            subparser.add_argument("--since", default=None, metavar="Nd",
                                   help="only repos active within a window (e.g. 30d, 2w, 12h)")
            subparser.add_argument("--min-stars", type=int, default=None, metavar="N",
                                   help="only repos with at least N stars")
        elif command in ("rising", "models", "papers", "news"):
            subparser.add_argument("--since", default=None, metavar="Nd",
                                   help="only items from within a window (e.g. 7d, 2w)")
        elif command == "setup":
            subparser.add_argument("--check", action="store_true", help="check local configuration")
            subparser.add_argument("--schedule", choices=("daily", "twice", "off"), default=None,
                                   help="install/remove a scheduled `hotin refresh` (daily=8am, twice=8am+8pm)")
        elif command == "search":
            subparser.add_argument("query", nargs="?", default=None, help="text to search for")
        elif command == "show":
            subparser.add_argument("repo", help="GitHub owner/repository")
    return parser


def _since_days(value: Any) -> Optional[float]:
    """Parse a `--since` window (Nd|Nw|Nh) to days. None if unset; raises ValueError on junk."""
    if value is None:
        return None
    text = str(value).strip().lower()
    match = re.fullmatch(r"(\d+)\s*([dwh])", text)
    if not match:
        raise ValueError("--since must look like 30d, 2w, or 12h")
    n = int(match.group(1))
    return {"d": n, "w": n * 7, "h": n / 24.0}[match.group(2)]


def _parse_date(value: Any):
    """Parse an ISO ('2026-06-19T…') or RFC-ish ('Wed, 22 Jul 2026 …') date -> date | None."""
    if not isinstance(value, str) or not value.strip():
        return None
    import datetime
    text = value.strip()
    try:
        return datetime.date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return datetime.datetime.strptime(text[:16], "%a, %d %b %Y").date()
    except (ValueError, TypeError):
        return None


def _dated_within(value: Any, cutoff) -> bool:
    """True if `value` parses to a date on/after `cutoff`; undated -> False (dropped)."""
    parsed = _parse_date(value)
    return parsed is not None and parsed >= cutoff


def _within_window(value: Any, days: float) -> Optional[bool]:
    """True/False if `value` parses to a date inside the last `days`;
    None when there is no usable date (caller decides keep-vs-drop)."""
    parsed = _parse_date(value)
    if parsed is None:
        return None
    import datetime
    return parsed >= datetime.date.today() - datetime.timedelta(days=int(days))


def _fresh_records(records: List[dict], days: float, date_of, *, keep_undated: bool) -> List[dict]:
    """The site's per-tab freshness window: same date semantics as --since
    (`_parse_date`), with each entity's keep-undated stance made explicit."""
    kept = []
    for record in records:
        if not isinstance(record, dict):
            continue
        verdict = _within_window(date_of(record), days)
        if verdict or (verdict is None and keep_undated):
            kept.append(record)
    return kept


def _since_cutoff(arguments: argparse.Namespace):
    """Resolve --since to a cutoff date. Returns (cutoff|None, exit_code|None):
    cutoff is None when --since is unset; exit_code is 2 when it is malformed."""
    since = getattr(arguments, "since", None)
    if since is None:
        return None, None
    try:
        days = _since_days(since)
    except ValueError as exc:
        print(_safe(str(exc)), file=sys.stderr)
        return None, 2
    if days is None:
        return None, None
    import datetime
    return datetime.date.today() - datetime.timedelta(days=int(days)), None


def _setup_check() -> int:
    config = load_config()
    print("config: {}".format(sanitize(str(env_path()))))
    print("configured entries: {}".format(len(config)))
    print("setup check passed")
    return 0


def _apply_schedule(choice: str) -> int:
    """Install (daily/twice) or remove (off) the scheduled ingest; report the result."""
    try:
        message = schedule.remove() if choice == "off" else schedule.install(choice)
    except Exception as exc:  # cron/schtasks missing or refused — report, don't crash
        print("could not update schedule: {}".format(_safe(str(exc) or "unknown error")), file=sys.stderr)
        return 1
    print(message)
    return 0


def _prompt_schedule() -> Optional[str]:
    """Ask whether to schedule ingest. Returns 'daily'/'twice'/'off', or None if declined."""
    print("\nKeep hotin fresh by running `hotin refresh` on a schedule?")
    print("  1) once a day   (8am)")
    print("  2) twice a day  (8am & 8pm)")
    print("  n) no thanks")
    try:
        answer = input("choice [1/2/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return {"1": "daily", "2": "twice", "n": None, "": None}.get(answer, None)


def _setup(arguments: argparse.Namespace) -> int:
    """Config check, plus an optional scheduler install (flag or interactive prompt)."""
    if arguments.schedule is not None:
        return _apply_schedule(arguments.schedule)
    code = _setup_check()
    if sys.stdin.isatty() and sys.stdout.isatty():
        choice = _prompt_schedule()
        if choice is not None:
            code = _apply_schedule(choice) or code
    else:
        print("(run `hotin setup --schedule daily|twice` to keep the store fresh automatically)")
    return code


def _json_default(value: object) -> object:
    return sorted(value) if isinstance(value, set) else str(value)


def _json_safe_key(key: object) -> Any:
    # json.dumps only accepts str/int/float/bool/None dict keys; anything else (a malformed
    # adapter could hand back a tuple, for instance) must be coerced, not just passed through.
    return key if isinstance(key, (str, int, float, bool)) or key is None else str(key)


def _sanitize_json(value: object) -> object:
    """Replace non-finite values and non-JSON-safe dict keys, retaining a machine-readable result."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {_json_safe_key(key): _sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, set):
        return sorted(_sanitize_json(item) for item in value)
    return value


def _dump_json(payload: object) -> None:
    try:
        rendered = json.dumps(payload, default=_json_default, allow_nan=False)
    except (ValueError, TypeError):
        # ValueError: a non-finite float slipped past _sanitize_json's normal pass (defense in
        # depth). TypeError: a genuinely unserializable Python shape from a malformed adapter
        # (e.g. a tuple used as a dict key) — this project never crashes on hostile/malformed
        # data, JSON output is no exception.
        rendered = json.dumps(_sanitize_json(payload), default=_json_default, allow_nan=False)
    print(rendered)


def _color_enabled(arguments: argparse.Namespace) -> bool:
    del arguments  # color follows the TTY; no manual flag
    return sys.stdout.isatty()


def _safe(value: object) -> str:
    return sanitize(value if isinstance(value, str) else str(value))


def _finite(value: object, default: float = 0.0) -> float:
    return finite_float(value, default)


def _format_number(value: object) -> str:
    number = _finite(value)
    return "{:.2f}".format(number) if not number.is_integer() else str(int(number))


def _render_badges(badges: object, enabled: bool) -> str:
    if not isinstance(badges, (list, tuple, set)):
        return ""
    rendered = []
    for badge in badges:
        text = _safe(badge)
        rendered.append(color(text, "1;" + _BADGE_COLORS.get(text, "36"), enabled))
    return " ".join(rendered)


def _score_color(score: float, top: float) -> str:
    """Bold SGR code heat-mapped by a score's share of the list's top score."""
    ratio = (score / top) if top > 0 else 0.0
    if ratio >= 0.66:
        return "1;38;5;42"   # bold green: hottest
    if ratio >= 0.33:
        return "1;38;5;214"  # bold amber: warm
    return "1;38;5;250"      # bold light: cooler


def _repo_link(repo: dict, enabled: bool) -> str:
    """Bold, hyperlinked ``owner/repo`` (falls back to the display name + its own url)."""
    slug = _safe(repo.get("canonical_repo") or "")
    if slug:
        return hyperlink(color(slug, "1", enabled), "https://github.com/{}".format(slug), enabled)
    name = color(_safe(repo.get("name", "")), "1", enabled)
    url = repo.get("url")
    return hyperlink(name, url, enabled) if isinstance(url, str) and url else name


def _render_ranked(repos: List[dict], arguments: argparse.Namespace) -> None:
    enabled = _color_enabled(arguments)
    top = max((_finite(repo.get("score")) for repo in repos), default=0.0)
    for repo in repos:
        score = _finite(repo.get("score"))
        row = "  ".join(part for part in (
            color("{:>6.2f}".format(score), _score_color(score, top), enabled),
            _repo_link(repo, enabled),
            color(_safe(repo.get("category", "uncategorized")), "2", enabled),
            _render_badges(repo.get("badges"), enabled),
        ) if part).rstrip()
        print(row)
        # Secondary dim line: the human title/context, when it adds something the
        # repo slug doesn't already say (HN/Reddit/YouTube titles, not repo names).
        name = _safe(repo.get("name", ""))
        slug = _safe(repo.get("canonical_repo") or "")
        if name and name.casefold() != slug.casefold():
            print("        " + color(name[:78], "2", enabled))


def _short_excerpt(record: dict) -> str:
    meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
    for field in ("description", "hn_title", "reddit_title", "youtube_title", "youtube_channel", "subreddit", "npm_package"):
        value = meta.get(field)
        if isinstance(value, str) and value.strip() and value != record.get("name"):
            return _safe(value)[:120]
    return ""


def _record_signal(record: dict) -> dict:
    signal = record.get("signal")
    return signal if isinstance(signal, dict) else {}


def _signal_metric(field: str, fallback_field: Optional[str] = None) -> Callable[[dict], Tuple[str, float]]:
    """Build a metric reading one signal field, with an optional fallback field."""
    def metric(record: dict) -> Tuple[str, float]:
        signal = _record_signal(record)
        value = signal.get(field, signal.get(fallback_field) if fallback_field else None)
        return field, _finite(value, float("-inf"))
    return metric


def _trend_metric(record: dict) -> Tuple[str, float]:
    signal = _record_signal(record)
    for key in ("trend_stars", "trend_total_score", "trend_collection_score"):
        if key in signal:
            return key, _finite(signal.get(key), float("-inf"))
    candidates = [(key, _finite(value, float("-inf"))) for key, value in signal.items() if str(key).startswith("trend_")]
    return max(candidates, key=lambda item: item[1]) if candidates else ("trend_score", float("-inf"))


def _render_single_source(
    records: List[dict], metric: Callable[[dict], Tuple[str, float]], arguments: argparse.Namespace
) -> None:
    enabled = _color_enabled(arguments)
    for record in records:
        label, value = metric(record)
        line = "{} {}  {}".format(
            color(_safe(label), "2", enabled),
            color(_format_number(value), "1", enabled),
            _repo_link(record, enabled),
        )
        excerpt = _short_excerpt(record)
        if excerpt:
            line += "  " + color("— " + excerpt, "2", enabled)
        print(line)


def _attribution(arguments: argparse.Namespace, *, force: bool = False) -> None:
    """Show the one-time terminal footer; errors here must never affect a command."""
    if not force and (getattr(arguments, "quiet", False) or getattr(arguments, "json", False) or not sys.stdout.isatty()):
        return
    try:
        marker = Path(config_dir()) / ".attribution-shown"
        if not force and marker.exists():
            return
        print(color(_ATTRIBUTION, "2;37", _color_enabled(arguments)))
        if not force:
            marker.touch(exist_ok=True)
    except OSError:
        return


@contextlib.contextmanager
def _cache_session() -> Iterator[Any]:
    cache = open_cache()
    try:
        yield cache
    finally:
        cache.close()


def _normal_limit(arguments: argparse.Namespace) -> Optional[int]:
    limit = arguments.limit if getattr(arguments, "limit", None) is not None else 20
    if limit < 0:
        print("limit must be zero or greater", file=sys.stderr)
        return None
    return limit


def _filter_repos(merged: Dict[str, dict], arguments: argparse.Namespace) -> Dict[str, dict]:
    """Apply `repos --min-stars` / `--since` filters to the merged repo map."""
    min_stars = getattr(arguments, "min_stars", None)
    since_days = _since_days(getattr(arguments, "since", None))
    if not min_stars and since_days is None:
        return merged
    cutoff = (time.time() - since_days * 86400.0) if since_days is not None else None
    kept: Dict[str, dict] = {}
    for repo_id, repo in merged.items():
        signal = repo.get("signal") if isinstance(repo.get("signal"), dict) else {}
        if min_stars and finite_float(signal.get("stars"), 0.0) < min_stars:
            continue
        if cutoff is not None:
            # Best-effort: keep repos with a recent activity/creation epoch; a repo
            # with no usable date is kept rather than hidden.
            dates = [finite_float(signal.get(k)) for k in ("pushed_at", "created_at", "fetched_at")]
            dates = [d for d in dates if d > 0]
            if dates and max(dates) < cutoff:
                continue
        kept[repo_id] = repo
    return kept


def _repo_source(command: str, arguments: argparse.Namespace) -> int:
    sources: Dict[str, Tuple[Any, Callable[[dict], Tuple[str, float]]]] = {
        "hn": (hn, _signal_metric("hn_points")),
        "npm": (npm, _signal_metric("npm_growth", "npm_downloads_week")),
        "stars": (github, _signal_metric("stars")),
        "trending": (trends, _trend_metric),
        "collections": (collections, _signal_metric("stars_growth")),
        "reddit": (reddit, _signal_metric("reddit_score")),
        "youtube": (youtube, _signal_metric("youtube_views")),
    }
    limit = _normal_limit(arguments)
    if limit is None:
        return 2
    adapter, metric = sources[command]
    try:
        result = adapter.fetch(limit=limit, config=load_config())
    except Exception as exc:
        result = {"records": [], "status": "error", "detail": str(exc) or "fetch failed"}
    if not isinstance(result, dict):
        result = {"records": [], "status": "error", "detail": "invalid adapter result"}
    status = result.get("status")
    detail = result.get("detail") if isinstance(result.get("detail"), str) else None
    records = result.get("records") if isinstance(result.get("records"), list) else []
    if arguments.json:
        _dump_json({"records": records, "status": status, "detail": detail})
    elif status == "error":
        print(_safe(detail or "source fetch failed"), file=sys.stderr)
    elif status == "empty":
        print("No {} results right now{}.".format(command, ": " + _safe(detail) if detail else ""))
    elif status == "ok":
        usable = [record for record in records if isinstance(record, dict)]
        usable.sort(key=lambda record: metric(record)[1], reverse=True)
        if usable:
            _render_single_source(usable[:limit], metric, arguments)
        else:
            print("No {} results right now.".format(command))
    else:
        if not arguments.json:
            print("invalid adapter status", file=sys.stderr)
        status = "error"
        detail = "invalid adapter status"
    exit_code = 1 if status == "error" else 0
    _attribution(arguments)
    return exit_code


def _label(name: str, value: str, enabled: bool, value_code: Optional[str] = "1") -> str:
    """A dim label with a (by default bold) value; value_code=None leaves value as-is."""
    shown = color(value, value_code, enabled) if value_code else value
    return "{}: {}".format(color(name, "2", enabled), shown)


def _entity_metric_line(entity: dict, entity_type: str) -> Tuple[str, str]:
    """Return (metric summary, dim context) for a paper/model row."""
    signal = entity.get("signal") if isinstance(entity.get("signal"), dict) else {}
    meta = entity.get("meta") if isinstance(entity.get("meta"), dict) else {}
    if entity_type == "model":
        metric = "{} downloads · {} likes".format(
            _format_number(signal.get("model_downloads")), _format_number(signal.get("model_likes")))
        context = _safe(meta.get("model_task")) if isinstance(meta.get("model_task"), str) else ""
    else:  # paper
        metric = "{} upvotes".format(_format_number(signal.get("paper_upvotes")))
        title = _safe(entity.get("name", ""))
        context = title if title != _safe(entity.get("entity_id", "")) else ""
    return metric, context


def _render_entities(entities: List[dict], arguments: argparse.Namespace, entity_type: str) -> None:
    enabled = _color_enabled(arguments)
    top = max((_finite(entity.get("score")) for entity in entities), default=0.0)
    for entity in entities:
        score = _finite(entity.get("score"))
        entity_id = _safe(entity.get("entity_id", ""))
        url = entity.get("url") if isinstance(entity.get("url"), str) else ""
        id_disp = hyperlink(color(entity_id, "1", enabled), url, enabled) if url else color(entity_id, "1", enabled)
        metric, context = _entity_metric_line(entity, entity_type)
        row = "  ".join(part for part in (
            color("{:>6.2f}".format(score), _score_color(score, top), enabled),
            id_disp,
            color(metric, "2", enabled),
        ) if part).rstrip()
        print(row)
        if context:
            print("        " + color(context[:78], "2", enabled))


def _render_releases(releases: List[dict], enabled: bool) -> None:
    for item in releases:
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        lab = color(_safe(meta.get("lab", ""))[:20].ljust(20), "38;5;45", enabled)
        date = color(_safe(meta.get("date", ""))[:16].ljust(16), "2", enabled)
        title = hyperlink(color(_safe(item.get("name", ""))[:60], "1", enabled),
                          item.get("url") if isinstance(item.get("url"), str) else "", enabled)
        print("  {}  {}  {}".format(lab, date, title))


def _frontier_releases(limit: int) -> Tuple[List[dict], Optional[str]]:
    """Best-effort fetch of frontier-lab releases; returns (records, detail)."""
    try:
        result = frontier.fetch(limit=limit, config=load_config())
    except Exception as exc:
        return [], str(exc) or "frontier fetch failed"
    if not isinstance(result, dict):
        return [], "invalid frontier result"
    records = [r for r in (result.get("records") or []) if isinstance(r, dict)]
    return records, result.get("detail") if isinstance(result.get("detail"), str) else None


def _releases(arguments: argparse.Namespace) -> int:
    limit = _normal_limit(arguments)
    if limit is None:
        return 2
    releases, detail = _frontier_releases(limit)
    if arguments.json:
        _dump_json({"releases": [{"lab": r["meta"].get("lab"), "title": r.get("name"),
                                  "url": r.get("url"), "date": r["meta"].get("date")} for r in releases],
                    "unsupported": frontier.UNSUPPORTED, "detail": detail})
        _attribution(arguments)
        return 0 if releases else 1
    if not releases:
        print("No frontier releases right now{}.".format(": " + _safe(detail) if detail else ""), file=sys.stderr)
        _attribution(arguments)
        return 1
    _render_releases(releases, _color_enabled(arguments))
    print(color("labs without a public feed (not yet covered): {}".format(", ".join(frontier.UNSUPPORTED)),
                "2", _color_enabled(arguments)))
    _attribution(arguments)
    return 0


def _render_rows(rows: List[dict], arguments: argparse.Namespace) -> None:
    """Render Row view-models to the active --format (text/md/html)."""
    fmt = getattr(arguments, "format", "text")
    if fmt == "md":
        print(render_board.render_md(rows))
    elif fmt == "html":
        print(render_board.render_html(rows))
    else:
        print(render_board.render_text(rows, color_on=_color_enabled(arguments)))


def _insiders(arguments: argparse.Namespace) -> int:
    """Repos the AI Insiders are backing — the raw smart-money signal, names first."""
    limit = _normal_limit(arguments)
    if limit is None:
        return 2
    try:
        result = insiders.fetch(limit=limit, config=load_config())
    except Exception as exc:  # adapters shouldn't raise
        result = {"records": [], "status": "error", "detail": str(exc) or "fetch failed"}
    if not isinstance(result, dict):
        result = {"records": [], "status": "error", "detail": "invalid adapter result"}
    records = [r for r in (result.get("records") or []) if isinstance(r, dict)]
    detail = result.get("detail") if isinstance(result.get("detail"), str) else None
    if arguments.json:
        _dump_json({"insiders": [{"rank": i + 1, "repo": r.get("canonical_repo"),
                                  "insider_stars": _record_signal(r).get("insider_stars"),
                                  "who": (r.get("meta") or {}).get("insiders"),
                                  "top_insider": (r.get("meta") or {}).get("top_insider")}
                                 for i, r in enumerate(records)], "status": result.get("status"), "detail": detail})
        _attribution(arguments)
        return 0 if records else 1
    if not records:
        print("No AI Insider signal right now{}.".format(": " + _safe(detail) if detail else ""), file=sys.stderr)
        _attribution(arguments)
        return 1
    _render_rows(board.insider_rows(records), arguments)
    _attribution(arguments)
    return 0


_RISING_QUERIES = ("agent", "llm", "mcp", "skill", "ai")
_RISING_WINDOW_DAYS = 60
_RISING_MAX_AGE = 90


def _age_days(created_iso: Any) -> int:
    """Whole days since an ISO8601 created_at (floored at 1); huge if unknown."""
    if not isinstance(created_iso, str):
        return 10 ** 6
    try:
        import datetime
        created = datetime.date.fromisoformat(created_iso[:10])
        return max((datetime.date.today() - created).days, 1)
    except (ValueError, TypeError):
        return 10 ** 6


def _rising_velocity(record: dict) -> float:
    signal = record.get("signal") if isinstance(record, dict) else None
    stars = finite_int((signal or {}).get("stars"), 0)
    return stars / _age_days((signal or {}).get("created_at"))


def _rising_ranked(config: Optional[dict], limit: int, max_age: int = _RISING_MAX_AGE) -> List[dict]:
    """Freshest fast-climbing AI repos: union of domain-scoped GitHub searches,
    ranked by star velocity (stars/day since creation). GitHub's own board ranks
    by absolute stars, which buries young rockets under established mega-repos.
    `max_age` caps repo age in days; a tight window also narrows the fetch so a
    small-but-fast young repo isn't buried under bigger ones in the star sort."""
    fetch_days = min(max_age, _RISING_WINDOW_DAYS) if max_age else _RISING_WINDOW_DAYS
    pool: Dict[str, dict] = {}
    for query in _RISING_QUERIES:
        result = github.fetch(query, limit=50, config=config, days=fetch_days)
        for record in (result.get("records") if isinstance(result, dict) else None) or []:
            if not isinstance(record, dict):
                continue
            key = record.get("canonical_repo") or record.get("name")
            meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
            if key and key not in pool and not meta.get("archived"):
                pool[key] = record
    fresh = [r for r in pool.values()
             if _age_days((r.get("signal") or {}).get("created_at")) <= max_age]
    fresh.sort(key=_rising_velocity, reverse=True)
    ranked = fresh[: max(limit, 0)]
    for record in ranked:
        signal = record.setdefault("signal", {})
        signal["age_days"] = _age_days(signal.get("created_at"))
        signal["velocity_per_day"] = round(_rising_velocity(record), 1)
    return ranked


def _rising(arguments: argparse.Namespace) -> int:
    """Rising view: brand-new repos climbing fastest (velocity, not lifetime size)."""
    limit = _normal_limit(arguments)
    if limit is None:
        return 2
    max_age = _RISING_MAX_AGE
    since = getattr(arguments, "since", None)
    if since is not None:
        try:
            days = _since_days(since)
        except ValueError as exc:
            print(_safe(str(exc)), file=sys.stderr)
            return 2
        if days is not None:
            max_age = max(int(days), 1)
    ranked = _rising_ranked(load_config(), limit or 20, max_age)
    if getattr(arguments, "json", False):
        _dump_json({"rising": [{"rank": i + 1, "repo": r.get("canonical_repo"),
                                "url": r.get("url"),
                                "stars": (r.get("signal") or {}).get("stars"),
                                "velocity_per_day": (r.get("signal") or {}).get("velocity_per_day"),
                                "age_days": (r.get("signal") or {}).get("age_days")}
                               for i, r in enumerate(ranked)]})
    else:
        _render_rows(board.rising_rows(ranked), arguments)
    _attribution(arguments)
    return 0 if ranked else 1


def _pacific_stamp() -> str:
    """Human 'last updated' stamp in Pacific time, to the minute.

    Cross-platform (no %-/%# strftime tricks). Falls back to naive local time
    labeled PT if the tz database is unavailable.
    """
    import datetime
    now = datetime.datetime.now()
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:
        pass
    hour12 = now.hour % 12 or 12
    ampm = "AM" if now.hour < 12 else "PM"
    return "{} {}, {} · {}:{:02d} {} PT".format(
        now.strftime("%b"), now.day, now.year, hour12, now.minute, ampm)


def _export(arguments: argparse.Namespace) -> int:
    """Bake the 5-tab board into docs/index.html + write docs/data/latest.json.

    The daily snapshot the live site self-updates from: no backend, just a static
    page + JSON regenerated on a schedule and committed. Every entity is rendered
    to HTML rows and injected between its <!-- BOARD:<id> --> markers.
    """
    import datetime
    repo_root = Path(__file__).resolve().parents[2]
    docs = repo_root / "docs"
    index = docs / "index.html"
    limit = _normal_limit(arguments) or 60
    config = load_config()
    with _cache_session() as cache:
        engine.fetch_all(config, limit=max(limit, 100), cache=cache)
        cached = cache.get_all()
        window = engine.EVIDENCE_WINDOW_DAYS
        links = engine.cross_entity_repo_links(cached, max_age_days=window)
        merged = engine.merge_by_repo(cached, max_age_days=window)
        for rid, repo in merged.items():
            if rid in links:
                repo.setdefault("meta", {})["paper_backed"] = True
        engine.annotate_velocity(merged, cache)
        repos = engine.rank(merged, limit=limit)
        models = engine.rank_entities(engine.merge_by_entity(cached, "model", max_age_days=window),
                                      _ENTITY_COMMANDS["models"][2], limit=limit)
        papers = engine.rank_entities(engine.merge_by_entity(cached, "paper", max_age_days=window),
                                      _ENTITY_COMMANDS["papers"][2], limit=limit)
    ins_res = insiders.fetch(limit=limit, config=config)
    ins = [r for r in (ins_res.get("records") or []) if isinstance(r, dict)] if isinstance(ins_res, dict) else []
    # The Digg page carries no repo creation date; the refresh heal fetches each
    # one once from the GitHub API into the cached insiders rows. Read them back
    # so the live fetch gets dated (the 7d/60d windows key on this).
    with _cache_session() as _c:
        _dates = {}
        for _raw in _c.get_all():
            _r = engine._decoded_record(_raw)
            if _r and _r.get("source") == insiders.SOURCE:
                _created = (_r.get("signal") or {}).get("created_at")
                if _created:
                    _dates[_r.get("entity_id")] = _created
    for rec in ins:
        if rec.setdefault("signal", {}).get("created_at") is None:
            known_date = _dates.get(rec.get("canonical_repo"))
            if known_date:
                rec["signal"]["created_at"] = known_date
    # Borrow board facts (age, velocity, HN points) from the fused repo map when
    # an insiders repo is also tracked there; the Digg page alone doesn't carry them.
    for rec in ins:
        known = merged.get(rec.get("canonical_repo"))
        if not isinstance(known, dict):
            continue
        ksig = known.get("signal") if isinstance(known.get("signal"), dict) else {}
        sig = rec.setdefault("signal", {})
        for key in ("created_at", "hn_points"):
            if ksig.get(key) is not None and sig.get(key) is None:
                sig[key] = ksig[key]
        kmeta = known.get("meta") if isinstance(known.get("meta"), dict) else {}
        if kmeta.get("velocity_per_day") is not None:
            rec.setdefault("meta", {}).setdefault("velocity_per_day", kmeta["velocity_per_day"])
    news_text = smolai._request()
    news = smolai.parse_news(news_text)[:limit] if news_text else []
    rising = _rising_ranked(config, 30)
    rising7 = _rising_ranked(config, 30, max_age=7)

    # Both windows are strictly enforced on every tab: the 60d container holds
    # items dated within 60 days, the 7d one within 7; undated rows drop from
    # both (a window you can't verify isn't a window). Date basis per tab:
    # repos = latest ACTIVITY (push/creation), insiders = the repo's own
    # creation date, models/papers/news = release/publish date.
    def _repo_activity(r):
        s = r.get("signal") if isinstance(r.get("signal"), dict) else {}
        return s.get("pushed_at") or s.get("created_at")

    def _sig_date(key):
        return lambda r: (r.get("signal") or {}).get(key) if isinstance(r.get("signal"), dict) else None

    def _windows(records, date_of):
        return (_fresh_records(records, 60, date_of, keep_undated=False),
                _fresh_records(records, 7, date_of, keep_undated=False))

    repos60, repos7 = _windows(repos, _repo_activity)
    # insiders window on the REPO'S OWN creation date (user call): the smart-money
    # view of young repos; an insider star on a 3-year-old repo is not "new".
    ins60, ins7 = _windows(ins, _sig_date("created_at"))
    models60, models7 = _windows(models, _sig_date("created_at"))
    papers60, papers7 = _windows(papers, _sig_date("created_at"))
    news60, news7 = _windows(news, lambda r: (r.get("meta") or {}).get("date"))

    rows = {
        "repos": board.repo_rows(repos60), "repos7": board.repo_rows(repos7),
        "rising": board.rising_rows(rising), "rising7": board.rising_rows(rising7),
        "insiders": board.insider_rows(ins60), "insiders7": board.insider_rows(ins7),
        "models": board.model_rows(models60), "models7": board.model_rows(models7),
        "papers": board.paper_rows(papers60), "papers7": board.paper_rows(papers7),
        "news": board.news_rows(news60), "news7": board.news_rows(news7),
    }
    stamp = datetime.date.today().isoformat()
    stamp_pt = _pacific_stamp()
    if index.exists():
        html = index.read_text()
        for eid, entity_rows in rows.items():
            rendered = "\n" + (render_board.render_html(entity_rows) or "") + "\n"
            html = re.sub(
                r"(<!-- BOARD:{0} -->).*?(<!-- /BOARD:{0} -->)".format(re.escape(eid)),
                lambda m, r=rendered: m.group(1) + r + m.group(2), html, flags=re.DOTALL)
        html = re.sub(r"(hotin · updated )\d{4}-\d{2}-\d{2}", r"\g<1>" + stamp, html)
        html = re.sub(r"<!-- STAMP -->.*?<!-- /STAMP -->",
                      lambda m: "<!-- STAMP -->last updated " + stamp_pt + " <!-- /STAMP -->",
                      html, flags=re.DOTALL)
        index.write_text(html)
    (docs / "data").mkdir(parents=True, exist_ok=True)
    (docs / "data" / "latest.json").write_text(json.dumps(
        {"generated": stamp, "generated_pt": stamp_pt, "entities": rows},
        indent=2, allow_nan=False))
    counts = ", ".join("{} {}".format(len(v), k) for k, v in rows.items())
    print("exported {} · baked {} + docs/data/latest.json".format(counts, index.name))
    return 0


def _models(arguments: argparse.Namespace) -> int:
    """Models view: official frontier-lab releases first, then HuggingFace trending."""
    limit = _normal_limit(arguments)
    if limit is None:
        return 2
    cutoff, code = _since_cutoff(arguments)
    if code:
        return code
    releases, _detail = _frontier_releases(min(limit, 6))
    adapter, entity_type, metric_weights = _ENTITY_COMMANDS["models"]
    with _cache_session() as cache:
        try:
            result = adapter.fetch(limit=limit, config=load_config())
        except Exception as exc:
            result = {"records": [], "status": "error", "detail": str(exc) or "fetch failed"}
        if not isinstance(result, dict):
            result = {"records": [], "status": "error", "detail": "invalid adapter result"}
        for record in result.get("records") if isinstance(result.get("records"), list) else []:
            if isinstance(record, dict):
                cache.upsert(engine._cache_record(record))
        merged = engine.merge_by_entity(cache.get_all(), entity_type, max_age_days=engine.EVIDENCE_WINDOW_DAYS)
        if cutoff is not None:
            merged = {k: v for k, v in merged.items()
                      if _dated_within((v.get("signal") or {}).get("created_at"), cutoff)}
        ranked = engine.rank_entities(merged, metric_weights, limit=limit)
        if arguments.json:
            _dump_json({"releases": [{"lab": r["meta"].get("lab"), "title": r.get("name"),
                                      "url": r.get("url"), "date": r["meta"].get("date")} for r in releases],
                        "trending": ranked, "status": result.get("status")})
            _attribution(arguments)
            return 0
        enabled = _color_enabled(arguments)
        if releases:
            print(color("Official press releases", "1", enabled))
            _render_releases(releases, enabled)
        if ranked:
            print(("\n" if releases else "") + color("Trending on HuggingFace", "1", enabled))
            _render_entities(ranked, arguments, entity_type)
        if not (releases or ranked):
            print("No models right now.")
        _attribution(arguments)
        return 0


def _entity_command(command: str, arguments: argparse.Namespace) -> int:
    limit = _normal_limit(arguments)
    if limit is None:
        return 2
    cutoff, code = _since_cutoff(arguments)
    if code:
        return code
    adapter, entity_type, metric_weights = _ENTITY_COMMANDS[command]
    with _cache_session() as cache:
        try:
            result = adapter.fetch(limit=limit, config=load_config())
        except Exception as exc:  # defensive: adapters shouldn't raise, but never crash the CLI
            result = {"records": [], "status": "error", "detail": str(exc) or "fetch failed"}
        if not isinstance(result, dict):
            result = {"records": [], "status": "error", "detail": "invalid adapter result"}
        status = result.get("status")
        detail = result.get("detail") if isinstance(result.get("detail"), str) else None
        for record in result.get("records") if isinstance(result.get("records"), list) else []:
            if isinstance(record, dict):
                cache.upsert(engine._cache_record(record))
        merged = engine.merge_by_entity(cache.get_all(), entity_type, max_age_days=engine.EVIDENCE_WINDOW_DAYS)
        if cutoff is not None:
            merged = {k: v for k, v in merged.items()
                      if _dated_within((v.get("signal") or {}).get("created_at"), cutoff)}
        ranked = engine.rank_entities(merged, metric_weights, limit=limit)
        if arguments.json:
            _dump_json({"entities": ranked, "status": status, "detail": detail})
        elif status == "error" and not ranked:
            print(_safe(detail or "source fetch failed"), file=sys.stderr)
        elif not ranked:
            print("No {} results right now{}.".format(command, ": " + _safe(detail) if detail else ""))
        else:
            _render_entities(ranked, arguments, entity_type)
        _attribution(arguments)
        return 1 if (status == "error" and not ranked) else 0


def _show_repo(repo: dict, arguments: argparse.Namespace) -> None:
    enabled = _color_enabled(arguments)
    slug = _safe(repo.get("canonical_repo", ""))
    print(color(_safe(repo.get("name", "")), "1", enabled))
    if slug:
        url = "https://github.com/{}".format(slug)
        print(_label("repository", hyperlink(color(slug, "1", enabled), url, enabled), enabled, value_code=None))
        print(_label("url", url, enabled, value_code="2"))
    print(_label("category", _safe(repo.get("category", "uncategorized")), enabled))
    print(_label("score", "{:.2f}".format(_finite(repo.get("score"))), enabled, value_code="1;38;5;42"))
    print(_label("momentum", "{:.2f}".format(_finite(repo.get("momentum"))), enabled))
    print(_label("credibility", "{:.2f}".format(_finite(repo.get("credibility"))), enabled))
    print(_label("signal_score", "{:.2f}".format(_finite(repo.get("signal_score"))), enabled))
    print(_label("consensus", "{:.2f}".format(_finite(repo.get("corroboration"))), enabled))
    print(_label("freshness_factor", "{:.2f}".format(_finite(repo.get("freshness_factor"))), enabled))
    freshness_days = repo.get("freshness_days")
    print(_label("freshness_days", "unknown" if freshness_days is None else "{:.2f}".format(_finite(freshness_days)), enabled))
    print("{}: {}".format(color("badges", "2", enabled), _render_badges(repo.get("badges"), enabled) or "none"))
    print(color("signals:", "2", enabled))
    by_source = repo.get("signal_by_source") if isinstance(repo.get("signal_by_source"), dict) else {}
    for source in sorted(by_source, key=str):
        print("  {}:".format(color(_safe(source), "1", enabled)))
        signal = by_source[source]
        if isinstance(signal, dict):
            for key in sorted(signal, key=str):
                value = signal[key]
                rendered = _safe(value) if isinstance(value, str) else _format_number(value)
                print("    {}: {}".format(color(_safe(key), "2", enabled), rendered))


def _news(arguments: argparse.Namespace) -> int:
    """Recent AI news headlines from smol.ai/AINews, most recent first.

    Surfaces titles + links (attribution to AINews / Latent Space); it never
    re-serves their editorial prose.
    """
    limit = _normal_limit(arguments)
    if limit is None:
        return 2
    cutoff, code = _since_cutoff(arguments)
    if code:
        return code
    try:
        text = smolai._request()
    except Exception:
        text = None
    parsed = smolai.parse_news(text) if text is not None else []
    if cutoff is not None:
        parsed = [it for it in parsed if _dated_within((it.get("meta") or {}).get("date"), cutoff)]
    items = parsed[:limit]
    if arguments.json:
        _dump_json({"news": [{"title": item["name"], "url": item["url"], "date": item["meta"].get("date")} for item in items],
                    "status": "ok" if text is not None else "error"})
        _attribution(arguments)
        return 0 if text is not None else 1
    if text is None:
        print("news source (smol.ai) unavailable", file=sys.stderr)
        _attribution(arguments)
        return 1
    enabled = _color_enabled(arguments)
    if not items:
        print("No AI news headlines right now.")
    else:
        for item in items:
            date = _safe(item["meta"].get("date", ""))[:16]
            title = hyperlink(color(_safe(item["name"]), "1", enabled), item["url"] if isinstance(item.get("url"), str) else "", enabled)
            print("{}  {}".format(color(date, "2", enabled), title))
        print(color("via AINews (smol.ai / Latent Space) — news.smol.ai", "2", enabled))
    _attribution(arguments)
    return 0


def _brief(arguments: argparse.Namespace) -> int:
    """A short, deterministic 'what's happening in AI' digest from the local store.

    Every line traces to real data (a velocity delta, a rank, an upvote count) —
    nothing is fabricated. LLM prose enrichment over these immutable facts is a
    documented future opt-in; the deterministic digest is the product.
    """
    with _cache_session() as cache:
        rows = cache.get_all()
        window = engine.EVIDENCE_WINDOW_DAYS
        merged = engine.merge_by_repo(rows, max_age_days=window)
        links = engine.cross_entity_repo_links(rows, max_age_days=window)
        for repo_id, repo in merged.items():
            if repo_id in links:
                repo.setdefault("meta", {})["paper_backed"] = True
        engine.annotate_velocity(merged, cache)
        repos = engine.rank(merged, limit=50)
        models = engine.rank_entities(engine.merge_by_entity(rows, "model", max_age_days=window), _ENTITY_COMMANDS["models"][2], limit=5)
        papers = engine.rank_entities(engine.merge_by_entity(rows, "paper", max_age_days=window), _ENTITY_COMMANDS["papers"][2], limit=5)
        rising = sorted(
            (repo for repo in repos if repo.get("meta", {}).get("rising")),
            key=lambda repo: -_finite(repo.get("meta", {}).get("velocity_per_day")),
        )[:5]
        # News is a best-effort live augmentation (smol.ai / AINews) — the one
        # section not sourced from the local store. A failed fetch just omits it.
        try:
            news_text = smolai._request()
        except Exception:
            news_text = None
        news = smolai.parse_news(news_text)[:6] if news_text else []
        releases, _rel_detail = _frontier_releases(5)

        if arguments.json:
            _dump_json({
                "rising": [{"repo": r.get("canonical_repo"), "stars_per_day": _finite(r.get("meta", {}).get("velocity_per_day"))} for r in rising],
                "releases": [{"lab": r["meta"].get("lab"), "title": r.get("name"), "url": r.get("url"), "date": r["meta"].get("date")} for r in releases],
                "top_repos": [{"repo": r.get("canonical_repo"), "score": _finite(r.get("score")), "badges": r.get("badges")} for r in repos[:5]],
                "top_papers": [{"paper": p.get("entity_id"), "title": p.get("name"), "url": p.get("url"),
                                "upvotes": _finite(_record_signal(p).get("paper_upvotes")),
                                "repo": p.get("meta", {}).get("linked_repo")} for p in papers],
                "top_models": [{"model": m.get("entity_id"), "url": m.get("url"),
                                "downloads": _finite(_record_signal(m).get("model_downloads")),
                                "likes": _finite(_record_signal(m).get("model_likes"))} for m in models],
                "news": [{"title": n["name"], "url": n["url"], "date": n["meta"].get("date")} for n in news],
            })
            _attribution(arguments)
            return 0

        enabled = _color_enabled(arguments)
        if not (repos or models or papers or news or releases):
            print("Nothing in the store yet. Run `hotin refresh` (or `hotin`) first to populate it.")
            _attribution(arguments)
            return 0

        def header(text):
            print("\n" + color(text, "1", enabled))

        print(color("hotin brief — what's happening in AI", "1;38;5;42", enabled))
        if rising:
            header("Rising (stars/day)")
            for repo in rising:
                per_day = _finite(repo.get("meta", {}).get("velocity_per_day"))
                print("  {}  {}".format(_repo_link(repo, enabled), color("+{}/day".format(_format_number(per_day)), "38;5;208", enabled)))
        if repos:
            header("Hottest repos")
            for repo in repos[:5]:
                print("  {}  {}  {}".format(
                    color("{:>6.2f}".format(_finite(repo.get("score"))), "1;38;5;42", enabled),
                    _repo_link(repo, enabled), _render_badges(repo.get("badges"), enabled)))
        def entity_link(entity, text):
            url = entity.get("url")
            return hyperlink(color(text, "1", enabled), url, enabled) if isinstance(url, str) and url else color(text, "1", enabled)

        if releases:
            header("Frontier lab press releases")
            _render_releases(releases, enabled)
        if models:
            header("Trending models")
            for model in models:
                signal = _record_signal(model)
                metric = "{} downloads · {} likes".format(
                    _format_number(signal.get("model_downloads")), _format_number(signal.get("model_likes")))
                print("  {}  {}".format(entity_link(model, _safe(model.get("entity_id", ""))),
                                        color(metric, "2", enabled)))
        if papers:
            header("Trending papers")
            for paper in papers:
                signal = _record_signal(paper)
                print("  {}  {}".format(
                    color("{:>4} upvotes".format(_format_number(signal.get("paper_upvotes"))), "2", enabled),
                    entity_link(paper, _safe(paper.get("name", ""))[:66])))
                repo = paper.get("meta", {}).get("linked_repo")
                if isinstance(repo, str) and repo:
                    print("        {}".format(hyperlink(color(repo, "2", enabled), "https://github.com/{}".format(repo), enabled)))
        if news:
            header("AI news (smol.ai / AINews)")
            for item in news:
                date = _safe(item["meta"].get("date", ""))[:16]
                title = hyperlink(color(_safe(item["name"])[:70], "1", enabled),
                                  item["url"] if isinstance(item.get("url"), str) else "", enabled)
                print("  {}  {}".format(color(date, "2", enabled), title))
        _attribution(arguments)
        return 0


def _refresh(arguments: argparse.Namespace) -> int:
    """Refresh every source (repos + papers + models), record a snapshot, prune, report health.

    Replaces the old `ingest` + `update`. It is the writer that turns hotin's
    snapshot into a continuous picture, and `--quiet` is the headless/scheduler
    mode. A run that could not PERSIST (SQLite fell to the in-memory cache) exits
    non-zero, since an in-memory store won't survive to the next scheduled run.
    """
    run_id = "run-{}".format(int(time.time()))
    now = time.time()
    config = load_config()
    cache = open_cache()
    statuses: List[health.SourceStatus] = []
    persisted = False
    # healed meta (card descriptions, paper summaries, gated flags) must survive
    # the re-upsert of a fresh fetch, or every refresh wipes what backfill built
    # and the bounded heal can never catch up.
    _PRESERVED_META = ("model_description", "model_gated", "paper_summary")
    preserved: Dict[tuple, Dict[str, Any]] = {}
    preserved_sig: Dict[tuple, Dict[str, Any]] = {}
    for _raw in cache.get_all():
        _rec = engine._decoded_record(_raw)
        if _rec is None:
            continue
        _key = (_rec.get("entity_type"), _rec.get("entity_id"), _rec.get("source"))
        if _rec.get("entity_type") in ("model", "paper"):
            _meta = _rec.get("meta") or {}
            _keep = {k: _meta[k] for k in _PRESERVED_META if k in _meta}
            if _keep:
                preserved[_key] = _keep
        # insiders rows: the healed repo creation date (Digg never sends one)
        if _rec.get("source") == insiders.SOURCE and (_rec.get("signal") or {}).get("created_at") is not None:
            preserved_sig[_key] = {"created_at": (_rec.get("signal") or {})["created_at"]}
    try:
        statuses = list(engine.fetch_all(config, limit=_INGEST_DEPTH, cache=cache, ttl=0))
        # insiders joins the persisted sources so its rows can be healed
        # (repo creation dates) and windowed like everything else.
        extra_adapters = [insiders]
        for adapter, _entity_type, _weights in (
                list(_ENTITY_COMMANDS.values()) + [(a, None, None) for a in extra_adapters]):
            try:
                result = adapter.fetch(limit=_INGEST_DEPTH, config=config)
            except Exception as exc:  # adapters shouldn't raise; ingest never crashes
                result = {"records": [], "status": "error", "detail": str(exc) or "fetch failed"}
            if isinstance(result, dict):
                statuses.append(health.SourceStatus(
                    getattr(adapter, "SOURCE", "?"),
                    result.get("status") if result.get("status") in ("ok", "empty", "error") else "error",
                    result.get("detail") if isinstance(result.get("detail"), str) else None,
                ))
                for record in result.get("records") if isinstance(result.get("records"), list) else []:
                    if isinstance(record, dict):
                        key = (record.get("entity_type"),
                               record.get("entity_id"), record.get("source"))
                        keep = preserved.get(key)
                        if keep:
                            meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
                            record["meta"] = {**keep, **meta}
                        keep_sig = preserved_sig.get(key)
                        if keep_sig:
                            sig = record.get("signal") if isinstance(record.get("signal"), dict) else {}
                            record["signal"] = {**keep_sig,
                                                **{k: v for k, v in sig.items() if v is not None}}
                        cache.upsert(engine._cache_record(record))
        healed = hfpapers.backfill_summaries(cache)
        healed_models = hfmodels.backfill_descriptions(cache)
        from .config import get as _config_get
        gh_token = _config_get(config, "GITHUB_TOKEN")
        healed_dates = insiders.backfill_created_at(
            cache, gh_token if isinstance(gh_token, str) and gh_token.strip() else None)
        if (healed or healed_models or healed_dates) and not arguments.quiet and not arguments.json:
            print("healed {} paper summaries, {} model descriptions, {} insider repo dates".format(
                healed, healed_models, healed_dates))
        cache.record_observations(engine.observations_from_cache(cache.get_all(), run_id, now))
        cache.prune_observations(now - _RETENTION_DAYS * 86400.0)
        persisted = not isinstance(cache, MemoryCache) and getattr(cache, "_fallback", None) is None
        if arguments.json:
            _dump_json({"run_id": run_id, "persisted": persisted,
                        "sources": [{"source": s.source, "status": s.status, "detail": s.detail} for s in statuses]})
        else:
            if not arguments.quiet:
                for status in statuses:
                    detail = " — {}".format(_safe(status.detail)) if status.detail else ""
                    print("{}  {}{}".format(_safe(status.source), _safe(status.status), detail))
            print("run {} recorded — cache {}".format(run_id, "persisted" if persisted else "NOT persisted (in-memory)"))
        if not persisted:
            print("refresh did not persist (SQLite unavailable); a scheduled run needs a durable store", file=sys.stderr)
    finally:
        cache.close()
    exit_code = 0 if persisted else 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
    return exit_code  # allows unit tests to substitute os._exit()


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    command = arguments.command or "repos"
    # Derive the legacy `arguments.json` flag from --format so every existing
    # handler keeps working; md/html land with the output renderer.
    fmt = getattr(arguments, "format", "text")
    arguments.json = (fmt == "json")
    if fmt in ("md", "html"):
        print("(--format {} lands with the output renderer; showing text)".format(fmt), file=sys.stderr)
    # Validate --since early: junk is a clean error, never a traceback.
    if getattr(arguments, "since", None) is not None:
        try:
            _since_days(arguments.since)
        except ValueError as exc:
            parser.error(str(exc))
    if command == "setup":
        code = _setup_check() if arguments.check else _setup(arguments)
        _attribution(arguments)
        return code
    if command == "about":
        if arguments.json:
            _dump_json({"name": "hotin", "version": __version__, "description": "What's hot in AI, from your terminal.", "attribution": _ATTRIBUTION})
        else:
            print(" _           _   _")
            print("| |__   ___ | |_(_)_ __")
            print("| '_ \\ / _ \\| __| | '_ \\")
            print("| | | | (_) | |_| | | | |")
            print("|_| |_|\\___/ \\__|_|_| |_|")
            print("hotin {} — What's hot in AI, from your terminal.".format(__version__))
            _attribution(arguments, force=True)
        return 0
    if command == "models":
        return _models(arguments)
    if command in _ENTITY_COMMANDS:
        return _entity_command(command, arguments)
    if command == "refresh":
        return _refresh(arguments)
    if command == "brief":
        return _brief(arguments)
    if command == "news":
        return _news(arguments)
    if command == "rising":
        return _rising(arguments)
    if command == "insiders":
        return _insiders(arguments)
    if command == "export":
        return _export(arguments)
    if command == "repos":
        if getattr(arguments, "source", None):
            return _repo_source(arguments.source, arguments)
        limit = _normal_limit(arguments)
        if limit is None:
            return 2
        config = load_config()
        with _cache_session() as cache:
            statuses = engine.fetch_all(config, limit=limit, cache=cache)
            cached = cache.get_all()
            # Cross-entity bridge: repos implementing a currently-cached trending
            # paper/model get a bounded boost + a paper-backed badge.
            links = engine.cross_entity_repo_links(cached, max_age_days=engine.EVIDENCE_WINDOW_DAYS)
            merged = engine.merge_by_repo(cached, max_age_days=engine.EVIDENCE_WINDOW_DAYS)
            for repo_id, repo in merged.items():
                if repo_id in links:
                    repo.setdefault("meta", {})["paper_backed"] = True
            merged = _filter_repos(merged, arguments)
            engine.annotate_velocity(merged, cache)  # rising/viral from the observation store
            ranked = engine.rank(merged, limit=limit)
            # Health reflects the repo view specifically: a cache holding only
            # papers/models must not report "sources completed" for `hot`.
            exit_code, message = health.summarize(statuses, cache_has_data=bool(ranked))
            if arguments.json:
                _dump_json({"tools": ranked, "sources": [{"source": status.source, "status": status.status, "detail": status.detail} for status in statuses]})
            elif getattr(arguments, "format", "text") in ("md", "html"):
                _render_rows(board.repo_rows(ranked), arguments)
            else:
                _render_ranked(ranked, arguments)
            if exit_code:
                print(_safe(message), file=sys.stderr)
            _attribution(arguments)
        # Adapters can leave network workers behind after the fetch deadline.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
        return exit_code  # Allows unit tests to substitute os._exit().
    if command == "search":
        if not arguments.query:
            parser.error("search requires a query")
        limit = _normal_limit(arguments)
        if limit is None:
            return 2
        with _cache_session() as cache:
            ranked = engine.rank(engine.merge_by_repo(cache.search(arguments.query), max_age_days=engine.EVIDENCE_WINDOW_DAYS), limit=limit)
            if arguments.json:
                _dump_json({"tools": ranked, "query": arguments.query})
            else:
                if ranked:
                    _render_ranked(ranked, arguments)
                else:
                    print("No cached tools match {}.".format(_safe(arguments.query)))
            _attribution(arguments)
            return 0
    if command == "show":
        with _cache_session() as cache:
            canonical = canonicalize(arguments.repo)
            repo = engine.merge_by_repo(cache.get_all()).get(canonical) if canonical else None
            if repo is None:
                if arguments.json:
                    _dump_json({"error": "not_cached", "repo": arguments.repo, "canonical_repo": canonical})
                else:
                    print("{} is not in the local cache yet — run `hotin` first to populate it.".format(_safe(arguments.repo)))
            else:
                scored = engine.score_repo(repo)
                if arguments.json:
                    _dump_json(scored)
                else:
                    _show_repo(scored, arguments)
            _attribution(arguments)
            return 0
    print("{}: not yet implemented".format(command))
    return 0


if __name__ == "__main__":
    sys.exit(main())
