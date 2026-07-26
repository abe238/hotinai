import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compute_embeddings import load_corpus  # noqa: E402


def _write(tmp_path, latest):
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(latest))
    return path


def test_load_corpus_dedupes_across_tabs(tmp_path):
    # a repo shown in both "repos" and "rising" must only be embedded once
    latest = {"entities": {
        "repos": [{"id": "a/b", "name": "a/b", "meta": "desc one"}],
        "rising": [{"id": "a/b", "name": "a/b", "meta": "desc one"}],
        "models": [{"id": "org/m", "name": "org/m", "meta": "a model"}],
    }}
    corpus = load_corpus(_write(tmp_path, latest))
    ids = [c[0] for c in corpus]
    assert ids.count("a/b") == 1
    assert "org/m" in ids


def test_load_corpus_skips_rows_without_id(tmp_path):
    latest = {"entities": {"news": [
        {"id": None, "name": "swept 12 feeds"},  # the provenance note row
        {"id": "https://x.com/y", "name": "A headline", "meta": "publisher"},
    ]}}
    corpus = load_corpus(_write(tmp_path, latest))
    assert len(corpus) == 1
    assert corpus[0][0] == "https://x.com/y"


def test_load_corpus_infers_entity_type_from_tab(tmp_path):
    latest = {"entities": {"papers": [{"id": "p1", "name": "Paper", "meta": "abstract"}]}}
    corpus = load_corpus(_write(tmp_path, latest))
    assert corpus[0][1] == "paper"


def test_load_corpus_falls_back_to_id_when_name_and_meta_are_empty(tmp_path):
    latest = {"entities": {"repos": [{"id": "a/b", "name": "", "meta": ""}]}}
    corpus = load_corpus(_write(tmp_path, latest))
    assert len(corpus) == 1
    assert corpus[0][3] == "a/b"  # text falls back to the id itself, never truly empty
