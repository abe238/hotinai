import os

import pytest

from hotin import config


def test_loader_merges_file_and_environment_with_environment_winning(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.write_config({"HOTIN_TOKEN": "from-file", "OTHER": "kept"})
    monkeypatch.setenv("HOTIN_TOKEN", "from-environment")

    assert config.load_config() == {"HOTIN_TOKEN": "from-environment", "OTHER": "kept"}


def test_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.load_config() == {}


def test_write_is_atomic_and_uses_replace(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    replaced = []
    real_replace = os.replace

    def recording_replace(source, destination):
        replaced.append((source, destination))
        return real_replace(source, destination)

    monkeypatch.setattr(config.os, "replace", recording_replace)
    config.write_config({"A": "one"})

    assert replaced
    assert config.env_path().read_text() == "A=one\n"
    assert config.env_path().stat().st_mode & 0o777 == 0o600
    assert not list(config.env_path().parent.glob(".env.*"))


def test_refuses_to_write_through_symlink(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    target = tmp_path / "outside"
    target.write_text("keep")
    path = config.env_path()
    path.symlink_to(target)

    with pytest.raises(RuntimeError, match="symlink"):
        config.write_config({"A": "one"})
    assert target.read_text() == "keep"


def test_write_rejects_carriage_return_in_value(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with pytest.raises(ValueError, match="single-line"):
        config.write_config({"TOKEN": "good\rINJECTED=yes"})
