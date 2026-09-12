"""Digg "Top GitHub Activity" board adapter (one more corroborating repo signal).

The page is a Next.js app: the table rows live in React Server Component
flight chunks (``self.__next_f.push([1, "<hexid>:<json>\\n..."])``), not in
``__NEXT_DATA__``. Each row is an element ``["$","tr","owner/repo",{props}]``
whose ``td`` cells are either inline or ``"$L<hexid>"`` references to other
chunks. We parse on that shape only (never CSS classes or component names),
treat every string as untrusted, and degrade to an empty result on any
surprise.
"""

from __future__ import annotations

import html as _html
import json
import re
import urllib.request
from typing import Any, Dict, List, Optional

from hotin.canonical import canonicalize
from hotin.coerce import finite_int
from hotin.throttle import Throttle


SOURCE = "diggactivity"
URL = "https://digg.com/tech/github/activity"
USER_AGENT = "hotin/0.2.0"
THROTTLE = Throttle(min_interval=2.0, jitter=1.0)
MIN_STARS = 12  # Abe: "only items with more than 11 stars"
MAX_DEVELOPER = 60

_PUSH = re.compile(r"self\.__next_f\.push\((\[.*?\])\)\s*</script>", re.S)
_LINE = re.compile(r"^([0-9a-f]+):(.*)$")
_REF = re.compile(r"^\$L([0-9a-f]+)$")
_REPO_ID = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9._-]+$")
_COUNT = re.compile(r"^(\d+(?:\.\d+)?)([kKmM]?)$")
_TAG = re.compile(r"<[^>]+>")
# td order on the board: rank, repo, actions, push, pr, issues, devs, stars, age, developer
_COLUMNS = ("digg_rank", None, "actions", "push", "pr", "issues", "devs", "stars", None, None)


def _chunks(page: Any) -> Dict[str, Any]:
    """Every ``hexid: element`` line across all flight pushes; bad lines skipped."""
    out: Dict[str, Any] = {}
    if not isinstance(page, str):
        return out
    for match in _PUSH.finditer(page):
        try:
            pushed = json.loads(match.group(1))
        except ValueError:
            continue
        payload = pushed[1] if isinstance(pushed, list) and len(pushed) > 1 else None
        if not isinstance(payload, str):
            continue
        for line in payload.splitlines():
            parts = _LINE.match(line)
            if not parts:
                continue
            try:
                out[parts.group(1)] = json.loads(parts.group(2))
            except ValueError:
                continue  # T (text) / I (import) chunks are not JSON
    return out


def _is_element(node: Any, tag: Optional[str] = None) -> bool:
    return (
        isinstance(node, list) and len(node) == 4 and node[0] == "$"
        and isinstance(node[1], str) and (tag is None or node[1] == tag)
        and isinstance(node[3], dict)
    )


def _resolve(node: Any, chunks: Dict[str, Any], depth: int = 0) -> Any:
    ref = _REF.match(node) if isinstance(node, str) else None
    if ref and depth < 4:
        return _resolve(chunks.get(ref.group(1)), chunks, depth + 1)
    return node


def _rows(chunks: Dict[str, Any]) -> List[Any]:
    found: List[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            if _is_element(node, "tr") and isinstance(node[2], str):
                found.append(node)
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            for child in node.values():
                walk(child)

    for element in chunks.values():
        walk(element)
    return found


def _leaf_text(node: Any, out: List[str]) -> None:
    """Rendered text of a cell: follows ``children`` only, never other props."""
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        out.append(str(node))
    elif _is_element(node):
        _leaf_text(node[3].get("children"), out)
    elif isinstance(node, list):
        for child in node:
            _leaf_text(child, out)


def _count(text: str) -> Optional[int]:
    text = text.strip().replace(",", "")
    if text in ("—", "-", "–"):
        return 0
    match = _COUNT.match(text)
    if not match:
        return None
    scale = {"": 1, "k": 1_000, "m": 1_000_000}[match.group(2).lower()]
    return finite_int(round(float(match.group(1)) * scale))


def _clean(text: str) -> str:
    return " ".join(_html.unescape(_TAG.sub(" ", text)).split())[:MAX_DEVELOPER]


def _developer(cell: Any) -> Optional[str]:
    """displayName (falling back to username) of the user prop inside the cell."""
    if isinstance(cell, dict):
        if isinstance(cell.get("username"), str) or isinstance(cell.get("displayName"), str):
            name = cell.get("displayName") if isinstance(cell.get("displayName"), str) else cell.get("username")
            return _clean(name) or None
        for child in cell.values():
            found = _developer(child)
            if found:
                return found
    elif isinstance(cell, list):
        for child in cell:
            found = _developer(child)
            if found:
                return found
    return None


def parse_page(page: Any) -> List[Dict[str, Any]]:
    """Purely convert the board HTML into hotin records (stars > 11 only)."""
    try:
        chunks = _chunks(page)
        records: List[Dict[str, Any]] = []
        seen = set()
        for row in _rows(chunks):
            repo = canonicalize(row[2])
            if repo is None or not _REPO_ID.match(repo) or repo in seen:
                continue
            cells = [_resolve(c, chunks) for c in row[3].get("children") or []]
            cells = [c for c in cells if _is_element(c, "td")]
            if len(cells) != len(_COLUMNS):
                continue
            meta: Dict[str, Any] = {}
            for cell, key in zip(cells, _COLUMNS):
                if key is None:
                    continue
                text: List[str] = []
                _leaf_text(_resolve(cell[3].get("children"), chunks), text)
                value = _count(" ".join(text))
                if value is not None:
                    meta[key] = value
            if meta.get("stars", 0) < MIN_STARS:
                continue
            developer = _developer(_resolve(cells[9][3].get("children"), chunks))
            if developer:
                meta["digg_developer"] = developer
            seen.add(repo)
            records.append({
                "url": "https://github.com/{}".format(repo),
                "canonical_repo": repo,
                "name": repo,
                "source": SOURCE,
                "signal": {},
                "meta": meta,
            })
        return records
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return []


def _request_page() -> Optional[str]:
    try:
        request = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        return body.decode("utf-8", "replace") if isinstance(body, bytes) else None
    except Exception:
        return None


def fetch(
    query: Optional[str] = None,
    *,
    limit: int = 50,
    config: Optional[dict] = None,
) -> Dict[str, Any]:
    """Fetch Digg's top GitHub activity board without an API key."""
    del query, config
    try:
        requested_limit = finite_int(limit)
        requested_limit = 50 if requested_limit is None else max(0, requested_limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        page = _request_page()
        if page is None:
            return {"records": [], "status": "error", "detail": "digg activity request failed"}
        if not _rows(_chunks(page)):
            return {"records": [], "status": "error", "detail": "digg activity page had no rows (shape changed?)"}
        records = parse_page(page)
        if not records:
            return {"records": [], "status": "empty", "detail": "no repositories with more than 11 stars"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "digg activity fetch failed"}
