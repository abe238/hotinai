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
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from hotin.canonical import canonicalize
from hotin.coerce import finite_int
from hotin.sources import _roster_data
from hotin.sources import _roster_graphql as _gql
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

#: Last poll's per-outcome tally, for the run summary and drift alerting (L5).
LAST_OUTCOMES: Dict[str, int] = {}


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
    # _OK, not False. The three-state contract used to be enforced by exclusion
    # ("not auth_failed and not rate_limited"), so a falsy success value was
    # harmless. It stopped being harmless the moment a caller mapped outcomes by
    # NAME: `False` fell through to UNRESOLVED and silently discarded every
    # successful REST-fallback poll. Returning the real state closes that.
    return out, _OK


#: Wall-clock ceiling for bisection retries within one batch. Without it, a
#: sustained 502 storm could bisect its way past the REST baseline it is
#: supposed to degrade *to*.
#: Bounded retries for a TRANSIENT secondary rate limit (403/429 + Retry-After).
#: Distinct from bisection: the batch size is not the problem, the pace is.
_RATE_LIMIT_RETRIES = 3
_BISECT_SECONDS = 90.0
_BISECT_ATTEMPTS = 4


#: Per-account REST polls run on a small worker pool. The shared _THROTTLE is
#: locked, so the pool overlaps network latency without adding requests or
#: beating the pacing; 1 restores the serial loop. Env, not config: the two
#: REST sites sit below every config-carrying signature.
_WORKERS_ENV = "HOTIN_INSIDERS_WORKERS"
_DEFAULT_WORKERS = 4


def _workers() -> int:
    try:
        return max(1, int(os.environ.get(_WORKERS_ENV, _DEFAULT_WORKERS)))
    except (TypeError, ValueError):
        return _DEFAULT_WORKERS


def _poll_many(logins: Sequence[str], token: str, *, window_days: int,
               now: Optional[datetime]) -> Dict[str, Tuple[List[Dict[str, Any]], bool]]:
    """``{login: _poll_one(login)}`` in roster order, on ``_workers()`` threads.

    Same requests as the serial loop, one _poll_one per login; only the wall
    clock changes. Result order is the input order (executor.map), so every
    downstream tally and aggregation is byte-identical to a serial run.
    """
    def one(login: str) -> Tuple[List[Dict[str, Any]], bool]:
        return _poll_one(login, token, window_days=window_days, now=now)

    logins = list(logins)
    workers = min(_workers(), len(logins))
    if workers <= 1:
        return {login: one(login) for login in logins}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip(logins, pool.map(one, logins)))


def _rest_floor(logins: Sequence[str], token: str, *, window_days: int,
                now: Optional[datetime]) -> Dict[str, Dict[str, Any]]:
    """Per-account REST poll: the backstop the batch path degrades to.

    Kept rather than deleted precisely so the batched path always has somewhere
    honest to fall to -- a too-heavy batch, or a credential GraphQL refuses.
    """
    results: Dict[str, Dict[str, Any]] = {}
    for login, (events, outcome) in _poll_many(
            logins, token, window_days=window_days, now=now).items():
        mapped = {_OK: _gql.OK, _AUTH_FAILED: _gql.AUTH_FAILED,
                  _RATE_LIMITED: _gql.RATE_LIMITED}.get(outcome, _gql.UNRESOLVED)
        results[login] = {"login": login, "events": events, "outcome": mapped,
                          "needs_rest": False, "detail": "rest"}
    return results


def _poll_batch_tree(
    logins: Sequence[str], token: str, *, window_days: int,
    now: Optional[datetime], stars: int, deadline: float, depth: int = 0,
) -> Dict[str, Dict[str, Any]]:
    """One batch, halving on a too-heavy response, REST at the floor.

    Halving is on USER COUNT, the named axis, because that is the dimension the
    measured cliff moves with (25x20 clean 5/5, 40x20 corrupt 5/5 at the SAME
    star count). Bounded by attempts and a deadline so the degrade path can
    never cost more than the REST baseline it falls back to.
    """
    logins = list(logins)
    if not logins:
        return {}

    # The floor applies only AFTER halving. On the first attempt GraphQL is the
    # primary path regardless of batch size -- gating it on size meant a roster
    # smaller than the floor never used the primary path at all.
    too_small = depth > 0 and len(logins) <= _gql.MIN_BATCH_USERS
    out_of_budget = depth >= _BISECT_ATTEMPTS or time.monotonic() > deadline
    if not (too_small or out_of_budget):
        # PACE THE REQUESTS. The REST path always did this and never tripped a
        # secondary limit; the first GraphQL build omitted it and CI came back
        # with 618 of 793 accounts rate-limited while GitHub still reported
        # remaining=4983. Nearly the whole quota was intact -- the 403s were
        # ABUSE DETECTION on a burst of 32 heavy queries fired back to back, not
        # exhaustion. Batching made each request cheaper in points and heavier in
        # server work, so pacing matters MORE here than it did per-account.
        _THROTTLE.wait()
        _t0 = time.monotonic()
        payload, status, headers = _gql.post(_gql.build_query(logins, stars), token)
        if headers is not None:
            _note_quota(headers)
        _gql.BATCH_TRACE.append({
            "n": len(logins), "depth": depth, "status": status,
            "secs": round(time.monotonic() - _t0, 1),
            "retry_after": (headers or {}).get("Retry-After") if headers else None,
            "gql_remaining": _gql.points_remaining(payload),
            "err": (payload.get("errors") or [{}])[0].get("type")
                   if isinstance(payload, dict) and payload.get("errors") else None,
        })
        if status == 401:
            return {u: {"login": u, "events": [], "outcome": _gql.AUTH_FAILED,
                        "needs_rest": False, "detail": "401"} for u in logins}
        if status in (403, 429):
            # A secondary limit is TRANSIENT and carries Retry-After, so back off
            # and retry the SAME batch: condemning it outright turned a
            # recoverable pause into 618 lost accounts. Retry in a bounded loop
            # rather than by recursing -- recursion raised `depth`, which then
            # read as "out of bisection budget" and dropped the batch through to
            # the REST floor, firing 25 MORE requests at a server that had just
            # asked us to slow down.
            for _ in range(_RATE_LIMIT_RETRIES):
                if time.monotonic() > deadline:
                    break
                retry = _retry_seconds(headers.get("Retry-After")) if headers else None
                _THROTTLE.wait_for_retry_after(retry if retry is not None else 2.0)
                _THROTTLE.wait()
                payload, status, headers = _gql.post(
                    _gql.build_query(logins, stars), token)
                if headers is not None:
                    _note_quota(headers)
                if status not in (403, 429):
                    break
            if status in (403, 429):
                body = _gql.LAST_ERROR_BODY[-1] if _gql.LAST_ERROR_BODY else None
                if _gql.is_secondary_rate_limit(body):
                    # A real limit: say so, and do NOT fall through to REST.
                    # More requests is the one thing that cannot help.
                    return {u: {"login": u, "events": [], "outcome": _gql.RATE_LIMITED,
                                "needs_rest": False, "detail": str(status)}
                            for u in logins}
                # A 403 that is NOT a rate limit means this credential cannot use
                # GraphQL (an unscoped classic PAT is refused by the GraphQL API
                # while still serving public REST reads perfectly). REST is not
                # "more load" in that case, it is the working path -- and this is
                # exactly the shape production showed: 693 accounts refused while
                # 4,879 of 5,000 points sat unused, on a token that reads public
                # data over REST all day.
                return _rest_floor(logins, token, window_days=window_days, now=now)
            if status == 401:
                return {u: {"login": u, "events": [], "outcome": _gql.AUTH_FAILED,
                            "needs_rest": False, "detail": "401"} for u in logins}
        shrink = status in _gql.TOO_HEAVY or (
            payload is not None and _gql.is_resource_limited(payload))
        if not shrink and payload is not None:
            remaining = _gql.points_remaining(payload)
            if remaining is not None:
                # GraphQL reports its own pool. Never invent a `limit` here --
                # reporting a number GitHub did not say is what this whole
                # mechanism exists to stop.
                _RATE_LIMIT_SEEN["remaining"] = remaining
            return _gql.parse_batch(payload, logins, window_days=window_days,
                                    now=now, fresh_fn=_fresh)
        if not shrink:
            # Unparseable body: retry once smaller rather than condemn the batch.
            shrink = True
        if shrink and len(logins) > _gql.MIN_BATCH_USERS:
            mid = len(logins) // 2
            merged: Dict[str, Dict[str, Any]] = {}
            for half in (logins[:mid], logins[mid:]):
                merged.update(_poll_batch_tree(
                    half, token, window_days=window_days, now=now, stars=stars,
                    deadline=deadline, depth=depth + 1))
            return merged

    return _rest_floor(logins, token, window_days=window_days, now=now)


def _poll_via_graphql(
    roster: Sequence[str], token: str, *, window_days: int,
    now: Optional[datetime],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Poll the whole roster in batches. Returns ``(events, outcome_tally)``."""
    events: List[Dict[str, Any]] = []
    tally: Dict[str, int] = {}
    remaining_budget: Optional[int] = None
    pending = list(roster)

    for batch in _gql.batches(pending, _gql.BATCH_USERS):
        # L4: stop BEFORE spending the last of the pool, and write an explicit
        # rate_limited row for everything we did not reach. Skipping them would
        # make "not looked at" indistinguishable from "starred nothing".
        # _RATE_LIMIT_SEEN is fed from BOTH HTTP headers (strings) and the
        # GraphQL rateLimit block (ints), so coerce rather than compare raw.
        budget = finite_int(remaining_budget, -1) if remaining_budget is not None else -1
        if budget >= 0 and budget < _gql.POINTS_FLOOR:
            for login in batch:
                tally[_gql.RATE_LIMITED] = tally.get(_gql.RATE_LIMITED, 0) + 1
            continue
        results = _poll_batch_tree(
            batch, token, window_days=window_days, now=now,
            stars=_gql.BATCH_STARS,
            deadline=time.monotonic() + _BISECT_SECONDS)
        remaining_budget = _RATE_LIMIT_SEEN.get("remaining", remaining_budget)

        # L3: a count-capped page that may have cut in-window stars goes to
        # REST, which paginates on the date. Polled together (worker pool),
        # then tallied below in batch order so the outcome is order-free.
        rest_polls = _poll_many(
            [u for u in batch if (results.get(u) or {}).get("needs_rest")],
            token, window_days=window_days, now=now)
        for login in batch:
            entry = results.get(login)
            if entry is None:
                tally[_gql.UNRESOLVED] = tally.get(_gql.UNRESOLVED, 0) + 1
                continue
            if entry.get("needs_rest"):
                # Counted, because this is the metric that says whether the
                # migration is still paying for itself: a roster selected for
                # prolific starrers can route itself back to REST one account at
                # a time, with no single account being at fault.
                tally["rest_fallback"] = tally.get("rest_fallback", 0) + 1
                rest_events, outcome = rest_polls[login]
                mapped = {_OK: _gql.OK, _AUTH_FAILED: _gql.AUTH_FAILED,
                          _RATE_LIMITED: _gql.RATE_LIMITED}.get(
                              outcome, _gql.UNRESOLVED)
                entry = {"events": rest_events, "outcome": mapped}
            outcome = entry.get("outcome", _gql.UNRESOLVED)
            tally[outcome] = tally.get(outcome, 0) + 1
            if outcome == _gql.OK:
                events.extend(entry.get("events") or [])
    return events, tally


def summarize_outcomes(tally: Dict[str, int], total: int) -> str:
    """L5: one line an operator can read without SSH-ing anywhere.

    Aggregate drift is its own failure mode: the sacred constraint can be
    honoured on every single run while the roster quietly erodes over weeks,
    because each run's status lines all read clean.
    """
    order = (_gql.OK, _gql.RATE_LIMITED, _gql.AUTH_FAILED, _gql.NOT_FOUND,
             _gql.MISMATCH, _gql.UNRESOLVED, "rest_fallback")
    parts = ["{}={}".format(name, tally.get(name, 0)) for name in order
             if tally.get(name)]
    return "roster {}/{} polled: {}".format(
        tally.get(_gql.OK, 0), total, " ".join(parts) or "nothing")


# Module-level memoization: one poll per process. The two adapters are called
# from different pipeline points (engine.fetch_all vs _export vs `hotin insiders`)
# so an in-process cache spans what a per-call cache cannot. NOT once-per-cycle:
# `hotin refresh` and `hotin export` are two processes, so a 3h cycle polls twice
# — negligible at roster scale, documented rather than chased.
_MEMO: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}


DEFAULT_WINDOW_DAYS = 45
_MIN_WINDOW_DAYS, _MAX_WINDOW_DAYS = 1, 365


def _window(config: Optional[dict], explicit: Optional[int]) -> int:
    """Resolve the star window: explicit argument, then config/env, then default.

    Exists so tuning this never again requires a PyPI release. It is the single
    most consequential number in the pipeline -- it decides how many repos reach
    the insiders tab at all -- and until 0.7.0 it was a bare default here,
    invisible from the repo that depends on it.

    Out-of-range values fall back to the default rather than raising: a typo in
    an environment variable must not take the board down, and a silently clamped
    window is easier to notice than a crashed bake.
    """
    if explicit is not None:
        return explicit
    raw = (config or {}).get("HOTIN_INSIDER_WINDOW_DAYS")
    if raw in (None, ""):
        return DEFAULT_WINDOW_DAYS
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DAYS
    if not _MIN_WINDOW_DAYS <= value <= _MAX_WINDOW_DAYS:
        return DEFAULT_WINDOW_DAYS
    return value


def poll_roster(
    config: Optional[dict] = None,
    *,
    window_days: Optional[int] = None,
    now: Optional[datetime] = None,
    _force: bool = False,
) -> List[Dict[str, Any]]:
    """Poll every roster member's recently-starred repos, memoized per process.

    The default window is measured, not guessed, and was widened 30 -> 45 in
    0.7.0. Override per deployment with ``HOTIN_INSIDER_WINDOW_DAYS``.

    A 7-day window sampled almost nobody: across a 797-account cohort it found
    93 events from 36 people (4.5% participation), and a single hyperactive
    account was 43% of the entire signal. 30 days gave 352 events from 87 people
    (10.9%) and dropped that account's share to 30%.

    30 -> 45 was measured the same way, on the trade that actually matters --
    pool size against how well corroboration predicts subsequent growth
    (repo growth as %/day of its own star count, so size is not mistaken for
    heat):

        window   repos with >=2 backers   their growth vs un-endorsed
          30d              28                      4.4x
          45d              39                      3.6x
          60d              45                      3.3x
          90d              75                      2.0x

    The signal DEGRADES monotonically as the window widens: older stars carry
    measurably less predictive power. 45 buys 39% more corroborated repos for an
    18% smaller lift, which is the best trade on the curve; past 60 it falls off.
    Widening further is not free and 90 halves the effect.

    Caveats worth keeping: n is 14-21 per row, so the direction is trustworthy
    and the individual figures are not; and the enrichment caps at 50 stars per
    account, so the wider windows are truncated for active accounts and their
    pools are undercounted.

    Returns a flat list of ``{username, canonical_repo, starred_at,
    stargazers_count, description}`` star events within ``window_days``. Raises
    :class:`MissingTokenError` if no token is configured, or
    :class:`RosterAuthError` if a present token is rejected (401) for every
    roster member — both loud, never a silent empty.
    """
    window_days = _window(config, window_days)
    roster = _roster(config)
    key = (roster, window_days, now.isoformat() if now else None)
    if not _force and key in _MEMO:
        return _MEMO[key]
    token = _token(config)  # raises loudly before any network work
    _gql.BATCH_TRACE.clear()
    _gql.LAST_ERROR_BODY.clear()
    events, tally = _poll_via_graphql(
        roster, token, window_days=window_days, now=now)
    auth_failures = tally.get(_gql.AUTH_FAILED, 0)
    rate_limited = tally.get(_gql.RATE_LIMITED, 0)
    LAST_OUTCOMES.clear()
    LAST_OUTCOMES.update(tally)
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
