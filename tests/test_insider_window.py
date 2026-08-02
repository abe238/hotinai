"""The star window: default, override, and the ways an override can be wrong."""

import pytest

from hotin.sources import _insider_roster as ir


def test_the_default_is_45_days():
    # Widened 30 -> 45 in 0.7.0. Measured: 45d yields 39 repos with >=2 backers
    # against 30d's 28, for a 3.6x growth lift against 4.4x. Best trade on the
    # curve; the signal degrades monotonically as the window widens.
    assert ir.DEFAULT_WINDOW_DAYS == 45
    assert ir._window(None, None) == 45


def test_an_explicit_argument_beats_everything():
    assert ir._window({"HOTIN_INSIDER_WINDOW_DAYS": "60"}, 30) == 30


def test_the_env_override_is_honoured():
    # The whole point: tuning this must never again require a PyPI release.
    assert ir._window({"HOTIN_INSIDER_WINDOW_DAYS": "60"}, None) == 60
    assert ir._window({"HOTIN_INSIDER_WINDOW_DAYS": " 21 "}, None) == 21


@pytest.mark.parametrize("bad", ["", None, "abc", "30d", "0", "-5", "9999", "1e3"])
def test_a_bad_override_falls_back_instead_of_raising(bad):
    # A typo in an environment variable must not take the board down. A silently
    # clamped window is far easier to notice than a crashed bake.
    assert ir._window({"HOTIN_INSIDER_WINDOW_DAYS": bad}, None) == 45


def test_the_bounds_are_inclusive():
    assert ir._window({"HOTIN_INSIDER_WINDOW_DAYS": "1"}, None) == 1
    assert ir._window({"HOTIN_INSIDER_WINDOW_DAYS": "365"}, None) == 365
    assert ir._window({"HOTIN_INSIDER_WINDOW_DAYS": "366"}, None) == 45


def test_the_variable_is_allowed_through_config():
    from hotin import config
    src = open(config.__file__).read()
    assert "HOTIN_INSIDER_WINDOW_DAYS" in src, "an env var not in the allowlist is inert"
