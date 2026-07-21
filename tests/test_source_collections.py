from hotin.sources import collections


COLLECTIONS = {
    "data": [
        {"id": 10, "name": "AI Agents"},
        {"id": 11, "name": "Machine Learning"},
        {"id": 12, "name": "Databases"},
    ]
}

RANKING = {
    "data": {
        "rows": [
            {"repo_name": "Owner/Project", "total": "120", "current_period_growth": "14",
             "current_period_rank": "2"},
        ]
    }
}


def test_parses_collections_ranking_into_repo_records():
    records = collections.parse_ranking(RANKING, "AI Agents")
    assert records == [{
        "entity_type": "repo",
        "entity_id": "owner/project",
        "canonical_repo": "owner/project",
        "url": "https://github.com/owner/project",
        "name": "owner/project",
        "source": "collections",
        "signal": {"stars": 120, "stars_growth": 14, "collections_rank": 2},
        "meta": {"collection": "AI Agents", "on_trending_list": True},
    }]


def test_filters_non_ai_collection_names():
    assert collections.parse_collections(COLLECTIONS) == [
        (10, "AI Agents"), (11, "Machine Learning")
    ]


def test_dedupes_by_entity_id_with_highest_stars_growth():
    lower = collections.parse_ranking(RANKING, "AI Agents")
    higher = collections.parse_ranking(
        {"rows": [{"repo_name": "owner/project", "total": 130, "current_period_growth": 30,
                    "current_period_rank": 1}]}, "LLM tools"
    )
    records = collections.dedupe_records(lower + higher)
    assert len(records) == 1
    assert records[0]["signal"]["stars_growth"] == 30
    assert records[0]["meta"]["collection"] == "LLM tools"


def test_hostile_inputs_degrade_without_raising():
    hostile = {
        "data": {"rows": [None, "not-a-row", {"repo_name": "bad repo"},
                          {"repo_name": "blog/post", "total": 1e309},
                          {"repo_name": "Owner/Good", "total": 1e309,
                           "current_period_growth": 1e309, "current_period_rank": 1e309}]}
    }
    records = collections.parse_ranking(hostile, "AI")
    assert len(records) == 1
    assert records[0]["signal"] == {"stars": 0, "stars_growth": 0, "collections_rank": None}
    assert collections.parse_collections(None) == []
    assert collections.parse_ranking(None, "AI") == []


def test_fetch_errors_when_all_requests_fail(monkeypatch):
    monkeypatch.setattr(collections, "_request", lambda url: None)
    result = collections.fetch(limit=5)
    assert result["status"] == "error"
    assert result["records"] == []


def test_selftest():
    collections.selftest()
