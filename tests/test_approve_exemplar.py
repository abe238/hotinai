import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import approve_exemplar  # noqa: E402


def _setup(tmp_path, embeddings=None, pending=None):
    data = tmp_path / "docs" / "data"
    data.mkdir(parents=True)
    (data / "embeddings.json").write_text(json.dumps(
        embeddings or {"_schema_version": 1, "items": {"a/b": {"vector": [1.0, 0.0]}}, "exemplars": {}}))
    (data / "exemplars_pending.json").write_text(json.dumps(
        pending or {"_schema_version": 1, "candidates": [{"entity_id": "a/b", "suggested_tag": "agents"}]}))
    return data


def test_approve_adds_to_exemplars_and_removes_from_pending(tmp_path, monkeypatch):
    data = _setup(tmp_path)
    monkeypatch.setattr(approve_exemplar, "__file__", str(tmp_path / "scripts" / "approve_exemplar.py"))

    rc = approve_exemplar.main(["a/b", "agents"])
    assert rc == 0
    embeddings = json.loads((data / "embeddings.json").read_text())
    assert embeddings["exemplars"]["agents"] == ["a/b"]
    pending = json.loads((data / "exemplars_pending.json").read_text())
    assert pending["candidates"] == []


def test_approve_is_idempotent(tmp_path, monkeypatch):
    data = _setup(tmp_path, embeddings={"_schema_version": 1, "items": {"a/b": {"vector": [1.0, 0.0]}},
                                          "exemplars": {"agents": ["a/b"]}})
    monkeypatch.setattr(approve_exemplar, "__file__", str(tmp_path / "scripts" / "approve_exemplar.py"))
    rc = approve_exemplar.main(["a/b", "agents"])
    assert rc == 0
    embeddings = json.loads((data / "embeddings.json").read_text())
    assert embeddings["exemplars"]["agents"] == ["a/b"]  # not duplicated


def test_approve_rejects_entity_with_no_embedding(tmp_path, monkeypatch, capsys):
    data = _setup(tmp_path, embeddings={"_schema_version": 1, "items": {}, "exemplars": {}})
    monkeypatch.setattr(approve_exemplar, "__file__", str(tmp_path / "scripts" / "approve_exemplar.py"))
    rc = approve_exemplar.main(["no-such/item", "agents"])
    assert rc == 1
    embeddings = json.loads((data / "embeddings.json").read_text())
    assert embeddings["exemplars"] == {}


def test_missing_args_returns_usage_error():
    assert approve_exemplar.main([]) == 2
    assert approve_exemplar.main(["only-one-arg"]) == 2
