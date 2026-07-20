"""Normalize the GitHub repository references that sources commonly emit."""

import re
from typing import Optional


RESERVED_TOP_LEVEL = {
    "topics", "trending", "sponsors", "marketplace", "settings", "orgs", "apps", "about",
    "features", "pricing", "explore", "enterprise", "notifications", "login", "join", "new",
    "collections", "readme", "security", "contact", "pulls", "issues", "dashboard", "watching",
    "stars", "site", "business", "customer-stories", "team", "mobile", "discussions", "account",
    "search", "blog", "organizations",
}

_GITHUB_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([^/\s]+)/([^/\s?#]+)(?:/.*)?/?$",
    re.IGNORECASE,
)
_SCP_STYLE = re.compile(
    r"^git@github\.com:([^/\s]+)/([^/\s?#]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_BARE_REPO = re.compile(r"^([^/\s@:]+)/([^/\s?#]+?)/?$", re.IGNORECASE)


def canonicalize(url: str) -> Optional[str]:
    """Return lower-case ``owner/repo`` for supported GitHub URL variants."""
    if not isinstance(url, str):
        return None
    candidate = url.strip().split("?", 1)[0].split("#", 1)[0]
    match = _GITHUB_URL.match(candidate) or _SCP_STYLE.match(candidate) or _BARE_REPO.match(candidate)
    if not match:
        return None
    owner, repo = match.group(1).lower(), match.group(2).lower()
    if owner in RESERVED_TOP_LEVEL or not owner or not repo:
        return None
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not repo or repo in {".", ".."}:
        return None
    return "{}/{}".format(owner, repo)
