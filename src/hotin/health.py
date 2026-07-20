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
    # No cache and nothing succeeded. If anything actually errored, the run
    # failed to deliver and something is broken -> exit 1. (We cannot require
    # EVERY status to be an error: permanently-inert sources like the x stub
    # and unconfigured reddit/youtube are always "empty", so keying off
    # len(errors)==len(statuses) would make the failure signal unreachable.)
    errors = [item for item in statuses if item.status == "error"]
    if errors:
        detail = "; ".join(
            "{}: {}".format(item.source, item.detail or "failed") for item in errors
        )
        return 1, "no usable results; source errors: {}".format(detail)
    return 0, "no results from available sources"
