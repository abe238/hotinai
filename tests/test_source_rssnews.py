import json

from hotin.sources import rssnews


def test_parse_feed_rss_normalizes_dates_and_skips_broken_items():
    rss = (
        '<rss><channel><item><title><![CDATA[GPT-6 ships]]></title>'
        '<link>https://openai.com/news/gpt-6</link>'
        '<pubDate>Wed, 22 Jul 2026 13:00:00 GMT</pubDate></item>'
        '<item><title>no link, skipped</title></item>'
        '<item><title></title><link>https://x.test/empty-title</link></item>'
        '</channel></rss>'
    )
    records = rssnews.parse_feed(rss, "OpenAI", "primary")
    assert len(records) == 1
    top = records[0]
    assert top["entity_type"] == "news" and top["entity_id"] == "https://openai.com/news/gpt-6"
    assert top["name"] == "GPT-6 ships"
    assert top["meta"] == {"date": "2026-07-22T13:00:00Z", "publisher": "OpenAI", "kind": "primary"}


def test_parse_feed_atom_prefers_alternate_link():
    atom = (
        '<feed><entry><title>Kimi K3 notes</title>'
        '<link rel="self" href="https://example.com/feed"/>'
        '<link rel="alternate" href="https://simonwillison.net/2026/Jul/23/kimi/"/>'
        '<published>2026-07-23T05:00:00+00:00</published></entry></feed>'
    )
    entry = rssnews.parse_feed(atom, "Simon Willison", "analysis")[0]
    assert entry["url"] == "https://simonwillison.net/2026/Jul/23/kimi/"
    assert entry["meta"]["date"] == "2026-07-23T05:00:00Z"
    assert entry["meta"]["kind"] == "analysis"


def test_parse_feed_hostile_inputs_and_caps():
    assert rssnews.parse_feed(None, "X", "primary") == []
    assert rssnews.parse_feed("garbage <item>", "X", "primary") == []
    one = ('<item><title>t{}</title><link>https://a.test/{}</link></item>')
    flood = "<rss>" + "".join(one.format(i, i) for i in range(30)) + "</rss>"
    assert len(rssnews.parse_feed(flood, "X", "primary")) == rssnews.MAX_PER_FEED


def test_iso_date_and_epoch_edge_cases():
    assert rssnews._iso_date("Wed, 22 Jul 2026 13:00:00 GMT") == "2026-07-22T13:00:00Z"
    assert rssnews._iso_date("2026-07-23T05:18:47+02:00") == "2026-07-23T03:18:47Z"
    assert rssnews._iso_date("junk") is None and rssnews._iso_date(None) is None
    assert rssnews._epoch("2026-07-22T13:00:00Z") > rssnews._epoch("2026-07-21T13:00:00Z")
    assert rssnews._epoch(None) == 0.0 and rssnews._epoch("junk") == 0.0


def test_url_key_is_scheme_www_and_slash_agnostic():
    assert rssnews._url_key("https://www.Example.com/a/") == "example.com/a"
    assert rssnews._url_key("http://example.com/a") == "example.com/a"
    assert rssnews._url_key(None) == ""


class FakeCache:
    def __init__(self, rows):
        self.rows = rows
        self.upserts = []

    def get_all(self):
        return list(self.rows)

    def upsert(self, record):
        self.upserts.append(record)


def _news_row(url, signal, date):
    return {"entity_type": "news", "entity_id": url, "source": "rssnews",
            "fetched_at": 9.0,
            "signal_json": json.dumps({"signal": signal,
                                       "meta": {"date": date, "publisher": "P", "kind": "primary"}})}


def test_backfill_hn_points_heals_newest_first_and_marks_checked(monkeypatch):
    cache = FakeCache([
        _news_row("https://a.test/old", {}, "2026-07-01T00:00:00Z"),
        _news_row("https://a.test/new", {}, "2026-07-22T00:00:00Z"),
        _news_row("https://a.test/done", {"hn_points": 7}, "2026-07-23T00:00:00Z"),   # checked, skipped
        _news_row("https://a.test/zero", {"hn_points": 0}, "2026-07-23T00:00:00Z"),   # checked-not-found, skipped
    ])
    monkeypatch.setattr(rssnews, "fetch_hn_points",
                        lambda url, **kw: {"https://a.test/new": 1195}.get(url, 0))
    healed = rssnews.backfill_hn_points(cache, max_calls=1)  # bounded: only newest pending
    assert healed == 1
    up = cache.upserts[0]
    assert up["entity_id"] == "https://a.test/new"
    assert up["signal_json"]["signal"]["hn_points"] == 1195
    assert up["fetched_at"] == 9.0  # heal keeps the row's age

    healed = rssnews.backfill_hn_points(cache, max_calls=10)
    assert healed == 2  # both pending rows now; checked rows never refetched
    assert {u["entity_id"] for u in cache.upserts[1:]} == {"https://a.test/new", "https://a.test/old"}


def test_backfill_hn_points_transport_failure_leaves_row_pending(monkeypatch):
    cache = FakeCache([_news_row("https://a.test/x", {}, "2026-07-22T00:00:00Z")])
    monkeypatch.setattr(rssnews, "fetch_hn_points", lambda url, **kw: None)
    assert rssnews.backfill_hn_points(cache) == 0
    assert cache.upserts == []  # no key written -> retried next run


def test_fetch_sweeps_feeds_and_reports_provenance(monkeypatch):
    feeds_by_url = {
        rssnews.FEEDS[0][0]: ('<rss><item><title>A</title><link>https://a.test/1</link>'
                              '<pubDate>Wed, 22 Jul 2026 13:00:00 GMT</pubDate></item></rss>'),
        rssnews.FEEDS[7][0]: ('<rss><item><title>B</title><link>https://b.test/1</link>'
                              '<pubDate>Thu, 23 Jul 2026 13:00:00 GMT</pubDate></item></rss>'),
    }
    monkeypatch.setattr(rssnews, "_request_feed", lambda url: feeds_by_url.get(url))
    result = rssnews.fetch(limit=10)
    assert result["status"] == "ok"
    assert result["detail"] == "2/{} feeds".format(len(rssnews.FEEDS))
    assert [r["name"] for r in result["records"]] == ["B", "A"]  # newest first

    monkeypatch.setattr(rssnews, "_request_feed", lambda url: None)
    dead = rssnews.fetch(limit=10)
    assert dead["status"] == "error" and dead["records"] == []
