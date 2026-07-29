"""Batched GraphQL polling for the insider roster.

Why this exists
---------------
REST costs one request per account: 793 requests, ~1,400 of a 5,000/hr REST
budget, ~13 minutes. GraphQL batches 25 accounts into ONE request at a
GitHub-reported cost of 1, putting the whole roster at ~32 requests and ~32
points on a SEPARATE 5,000/hr pool in ~195s.

The transport swap is the easy part. The hazard is that GraphQL RELOCATES every
failure signal, and each relocation is a fresh path to "ok, starred nothing" --
the shape that once shipped a small, plausible, entirely fictional board:

    REST                              GraphQL
    ----------------------------      --------------------------------------
    401                               errors[] entry, HTTP 200
    403/429 + Retry-After             typed RATE_LIMITED error + rateLimit{}
    404 (renamed/deleted)             `null` user node inside `data`, HTTP 200
    (n/a)                             RESOURCE_LIMITS_EXCEEDED: partial data

So the load-bearing design here is NOT the query. It is DEFAULT-DENY: every
requested account starts UNRESOLVED and only an explicit, fully-validated
success path may promote it to OK. A parsing bug can then only over-report
failure, which is safe and trips the existing >50% guard. It can never
fabricate an empty result.

The measured hazard this module was rebuilt around
--------------------------------------------------
At 40 users x 20 stars, GitHub returned **HTTP 200, rateLimit cost 1, all 40
users present in `data`, zero null user nodes** -- and 355 `errors[]` entries of
type RESOURCE_LIMITS_EXCEEDED, each nulling one edge's `starredAt`. Because
`starredAt` is non-null in the schema, GitHub nulls the whole EDGE: `edges` came
back as a list containing `None`. 29 of the 40 accounts were affected and one
had all 20 of its edges nulled.

Every cheap success metric reads perfect on that response. And the corrupted
field is exactly the one the window filter drops when it is not a string, so the
account would look quieter than it is: plausible, fictional, invisible.

Hence two INDEPENDENT defences, deliberately belt-and-braces:

1. Parse `errors[]` and attribute by `path` -- the diagnostic.
2. **Validate payload completeness directly** -- the gate. An edge that is None,
   or missing `starredAt`, or missing its repo's `createdAt`, is unusable NO
   MATTER WHY, and needs no interpretation of the error envelope to detect.

Defence 2 matters because error `path` shapes vary by where the error
originates, and a global error carries no path at all. A missing required field
is self-evident.

Batch sizing is measured, and is a load-dependent GitHub-side boundary, never a
contract: N=5 per config on the real roster gave 25x20 clean 5/5; 40x20
partial-corruption 5/5; 50x15 502 3/5 plus corruption 2/5; 50x30 502 5/5. A
completeness sweep found 10/15/20/25/30/35 users clean at first:20, so the
boundary sits between 35 and 40. 25x20 is the default for the headroom.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..canonical import canonicalize
from ..coerce import finite_int

# --- outcomes (L1: default-deny) -------------------------------------------
# UNRESOLVED is the DEFAULT and the safety property: anything this module fails
# to explicitly validate stays here, and a non-OK account never contributes a
# zero-star row to the board.
OK = "ok"
AUTH_FAILED = "auth_failed"
RATE_LIMITED = "rate_limited"
NOT_FOUND = "not_found"
MISMATCH = "mismatch"
UNRESOLVED = "unresolved"

#: Outcomes that mean "we were not able to look", as opposed to "we looked and
#: the account had starred nothing". Never collapse these into OK.
NON_OK = (AUTH_FAILED, RATE_LIMITED, NOT_FOUND, MISMATCH, UNRESOLVED)

BATCH_USERS = 25   # measured clean 5/5; boundary observed between 35 and 40
BATCH_STARS = 20
MIN_BATCH_USERS = 4   # below this, fall back to REST rather than keep halving

GRAPHQL_URL = "https://api.github.com/graphql"
#: Stop issuing batches below this many GraphQL points and mark the remainder
#: rate_limited explicitly. A full roster costs ~32, so this leaves ample room
#: to finish a run that is already in flight.
POINTS_FLOOR = 200

#: Last few raw HTTP error bodies from GraphQL, for diagnosis. GitHub explains
#: WHY it refused in the body; discarding it forced two wrong inferences.
LAST_ERROR_BODY: List[str] = []

#: Per-batch trace of the last poll: what was attempted and what came back.
#: Populated by the caller. Cleared at the start of each poll.
BATCH_TRACE: List[Dict[str, Any]] = []


def build_query(logins: Sequence[str], first: int = BATCH_STARS) -> str:
    """One aliased `user` block per login.

    `login` is requested back on every node so results are attributed by the
    SERVER-ECHOED identity rather than by alias position. Positional mapping
    would silently misattribute stars to the wrong account on any drift, and
    GitHub does return canonical casing that differs from the request.
    """
    parts = []
    for i, login in enumerate(logins):
        parts.append(
            'u{i}: user(login: {login}) {{ login '
            'starredRepositories(first: {first}, '
            'orderBy: {{field: STARRED_AT, direction: DESC}}) {{ '
            'pageInfo {{ hasNextPage }} '
            'edges {{ starredAt node {{ nameWithOwner createdAt '
            'stargazerCount description }} }} }} }}'.format(
                i=i, login=json.dumps(login), first=int(first))
        )
    return "query {\n" + "\n".join(parts) + "\n rateLimit { cost remaining resetAt }\n}"


def _blank(login: str) -> Dict[str, Any]:
    return {"login": login, "events": [], "outcome": UNRESOLVED,
            "needs_rest": False, "detail": None}


def _edge_is_usable(edge: Any) -> bool:
    """The completeness gate. Independent of `errors[]` interpretation.

    A nulled `starredAt` nulls the whole edge (the field is non-null in the
    schema), so `edges` can legitimately arrive as a list containing None.
    """
    if not isinstance(edge, dict):
        return False
    starred_at = edge.get("starredAt")
    if not isinstance(starred_at, str) or not starred_at.strip():
        return False
    node = edge.get("node")
    if not isinstance(node, dict):
        return False
    if not isinstance(node.get("nameWithOwner"), str):
        return False
    # created_at drives the 180-day age cap; without it the row cannot be ranked
    # correctly, so an account missing it is not a clean poll.
    return isinstance(node.get("createdAt"), str)


def parse_batch(
    payload: Any,
    requested: Sequence[str],
    *,
    window_days: int,
    now: Optional[datetime] = None,
    fresh_fn=None,
) -> Dict[str, Dict[str, Any]]:
    """Turn one GraphQL response into a per-account result, default-deny.

    ``fresh_fn(starred_at, window_days=..., now=...) -> bool`` is injected so
    this module shares the roster poller's own window logic rather than
    reimplementing it.
    """
    results: Dict[str, Dict[str, Any]] = {
        login: _blank(login) for login in requested}
    alias_of = {"u{}".format(i): login for i, login in enumerate(requested)}

    if not isinstance(payload, dict):
        return results  # malformed/truncated body: everything stays UNRESOLVED

    data = payload.get("data")
    data = data if isinstance(data, dict) else {}
    errors = payload.get("errors")
    errors = errors if isinstance(errors, list) else []

    # --- pass 1: errors[]. Attribute by path where possible. -----------------
    corrupted: set = set()
    for error in errors:
        if not isinstance(error, dict):
            continue
        etype = error.get("type")
        path = error.get("path")
        alias = path[0] if isinstance(path, list) and path else None
        login = alias_of.get(alias) if isinstance(alias, str) else None
        if login is None:
            # A GLOBAL error (no path) applies to the whole batch. Rate limiting
            # is the one we can name; anything else leaves the batch unresolved.
            state = RATE_LIMITED if etype == "RATE_LIMITED" else UNRESOLVED
            for entry in results.values():
                entry["outcome"] = state
                entry["detail"] = etype or "global error"
            return results
        if etype == "NOT_FOUND":
            results[login]["outcome"] = NOT_FOUND
        elif etype == "RATE_LIMITED":
            results[login]["outcome"] = RATE_LIMITED
        elif etype == "FORBIDDEN":
            results[login]["outcome"] = AUTH_FAILED
        else:
            # RESOURCE_LIMITS_EXCEEDED and anything unenumerated: the account's
            # data is partial. Stays UNRESOLVED; the caller shrinks and retries.
            corrupted.add(login)
        results[login]["detail"] = etype or "error"

    # --- pass 2: data. Only a fully clean account is promoted to OK. ---------
    for alias, login in alias_of.items():
        entry = results[login]
        if entry["outcome"] in (NOT_FOUND, RATE_LIMITED, AUTH_FAILED):
            continue
        if alias not in data:
            continue  # absent from BOTH data and errors -> stays UNRESOLVED
        node = data.get(alias)
        if node is None:
            entry["outcome"] = NOT_FOUND
            continue
        if not isinstance(node, dict):
            continue
        echoed = node.get("login")
        if not isinstance(echoed, str) or echoed.casefold() != login.casefold():
            entry["outcome"] = MISMATCH
            entry["detail"] = "echoed {!r} for requested {!r}".format(echoed, login)
            continue
        if login in corrupted:
            continue  # partial data for this account; never OK

        starred = node.get("starredRepositories")
        starred = starred if isinstance(starred, dict) else {}
        edges = starred.get("edges")
        edges = edges if isinstance(edges, list) else []

        # THE GATE: one unusable edge invalidates the account's whole poll.
        if any(not _edge_is_usable(edge) for edge in edges):
            entry["detail"] = "incomplete edge"
            continue

        events: List[Dict[str, Any]] = []
        oldest_in_window = False
        for edge in edges:
            starred_at = edge["starredAt"]
            if fresh_fn is not None and not fresh_fn(
                    starred_at, window_days=window_days, now=now):
                continue
            oldest_in_window = True
            node_repo = edge["node"]
            canonical = canonicalize(node_repo.get("nameWithOwner"))
            if not canonical:
                continue
            description = node_repo.get("description")
            events.append({
                "username": login,
                "canonical_repo": canonical,
                "starred_at": starred_at,
                "repo_created_at": node_repo.get("createdAt"),
                "stargazers_count": finite_int(node_repo.get("stargazerCount"), 0),
                "description": description if isinstance(description, str) else None,
            })

        # TRUNCATION: `first: K` caps by COUNT, but the window is a DATE. If the
        # page is full, more pages exist, and the OLDEST edge we got is still
        # inside the window, then in-window stars were cut off. REST paginates
        # with a true date early-exit, so hand this account to it rather than
        # accept a quietly short list.
        page_info = starred.get("pageInfo")
        has_next = bool(page_info.get("hasNextPage")) if isinstance(page_info, dict) else False
        if has_next and edges and oldest_in_window:
            last = edges[-1]["starredAt"]
            if fresh_fn is None or fresh_fn(last, window_days=window_days, now=now):
                entry["needs_rest"] = True
                entry["detail"] = "truncated in-window"
                continue

        entry["events"] = events
        entry["outcome"] = OK

    return results


def points_remaining(payload: Any) -> Optional[int]:
    """`rateLimit.remaining` from a response, or None if absent."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    rate = data.get("rateLimit")
    if not isinstance(rate, dict):
        return None
    remaining = rate.get("remaining")
    return remaining if isinstance(remaining, int) else None


def is_secondary_rate_limit(body: Optional[str]) -> bool:
    """Does GitHub's 403 body actually say 'rate limit'?

    This distinction decides whether falling back to REST helps or hurts, and it
    cannot be inferred from the status code -- 403 covers both "slow down" and
    "this credential cannot do that". Guessing it wrong is expensive in both
    directions: retrying REST during a real rate limit adds load, while treating
    a capability rejection as a rate limit throws away a whole cohort that REST
    could have fetched fine.

    Conservative on purpose: anything that looks like a limit is treated as one,
    because adding load to an already-limited endpoint is the worse error.
    """
    # Unknown means unknown: a missing OR EMPTY body must take the conservative
    # branch. An empty string read as "not a rate limit" and sent the poller to
    # REST during a genuine limit -- the one direction that adds load.
    if not isinstance(body, str) or not body.strip():
        return True
    lowered = body.lower()
    return ("rate limit" in lowered or "abuse" in lowered
            or "too many requests" in lowered or "try again later" in lowered)


def is_resource_limited(payload: Any) -> bool:
    """True when GitHub partially served the query because it was too heavy.

    The signal to SHRINK the batch, as distinct from backing off entirely.
    """
    if not isinstance(payload, dict):
        return False
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return False
    return any(isinstance(e, dict) and e.get("type") == "RESOURCE_LIMITS_EXCEEDED"
               for e in errors)


def batches(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    size = max(1, int(size))
    for i in range(0, len(items), size):
        yield items[i:i + size]


# --- transport -------------------------------------------------------------

#: HTTP statuses that mean "this batch was too heavy", as opposed to "the
#: service is unwell". 502 was observed 5/5 at 50 users x 30 stars.
TOO_HEAVY = (502, 503, 504)


def post(query: str, token: str, *, timeout: int = 120, opener=None):
    """POST one GraphQL query. Returns ``(payload, http_status, headers)``.

    ``payload`` is None when nothing parseable came back. ``http_status`` is
    None on success and the code on an HTTP error, so the caller can tell a
    too-heavy batch (shrink) from a dead service (back off) without inspecting
    exceptions.

    ``headers`` is returned even on failure BECAUSE the failure case is the one
    that needs them: an exhausted token's own X-RateLimit-* values are how a run
    reports the real quota rather than inferring one. Dropping them on the error
    path would silently re-introduce the guesswork they exist to replace.
    """
    import urllib.error
    import urllib.request

    body = json.dumps({"query": query}).encode("utf-8")
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "hotin (+https://hotin.ai)",
    }
    request = urllib.request.Request(GRAPHQL_URL, data=body, headers=headers)
    _open = opener or urllib.request.urlopen
    try:
        with _open(request, timeout=timeout) as response:
            raw = response.read()
            headers = getattr(response, "headers", None)
        return json.loads(raw.decode("utf-8", "replace")), None, headers
    except urllib.error.HTTPError as exc:
        # CAPTURE THE BODY. Two root causes were inferred from circumstantial
        # evidence and both were wrong; GitHub states the actual reason in the
        # 403 body ("exceeded a secondary rate limit", "requires authentication",
        # a scope complaint) and we were throwing it away. Diagnosing from
        # inference is what cost the time -- read what it says instead.
        try:
            LAST_ERROR_BODY.append(exc.read().decode("utf-8", "replace")[:400])
            del LAST_ERROR_BODY[:-5]
        except Exception:
            pass
        return None, exc.code, getattr(exc, "headers", None)
    except (urllib.error.URLError, OSError, ValueError):
        # A truncated or non-JSON body lands here. Nothing parseable means every
        # account in the batch stays UNRESOLVED, which is the safe direction.
        return None, None, None
