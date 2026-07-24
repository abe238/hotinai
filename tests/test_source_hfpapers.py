import json

from hotin.sources import hfpapers


class FakeCache:
    def __init__(self, rows):
        self.rows = rows
        self.upserts = []

    def get_all(self):
        return list(self.rows)

    def upsert(self, record):
        self.upserts.append(record)


def _paper_row(pid, meta):
    return {"entity_type": "paper", "entity_id": pid, "source": "hfpapers",
            "fetched_at": 123.0,
            "signal_json": json.dumps({"signal": {"paper_upvotes": 1}, "meta": meta})}


def test_backfill_heals_only_missing_summaries(monkeypatch):
    cache = FakeCache([
        _paper_row("1", {"paper_title": "A"}),                            # missing -> healed
        _paper_row("2", {"paper_title": "B", "paper_summary": "have"}),   # present -> skipped
        {"entity_type": "repo", "entity_id": "x/y", "signal_json": "{}"},  # not a paper
        _paper_row("3", {"paper_title": "C"}),                            # API has none -> skipped
    ])
    monkeypatch.setattr(hfpapers, "fetch_summary",
                        lambda pid: {"1": "An abstract."}.get(pid))
    healed = hfpapers.backfill_summaries(cache)
    assert healed == 1
    assert len(cache.upserts) == 1
    up = cache.upserts[0]
    assert up["entity_id"] == "1"
    assert up["fetched_at"] == 123.0  # age preserved, not refreshed
    assert up["signal_json"]["meta"]["paper_summary"] == "An abstract."
    # original signal survives the heal
    assert up["signal_json"]["signal"] == {"paper_upvotes": 1}


def test_backfill_is_bounded_and_never_raises(monkeypatch):
    rows = [_paper_row(str(i), {"paper_title": str(i)}) for i in range(10)]
    cache = FakeCache(rows)
    monkeypatch.setattr(hfpapers, "fetch_summary", lambda pid: "s")
    assert hfpapers.backfill_summaries(cache, max_calls=3) == 3

    class ExplodingCache:
        def get_all(self):
            raise RuntimeError("boom")

    assert hfpapers.backfill_summaries(ExplodingCache()) == 0
