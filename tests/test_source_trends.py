from hotin.sources import trends


COLUMNS = [
    {"col": "repo_name"},
    {"col": "primary_language"},
    {"col": "description"},
    {"col": "stars"},
    {"col": "pull_requests"},
    {"col": "pushes"},
    {"col": "total_score"},
]


def test_positional_and_object_rows_parse_identically():
    positional = {
        "data": {
            "columns": COLUMNS,
            "rows": [["Example/Project", "Python", "Useful", "12", "3", "4", "9.5"]],
        }
    }
    object_rows = {
        "data": {
            "columns": COLUMNS,
            "rows": [
                {
                    "repo_name": "Example/Project",
                    "primary_language": "Python",
                    "description": "Useful",
                    "stars": "12",
                    "pull_requests": "3",
                    "pushes": "4",
                    "total_score": "9.5",
                }
            ],
        }
    }

    positional_records = trends.parse_response(positional)
    assert positional_records == trends.parse_response(object_rows)
    assert positional_records == [
        {
            "url": "https://github.com/example/project",
            "canonical_repo": "example/project",
            "name": "example/project",
            "source": "trends",
            "signal": {
                "trend_stars": 12,
                "trend_pull_requests": 3,
                "trend_pushes": 4,
                "trend_total_score": 9.5,
            },
            "meta": {"language": "Python", "description": "Useful"},
        }
    ]


def test_collection_score_and_full_name_are_supported():
    payload = {
        "data": {
            "columns": [{"col": "full_name"}, {"col": "collection_score"}],
            "rows": [{"full_name": "Owner/Repo", "collection_score": 4.25}],
        }
    }

    records = trends.parse_response(payload)
    assert records[0]["canonical_repo"] == "owner/repo"
    assert records[0]["signal"] == {"trend_collection_score": 4.25}


def test_hostile_input_degrades_without_raising():
    malformed_rows = {
        "data": {
            "columns": COLUMNS,
            "rows": [["Example/Project"], "not-a-row", {"repo_name": "bad repo"}],
        }
    }
    assert trends.parse_response(malformed_rows) == []
    assert trends.parse_response({"data": {"rows": []}}) == []
    assert trends.parse_response({"data": {"columns": "wrong", "rows": []}}) == []


def test_infinite_metrics_are_ignored():
    payload = {
        "data": {
            "columns": [{"col": "repo_name"}, {"col": "stars"}, {"col": "total_score"}],
            "rows": [["Example/Project", 1e309, 1e309]],
        }
    }
    assert trends.parse_response(payload)[0]["signal"] == {}


def test_selftest():
    trends.selftest()


def test_an_upstream_retirement_is_reported_as_such_not_as_a_quiet_day():
    """The provider publishes its own availability; say what it says.

    This ranking has been unavailable since 2026-03-01 (their GitHub event capture fell to
    ~0.3% of baseline). For months it reported a bare "no usable GitHub repositories found",
    which reads exactly like a quiet day, so a source contributing a guaranteed zero was
    indistinguishable from one that simply had nothing that morning.
    """
    payload = {
        "data": {"columns": [], "rows": [], "result": {"row_count": 0}},
        "data_quality": {"status": "unavailable", "unavailable_since": "2026-03-01",
                         "reason": "event capture fell to ~0.3% of baseline"},
    }
    detail = trends._unavailable_detail(payload)
    assert "RETIRED" in detail
    assert "2026-03-01" in detail
    assert "not a quiet day" in detail


def test_a_genuinely_empty_but_healthy_upstream_still_reads_as_empty():
    """A real quiet day must NOT be mislabelled as a retirement."""
    payload = {"data": {"columns": ["repo_name"], "rows": [], "result": {"row_count": 0}}}
    assert trends._unavailable_detail(payload) == "no usable GitHub repositories found"
    payload_ok = {"data": {"rows": []}, "data_quality": {"status": "ok"}}
    assert trends._unavailable_detail(payload_ok) == "no usable GitHub repositories found"
