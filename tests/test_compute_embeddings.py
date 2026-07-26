import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compute_embeddings import (load_corpus, load_existing,  # noqa: E402
                                 merge_vectors, select_uncomputed)


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


def test_load_existing_never_overwrites_confirmed_exemplars(tmp_path):
    # This is the exact bug review caught: a wholesale rewrite of
    # embeddings.json would wipe every human-confirmed exemplar on the next
    # 3h run. load_existing() is the read half of the merge-not-replace fix.
    path = tmp_path / "embeddings.json"
    path.write_text(json.dumps({"_schema_version": 1,
                                 "items": {"a/b": {"vector": [1.0, 0.0], "model": "all-MiniLM-L6-v2"}},
                                 "exemplars": {"agents": ["a/b"]}}))
    items, exemplars = load_existing(path)
    assert exemplars == {"agents": ["a/b"]}
    assert items == {"a/b": {"vector": [1.0, 0.0], "model": "all-MiniLM-L6-v2"}}


def test_load_existing_defaults_when_file_absent(tmp_path):
    items, exemplars = load_existing(tmp_path / "absent.json")
    assert items == {} and exemplars == {}


def test_select_uncomputed_skips_items_already_embedded_with_current_model():
    corpus = [("a/b", "repo", "a/b", "text a"), ("c/d", "repo", "c/d", "text c")]
    items = {"a/b": {"model": "all-MiniLM-L6-v2"}}
    to_embed = select_uncomputed(corpus, items, "all-MiniLM-L6-v2")
    assert [c[0] for c in to_embed] == ["c/d"]


def test_select_uncomputed_re_embeds_on_a_model_change():
    corpus = [("a/b", "repo", "a/b", "text a")]
    items = {"a/b": {"model": "an-old-model"}}
    to_embed = select_uncomputed(corpus, items, "all-MiniLM-L6-v2")
    assert [c[0] for c in to_embed] == ["a/b"]


def test_merge_vectors_only_touches_the_embedded_ids():
    items = {"exemplar/1": {"vector": [9.0, 9.0], "model": "all-MiniLM-L6-v2"}}
    to_embed = [("new/x", "repo", "new/x", "text")]
    merge_vectors(items, to_embed, [[0.5, 0.5]], "all-MiniLM-L6-v2", "2026-07-26T00:00:00Z")
    assert items["exemplar/1"]["vector"] == [9.0, 9.0]  # untouched
    assert items["new/x"]["vector"] == [0.5, 0.5]


def test_merge_vectors_preserves_an_exemplar_whose_repo_left_the_board():
    # the durability bug review caught: items rebuilds from a churning
    # trending board, so a merge (never dropping old entries) is what keeps
    # a confirmed exemplar's vector alive after it scrolls off.
    items = {"old-exemplar/1": {"vector": [1.0, 0.0], "model": "all-MiniLM-L6-v2"}}
    to_embed = []  # old-exemplar/1 no longer appears in the live corpus at all
    merge_vectors(items, to_embed, [], "all-MiniLM-L6-v2", "2026-07-26T00:00:00Z")
    assert "old-exemplar/1" in items
    assert items["old-exemplar/1"]["vector"] == [1.0, 0.0]
