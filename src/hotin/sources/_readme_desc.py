"""Fill in the descriptions GitHub itself does not have.

A repo with `description: null` renders on the board as a bare `owner/repo`
with nothing telling a visitor why to care -- the opposite of what this site
is for. Its README almost always says, in its first prose sentence, exactly
what the missing field should have said.

Two rules keep this honest:

* **Never fabricate.** A line is used verbatim or not at all. Where no line
  passes the gate, the row keeps its blank description. Blank beats wrong.
* **A README's opening lines are mostly not prose.** They are badge tables,
  logo `<img>` blocks, download links, and "Open to Work" banners. The gate
  below rejects all four and keeps scanning, which is what makes it work:
  against seven real description-less repos from a live board it returns a
  genuine description for six. The seventh (a tutorial repo whose first
  sentence is "click the Fork button") gets a true but unhelpful line --
  detecting an imperative across languages is not worth the machinery, and
  a verbatim weak line still beats an invented strong one.

Fetching is a single batched GraphQL query (one request, cost 1, for every
repo on the board that needs one) because the REST readme endpoint has no
batch form and would spend one request per row.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Mapping, Optional

from ..throttle import Throttle

USER_AGENT = "hotin/board (+https://hotin.ai)"
GRAPHQL_URL = "https://api.github.com/graphql"
THROTTLE = Throttle(0.2)

# Enough of a README to clear the badge/logo preamble without wandering into
# the installation section and quoting a shell command as a description.
SCAN_LINES = 40
MIN_WORDS = 5
MAX_CHARS = 200
# One query per run, so the cap only bounds a pathological board.
MAX_REPOS_PER_QUERY = 60

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(r"[*_`]+")
_ENTITY = re.compile(r"&[a-zA-Z]+;|&#\d+;")
_HTML = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
# Lines that are structure, not prose.
_SKIP_PREFIX = ("#", ">", "-", "*", "+", "|", "```", "~~~", "<", "=")


def _normalise(line: str) -> str:
    """Markdown prose reduced to the words a reader would actually see."""
    text = _IMAGE.sub("", line)
    text = _LINK.sub(r"\1", text)
    text = _EMPHASIS.sub("", text)
    return _SPACES.sub(" ", text).strip()


def _is_prose(text: str) -> bool:
    if not text or not text[0].isalpha():
        return False
    # A surviving URL means the line was a link row, not a sentence.
    if "http" in text.lower():
        return False
    # Entities and tags mean raw HTML leaked through: a badge or banner.
    if _ENTITY.search(text) or _HTML.search(text):
        return False
    return len(text.split()) >= MIN_WORDS


def _tidy(paragraph: str) -> str:
    """Cut a paragraph to one sentence, or to a word boundary if it has none.

    READMEs hard-wrap, so the prose line the scanner lands on is usually half
    a sentence ending in "from" or "each working". Taking the line alone put
    exactly those fragments on the board.
    """
    text = _SPACES.sub(" ", paragraph).strip()
    match = re.search(r"(?<=[.!?])\s", text)
    if match and match.start() <= MAX_CHARS:
        return text[:match.start()].strip()
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS].rsplit(" ", 1)[0]
    return (cut or text[:MAX_CHARS]).rstrip(" ,;:-")


def derive_description(readme: Any) -> Optional[str]:
    """The README's first real sentence, or None.

    Pure and network-free so the gate is testable against real READMEs.
    """
    if not isinstance(readme, str) or not readme.strip():
        return None
    fenced = False
    lines = readme.splitlines()[:SCAN_LINES]
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("```") or line.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced or not line or line.startswith(_SKIP_PREFIX):
            continue
        text = _normalise(line)
        if not _is_prose(text):
            continue
        # Absorb the rest of the wrapped paragraph, so a sentence broken
        # across source lines is reassembled before it is cut.
        parts = [text]
        for follow in lines[i + 1:]:
            nxt = follow.strip()
            if not nxt or nxt.startswith(_SKIP_PREFIX):
                break
            parts.append(_normalise(nxt))
            if len(" ".join(parts)) > MAX_CHARS * 2:
                break
        return _tidy(" ".join(parts)) or None
    return None


def _slug_of(record: Mapping[str, Any]) -> Optional[str]:
    slug = record.get("canonical_repo") or record.get("name")
    if not isinstance(slug, str) or slug.count("/") != 1:
        return None
    owner, name = slug.split("/")
    return slug if owner and name else None


def _needs_description(record: Any) -> Optional[str]:
    if not isinstance(record, dict):
        return None
    meta = record.get("meta")
    existing = meta.get("description") if isinstance(meta, Mapping) else None
    if isinstance(existing, str) and existing.strip():
        return None
    return _slug_of(record)


def build_query(slugs: List[str]) -> str:
    """One aliased `repository` block per slug, three candidate README paths.

    GitHub charges this a flat cost of 1 no matter how many aliases it holds,
    which is the entire reason this is batched rather than looped.
    """
    parts = []
    for i, slug in enumerate(slugs):
        owner, name = slug.split("/")
        parts.append(
            'r{i}: repository(owner: {o}, name: {n}) {{ nameWithOwner '
            'a: object(expression: "HEAD:README.md") {{ ... on Blob {{ text }} }} '
            'b: object(expression: "HEAD:readme.md") {{ ... on Blob {{ text }} }} '
            'c: object(expression: "HEAD:README") {{ ... on Blob {{ text }} }} }}'
            .format(i=i, o=json.dumps(owner), n=json.dumps(name))
        )
    return "query {\n" + "\n".join(parts) + "\n}"


def _post(query: str, token: str) -> Optional[dict]:
    body = json.dumps({"query": query}).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Authorization": "Bearer {}".format(token),
    }
    try:
        request = urllib.request.Request(GRAPHQL_URL, data=body, headers=headers)
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (urllib.error.HTTPError, urllib.error.URLError, OSError,
            UnicodeDecodeError, ValueError):
        return None


def _descriptions(payload: Optional[dict]) -> Dict[str, str]:
    """Map casefolded slug -> derived description, skipping anything unusable.

    GraphQL echoes GitHub's canonical casing (`x4gKing/X4G` for a board row
    reading `x4gking/x4g`), so the join has to be case-insensitive.
    """
    out: Dict[str, str] = {}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return out
    for value in data.values():
        if not isinstance(value, dict):
            continue
        slug = value.get("nameWithOwner")
        if not isinstance(slug, str):
            continue
        for key in ("a", "b", "c"):
            blob = value.get(key)
            text = blob.get("text") if isinstance(blob, dict) else None
            derived = derive_description(text)
            if derived:
                out[slug.casefold()] = derived
                break
    return out


def fill_missing_descriptions(record_groups: Iterable[Iterable[Any]],
                              token: Optional[str]) -> int:
    """Write derived descriptions into records that have none. Returns the count.

    Best-effort throughout: no token, a failed query, or a README that never
    clears the gate all leave the board exactly as it was.
    """
    if not isinstance(token, str) or not token.strip():
        return 0
    pending: Dict[str, List[dict]] = {}
    for group in record_groups:
        for record in group or []:
            slug = _needs_description(record)
            if slug:
                pending.setdefault(slug.casefold(), []).append(record)
    if not pending:
        return 0
    slugs = [records[0].get("canonical_repo") or records[0].get("name")
             for records in list(pending.values())[:MAX_REPOS_PER_QUERY]]
    derived = _descriptions(_post(build_query(slugs), token.strip()))
    filled = 0
    for key, records in pending.items():
        text = derived.get(key)
        if not text:
            continue
        for record in records:
            meta = record.get("meta")
            if not isinstance(meta, dict):
                meta = {}
                record["meta"] = meta
            meta["description"] = text
            filled += 1
    return filled
