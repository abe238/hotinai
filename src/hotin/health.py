"""Source-result health reporting with a deliberately tiny exit contract."""

from dataclasses import dataclass
from typing import List, Literal, Optional, Tuple


@dataclass
class SourceStatus:
    source: str
    status: Literal["ok", "empty", "error"]
    detail: Optional[str] = None


def summarize(statuses: List[SourceStatus], cache_has_data: bool = False) -> Tuple[int, str]:
    """Turn source outcomes into a process exit code and a concise message."""
    if cache_has_data or any(item.status == "ok" for item in statuses):
        return 0, "sources completed"
    errors = [item for item in statuses if item.status == "error"]
    if errors and len(errors) == len(statuses):
        detail = "; ".join(
            "{}: {}".format(item.source, item.detail or "failed") for item in errors
        )
        return 1, "all sources failed: {}".format(detail)
    if any(item.status == "empty" for item in statuses):
        return 0, "no results from available sources"
    return 1, "no source results available"
