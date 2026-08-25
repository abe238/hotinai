import json
from pathlib import Path

from hotin.cli import _classify_entities, _write_tags_json


def test_classify_entities_covers_every_entity_type():
    # fake-success mode this guards: classify_entities silently drops
    # papers/models/news and only ever tags repo-type entities.
    repo_lists = [[
        {"entity_id": "a/agentic", "canonical_repo": "a/agentic", "name": "a/agentic",
         "category": "agents", "meta": {}},
        {"entity_id": None, "canonical_repo": None, "name": "no-id-row", "meta": {}},
    ]]
    models = [{"entity_id": "org/mini-8b",
               "meta": {"model_description": "an open-weights small-model for efficient on-device inference"}}]
    papers = [{"entity_id": "p1", "name": "DocReason",
               "meta": {"paper_summary": "an OCR pipeline for document-understanding"}}]
    news = [{"entity_id": "n1", "name": "New agentic reasoning model ships"}]

    items = _classify_entities(repo_lists, models, papers, news)

    assert items["a/agentic"] == "agents"  # repo: uses precomputed category
    assert "None" not in items and None not in items  # id-less rows never enter the ledger
    assert items["org/mini-8b"] == "inference"
    assert items["p1"] == "app-building"
    assert items["n1"] == "agents"


def test_classify_entities_falls_back_when_repo_category_missing():
    repo_lists = [[{"entity_id": "x/y", "canonical_repo": "x/y", "name": "x/y",
                    "meta": {"description": "a multi-agent orchestration framework"}}]]
    items = _classify_entities(repo_lists, [], [], [])
    assert items["x/y"] == "agents"


def test_write_tags_json_merges_and_never_drops_prior_entries(tmp_path):
    docs = tmp_path / "docs"
    (docs / "data").mkdir(parents=True)
    _write_tags_json(docs, {"a/b": "agents"}, "2026-07-26 10:00 PT")
    _write_tags_json(docs, {"c/d": "inference"}, "2026-07-26 13:00 PT")

    data = json.loads((docs / "data" / "tags.json").read_text())
    assert data["_schema_version"] == 1
    assert data["items"]["a/b"]["tag"] == "agents"  # first run's entry survives
    assert data["items"]["c/d"]["tag"] == "inference"
    assert data["items"]["c/d"]["source"] == "keyword"


def test_write_tags_json_overwrites_same_entity_idempotently(tmp_path):
    docs = tmp_path / "docs"
    (docs / "data").mkdir(parents=True)
    _write_tags_json(docs, {"a/b": "agents"}, "2026-07-26 10:00 PT")
    _write_tags_json(docs, {"a/b": "inference"}, "2026-07-26 13:00 PT")

    data = json.loads((docs / "data" / "tags.json").read_text())
    assert data["items"]["a/b"]["tag"] == "inference"
    assert len(data["items"]) == 1


def test_write_tags_json_never_raises_on_malformed_prior_file(tmp_path):
    # fake-success mode this guards: a broken tags.json (bad merge, truncated
    # write, a top-level JSON array/string/null instead of an object) must
    # degrade gracefully, never raise and take the whole `hotin export` down.
    docs = tmp_path / "docs"
    (docs / "data").mkdir(parents=True)
    path = docs / "data" / "tags.json"
    for broken in ("[]", '"just a string"', "null", "{not valid json", ""):
        path.write_text(broken)
        _write_tags_json(docs, {"a/b": "agents"}, "2026-07-26 10:00 PT")
        data = json.loads(path.read_text())
        assert data["items"]["a/b"]["tag"] == "agents"


def test_write_tags_json_uncategorized_never_stomps_a_propagated_tag(tmp_path):
    # The tagging workflow fills uncategorized items via exemplar propagation;
    # the next bake re-classifies board items and must not revert those fills
    # ("uncategorized" is an absence, not a verdict).
    docs = tmp_path / "docs"
    (docs / "data").mkdir(parents=True)
    (docs / "data" / "tags.json").write_text(json.dumps({
        "_schema_version": 1,
        "items": {"a/b": {"tag": "inference", "source": "exemplar-inferred",
                          "confidence": 0.51}}}))
    _write_tags_json(docs, {"a/b": "uncategorized"}, "2026-08-25 10:00 PT")
    data = json.loads((docs / "data" / "tags.json").read_text())
    assert data["items"]["a/b"]["tag"] == "inference"
    assert data["items"]["a/b"]["source"] == "exemplar-inferred"


def test_write_tags_json_real_keyword_tag_still_wins_over_propagated(tmp_path):
    docs = tmp_path / "docs"
    (docs / "data").mkdir(parents=True)
    (docs / "data" / "tags.json").write_text(json.dumps({
        "_schema_version": 1,
        "items": {"a/b": {"tag": "training", "source": "exemplar-inferred",
                          "confidence": 0.44}}}))
    _write_tags_json(docs, {"a/b": "agents"}, "2026-08-25 10:00 PT")
    data = json.loads((docs / "data" / "tags.json").read_text())
    assert data["items"]["a/b"]["tag"] == "agents"
    assert data["items"]["a/b"]["source"] == "keyword"
