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


def test_total_outage_exits_nonzero_even_with_always_empty_stubs():
    # The x stub and unconfigured reddit/youtube are always "empty"; a real
    # total outage (every network source erroring) must still exit 1 rather than
    # be masked by those empties into a success.
    code, message = summarize([
        SourceStatus("github", "error", "rate limited"),
        SourceStatus("hn", "error", "offline"),
        SourceStatus("npm", "error", "timed out"),
        SourceStatus("reddit", "empty", "no SCRAPECREATORS_API_KEY configured"),
        SourceStatus("youtube", "empty", "no SCRAPECREATORS_API_KEY configured"),
        SourceStatus("x", "empty", "not implemented"),
    ])
    assert code == 1
    assert "github: rate limited" in message
