"""X (Twitter) is not offered by our ScrapeCreators integration and has no public,
unauthenticated search API. This adapter is an honest stub, not a broken integration:
it always reports itself as unconfigured rather than pretending to try. Bring-your-own-
credentials support is a possible future extension, not part of v1.
"""
from typing import Any, Dict, Optional


def fetch(query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None) -> Dict[str, Any]:
    return {
        "records": [],
        "status": "empty",
        "detail": "the x source is not implemented (no public API available); bring-your-own-credentials only, not v1-core",
    }


def selftest() -> None:
    result = fetch()
    assert result["records"] == []
    assert result["status"] == "empty"
    print("x selftest: ok")


if __name__ == "__main__":
    selftest()
