"""Keep every test's data store (cache.db, insiders_poll.json) in a tmp dir.

Without this, tests that poll the roster through stubbed transports would
persist fixture events into the real ~/.local/share/hotin store, and a live
`hotin export` on the same machine could reuse them within the TTL.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
