from hotin.render_board import render_html, render_md, render_text

BORDER_CHARS = "│─┌┐└┘├┤┬┴┼╭╮╰╯"

ROWS = [
    {
        "rank": 1,
        "name": "vercel-labs/deepsec",
        "url": "https://github.com/vercel-labs/deepsec",
        "meta": "AI security scanner",
        "receipts": [
            {"label": "HN #1", "kind": "hn"},
            {"label": "npm 1.2M/wk", "kind": "npm"},
            {"label": "reddit 340", "kind": "reddit"},
        ],
        "badges": [{"label": "fresh", "hot": False}],
    },
    {
        "rank": 2,
        "name": "xai-org/grok-build",
        "url": "https://github.com/xai-org/grok-build",
        "meta": "Grok Build is open source",
        "receipts": [
            {"label": "stars +2.1k", "kind": "stars"},
            {"label": "AI Insiders 12", "kind": "insiders"},
        ],
        "badges": [
            {"label": "trending", "hot": True},
            {"label": "smart-money", "hot": False},
        ],
    },
]


def test_render_text_has_names_no_markup():
    out = render_text(ROWS)
    assert "vercel-labs/deepsec" in out
    assert "xai-org/grok-build" in out
    assert "<" not in out
    for ch in BORDER_CHARS:
        assert ch not in out


def test_render_text_color_off_has_no_ansi():
    out = render_text(ROWS, color_on=False)
    assert "\x1b" not in out
    assert "vercel-labs/deepsec" in out


def test_render_md_is_pipe_table_with_header():
    out = render_md(ROWS)
    lines = out.splitlines()
    assert lines[0] == "| # | Item | Receipts | Badges |"
    assert lines[1] == "| --- | --- | --- | --- |"
    # name links out, receipts joined by the middle dot, badges are code tokens.
    assert "[vercel-labs/deepsec](https://github.com/vercel-labs/deepsec)" in out
    assert " · " in out
    assert "`fresh`" in out


def test_render_html_has_board_markup():
    out = render_html(ROWS)
    assert 'class="row"' in out
    assert 'class="chip' in out
    assert 'class="badge' in out
    assert 'class="chip gold"' in out  # stars + insiders both map to gold
    assert 'class="badge trend hot"' in out  # hot trending badge
    assert 'class="badge smart"' in out


def test_render_html_links_the_name():
    out = render_html(ROWS)
    # a row with a url wraps the name in an anchor that opens the source
    assert ('<a href="https://github.com/vercel-labs/deepsec" '
            'target="_blank" rel="noopener">') in out
    # a url-less row has no dangling anchor but still shows the name
    sparse = [{"rank": 1, "name": "bare/row", "receipts": [], "badges": []}]
    assert "<a " not in render_html(sparse)
    assert "bare/row" in render_html(sparse)


def test_render_html_escapes_hostile_name():
    rows = [{"rank": 1, "name": "<script>alert(1)</script>", "receipts": [], "badges": []}]
    out = render_html(rows)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_missing_keys_never_raise():
    sparse = [{"rank": 7, "name": "bare/row"}]  # no receipts/badges/meta/url keys
    assert "bare/row" in render_text(sparse)
    assert "bare/row" in render_md(sparse)
    assert "bare/row" in render_html(sparse)
    # fully empty and malformed inputs must also be total.
    for bad in ([], [None], [{}], None):
        render_text(bad)
        render_md(bad)
        render_html(bad)
