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


def test_injection_payloads_stay_neutralized():
    # sanitize() is the single most important security control (every untrusted
    # source string routes through it before hitting the terminal). Pin the
    # exact payload classes a security review verified so a future refactor of
    # the regexes can't silently regress the neutralizer. Each payload must
    # leave no escape byte, control byte, or bidi override behind.
    payloads = [
        "\x1b[31mred",                       # 7-bit CSI (SGR color)
        "\x1b]0;title\x07",                  # 7-bit OSC (window-title set, BEL-terminated)
        "\x1b]8;;https://evil.example\x1b\\txt\x1b]8;;\x1b\\",  # OSC-8 hyperlink
        "\x9b31mred",                        # 8-bit CSI (C1)
        "\x9d0;title\x07",                   # 8-bit OSC (C1)
        "before‮after",                 # bidi override (trojan-source)
        "lone\x1bescape",                    # bare ESC
        "line1\nline2\rline3",               # newline/CR line injection
        "tail\x7fdel",                       # DEL
        "trunc\x1b[",                        # truncated CSI
    ]
    for payload in payloads:
        safe = sanitize(payload)
        assert "\x1b" not in safe, payload
        assert "\x9b" not in safe and "\x9d" not in safe, payload
        assert "‮" not in safe, payload
        assert "\n" not in safe and "\r" not in safe, payload
        assert "\x7f" not in safe, payload
        assert "evil.example" not in safe
