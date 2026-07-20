"""Safe rendering primitives for terminal-bound, untrusted source text."""

import re


_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?")
_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OTHER_ESCAPE = re.compile(r"\x1b.", re.DOTALL)
_BIDI = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_CONTROL_KEEP_WHITESPACE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_COLOR_CODE = re.compile(r"^[0-9;]+$")


def sanitize(text: str, allow_whitespace: bool = False) -> str:
    """Remove terminal control syntax from arbitrary, untrusted text."""
    safe = str(text)
    safe = _OSC.sub("", safe)
    safe = _CSI.sub("", safe)
    safe = _OTHER_ESCAPE.sub("", safe)
    safe = _BIDI.sub("", safe)
    controls = _CONTROL_KEEP_WHITESPACE if allow_whitespace else _CONTROL
    return controls.sub("", safe)


def color(text: str, code: str, enabled: bool = True) -> str:
    """Apply one of hotin's own SGR codes; never use this to sanitize input."""
    if not enabled:
        return text
    sgr = code
    if code.startswith("\x1b[") and code.endswith("m"):
        sgr = code[2:-1]
    if not _COLOR_CODE.fullmatch(sgr):
        raise ValueError("color code must be an SGR numeric code")
    return "\x1b[{}m{}\x1b[0m".format(sgr, text)


def hyperlink(text: str, url: str, enabled: bool = True) -> str:
    """Wrap ``text`` in an OSC 8 terminal hyperlink when enabled, else return it plain.

    The URL is caller-trusted (built from an already-validated canonical repo), but
    control bytes are stripped defensively so hotin can never emit an escape it did
    not intend. Terminals without OSC 8 support simply show ``text``.
    """
    if not enabled:
        return text
    safe_url = _CONTROL.sub("", url)
    return "\x1b]8;;{}\x1b\\{}\x1b]8;;\x1b\\".format(safe_url, text)
