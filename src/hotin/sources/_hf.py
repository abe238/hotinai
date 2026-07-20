"""Shared HuggingFace host access.

hfpapers and hfmodels both hit huggingface.co, so they share one Throttle here
(a per-adapter Throttle would let them hammer the same host concurrently).
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Optional

from hotin.throttle import Throttle

HOST_THROTTLE = Throttle(min_interval=1.0, jitter=0.5)
USER_AGENT = "hotin/0.2.0"


def _read(url: str) -> Optional[bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    HOST_THROTTLE.wait()
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return body if isinstance(body, bytes) else None


def request_json(url: str) -> Optional[Any]:
    """GET a JSON endpoint on huggingface.co, or None for any failure."""
    try:
        body = _read(url)
        return json.loads(body.decode("utf-8")) if body is not None else None
    except Exception:
        return None


def request_text(url: str) -> Optional[str]:
    """GET an HTML/text page on huggingface.co, or None for any failure."""
    try:
        body = _read(url)
        return body.decode("utf-8") if body is not None else None
    except Exception:
        return None
