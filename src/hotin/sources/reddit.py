"""Reddit posts surfaced through the optional ScrapeCreators API."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

from hotin.canonical import GITHUB_URL_IN_TEXT_RE, canonicalize, trim_glued_repo_name
from hotin.coerce import finite_int
from hotin.dedupe import dedupe_by_metric
from hotin.throttle import Throttle


SOURCE = "reddit"
SUBREDDITS = (
    "LocalLLaMA",
    "MachineLearning",
    "selfhosted",
    "opensource",
    "ChatGPTCoding",
    "artificial",
)
ENDPOINT = "https://api.scrapecreators.com/v1/reddit/subreddit"
SEARCH_ENDPOINT = "https://api.scrapecreators.com/v1/reddit/search"
THROTTLE = Throttle(min_interval=2.0, jitter=1.0)


def _empty(detail: str) -> Dict[str, Any]:
    return {"records": [], "status": "empty", "detail": detail}


def _github_reference(post: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Return a canonical GitHub URL and owner/repository pair from one post."""
    # Structured destination fields preserve an intentional CamelCase repo name.
    for key in ("url", "url_overridden_by_dest"):
        value = post.get(key)
        if isinstance(value, str):
            canonical = canonicalize(value.strip().rstrip(".,;:!?)]}>\"'"))
            if canonical:
                return "https://github.com/{}".format(canonical), canonical

    # Free text sometimes glues the next sentence directly onto a GitHub URL.
    # This deliberately sacrifices CamelCase repo names such as ``myProject``
    # to avoid attributing prose such as ``repoGithub`` to a nonexistent repo.
    for key in ("selftext", "body"):
        value = post.get(key)
        if isinstance(value, str):
            for match in GITHUB_URL_IN_TEXT_RE.finditer(value):
                owner, repo = match.groups()
                repo = trim_glued_repo_name(repo)
                canonical = canonicalize("{}/{}".format(owner, repo))
                if canonical:
                    return "https://github.com/{}".format(canonical), canonical
    return None


def _reddit_permalink(value: Any) -> Optional[str]:
    """Convert Reddit's path-like permalink field into a full Reddit URL."""
    if not isinstance(value, str):
        return None
    path = value.strip()
    if not path.startswith("/"):
        return None
    return "https://www.reddit.com{}".format(path)


def parse_response(payload: Any, subreddit: str) -> List[Dict[str, Any]]:
    """Purely parse one documented ScrapeCreators subreddit response.

    Invalid response shapes and malformed individual posts are ignored.  This
    function deliberately never performs network I/O so it is safe to fixture.
    """
    if not isinstance(payload, dict) or not isinstance(subreddit, str):
        return []
    posts = payload.get("posts")
    if not isinstance(posts, list):
        return []

    records: List[Dict[str, Any]] = []
    try:
        for post in posts:
            if not isinstance(post, dict):
                continue
            score = finite_int(post.get("score"))
            if score is None:
                continue
            reference = _github_reference(post)
            if reference is None:
                continue
            url, canonical_repo = reference

            title = post.get("title")
            name = title.strip() if isinstance(title, str) and title.strip() else canonical_repo
            signal: Dict[str, Any] = {"reddit_score": score}
            if "num_comments" in post:
                comments = finite_int(post.get("num_comments"))
                if comments is not None:
                    signal["reddit_comments"] = comments

            meta: Dict[str, Any] = {"subreddit": subreddit}
            permalink = _reddit_permalink(post.get("permalink"))
            if permalink is not None:
                meta["reddit_permalink"] = permalink

            records.append(
                {
                    "url": url,
                    "canonical_repo": canonical_repo,
                    "name": name,
                    "source": SOURCE,
                    "signal": signal,
                    "meta": meta,
                }
            )
    except (TypeError, ValueError, OverflowError, AttributeError):
        # JSON itself yields only native data, but retaining this boundary keeps
        # the parser safe when passed adversarial fixtures by callers or tests.
        return []
    return records


def dedupe_records(records: Iterable[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Keep the highest-scored Reddit post for each canonical repository."""
    return dedupe_by_metric(records, limit, "reddit_score", finite_int)


def _request_subreddit(subreddit: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Fetch one subreddit, returning ``None`` for every request/schema failure."""
    try:
        query = urllib.parse.urlencode(
            {"subreddit": subreddit, "sort": "top", "timeframe": "week"}
        )
        request = urllib.request.Request(
            "{}?{}".format(ENDPOINT, query),
            headers={"x-api-key": api_key, "User-Agent": "hotin/0.0.1"},
        )
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        if not isinstance(body, bytes):
            return None
        payload = json.loads(body.decode("utf-8"))
        # A missing/null posts list is a malformed API response, not a valid
        # empty subreddit result.
        if not isinstance(payload, dict) or not isinstance(payload.get("posts"), list):
            return None
        return payload
    except (Exception,):
        return None


def _request_search(query: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Fetch one Reddit keyword search, returning None for all failures."""
    try:
        params = urllib.parse.urlencode({"query": query, "sort": "top", "timeframe": "week"})
        request = urllib.request.Request(
            "{}?{}".format(SEARCH_ENDPOINT, params),
            headers={"x-api-key": api_key, "User-Agent": "hotin/0.0.1"},
        )
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        if not isinstance(body, bytes):
            return None
        payload = json.loads(body.decode("utf-8"))
        return payload if isinstance(payload, dict) and isinstance(payload.get("posts"), list) else None
    except (Exception,):
        return None


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Fetch GitHub repositories discussed in this week's top subreddit posts."""
    try:
        api_key = config.get("SCRAPECREATORS_API_KEY") if isinstance(config, dict) else None
        if not isinstance(api_key, str) or not api_key.strip():
            return _empty("no SCRAPECREATORS_API_KEY configured")

        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return _empty("limit is zero")

        parsed: List[Dict[str, Any]] = []
        if isinstance(query, str) and query.strip():
            payload = _request_search(query.strip(), api_key)
            if payload is None:
                return {"records": [], "status": "error", "detail": "reddit search request failed"}
            records = dedupe_records(parse_response(payload, "search"), requested_limit)
            if not records:
                return _empty("no GitHub repositories found")
            return {"records": records, "status": "ok", "detail": None}

        successful_subreddits = 0
        for subreddit in SUBREDDITS:
            payload = _request_subreddit(subreddit, api_key)
            if payload is None:
                continue
            successful_subreddits += 1
            parsed.extend(parse_response(payload, subreddit))

        if successful_subreddits == 0:
            return {"records": [], "status": "error", "detail": "all subreddit requests failed"}

        records = dedupe_records(parsed, requested_limit)
        if not records:
            return _empty("no GitHub repositories found")
        return {"records": records, "status": "ok", "detail": None}
    except (Exception,):
        # fetch is an optional integration boundary: callers must never need to
        # protect themselves from malformed configuration or response data.
        return {"records": [], "status": "error", "detail": "reddit fetch failed"}


def selftest() -> None:
    """Exercise parser-only realistic and deliberately hostile fixtures."""
    first = {
        "posts": [
            {
                "title": "Useful project",
                "url": "https://github.com/Example/Useful",
                "score": 12,
                "num_comments": 3,
                "permalink": "/r/LocalLLaMA/comments/one/useful/",
            },
            {
                "title": "Only a body link",
                "selftext": "Try https://github.com/example/body-link today.",
                "score": 8,
            },
            {"title": "Not a repository", "url": "https://example.com/nope", "score": 99},
        ]
    }
    second = {
        "posts": [
            {
                "title": "Higher-scored duplicate",
                "url_overridden_by_dest": "https://github.com/example/useful/issues/1",
                "score": 20,
            }
        ]
    }
    records = dedupe_records(
        parse_response(first, "LocalLLaMA") + parse_response(second, "MachineLearning"), 50
    )
    assert len(records) == 2
    assert records[0]["canonical_repo"] == "example/useful"
    assert records[0]["signal"]["reddit_score"] == 20
    assert parse_response({"posts": None}, "LocalLLaMA") == []
    assert parse_response({"posts": [{"title": "no score", "url": "https://github.com/a/b"}]}, "LocalLLaMA") == []
    print("reddit selftest: ok")


if __name__ == "__main__":
    selftest()
