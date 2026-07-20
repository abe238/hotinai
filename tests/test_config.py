import os

import pytest

from hotin import config


def test_loader_merges_file_and_environment_with_environment_winning(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Clear the known overlay keys so the environment (e.g. CI's GITHUB_TOKEN)
    # can't leak into this exact-equality assertion.
    for key in config._ENV_OVERLAY_KEYS:
        monkeypatch.delenv(key, raising=False)
    config.write_config({"HOTIN_TOKEN": "from-file", "OTHER": "kept"})
    monkeypatch.setenv("HOTIN_TOKEN", "from-environment")

    assert config.load_config() == {"HOTIN_TOKEN": "from-environment", "OTHER": "kept"}


def test_known_key_is_read_from_environment_even_when_file_omits_it(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # No .env file at all; a known hotin key set purely in the environment must
    # still be picked up (the shipped v0.1.0 bug: env-only keys were ignored).
    monkeypatch.setenv("YOUTUBE_API_KEY", "env-only-key")
    cfg = config.load_config()
    assert cfg.get("YOUTUBE_API_KEY") == "env-only-key"
    # An unrelated process variable is NOT pulled in.
    monkeypatch.setenv("SOME_UNRELATED_VAR", "nope")
    assert "SOME_UNRELATED_VAR" not in config.load_config()


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
    if os.name != "nt":
        # POSIX modes don't apply on Windows (file privacy comes from profile
        # ACLs); config.write_config already guards the Unix-only os.fchmod.
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
