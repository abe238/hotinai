from hotin.health import SourceStatus, summarize


def test_all_source_errors_fail_with_details():
    code, message = summarize([
        SourceStatus("github", "error", "rate limited"),
        SourceStatus("hn", "error", "offline"),
    ])

    assert code == 1
    assert "github: rate limited" in message
    assert "hn: offline" in message


def test_ok_or_cached_data_succeeds():
    assert summarize([SourceStatus("hn", "ok")])[0] == 0
    assert summarize([SourceStatus("hn", "error", "offline")], cache_has_data=True)[0] == 0


def test_empty_source_is_not_a_fetch_failure():
    assert summarize([SourceStatus("hn", "empty")]) == (0, "no results from available sources")
