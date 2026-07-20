from hotin.render import color, sanitize


def test_hostile_terminal_content_is_stripped():
    hostile = "good\x1b[31mred\x1b[0m\u202eevil\x1b]8;;https://bad.example\x1b\\link\x1b]8;;\x1b\\"
    safe = sanitize(hostile)

    assert "\x1b" not in safe
    assert "\u202e" not in safe
    assert "https://bad.example" not in safe
    assert safe == "goodredevillink"


def test_color_only_adds_codes_when_enabled():
    assert color("hello", "31", enabled=False) == "hello"
    assert color("hello", "31", enabled=True) == "\x1b[31mhello\x1b[0m"
