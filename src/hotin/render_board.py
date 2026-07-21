"""Pure, I/O-free renderers for hotin's receipts board.

Every function is total: it never raises, never touches I/O, and defaults every
missing key safely. All untrusted source text routes through ``sanitize`` (for
terminals) or ``html.escape`` (for the web board) before it is emitted.

A ROW is a dict::

    {
      "rank": int | str,
      "name": str,
      "url": str | None,
      "meta": str | None,
      "receipts": [{"label": str, "kind": str}],
      "badges": [{"label": str, "hot": bool}],
    }
"""

import html

from hotin.render import color, hyperlink, sanitize

# hyperlink is re-exported for callers that wrap board rows in OSC-8 links.
__all__ = ["render_text", "render_md", "render_html", "hyperlink"]

# receipt kind -> ANSI 256 source color (used with the "38;5;N" SGR form).
_RECEIPT_ANSI = {
    "stars": "214",
    "hn": "208",
    "npm": "203",
    "reddit": "196",
    "paper": "45",
    "x": "99",
    "insiders": "220",
}

# receipt kind -> chip CSS class on the web board.
_CHIP_CLASS = {
    "stars": "gold",
    "hn": "hn",
    "npm": "npm",
    "reddit": "reddit",
    "paper": "paper",
    "x": "x",
    "insiders": "gold",
}

# badge label -> ANSI 256 color for the terminal board.
_BADGE_ANSI = {
    "fresh": "46",
    "smart-money": "220",
    "paper-backed": "45",
    "trending": "99",
}

# badge label -> badge CSS class on the web board.
_BADGE_CLASS = {
    "fresh": "fresh",
    "smart-money": "smart",
    "paper-backed": "paper",
    "trending": "trend",
}

_RANK_ANSI = "38;5;208"  # heat/orange


def _rows(rows):
    """Yield only dict rows, tolerating None or a non-list argument."""
    if not isinstance(rows, (list, tuple)):
        return
    for row in rows:
        if isinstance(row, dict):
            yield row


def _items(row, key):
    """Return the list under ``key``, tolerating a missing or None value."""
    value = row.get(key)
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, dict)]


def render_text(rows, *, color_on=True):
    """Render the board as sanitized terminal lines: "rank  name - meta  receipts  badges"."""
    lines = []
    for row in _rows(rows):
        rank = sanitize(str(row.get("rank", "")))
        name = sanitize(str(row.get("name", "")))
        meta = row.get("meta")

        seg = color(rank, _RANK_ANSI, color_on) + "  " + color(name, "1", color_on)
        if meta not in (None, ""):
            seg += " - " + color(sanitize(str(meta)), "2", color_on)

        receipts = []
        for r in _items(row, "receipts"):
            label = sanitize(str(r.get("label", "")))
            ansi = _RECEIPT_ANSI.get(str(r.get("kind", "")))
            receipts.append(color(label, "38;5;" + ansi, color_on) if ansi else label)
        if receipts:
            seg += "   " + "  ".join(receipts)

        badges = []
        for b in _items(row, "badges"):
            label = sanitize(str(b.get("label", "")))
            base = _BADGE_ANSI.get(str(b.get("label", "")), "245")
            code = ("1;38;5;" + base) if b.get("hot") else ("38;5;" + base)
            badges.append(color(label, code, color_on))
        if badges:
            seg += "   " + " ".join(badges)

        lines.append(seg)
    return "\n".join(lines)


def _md_cell(text):
    """Sanitize a value and escape pipes so it cannot break the table grid."""
    return sanitize(str(text)).replace("|", "\\|")


def render_md(rows):
    """Render the board as a GitHub markdown table."""
    out = ["| # | Item | Receipts | Badges |", "| --- | --- | --- | --- |"]
    for row in _rows(rows):
        rank = _md_cell(row.get("rank", ""))
        name = _md_cell(row.get("name", ""))
        url = row.get("url")
        if url:
            name = "[{}]({})".format(name, _md_cell(url))

        receipts = " · ".join(
            _md_cell(r.get("label", "")) for r in _items(row, "receipts")
        )
        badges = " ".join(
            "`{}`".format(_md_cell(b.get("label", ""))) for b in _items(row, "badges")
        )
        out.append("| {} | {} | {} | {} |".format(rank, name, receipts, badges))
    return "\n".join(out)


def render_html(rows, *, entity="repos"):
    """Render the light-board row markup (matches docs/index.html). No outer wrapper."""
    # ponytail: `entity` is part of the board API (wrapper/aria callers use it);
    # the per-row markup below has no wrapper, so it is intentionally unused here.
    del entity

    out = []
    for row in _rows(rows):
        rank = html.escape(str(row.get("rank", "")))
        name = html.escape(str(row.get("name", "")))
        meta = row.get("meta")
        meta_html = (
            '<span class="meta">{}</span>'.format(html.escape(str(meta)))
            if meta not in (None, "")
            else ""
        )

        chips = []
        for r in _items(row, "receipts"):
            cls = _CHIP_CLASS.get(str(r.get("kind", "")), "")
            label = html.escape(str(r.get("label", "")))
            chips.append(
                '<span class="{}"><i class="dot"></i>{}</span>'.format(
                    ("chip " + cls).strip(), label
                )
            )

        badges = []
        for b in _items(row, "badges"):
            cls = _BADGE_CLASS.get(str(b.get("label", "")), "")
            if b.get("hot"):
                cls = (cls + " hot").strip()
            label = html.escape(str(b.get("label", "")))
            badges.append(
                '<span class="{}">{}</span>'.format(("badge " + cls).strip(), label)
            )

        out.append(
            '<div class="row"><div class="rank">{rank}</div>'
            '<div class="item"><div class="name">{name}{meta}</div>'
            '<div class="receipts">{chips}</div></div>'
            '<div class="badges">{badges}</div></div>'.format(
                rank=rank,
                name=name,
                meta=meta_html,
                chips="".join(chips),
                badges="".join(badges),
            )
        )
    return "".join(out)
