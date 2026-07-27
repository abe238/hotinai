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
from hotin.sources import _roster_data
from hotin.throttle import Throttle

# The seed roster: known AI-community GitHub accounts. Hand-curated; L2's
# discovery pipeline grows it over time via a review queue, but the feature must
# not depend on L2 existing yet, so this is a real starting set, not a stub.
# A module constant (not a packaged data file) deliberately: the project has no
# package-data config, so a src/hotin/data/*.json would load editable but be
# ABSENT from the PyPI wheel — the exact works-editable-breaks-installed failure
# the export path bug already cost us once. Override at runtime with the config
# key HOTIN_INSIDER_ROSTER_PATH (a newline- or comma-separated list of handles).
# The roster and its provenance live in _roster_data.py (data, not logic) so the
# methodology stays auditable and regenerable. See that module's docstring for
# how each tier was derived and why the size is what it is.
SEED_ROSTER: Tuple[str, ...] = _roster_data.ROSTER

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


class RosterRateLimitError(RuntimeError):
    """Raised when enough of the roster was rate-limited that the poll no longer
    describes reality.

    401 was loud from the start; 403/429 was not, and that asymmetry was wrong.
    A rate-limited account returns zero stars, which is byte-identical to an
    account that genuinely starred nothing — so an exhausted token produced a
    small, plausible, entirely fictional board while every status line said
    "ok". It cost three separate misdiagnoses (a "cold store", a "cap-then-
    filter" bug, an "ordering" bug) before the real cause was traced.

    Live case: hotin.ai's CI authenticates with ``github.token``, capped at
    1,000 REST requests/hour/repo, while one cycle polls the roster twice
    (refresh + export) at ~793 accounts each. On the normal 3-hour cadence that
    fits. Two runs inside one hour cannot, and the second silently produced 3
    rows where the first produced 60.

    Partial rate limiting is normal and tolerated; the threshold is about
    whether the RESULT is still trustworthy, not whether anything went wrong."""


# What a single account's poll tells us. Three outcomes, because "no stars"
# and "not allowed to look" must never collapse into the same value again.
_OK = "ok"
_AUTH_FAILED = "auth_failed"
_RATE_LIMITED = "rate_limited"

# Fraction of the roster that may be rate-limited before the poll is refused.
#
# Set high on purpose. The hard gate in CI already catches a collapsed board, so
# this guard's job is to name the CAUSE, not to be a second gate -- and a tight
# threshold here would trade a silent failure for a noisy one, blocking healthy
# runs on routine partial limiting. Above half the cohort the result is not a
# degraded board, it is a different board, and publishing it would be a lie.
#
# Deliberately NOT derived from an assumed hourly quota: the real budget for
# CI's token could not be verified from outside, so the poll now REPORTS the
# quota it saw (see _RATE_LIMIT_SEEN) instead of inferring one.
_RATE_LIMIT_TOLERANCE = 0.50

# Last rate-limit headers observed, so a run can say what the budget actually
# was rather than guessing. Populated opportunistically; empty is normal.
_RATE_LIMIT_SEEN: Dict[str, Any] = {}


def _note_quota(headers: Any) -> None:
    """Record GitHub's own rate-limit headers. Never raises: this is diagnostics,
    and diagnostics must not be able to break the thing they describe."""
    try:
        for header, key in (("X-RateLimit-Limit", "limit"),
                            ("X-RateLimit-Remaining", "remaining"),
                            ("X-RateLimit-Reset", "reset")):
            value = headers.get(header)
            if value is not None:
                _RATE_LIMIT_SEEN[key] = value
    except Exception:
        pass


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
        # Strip `#` comments FIRST: a roster file usually carries a header, and
        # splitting on whitespace before stripping turns every comment word into
        # a bogus handle (a real bug this caught: 26 phantom entries).
        text = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
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


# How much a brand-new repo is lifted over one sitting at the age cap.
FRESH_BOOST = 0.66
# Repo age at which the boost has fully decayed. Matches the board's age cap, so
# a repo on the edge of being filtered out gets no boost rather than a cliff.
FRESH_FULL_DECAY_DAYS = 180.0


def _repo_age_days(created_at: Any, now: Optional[datetime] = None) -> Optional[float]:
    """Repo age in days, or None when the creation date is unknown."""
    if not isinstance(created_at, str) or not created_at.strip():
        return None
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max(0.0, (reference - parsed).total_seconds() / 86400.0)


def score_record(weight: float, created_at: Any, now: Optional[datetime] = None) -> float:
    """Board score: consensus with diminishing returns, lifted by freshness.

        score = sqrt(weight) * (1 + FRESH_BOOST * (1 - age/FRESH_FULL_DECAY_DAYS))

    Two deliberate choices:

    ``sqrt(weight)`` gives insider consensus **diminishing returns**. Raw weight
    spans 1..6+ while the freshness factor only spans 1.0..1.66, so multiplying
    the two leaves consensus in charge and freshness as decoration. Compressing
    the weight term is what actually lets freshness outrank one extra insider,
    which is the intended ordering ("starring matters, but a bit less than
    freshness"). It is also the honest shape for votes: the 6th insider on a
    repo tells you less than the 2nd did.

    An unknown creation date scores as fully decayed (factor 1.0) rather than
    fresh. Missing data must never look like a brand-new repo -- that is exactly
    the failure that put 1077-day-old repos on the board.
    """
    fresh = 1.0
    age = _repo_age_days(created_at, now)
    if age is not None:
        fresh += FRESH_BOOST * max(0.0, 1.0 - age / FRESH_FULL_DECAY_DAYS)
    return (max(0.0, float(weight)) ** 0.5) * fresh


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
                _note_quota(response.headers)
                retry_after = _retry_seconds(response.headers.get("Retry-After"))
                if retry_after is not None:
                    _THROTTLE.wait_for_retry_after(retry_after)
                entries = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:  # bad/revoked token — the caller must see this
                return out, _AUTH_FAILED
            if exc.code in (403, 429):  # rate limited — back off, and SAY SO
                _note_quota(exc.headers)
                retry = _retry_seconds(exc.headers.get("Retry-After")) if exc.headers else None
                if retry is not None:
                    _THROTTLE.wait_for_retry_after(retry)
                # Reporting this is the whole point: an empty result here means
                # "we were not allowed to look", not "there was nothing to see".
                return out, _RATE_LIMITED
            return out, _OK  # 404/410/etc: renamed/suspended/deleted — skip cleanly
        except Exception:
            return out, _OK
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
                # The repo's own creation date, straight from this response. It
                # was always here -- the board previously sourced it from a
                # separate backfill capped at 40 repos/run, so freshly-surfaced
                # rows had no date and any age filter silently dropped 100% of
                # them. Taking it at poll time makes repo age usable on the
                # first sighting instead of eight runs later.
                "repo_created_at": repo.get("created_at")
                if isinstance(repo.get("created_at"), str) else None,
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
    window_days: int = 30,
    now: Optional[datetime] = None,
    _force: bool = False,
) -> List[Dict[str, Any]]:
    """Poll every roster member's recently-starred repos, memoized per process.

    The 30-day default window is measured, not guessed. Notable people star
    rarely, so a 7-day window sampled almost nobody: across a 797-account cohort
    it found 93 events from 36 people (4.5% participation), and a single
    hyperactive account was 43% of the entire signal. Widening to 30 days gave
    352 events from 87 people (10.9%), 301 distinct repos, and dropped that
    account's share to 30% -- not by penalising anyone, but because the rest of
    the cohort finally appeared. Costs nothing extra: the per-user page cap
    already bounds the work.

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
    rate_limited = 0
    for username in roster:
        user_events, outcome = _poll_one(
            username, token, window_days=window_days, now=now)
        events.extend(user_events)
        if outcome == _AUTH_FAILED:
            auth_failures += 1
        elif outcome == _RATE_LIMITED:
            rate_limited += 1
    # Every single member's request was 401-rejected => the token is broken, not
    # "nobody starred anything". Fail loud rather than cache/return an empty.
    if roster and auth_failures == len(roster):
        raise RosterAuthError(
            "GITHUB_TOKEN rejected (401) for all {} roster members — "
            "the token is invalid, revoked, or expired".format(len(roster)))
    # Enough of the cohort was unreachable that the result no longer describes
    # reality. Fail loudly instead of caching a small, plausible, wrong board.
    if roster and rate_limited > _RATE_LIMIT_TOLERANCE * len(roster):
        quota = ""
        if _RATE_LIMIT_SEEN:
            quota = " GitHub reported limit={limit} remaining={remaining}.".format(
                limit=_RATE_LIMIT_SEEN.get("limit", "?"),
                remaining=_RATE_LIMIT_SEEN.get("remaining", "?"))
        raise RosterRateLimitError(
            "{} of {} roster members were rate-limited (403/429) — this poll saw "
            "only part of the cohort and must not be published.{} A cycle polls "
            "the roster once per process and `refresh`/`export` are two "
            "processes, so back-to-back runs cost roughly twice a single "
            "cycle.".format(rate_limited, len(roster), quota))
    _MEMO[key] = events
    return events


def load_weights(config: Optional[dict] = None) -> Tuple[Dict[str, float], float]:
    """Per-account weights, if any: ``({handle_lower: weight}, default)``.

    Not every roster member is equally informative, and treating them as equal
    is its own editorial choice. Point HOTIN_INSIDER_WEIGHTS_PATH at a JSON file
    to say so explicitly::

        {"default": 1.0, "weights": {"someone": 3.5, "someone-else": 0.5}}

    or just ``{"someone": 3.5}`` with the default left at 1.0. Unlisted members
    get the default, so a partial file is fine. Absent entirely, every member
    weighs 1.0 and the behaviour is exactly as before.
    """
    raw = (config or {}).get("HOTIN_INSIDER_WEIGHTS_PATH")
    if not isinstance(raw, str) or not raw.strip():
        return {}, 1.0
    try:
        with open(raw.strip(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}, 1.0
    if not isinstance(data, dict):
        return {}, 1.0
    table = data.get("weights") if isinstance(data.get("weights"), dict) else data
    default = data.get("default", 1.0)
    try:
        default = float(default)
    except (TypeError, ValueError):
        default = 1.0
    out: Dict[str, float] = {}
    for name, value in table.items():
        if name in ("default", "weights") or not isinstance(name, str):
            continue
        try:
            out[name.lower()] = float(value)
        except (TypeError, ValueError):
            continue
    return out, default


def aggregate_by_repo(
    events: List[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
    default_weight: float = 1.0,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Fold flat star events into per-repo records the adapters both build on.

    One repo may be starred by several roster members; we keep the distinct
    starrer count, the union of their usernames, and the most-recent star time.

    ``weight`` is the sum of each distinct starrer's weight (all 1.0 unless a
    weights table is supplied), so with no weights it equals the starrer count.

    ``score`` is what the board actually orders on: ``sqrt(weight)`` lifted by a
    freshness factor (see :func:`score_record`). Weight remains on the record
    because the display layer and the ledger both report raw consensus -- the
    number a reader can verify by counting receipt chips -- while ``score`` is
    the ranking function and may change without changing what we claim.

    ``now`` is injectable so tests can pin the freshness curve instead of
    depending on the wall clock.
    """
    weights = weights or {}
    by_repo: Dict[str, Dict[str, Any]] = {}
    for event in events:
        repo = event.get("canonical_repo")
        if not repo:
            continue
        rec = by_repo.setdefault(repo, {
            "canonical_repo": repo,
            "starrers": [],
            "most_recent_star_at": None,
            "repo_created_at": None,
            "stargazers_count": 0,
            "description": None,
        })
        if rec["repo_created_at"] is None and event.get("repo_created_at"):
            rec["repo_created_at"] = event["repo_created_at"]
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
    for rec in by_repo.values():
        rec["weight"] = round(
            sum(weights.get(u.lower(), default_weight) for u in rec["starrers"]), 3)
        rec["score"] = round(score_record(rec["weight"], rec["repo_created_at"], now), 4)
    return sorted(
        by_repo.values(),
        key=lambda r: (-r["score"], -r["weight"], -len(r["starrers"]), r["canonical_repo"]),
    )


def _reset_memo() -> None:
    """Test hook: clear the per-process memo."""
    _MEMO.clear()
