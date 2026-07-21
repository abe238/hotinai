from hotin.sources import frontier


def test_parses_rss_and_sorts_newest_first():
    rss = (
        '<rss><channel>'
        '<item><title>GPT-6 is here</title><link>https://openai.com/news/gpt-6</link>'
        '<pubDate>Fri, 18 Jul 2026 00:00:00 GMT</pubDate></item>'
        '<item><title>Older post</title><link>https://openai.com/news/older</link>'
        '<pubDate>Mon, 01 Jun 2026 00:00:00 GMT</pubDate></item>'
        '<item><title>no link here</title></item>'
        '</channel></rss>'
    )
    recs = frontier.parse_feed(rss, "OpenAI")
    assert [r["name"] for r in recs] == ["GPT-6 is here", "Older post"]
    assert recs[0]["entity_type"] == "release"
    assert recs[0]["meta"] == {"official": True, "lab": "OpenAI",
                               "date": "Fri, 18 Jul 2026 00:00:00 GMT"}
    assert recs[0]["signal"]["released_at"] > recs[1]["signal"]["released_at"]


def test_parses_atom_link_href_and_iso_date():
    atom = ('<feed><entry><title>Gemini 4</title>'
            '<link href="https://deepmind.google/blog/gemini-4"/>'
            '<updated>2026-07-19T12:00:00Z</updated></entry></feed>')
    recs = frontier.parse_feed(atom, "Google DeepMind")
    assert recs[0]["url"] == "https://deepmind.google/blog/gemini-4"
    assert recs[0]["signal"]["released_at"] > 0


def test_malformed_and_non_string_are_safe():
    assert frontier.parse_feed("garbage", "X") == []
    assert frontier.parse_feed(None, "X") == []


def test_fetch_error_when_no_feed_reachable(monkeypatch):
    monkeypatch.setattr(frontier, "_request", lambda url: None)
    result = frontier.fetch(limit=5)
    assert result["status"] == "error"
    assert result["records"] == []


def test_fetch_aggregates_and_caps(monkeypatch):
    feed = ('<rss><channel><item><title>Post</title>'
            '<link>https://example.com/a</link>'
            '<pubDate>Fri, 18 Jul 2026 00:00:00 GMT</pubDate></item></channel></rss>')
    monkeypatch.setattr(frontier, "_request", lambda url: feed)
    result = frontier.fetch(limit=2)
    assert result["status"] == "ok"
    assert 0 < len(result["records"]) <= 2


def test_selftest():
    frontier.selftest()
