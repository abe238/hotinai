#!/usr/bin/env python3
"""Render real `hotin` output as an SVG terminal for the README.

A CLI whose entire value is a ranked board with receipt chips had no image in
its README. For a terminal tool that is the single highest-leverage thing
missing: people decide whether to read further from the picture, and hotin was
describing something whose whole point is how it looks.

SVG rather than a GIF or PNG, deliberately:
  * text stays crisp at any zoom and on any display
  * a few KB instead of a few hundred
  * no recording tooling, no binary in git history
  * regenerable from real output, so it cannot drift into a lie about what the
    tool prints

STRICT XML. GitHub renders this through <img>, which parses SVG as XML rather
than HTML: one unescaped & or < blanks the whole image with no error anywhere.
Everything user-supplied goes through esc().

    python3 -m hotin repos --limit 8 | python3 scripts/render_demo_svg.py > docs/demo.svg
"""

from __future__ import annotations

import re
import sys

CHAR_W, LINE_H, PAD = 7.8, 21.0, 18.0
BG, FG, DIM = "#0d1117", "#e6edf3", "#8b949e"
SCORE, NAME, TAG = "#f0883e", "#e6edf3", "#7d8590"
BADGE = {"fresh": "#3fb950", "rising": "#f0883e", "viral": "#f85149",
         "smart-money": "#d29922", "paper-backed": "#a371f7"}


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def spans(line: str) -> list:
    """(text, colour, bold) runs for one line of `hotin repos` output.

    Parsed from the real shape rather than re-implementing the formatter: a
    leading score, a repo slug, a tag, then badges. Anything unrecognised is
    rendered dim, so an output change degrades to plain text instead of
    silently mis-colouring.
    """
    m = re.match(r"^(\s*)(\d+\.\d+)\s+(\S+)\s*(.*)$", line)
    if not m:
        return [(line, DIM, False)]
    lead, score, slug, rest = m.groups()
    out = [(lead + score, SCORE, True), ("  " + slug, NAME, True)]
    for word in rest.split():
        colour = BADGE.get(word)
        out.append(("  " + word, colour or TAG, bool(colour)))
    return out


def render(lines: list, title: str = "hotin repos") -> str:
    width = max([len(l) for l in lines] + [len(title) + 24])
    w = int(width * CHAR_W + PAD * 2)
    h = int((len(lines) + 3) * LINE_H + PAD * 2)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="{}" height="{}" '
        'viewBox="0 0 {} {}" role="img" aria-label="hotin terminal output">'.format(w, h, w, h),
        '<rect width="{}" height="{}" rx="10" fill="{}"/>'.format(w, h, BG),
        # window chrome: three dots, the universal "this is a terminal" cue
        '<circle cx="20" cy="18" r="5" fill="#ff5f56"/>',
        '<circle cx="38" cy="18" r="5" fill="#ffbd2e"/>',
        '<circle cx="56" cy="18" r="5" fill="#27c93f"/>',
        '<g font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" '
        'font-size="13">',
        '<text x="{}" y="{}" fill="{}">$ </text>'.format(PAD, PAD + LINE_H * 1.6, "#3fb950"),
        '<text x="{}" y="{}" fill="{}">{}</text>'.format(
            PAD + CHAR_W * 2, PAD + LINE_H * 1.6, FG, esc(title)),
    ]
    for i, line in enumerate(lines):
        y = PAD + LINE_H * (i + 3)
        x = PAD
        for text, colour, bold in spans(line):
            if text.strip():
                parts.append(
                    '<text x="{:.1f}" y="{:.1f}" fill="{}"{}>{}</text>'.format(
                        x, y, colour, ' font-weight="600"' if bold else "", esc(text)))
            x += len(text) * CHAR_W
    parts += ["</g>", "</svg>"]
    return "\n".join(parts) + "\n"


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    lines = [l.rstrip("\n") for l in sys.stdin.read().splitlines() if l.strip()]
    if not lines:
        print("no input on stdin", file=sys.stderr)
        return 2
    sys.stdout.write(render(lines))
    return 0


def selftest() -> int:
    out = render([" 70.09  a/b  dev-tools  fresh rising",
                  '        Show HN: 5 < 6 & "quotes"'])
    for raw, encoded in (("<", "&lt;"), ("&", "&amp;"), ('"', "&quot;")):
        assert encoded in out, ("must escape " + raw)
    # Strict XML: GitHub's <img> parser blanks the image on one bad token.
    import xml.etree.ElementTree as ET
    ET.fromstring(out)
    assert BADGE["fresh"] in out and BADGE["rising"] in out, "badges must be coloured"
    assert 'role="img"' in out and "aria-label" in out, "needs an accessible name"
    # An unrecognised line degrades to plain dim text rather than mis-colouring.
    assert spans("just some prose")[0][1] == DIM
    print("selftest ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
