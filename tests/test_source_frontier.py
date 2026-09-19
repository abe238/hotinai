from datetime import datetime, timezone

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


# --- feedless labs, polled by sitemap -------------------------------------------------

# Trimmed from the real typesafe.ai page. The comment is Framer's SITE publish stamp and is
# byte-identical across every post on the site; the <p> is the post's own date.
_FRAMER_PAGE = (
    "<!doctype html>\n<!-- Made in Framer · framer.com -->\n"
    "<!-- Published Sep 18, 2026, 11:44 PM UTC -->\n"
    '<html lang="en"><head><title>The Bitterest Lesson - TypeSafe AI Blog</title></head>'
    '<body><div><p class="framer-text">Sep 10, 2026</p></div>'
    '<div><p class="framer-text">Sep 10, 2026</p></div></body></html>'
)


def test_a_feedless_post_is_dated_from_the_page_not_the_framer_stamp():
    """PIN, and the whole reason this parser is not 'first date in the page'.

    Framer writes the date the SITE was last deployed into an HTML comment at the top of every
    page. It is the same on all of them. Reading it would date every TypeSafe post to today and
    march the entire lab to the top of the board every time they touch any unrelated page, while
    looking perfectly healthy.
    """
    record = frontier.parse_post(_FRAMER_PAGE, "https://typesafe.ai/blog/bitterest-lesson",
                                 "TypeSafe AI")
    assert record is not None
    assert record["meta"]["date"] == "Sep 10, 2026"
    assert "Sep 18" not in record["meta"]["date"]
    # Derived, not hardcoded: a literal here is just a second chance to get the date wrong.
    expected = datetime(2026, 9, 10, tzinfo=timezone.utc).timestamp()
    assert record["signal"]["released_at"] == expected


def test_a_feedless_post_keeps_the_lab_and_the_official_flag():
    record = frontier.parse_post(_FRAMER_PAGE, "https://typesafe.ai/blog/x", "TypeSafe AI")
    assert record["meta"]["lab"] == "TypeSafe AI"
    assert record["meta"]["official"] is True
    assert record["entity_type"] == "release"
    assert record["url"] == "https://typesafe.ai/blog/x"


def test_the_site_name_is_stripped_off_the_post_title():
    record = frontier.parse_post(_FRAMER_PAGE, "https://typesafe.ai/blog/x", "TypeSafe AI")
    assert record["name"] == "The Bitterest Lesson"


def test_an_undated_post_is_dropped_rather_than_given_a_fallback_date():
    """The freshness gate reads this date. Inventing one presents an old post as today's news."""
    page = ('<!-- Published Sep 18, 2026, 11:44 PM UTC -->'
            "<html><head><title>No date here - TypeSafe AI Blog</title></head>"
            "<body><p>words, no date</p></body></html>")
    assert frontier.parse_post(page, "https://typesafe.ai/blog/x", "TypeSafe AI") is None


def test_the_sitemap_yields_only_blog_posts_in_order_without_duplicates():
    sitemap = (
        "<urlset>"
        "<url><loc>https://typesafe.ai/</loc></url>"
        "<url><loc>https://typesafe.ai/team</loc></url>"
        "<url><loc>https://typesafe.ai/legal/terms</loc></url>"
        "<url><loc>https://typesafe.ai/blog/newest</loc></url>"
        "<url><loc>https://typesafe.ai/blog/older</loc></url>"
        "<url><loc>https://typesafe.ai/blog/newest</loc></url>"
        "</urlset>")
    assert frontier.parse_sitemap(sitemap, "/blog/") == [
        "https://typesafe.ai/blog/newest", "https://typesafe.ai/blog/older"]


def test_typesafe_is_registered_as_a_sitemap_lab_and_not_as_unsupported():
    labs = [lab for lab, _url, _marker in frontier.SITEMAP_LABS]
    assert "TypeSafe AI" in labs
    assert "TypeSafe AI" not in frontier.UNSUPPORTED


def test_a_sitemap_lab_never_raises_when_the_site_is_unreachable(monkeypatch):
    monkeypatch.setattr(frontier, "_request", lambda url: None)
    assert frontier.fetch_sitemap_lab("TypeSafe AI", "https://typesafe.ai/sitemap.xml", "/blog/") == []


def test_the_per_run_post_budget_is_enforced(monkeypatch):
    """1 request for the sitemap + 1 per post. Unbounded, a lab with 500 posts would blow the
    bake's API budget on its own."""
    many = "<urlset>" + "".join(
        "<url><loc>https://typesafe.ai/blog/p{}</loc></url>".format(i) for i in range(50)) + "</urlset>"
    calls = []

    def fake_request(url):
        calls.append(url)
        return many if url.endswith("sitemap.xml") else _FRAMER_PAGE

    monkeypatch.setattr(frontier, "_request", fake_request)
    records = frontier.fetch_sitemap_lab("TypeSafe AI", "https://typesafe.ai/sitemap.xml", "/blog/")
    assert len(records) == frontier.MAX_SITEMAP_POSTS
    assert len(calls) == frontier.MAX_SITEMAP_POSTS + 1
