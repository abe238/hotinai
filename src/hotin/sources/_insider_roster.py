"""Shared roster-polling core for the AI-insiders signal.

Replaces the two dead digg.com scrapers (``smartmoney.py`` and ``insiders.py``,
both blocked behind a site-wide bot checkpoint). Instead of asking a third-party
site "who are the insiders and what did they star", we hold a curated roster of
known AI-community GitHub accounts and read each one's OWN recently-starred repos
straight from the sanctioned GitHub API (``GET /users/{username}/starred`` with
the ``star+json`` media type, which carries a ``starred_at`` timestamp the plain
endpoint omits).

Directionality matters: GitHub restricted the REVERSE lookup
(``/repos/{owner}/{repo}/stargazers``, admins/collaborators only since
2026-06-30) but the FORWARD lookup (a user's own stars) is unrestricted. This
core only ever uses the forward direction.

Both ``smartmoney.py`` and ``insiders.py`` are now thin shape-mappers over ONE
call to :func:`poll_roster` per process — the result is memoized module-side so
a single ``hotin`` invocation never polls the same roster twice, even though the
two adapters are called from different points in the pipeline.

Best-effort like every adapter: a per-user failure (renamed/suspended/deleted
account, transient error) skips that user, never raises. A missing GITHUB_TOKEN
is a LOUD error (unauthenticated calls silently degrade to 60/hr and would pass
locally while failing intermittently in CI), not a silent fallback.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from hotin.canonical import canonicalize
from hotin.coerce import finite_int
from hotin.throttle import Throttle

# The seed roster: known AI-community GitHub accounts. Hand-curated; L2's
# discovery pipeline grows it over time via a review queue, but the feature must
# not depend on L2 existing yet, so this is a real starting set, not a stub.
# A module constant (not a packaged data file) deliberately: the project has no
# package-data config, so a src/hotin/data/*.json would load editable but be
# ABSENT from the PyPI wheel — the exact works-editable-breaks-installed failure
# the export path bug already cost us once. Override at runtime with the config
# key HOTIN_INSIDER_ROSTER_PATH (a newline- or comma-separated list of handles).
SEED_ROSTER: Tuple[str, ...] = (
    # --- Recovered from our own observation store (~/.local/share/hotin/cache.db,
    # 274 cached insiders/smartmoney rows). This is the real surviving trace of
    # digg's AI-1000 cohort: 63 distinct handles were captured across all the
    # repos we ever tracked, of which these 35 resolve as genuine GitHub
    # accounts. The other 28 are X/Twitter handles -- digg's list was
    # social-graph based, so a chunk of it never had a GitHub identity attached
    # in the data we saw. We never held the full 1000: their page only exposed
    # the top ~12 starrers per repo, never the underlying roster.
    "ChowdhuryNeil", "DynamicWebPaige", "MilesCranmer", "PMinervini",
    "VictorTaelin", "altryne", "antgoldbloom", "antimatter15", "backpropper",
    "davemorin", "deepfates", "ggerganov", "hmason", "jmtomczak", "jsngr",
    "kepano", "leloykun", "lintool", "marksaroufim", "mayfer", "mckaywrigley",
    "mrdrozdov", "peterjliu", "quasimondo", "samsja19", "simonw", "skirano",
    "smolix", "steipete", "syhw", "theo", "thesephist", "wongmjane",
    "yisongyue", "yuntiandeng",
    # --- Hand-added known AI-community accounts, to broaden coverage beyond
    # whatever digg happened to surface on our board.
    "karpathy", "jeremyphoward", "rasbt", "clefourrier", "Tostino", "abetlen",
    "tomaarsen", "vikhyat", "huybery", "winglian", "teknium1", "Vaibhavs10",
    "philschmid", "osanseviero", "julien-c", "thomwolf", "lvwerra",
    "natolambert", "soumith", "lhoestq",
)

# GitHub with a token sustains 5000/hr — nothing like the politeness pacing the
# digg scrapers needed. A light interval keeps roster growth from feeling broken
# (a 50-person roster at 3s/user would cost 150s+ per poll); secondary-rate-limit
# backoff via wait_for_retry_after handles the real ceiling.
_THROTTLE = Throttle(min_interval=0.2, jitter=0.1)
_USER_AGENT = "hotin (+https://hotin.ai)"
_STAR_MEDIA_TYPE = "application/vnd.github.star+json"
_API = "https://api.github.com"
_PER_PAGE = 100
_MAX_PAGES = 3  # 300 most-recent stars per user; the window rarely reaches it


class MissingTokenError(RuntimeError):
    """Raised when no GITHUB_TOKEN is configured — a loud failure, not silent."""


class RosterAuthError(RuntimeError):
    """Raised when a configured token is rejected (401) for the ENTIRE roster —
    a broken/revoked token must be loud, not a silent empty result that reads
    like "nobody starred anything" (a recurring real-world failure mode)."""


def _token(config: Optional[dict]) -> str:
    token = (config or {}).get("GITHUB_TOKEN")
    if not isinstance(token, str) or not token.strip():
        raise MissingTokenError(
            "no GITHUB_TOKEN configured; the insiders roster poll needs an "
            "authenticated token (unauthenticated calls degrade to 60/hr)"
        )
    return token.strip()


def _roster(config: Optional[dict]) -> Tuple[str, ...]:
    """The active roster: the config override if present, else the seed."""
    raw = (config or {}).get("HOTIN_INSIDER_ROSTER_PATH")
    if isinstance(raw, str) and raw.strip():
        # The override value is a literal list of handles (newline/comma sep),
        # OR a path to a file of the same. Try file first, fall back to literal.
        text = raw
        try:
            with open(raw.strip(), "r", encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, ValueError):
            pass
        names = [n.strip() for n in re.split(r"[\s,]+", text) if n.strip()]
        if names:
            # dedupe, preserve order
            seen: Dict[str, None] = {}
            for n in names:
                seen.setdefault(n, None)
            return tuple(seen)
    return SEED_ROSTER


def _fresh(starred_at: Any, *, window_days: int, now: Optional[datetime]) -> bool:
    if not isinstance(starred_at, str) or not starred_at.strip():
        return False
    try:
        parsed = datetime.fromisoformat(starred_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return parsed >= reference - timedelta(days=window_days)


def _retry_seconds(value: Any) -> Optional[float]:
    """Parse a Retry-After header. HTTP allows an integer-seconds OR an
    HTTP-date; we only honor the numeric form and ignore the date rather than
    crashing the poll on a ValueError (the whole point of skipping cleanly)."""
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _poll_one(
    username: str, token: str, *, window_days: int, now: Optional[datetime]
) -> Tuple[List[Dict[str, Any]], bool]:
    """One user's recently-starred repos, star+json, capped and windowed.

    Returns ``(events, auth_failed)``. Never raises — a bad account must not take
    down the whole roster poll. ``auth_failed`` is True only for a 401 (bad/
    revoked credentials); the caller uses it to distinguish "token is broken for
    everyone" (loud error) from "this one user had no stars / is gone" (silent).
    """
    out: List[Dict[str, Any]] = []
    for page in range(1, _MAX_PAGES + 1):
        url = (
            "{api}/users/{user}/starred?sort=created&direction=desc"
            "&per_page={pp}&page={page}".format(
                api=_API, user=urllib.parse.quote(username), pp=_PER_PAGE, page=page
            )
        )
        request = urllib.request.Request(
            url,
            headers={
                "Accept": _STAR_MEDIA_TYPE,
                "Authorization": "Bearer {}".format(token),
                "User-Agent": _USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            _THROTTLE.wait()
            with urllib.request.urlopen(request, timeout=30) as response:
                retry_after = _retry_seconds(response.headers.get("Retry-After"))
                if retry_after is not None:
                    _THROTTLE.wait_for_retry_after(retry_after)
                entries = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:  # bad/revoked token — the caller must see this
                return out, True
            if exc.code in (403, 429):  # secondary rate limit — back off, stop this user
                retry = _retry_seconds(exc.headers.get("Retry-After")) if exc.headers else None
                if retry is not None:
                    _THROTTLE.wait_for_retry_after(retry)
            return out, False  # 404/410/etc: renamed/suspended/deleted — skip cleanly
        except Exception:
            return out, False
        if not isinstance(entries, list) or not entries:
            break
        stop = False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            starred_at = entry.get("starred_at")
            repo = entry.get("repo")
            if not isinstance(repo, dict):
                continue
            # sort=created desc => once we cross the window edge, everything after
            # is older too. Stop paginating (L0 confirmed the descending order).
            if not _fresh(starred_at, window_days=window_days, now=now):
                stop = True
                break
            canonical = canonicalize(repo.get("full_name"))
            if not canonical:
                continue
            out.append({
                "username": username,
                "canonical_repo": canonical,
                "starred_at": starred_at,
                "stargazers_count": finite_int(repo.get("stargazers_count"), 0),
                "description": repo.get("description")
                if isinstance(repo.get("description"), str) else None,
            })
        if stop or len(entries) < _PER_PAGE:
            break
    return out, False


# Module-level memoization: one poll per process. The two adapters are called
# from different pipeline points (engine.fetch_all vs _export vs `hotin insiders`)
# so an in-process cache spans what a per-call cache cannot. NOT once-per-cycle:
# `hotin refresh` and `hotin export` are two processes, so a 3h cycle polls twice
# — negligible at roster scale, documented rather than chased.
_MEMO: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}


def poll_roster(
    config: Optional[dict] = None,
    *,
    window_days: int = 7,
    now: Optional[datetime] = None,
    _force: bool = False,
) -> List[Dict[str, Any]]:
    """Poll every roster member's recently-starred repos, memoized per process.

    Returns a flat list of ``{username, canonical_repo, starred_at,
    stargazers_count, description}`` star events within ``window_days``. Raises
    :class:`MissingTokenError` if no token is configured, or
    :class:`RosterAuthError` if a present token is rejected (401) for every
    roster member — both loud, never a silent empty.
    """
    roster = _roster(config)
    key = (roster, window_days, now.isoformat() if now else None)
    if not _force and key in _MEMO:
        return _MEMO[key]
    token = _token(config)  # raises loudly before any network work
    events: List[Dict[str, Any]] = []
    auth_failures = 0
    for username in roster:
        user_events, auth_failed = _poll_one(
            username, token, window_days=window_days, now=now)
        events.extend(user_events)
        if auth_failed:
            auth_failures += 1
    # Every single member's request was 401-rejected => the token is broken, not
    # "nobody starred anything". Fail loud rather than cache/return an empty.
    if roster and auth_failures == len(roster):
        raise RosterAuthError(
            "GITHUB_TOKEN rejected (401) for all {} roster members — "
            "the token is invalid, revoked, or expired".format(len(roster)))
    _MEMO[key] = events
    return events


def aggregate_by_repo(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fold flat star events into per-repo records the adapters both build on.

    One repo may be starred by several roster members; we keep the distinct
    starrer count, the union of their usernames, and the most-recent star time.
    Ordered by distinct-starrer count desc, then repo id, for stable output.
    """
    by_repo: Dict[str, Dict[str, Any]] = {}
    for event in events:
        repo = event.get("canonical_repo")
        if not repo:
            continue
        rec = by_repo.setdefault(repo, {
            "canonical_repo": repo,
            "starrers": [],
            "most_recent_star_at": None,
            "stargazers_count": 0,
            "description": None,
        })
        user = event.get("username")
        if user and user not in rec["starrers"]:
            rec["starrers"].append(user)
        starred_at = event.get("starred_at")
        if isinstance(starred_at, str) and (
            rec["most_recent_star_at"] is None or starred_at > rec["most_recent_star_at"]
        ):
            rec["most_recent_star_at"] = starred_at
        rec["stargazers_count"] = max(
            rec["stargazers_count"], finite_int(event.get("stargazers_count"), 0)
        )
        if rec["description"] is None and event.get("description"):
            rec["description"] = event["description"]
    return sorted(
        by_repo.values(),
        key=lambda r: (-len(r["starrers"]), r["canonical_repo"]),
    )


def _reset_memo() -> None:
    """Test hook: clear the per-process memo."""
    _MEMO.clear()
