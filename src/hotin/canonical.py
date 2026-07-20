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

# Finds a repository-shaped GitHub link embedded in free text (an HN story body,
# a Reddit post, a YouTube description). canonicalize() performs the
# authoritative owner/repository validation on whatever this matches.
GITHUB_URL_IN_TEXT_RE = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)


def trim_glued_repo_name(repo: str) -> str:
    """Trim prose glued directly onto a repo name with no separator.

    Free text sometimes glues the next sentence straight onto a URL. This
    deliberately sacrifices genuine camelCase repo names such as ``myProject``
    to avoid attributing prose such as ``repoGithub`` to a nonexistent repo.
    """
    return re.split(r"(?<=[a-z0-9])(?=[A-Z])", repo, maxsplit=1)[0]


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
