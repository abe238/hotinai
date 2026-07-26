import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from surface_exemplar_candidates import EXEMPLAR_CLICK_THRESHOLD, MAX_PENDING, surface  # noqa: E402


def _clicks(entity_id, total_clicks):
    return {"items": {entity_id: {"days": {"20260726": {"clicks": total_clicks, "sessions": 1}},
                                    "clicks_total": 0}}}


def test_item_over_threshold_becomes_a_candidate():
    clicks = _clicks("a/b", EXEMPLAR_CLICK_THRESHOLD)
    tags = {"a/b": {"tag": "agents", "source": "keyword"}}
    pending = {"candidates": []}
    added = surface(clicks, tags, {"exemplars": {}}, pending)
    assert added == 1
    assert pending["candidates"][0]["entity_id"] == "a/b"
    assert pending["candidates"][0]["suggested_tag"] == "agents"
    assert pending["candidates"][0]["tag_source"] == "keyword"


def test_candidate_flags_when_the_suggestion_is_itself_an_inference():
    # laundering mitigation: a human approving a pre-filled suggestion that
    # is ALREADY exemplar-inferred would be rubber-stamping a second hop
    # through the human step rather than through code. The queue must say so.
    clicks = _clicks("a/b", EXEMPLAR_CLICK_THRESHOLD)
    tags = {"a/b": {"tag": "agents", "source": "exemplar-inferred"}}
    pending = {"candidates": []}
    surface(clicks, tags, {"exemplars": {}}, pending)
    assert pending["candidates"][0]["tag_source"] == "exemplar-inferred"


def test_item_under_threshold_is_not_a_candidate():
    clicks = _clicks("a/b", EXEMPLAR_CLICK_THRESHOLD - 1)
    pending = {"candidates": []}
    added = surface(clicks, {}, {"exemplars": {}}, pending)
    assert added == 0
    assert pending["candidates"] == []


def test_already_pending_item_is_not_added_twice():
    clicks = _clicks("a/b", EXEMPLAR_CLICK_THRESHOLD)
    pending = {"candidates": [{"entity_id": "a/b", "suggested_tag": "agents"}]}
    added = surface(clicks, {}, {"exemplars": {}}, pending)
    assert added == 0
    assert len(pending["candidates"]) == 1


def test_already_confirmed_exemplar_is_never_re_surfaced():
    clicks = _clicks("a/b", EXEMPLAR_CLICK_THRESHOLD)
    embeddings = {"exemplars": {"agents": ["a/b"]}}
    pending = {"candidates": []}
    added = surface(clicks, {}, embeddings, pending)
    assert added == 0


def test_queue_is_bounded_at_max_pending():
    clicks = {"items": {f"item/{i}": {"days": {"d": {"clicks": EXEMPLAR_CLICK_THRESHOLD, "sessions": 1}}}
                         for i in range(MAX_PENDING + 10)}}
    pending = {"candidates": []}
    surface(clicks, {}, {"exemplars": {}}, pending)
    assert len(pending["candidates"]) == MAX_PENDING


def test_untagged_item_gets_uncategorized_suggestion():
    clicks = _clicks("a/b", EXEMPLAR_CLICK_THRESHOLD)
    pending = {"candidates": []}
    surface(clicks, {}, {"exemplars": {}}, pending)
    assert pending["candidates"][0]["suggested_tag"] == "uncategorized"
