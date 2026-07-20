"""Shared numeric coercion for malformed API and free-text input.

Every source adapter and the scoring engine need the same tolerant int/float
conversion: reject bools and None, catch every way a hostile or malformed
value can fail to convert (including OverflowError from values like 1e309),
and let each call site choose its own fallback.
"""

from __future__ import annotations

import math
from typing import Any, Optional


def finite_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def finite_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default
