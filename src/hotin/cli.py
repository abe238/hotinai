"""The command dispatcher and safe terminal renderers for hotin."""

import argparse
import contextlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from . import __version__, engine, health
from .cache import open_cache
from .canonical import canonicalize
from .coerce import finite_float
from .config import config_dir, env_path, load_config
from .render import color, sanitize
from .sources import github, hn, npm, trends, reddit, youtube


COMMANDS = {
    "hot": "show the hottest AI tools",
    "hn": "show Hacker News signals",
    "npm": "show npm signals",
    "stars": "show GitHub star growth",
    "trending": "show trending repositories",
    "reddit": "show Reddit signals",
    "youtube": "show YouTube signals",
    "search": "search cached tools",
    "show": "show one tool",
    "setup": "check local configuration",
    "update": "update hotin",
    "about": "show project information",
}

_BADGE_COLORS = {"fresh": "32", "smart-money": "38;5;220", "new": "34", "corroborated": "35"}
_ATTRIBUTION = "hotin · what's hot in AI · github.com/abe238/hotinai"


def _add_global_flags(parser: argparse.ArgumentParser, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument("--json", action="store_true", default=default, help="emit JSON output")
    parser.add_argument("--no-color", action="store_true", default=default, help="disable ANSI color")
    parser.add_argument("--quiet", action="store_true", default=default, help="reduce output")
    parser.add_argument("--verbose", action="store_true", default=default, help="increase output")
    parser.add_argument("--limit", type=int, default=argparse.SUPPRESS if suppress_defaults else None, metavar="N", help="limit results")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hotin", description="What's hot in AI, from your terminal.")
    _add_global_flags(parser)
    subcommands = parser.add_subparsers(dest="command", title="subcommands")
    for command, description in COMMANDS.items():
        subparser = subcommands.add_parser(command, help=description, description=description)
        _add_global_flags(subparser, suppress_defaults=True)
        if command == "setup":
            subparser.add_argument("--check", action="store_true", help="check local configuration")
        elif command == "search":
            subparser.add_argument("query", nargs="?", default=None, help="text to search for")
        elif command == "show":
            subparser.add_argument("repo", help="GitHub owner/repository")
    return parser


def _setup_check() -> int:
    config = load_config()
    print("config: {}".format(sanitize(str(env_path()))))
    print("configured entries: {}".format(len(config)))
    print("setup check passed")
    return 0


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
    return sys.stdout.isatty() and not getattr(arguments, "no_color", False)


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
        rendered.append(color(text, _BADGE_COLORS.get(text, "36"), enabled))
    return ",".join(rendered)


def _render_ranked(repos: List[dict], arguments: argparse.Namespace) -> None:
    enabled = _color_enabled(arguments)
    for repo in repos:
        print("{:.2f}  {}  {}  {}".format(
            _finite(repo.get("score")), _safe(repo.get("name", "")),
            _safe(repo.get("category", "uncategorized")), _render_badges(repo.get("badges"), enabled),
        ).rstrip())


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


def _render_single_source(records: List[dict], metric: Callable[[dict], Tuple[str, float]]) -> None:
    for record in records:
        label, value = metric(record)
        line = "{} {}  {}".format(_safe(label), _format_number(value), _safe(record.get("name", "")))
        excerpt = _short_excerpt(record)
        print("{}  — {}".format(line, excerpt) if excerpt else line)


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
    limit = arguments.limit if arguments.limit is not None else 50
    if limit < 0:
        print("limit must be zero or greater", file=sys.stderr)
        return None
    return limit


def _single_source(command: str, arguments: argparse.Namespace) -> int:
    sources: Dict[str, Tuple[Any, Callable[[dict], Tuple[str, float]]]] = {
        "hn": (hn, _signal_metric("hn_points")),
        "npm": (npm, _signal_metric("npm_growth", "npm_downloads_week")),
        "stars": (github, _signal_metric("stars")),
        "trending": (trends, _trend_metric),
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
            _render_single_source(usable[:limit], metric)
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


def _show_repo(repo: dict, arguments: argparse.Namespace) -> None:
    enabled = _color_enabled(arguments)
    print(_safe(repo.get("name", "")))
    print("repository: {}".format(_safe(repo.get("canonical_repo", ""))))
    print("category: {}".format(_safe(repo.get("category", "uncategorized"))))
    print("score: {:.2f}".format(_finite(repo.get("score"))))
    print("momentum: {:.2f}".format(_finite(repo.get("momentum"))))
    print("credibility: {:.2f}".format(_finite(repo.get("credibility"))))
    print("signal_score: {:.2f}".format(_finite(repo.get("signal_score"))))
    print("corroboration: {:.2f}".format(_finite(repo.get("corroboration"))))
    print("freshness_factor: {:.2f}".format(_finite(repo.get("freshness_factor"))))
    freshness_days = repo.get("freshness_days")
    print("freshness_days: {}".format("unknown" if freshness_days is None else "{:.2f}".format(_finite(freshness_days))))
    print("badges: {}".format(_render_badges(repo.get("badges"), enabled) or "none"))
    print("signals:")
    by_source = repo.get("signal_by_source") if isinstance(repo.get("signal_by_source"), dict) else {}
    for source in sorted(by_source, key=str):
        print("  {}:".format(_safe(source)))
        signal = by_source[source]
        if isinstance(signal, dict):
            for key in sorted(signal, key=str):
                value = signal[key]
                rendered = _safe(value) if isinstance(value, str) else _format_number(value)
                print("    {}: {}".format(_safe(key), rendered))


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    command = arguments.command or "hot"
    if command == "setup" and arguments.check:
        code = _setup_check()
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
    if command in {"hn", "npm", "stars", "trending", "reddit", "youtube"}:
        return _single_source(command, arguments)
    if command == "hot":
        limit = _normal_limit(arguments)
        if limit is None:
            return 2
        config = load_config()
        with _cache_session() as cache:
            statuses = engine.fetch_all(config, limit=limit, cache=cache)
            cached = cache.get_all()
            ranked = engine.rank(engine.merge_by_repo(cached), limit=limit)
            exit_code, message = health.summarize(statuses, cache_has_data=bool(cached))
            if arguments.json:
                _dump_json({"tools": ranked, "sources": [{"source": status.source, "status": status.status, "detail": status.detail} for status in statuses]})
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
            ranked = engine.rank(engine.merge_by_repo(cache.search(arguments.query)), limit=limit)
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
                    print("{} is not in the local cache yet — run `hotin hot` first to populate it.".format(_safe(arguments.repo)))
            else:
                scored = engine.score_repo(repo)
                if arguments.json:
                    _dump_json(scored)
                else:
                    _show_repo(scored, arguments)
            _attribution(arguments)
            return 0
    if command == "update":
        limit = _normal_limit(arguments)
        if limit is None:
            return 2
        with _cache_session() as cache:
            statuses = engine.fetch_all(load_config(), limit=limit, cache=cache, ttl=0)
            exit_code, message = health.summarize(statuses, cache_has_data=bool(cache.get_all()))
            if arguments.json:
                _dump_json({"sources": [{"source": status.source, "status": status.status, "detail": status.detail} for status in statuses]})
            else:
                for status in statuses:
                    detail = " — {}".format(_safe(status.detail)) if status.detail else ""
                    print("{}  {}{}".format(_safe(status.source), _safe(status.status), detail))
            if exit_code:
                print(_safe(message), file=sys.stderr)
            _attribution(arguments)
        # Like `hot`: adapters can leave non-daemon network workers behind after
        # the fetch deadline (e.g. a source still inside urlopen, or a throttle
        # honoring a long server retry delay), which would otherwise block a
        # normal interpreter exit for seconds to minutes. os._exit skips that join.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
        return exit_code  # Allows unit tests to substitute os._exit().
    print("{}: not yet implemented".format(command))
    return 0


if __name__ == "__main__":
    sys.exit(main())
