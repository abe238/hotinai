import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from propagate_tags import propagate  # noqa: E402


def _emb(items, exemplars):
    return {"items": items, "exemplars": exemplars}


def test_no_exemplars_yet_tags_nothing():
    # the cold-start / bootstrap case: day one, no human has confirmed
    # anything, propagation must be a safe no-op, never a crash.
    embeddings = _emb({"a/b": {"vector": [1.0, 0.0]}}, {})
    tags, pending = {}, {"candidates": []}
    assert propagate(embeddings, tags, pending) == 0
    assert tags == {}


def test_strong_match_propagates_the_tag():
    embeddings = _emb(
        {"exemplar/1": {"vector": [1.0, 0.0]}, "untagged/x": {"vector": [0.9, 0.1]}},
        {"agents": ["exemplar/1"]},
    )
    tags, pending = {}, {"candidates": []}
    tagged = propagate(embeddings, tags, pending)
    assert tagged == 1
    assert tags["untagged/x"]["tag"] == "agents"
    assert tags["untagged/x"]["source"] == "exemplar-inferred"
    assert tags["untagged/x"]["matched_exemplar"] == "exemplar/1"


def test_below_propagation_threshold_never_tags():
    embeddings = _emb(
        {"exemplar/1": {"vector": [1.0, 0.0]}, "unrelated/x": {"vector": [0.1, 0.99]}},
        {"agents": ["exemplar/1"]},
    )
    tags, pending = {}, {"candidates": []}
    assert propagate(embeddings, tags, pending) == 0
    assert "unrelated/x" not in tags


def test_guardrail_one_hop_cap_inferred_tags_never_anchor_further_propagation():
    # fake-success mode this guards: propagate() must NEVER read from `tags`
    # (only-inferred entities) as a source of exemplar vectors — only
    # embeddings["exemplars"], which only approve_exemplar.py ever writes to.
    embeddings = _emb(
        {"exemplar/1": {"vector": [1.0, 0.0]},
         "inferred/x": {"vector": [0.95, 0.05]},   # would propagate from exemplar/1
         "far/y": {"vector": [0.3, 0.95]}},         # would ONLY match if inferred/x anchored
        {"agents": ["exemplar/1"]},
    )
    tags, pending = {}, {"candidates": []}
    propagate(embeddings, tags, pending)
    assert tags["inferred/x"]["source"] == "exemplar-inferred"
    assert "far/y" not in tags  # never propagated from the newly-inferred item


def test_guardrail_multi_exemplar_consensus_blocks_an_exact_tie():
    # equidistant between two conflicting tags -- must propagate to NEITHER
    embeddings = _emb(
        {"agents-ex": {"vector": [1.0, 0.0]}, "inference-ex": {"vector": [0.0, 1.0]},
         "ambiguous/x": {"vector": [0.7071, 0.7071]}},  # equal cosine sim to both
        {"agents": ["agents-ex"], "inference": ["inference-ex"]},
    )
    tags, pending = {}, {"candidates": []}
    propagate(embeddings, tags, pending)
    assert "ambiguous/x" not in tags


def test_guardrail_consensus_allows_a_clear_winner():
    embeddings = _emb(
        {"agents-ex": {"vector": [1.0, 0.0]}, "inference-ex": {"vector": [0.0, 1.0]},
         "clear/x": {"vector": [0.99, 0.05]}},
        {"agents": ["agents-ex"], "inference": ["inference-ex"]},
    )
    tags, pending = {}, {"candidates": []}
    propagate(embeddings, tags, pending)
    assert tags["clear/x"]["tag"] == "agents"


def test_guardrail_re_verification_queues_low_confidence_matches():
    embeddings = _emb(
        {"exemplar/1": {"vector": [1.0, 0.0]}, "weak/x": {"vector": [0.45, 0.89]}},
        {"agents": ["exemplar/1"]},
    )
    tags, pending = {}, {"candidates": []}
    propagate(embeddings, tags, pending)
    assert tags["weak/x"]["tag"] == "agents"  # cleared the floor, so it propagates
    ids = {c["entity_id"] for c in pending["candidates"]}
    assert "weak/x" in ids  # but flagged for a human spot-check (low confidence)


def test_guardrail_near_duplicate_flag_on_very_high_similarity():
    embeddings = _emb(
        {"exemplar/1": {"vector": [1.0, 0.0]}, "dup/x": {"vector": [0.999, 0.001]}},
        {"agents": ["exemplar/1"]},
    )
    tags, pending = {}, {"candidates": []}
    propagate(embeddings, tags, pending)
    assert tags["dup/x"]["near_duplicate_of"] == "exemplar/1"


def test_exemplars_are_never_re_tagged():
    embeddings = _emb(
        {"exemplar/1": {"vector": [1.0, 0.0]}, "exemplar/2": {"vector": [0.99, 0.01]}},
        {"agents": ["exemplar/1"], "inference": ["exemplar/2"]},
    )
    tags, pending = {}, {"candidates": []}
    propagate(embeddings, tags, pending)
    assert "exemplar/1" not in tags
    assert "exemplar/2" not in tags


def test_items_with_no_vector_never_crash_the_run():
    embeddings = _emb(
        {"exemplar/1": {"vector": [1.0, 0.0]}, "malformed/x": {}},
        {"agents": ["exemplar/1"]},
    )
    tags, pending = {}, {"candidates": []}
    tagged = propagate(embeddings, tags, pending)  # must not raise
    assert tagged == 0
    assert "malformed/x" not in tags


def test_guardrail_consensus_margin_blocks_a_thin_but_nonzero_lead():
    # a real, valid finding from review: "strictly greater" alone lets a
    # razor-thin, near-noise margin decide a tag. CONSENSUS_MARGIN requires
    # a real gap, not just any margin above zero.
    embeddings = _emb(
        {"agents-ex": {"vector": [1.0, 0.0]}, "inference-ex": {"vector": [0.995, 0.0998]},
         "thin/x": {"vector": [0.999, 0.0447]}},
        {"agents": ["agents-ex"], "inference": ["inference-ex"]},
    )
    tags, pending = {}, {"candidates": []}
    propagate(embeddings, tags, pending)
    assert "thin/x" not in tags  # margin between the two candidate tags is < CONSENSUS_MARGIN


def test_near_dup_threshold_does_not_flag_the_strongest_genuine_match():
    # recalibration check: the tracer's strongest observed GENUINE
    # same-category match (0.58) must stay below NEAR_DUP_THRESHOLD (0.70).
    embeddings = _emb(
        {"exemplar/1": {"vector": [1.0, 0.0]}, "genuine/x": {"vector": [0.58, 0.8146]}},
        {"agents": ["exemplar/1"]},
    )
    tags, pending = {}, {"candidates": []}
    propagate(embeddings, tags, pending)
    assert "near_duplicate_of" not in tags["genuine/x"]


def test_re_verification_queue_respects_max_pending():
    embeddings = _emb(
        {"exemplar/1": {"vector": [1.0, 0.0]},
         **{f"weak/{i}": {"vector": [0.45, 0.89]} for i in range(60)}},
        {"agents": ["exemplar/1"]},
    )
    tags, pending = {}, {"candidates": []}
    tagged = propagate(embeddings, tags, pending)
    assert tagged == 60  # every item still gets tagged...
    assert len(pending["candidates"]) == 50  # ...but the review queue stays bounded
