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
