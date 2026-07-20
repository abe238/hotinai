"""YouTube videos surfaced via the official Data API v3, or ScrapeCreators.

When ``YOUTUBE_API_KEY`` is configured, the official YouTube Data API v3 is
preferred (sanctioned, reliable): ``search.list`` for video IDs, then
``videos.list`` for the full descriptions + view counts we mine GitHub repos
from. Otherwise the optional ScrapeCreators integration is used
(``SCRAPECREATORS_API_KEY``). Either way this adapter never raises.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from hotin.canonical import GITHUB_URL_IN_TEXT_RE, canonicalize, trim_glued_repo_name
from hotin.coerce import finite_int
from hotin.throttle import Throttle


SOURCE = "youtube"
ENDPOINT = "https://api.scrapecreators.com/v1/youtube/search"
V3_SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
V3_VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
V3_CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"
V3_PLAYLIST_ITEMS_ENDPOINT = "https://www.googleapis.com/youtube/v3/playlistItems"
DEFAULT_QUERIES = ("new AI tool", "AI agent github", "open source AI")
# Curator channels publish a full repo index (20-35 repos) in each video
# description. A starting set of verified handles; overridable via
# HOTIN_YT_CHANNELS (comma-separated handles or channel IDs). Expand empirically.
DEFAULT_CHANNELS = ("@ManuAGI", "@GithubAwesome")
THROTTLE = Throttle(min_interval=2.0, jitter=1.0)
# The official API is quota- not rate-limited (10k units/day; search.list costs
# 100 units, videos.list 1), so it can be paced lighter than the scrape backend.
V3_THROTTLE = Throttle(min_interval=0.4, jitter=0.3)
_V3_MAX_RESULTS = 15  # per search query; keeps search.list quota spend modest
_CURATED_MAX_CHANNELS = 6
_CURATED_VIDEOS_PER_CHANNEL = 4


def _empty(detail: str) -> Dict[str, Any]:
    return {"records": [], "status": "empty", "detail": detail}


def _github_reference(text: Any) -> Optional[Tuple[str, str]]:
    """Return the first canonical repository link in a video text field."""
    if not isinstance(text, str):
        return None
    for match in GITHUB_URL_IN_TEXT_RE.finditer(text):
        owner, repo = match.groups()
        repo = trim_glued_repo_name(repo)
        canonical = canonicalize("{}/{}".format(owner, repo))
        if canonical:
            return "https://github.com/{}".format(canonical), canonical
    return None


def _record(url: str, canonical_repo: str, name: str, signal: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "url": url,
        "canonical_repo": canonical_repo,
        "name": name,
        "source": SOURCE,
        "signal": signal,
        "meta": meta,
    }


# ---- ScrapeCreators backend -------------------------------------------------

def _description_reference(video: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Check the documented description and common snippet alternative."""
    for key in ("description", "snippet"):
        reference = _github_reference(video.get(key))
        if reference is not None:
            return reference
    return None


def _view_count(video: Dict[str, Any]) -> Optional[int]:
    """Read documented and compatibility view-count fields without guessing text."""
    for key in ("viewCountInt", "viewCount", "view_count"):
        if key in video:
            value = finite_int(video.get(key))
            if value is not None:
                return value
    return None


def _published_at(video: Dict[str, Any]) -> Optional[str]:
    for key in ("publishedTime", "publishedAt", "published_at"):
        value = video.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _channel_name(video: Dict[str, Any]) -> Optional[str]:
    channel = video.get("channel")
    if not isinstance(channel, dict):
        return None
    title = channel.get("title")
    return title.strip() if isinstance(title, str) and title.strip() else None


def parse_response(payload: Any) -> List[Dict[str, Any]]:
    """Purely parse one ScrapeCreators YouTube search response.

    Search responses only yield records when a video's supplied description or
    snippet contains a canonicalizable GitHub repository link.  Every malformed
    item is ignored so this parser remains safe for adversarial fixtures.
    """
    if not isinstance(payload, dict):
        return []
    videos = payload.get("videos")
    if not isinstance(videos, list):
        return []

    records: List[Dict[str, Any]] = []
    try:
        for video in videos:
            if not isinstance(video, dict):
                continue
            reference = _description_reference(video)
            if reference is None:
                continue
            video_id = video.get("id")
            if not isinstance(video_id, str) or not video_id.strip():
                continue
            url, canonical_repo = reference
            title = video.get("title")
            name = title.strip() if isinstance(title, str) and title.strip() else canonical_repo

            signal: Dict[str, Any] = {}
            views = _view_count(video)
            if views is not None:
                signal["youtube_views"] = views
            published_at = _published_at(video)
            if published_at is not None:
                signal["youtube_published_at"] = published_at

            meta: Dict[str, Any] = {
                "youtube_title": title.strip() if isinstance(title, str) and title.strip() else name,
                "youtube_video_id": video_id.strip(),
            }
            channel = _channel_name(video)
            if channel is not None:
                meta["youtube_channel"] = channel

            records.append(_record(url, canonical_repo, name, signal, meta))
    except (TypeError, ValueError, OverflowError, AttributeError):
        return []
    return records


# ---- YouTube Data API v3 backend --------------------------------------------

def parse_v3_videos(payload: Any) -> List[Dict[str, Any]]:
    """Parse a YouTube Data API v3 ``videos.list`` response into Records.

    Yields a record only when the full description contains a canonicalizable
    GitHub repository link. Malformed items are skipped; never raises.
    """
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []

    records: List[Dict[str, Any]] = []
    try:
        for item in items:
            if not isinstance(item, dict):
                continue
            snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
            reference = _github_reference(snippet.get("description"))
            if reference is None:
                continue
            video_id = item.get("id")
            if not isinstance(video_id, str) or not video_id.strip():
                continue
            url, canonical_repo = reference
            title = snippet.get("title")
            name = title.strip() if isinstance(title, str) and title.strip() else canonical_repo

            signal: Dict[str, Any] = {}
            stats = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
            views = finite_int(stats.get("viewCount"))
            if views is not None:
                signal["youtube_views"] = views
            published = snippet.get("publishedAt")
            if isinstance(published, str) and published.strip():
                signal["youtube_published_at"] = published.strip()

            meta: Dict[str, Any] = {
                "youtube_title": title.strip() if isinstance(title, str) and title.strip() else name,
                "youtube_video_id": video_id.strip(),
            }
            channel = snippet.get("channelTitle")
            if isinstance(channel, str) and channel.strip():
                meta["youtube_channel"] = channel.strip()

            records.append(_record(url, canonical_repo, name, signal, meta))
    except (TypeError, ValueError, OverflowError, AttributeError):
        return []
    return records


def _v3_video_ids(payload: Any) -> List[str]:
    """Extract video IDs from a v3 ``search.list`` response."""
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    ids: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ident = item.get("id")
        video_id = ident.get("videoId") if isinstance(ident, dict) else None
        if isinstance(video_id, str) and video_id.strip():
            ids.append(video_id.strip())
    return ids


def _request_v3(url: str) -> Optional[Dict[str, Any]]:
    """Fetch one v3 endpoint, returning None for all transport/schema failures.

    The API key is a query parameter (Google's design; there is no header form),
    so this URL must never be logged.
    """
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "hotin/0.1.0"})
        V3_THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        if not isinstance(body, bytes):
            return None
        payload = json.loads(body.decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (Exception,):
        return None


def _request_v3_search(query: str, api_key: str) -> Optional[List[str]]:
    """search.list -> up to _V3_MAX_RESULTS video IDs, or None on failure."""
    params = urllib.parse.urlencode({
        "part": "snippet", "type": "video", "q": query,
        "maxResults": str(_V3_MAX_RESULTS), "order": "relevance", "key": api_key,
    })
    payload = _request_v3("{}?{}".format(V3_SEARCH_ENDPOINT, params))
    if payload is None or not isinstance(payload.get("items"), list):
        return None
    return _v3_video_ids(payload)


def _request_v3_videos(video_ids: List[str], api_key: str) -> Optional[Dict[str, Any]]:
    """videos.list(part=snippet,statistics) for up to 50 IDs, or None on failure."""
    params = urllib.parse.urlencode({
        "part": "snippet,statistics", "id": ",".join(video_ids[:50]), "key": api_key,
    })
    payload = _request_v3("{}?{}".format(V3_VIDEOS_ENDPOINT, params))
    if payload is None or not isinstance(payload.get("items"), list):
        return None
    return payload


def _channel_config(config: Dict[str, Any]) -> Tuple[str, ...]:
    raw = config.get("HOTIN_YT_CHANNELS")
    if isinstance(raw, str) and raw.strip():
        return tuple(part.strip() for part in raw.split(",") if part.strip())[:_CURATED_MAX_CHANNELS]
    return DEFAULT_CHANNELS


def _resolve_uploads_playlist(channel: str, api_key: str) -> Optional[str]:
    """Resolve a channel handle/ID to its uploads-playlist ID, or None."""
    param = "forHandle" if channel.startswith("@") else "id"
    params = urllib.parse.urlencode({"part": "contentDetails", param: channel, "key": api_key})
    payload = _request_v3("{}?{}".format(V3_CHANNELS_ENDPOINT, params))
    if payload is None:
        return None
    items = payload.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    details = items[0].get("contentDetails")
    playlists = details.get("relatedPlaylists") if isinstance(details, dict) else None
    uploads = playlists.get("uploads") if isinstance(playlists, dict) else None
    return uploads if isinstance(uploads, str) and uploads.strip() else None


def _request_v3_playlist_items(playlist_id: str, api_key: str) -> List[str]:
    """Recent video IDs from a channel's uploads playlist (bounded)."""
    params = urllib.parse.urlencode({
        "part": "contentDetails", "playlistId": playlist_id,
        "maxResults": str(_CURATED_VIDEOS_PER_CHANNEL), "key": api_key,
    })
    payload = _request_v3("{}?{}".format(V3_PLAYLIST_ITEMS_ENDPOINT, params))
    if payload is None or not isinstance(payload.get("items"), list):
        return []
    ids: List[str] = []
    for item in payload["items"]:
        details = item.get("contentDetails") if isinstance(item, dict) else None
        video_id = details.get("videoId") if isinstance(details, dict) else None
        if isinstance(video_id, str) and video_id.strip():
            ids.append(video_id.strip())
    return ids


def _fetch_curated(channels: Tuple[str, ...], api_key: str) -> List[Dict[str, Any]]:
    """Harvest repos from curator channels' recent uploads, flagged curated.

    Curated repos are a bounded credibility signal, NOT a separate source: they
    still carry source="youtube" and only add a `youtube_curated` meta flag.
    """
    records: List[Dict[str, Any]] = []
    for channel in channels[:_CURATED_MAX_CHANNELS]:
        uploads = _resolve_uploads_playlist(channel, api_key)
        if not uploads:
            continue
        video_ids = _request_v3_playlist_items(uploads, api_key)
        if not video_ids:
            continue
        payload = _request_v3_videos(video_ids, api_key)
        if payload is None:
            continue
        for record in parse_v3_videos(payload):
            record["meta"]["youtube_curated"] = True
            records.append(record)
    return records


# ---- shared -----------------------------------------------------------------

def dedupe_records(records: Iterable[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Keep the first video mentioning each repository across search queries."""
    try:
        seen: Set[str] = set()
        result: List[Dict[str, Any]] = []
        for record in records:
            if len(result) >= limit:
                break
            if not isinstance(record, dict):
                continue
            canonical = record.get("canonical_repo")
            if not isinstance(canonical, str) or canonical in seen:
                continue
            seen.add(canonical)
            result.append(record)
        return result
    except (TypeError, ValueError, OverflowError, AttributeError):
        return []


def _request_search(query: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Fetch one ScrapeCreators search response, or None for transport failures."""
    try:
        request_url = "{}?{}".format(
            ENDPOINT, urllib.parse.urlencode({"query": query, "includeExtras": "true"})
        )
        request = urllib.request.Request(
            request_url,
            headers={"x-api-key": api_key, "User-Agent": "hotin/0.1.0"},
        )
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        if not isinstance(body, bytes):
            return None
        payload = json.loads(body.decode("utf-8"))
        return payload if isinstance(payload, dict) and isinstance(payload.get("videos"), list) else None
    except (Exception,):
        return None


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def _fetch_v3(queries: Tuple[str, ...], limit: int, api_key: str, channels: Tuple[str, ...] = ()) -> Dict[str, Any]:
    parsed: List[Dict[str, Any]] = []
    successful = 0
    for query in queries:
        ids = _request_v3_search(query, api_key)
        if ids is None:
            continue
        successful += 1
        if not ids:
            continue
        payload = _request_v3_videos(ids, api_key)
        if payload is None:
            continue
        parsed.extend(parse_v3_videos(payload))
    # Curated channels first, so dedupe keeps the curated-flagged record when a
    # repo also appears in keyword search.
    curated = _fetch_curated(channels, api_key) if channels else []
    if curated:
        successful += 1
        parsed = curated + parsed
    if successful == 0:
        return {"records": [], "status": "error", "detail": "all YouTube API requests failed"}
    records = dedupe_records(parsed, limit)
    if not records:
        return _empty("no GitHub repositories found")
    return {"records": records, "status": "ok", "detail": None}


def _fetch_scrapecreators(queries: Tuple[str, ...], limit: int, api_key: str) -> Dict[str, Any]:
    parsed: List[Dict[str, Any]] = []
    successful = 0
    for query in queries:
        payload = _request_search(query, api_key)
        if payload is None:
            continue
        successful += 1
        parsed.extend(parse_response(payload))
    if successful == 0:
        return {"records": [], "status": "error", "detail": "all YouTube search requests failed"}
    records = dedupe_records(parsed, limit)
    if not records:
        return _empty("no GitHub repositories found")
    return {"records": records, "status": "ok", "detail": None}


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Fetch repositories linked from AI-tool YouTube video descriptions.

    Prefers the official YouTube Data API v3 (``YOUTUBE_API_KEY``); otherwise
    uses ScrapeCreators (``SCRAPECREATORS_API_KEY``).
    """
    try:
        cfg = config if isinstance(config, dict) else {}
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return _empty("limit is zero")
        queries = (query.strip(),) if isinstance(query, str) and query.strip() else DEFAULT_QUERIES

        yt_key = cfg.get("YOUTUBE_API_KEY")
        if isinstance(yt_key, str) and yt_key.strip():
            return _fetch_v3(queries, requested_limit, yt_key.strip(), _channel_config(cfg))
        sc_key = cfg.get("SCRAPECREATORS_API_KEY")
        if isinstance(sc_key, str) and sc_key.strip():
            return _fetch_scrapecreators(queries, requested_limit, sc_key.strip())
        return _empty("no YOUTUBE_API_KEY or SCRAPECREATORS_API_KEY configured")
    except (Exception,):
        return {"records": [], "status": "error", "detail": "youtube fetch failed"}


def selftest() -> None:
    """Exercise both parsers against valid and hostile fixtures (no network)."""
    # ScrapeCreators shape
    sc = {
        "videos": [
            {
                "id": "demo-1",
                "title": "An excellent project",
                "description": "Source: https://github.com/Example/Useful-Tool).",
                "viewCountInt": "1200",
                "publishedTime": "2026-07-01T12:00:00Z",
                "channel": {"title": "Example Channel"},
            },
            {"id": "no-link", "title": "No linked repository", "description": "No links here."},
        ]
    }
    records = parse_response(sc)
    assert len(records) == 1
    assert records[0]["canonical_repo"] == "example/useful-tool"
    assert records[0]["signal"]["youtube_views"] == 1200

    # YouTube Data API v3 shape
    v3 = {
        "items": [
            {
                "id": "vid-1",
                "snippet": {
                    "title": "Top repo",
                    "description": "Check https://github.com/Example/Repo out",
                    "channelTitle": "Repo Channel",
                    "publishedAt": "2026-07-10T00:00:00Z",
                },
                "statistics": {"viewCount": "9001"},
            },
            {"id": "vid-2", "snippet": {"title": "no repo", "description": "nothing"}, "statistics": {}},
        ]
    }
    v3_records = parse_v3_videos(v3)
    assert len(v3_records) == 1
    assert v3_records[0]["canonical_repo"] == "example/repo"
    assert v3_records[0]["signal"]["youtube_views"] == 9001
    assert v3_records[0]["meta"]["youtube_channel"] == "Repo Channel"
    assert _v3_video_ids({"items": [{"id": {"videoId": "abc"}}, {"id": "bad"}]}) == ["abc"]
    assert parse_v3_videos({"items": [{"snippet": {"description": None}}]}) == []
    print("youtube selftest: ok")


if __name__ == "__main__":
    selftest()
