import pytest

from hotin.cli import COMMANDS, main


def test_help_lists_every_subcommand(capsys):
    with pytest.raises(SystemExit) as exited:
        main(["--help"])

    output = capsys.readouterr().out
    assert exited.value.code == 0
    for command in COMMANDS:
        assert command in output


def test_setup_check_succeeds_without_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert main(["setup", "--check"]) == 0
    output = capsys.readouterr().out
    assert "configured entries: 0" in output
    assert "setup check passed" in output


def test_setup_check_sanitizes_config_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "\x1b[31mHACKED\x1b[0m" / "xdgconfig"))

    assert main(["setup", "--check"]) == 0
    assert "\x1b" not in capsys.readouterr().out
