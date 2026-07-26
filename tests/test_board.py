from hotin.board import join_id, news_rows, repo_rows


def test_join_id_passes_through_short_ids():
    assert join_id("vercel-labs/deepsec") == "vercel-labs/deepsec"


def test_join_id_none_stays_none():
    assert join_id(None) is None
    assert join_id("") is None


def test_join_id_hashes_ids_over_ga4_event_param_limit():
    # fake-success mode this guards: a raw id long enough that GA4 silently
    # truncates it (100-char cap on Standard properties) would mismatch the
    # untruncated key stored in tags.json, silently breaking the join for
    # exactly the news entity_ids (full article URLs) that need this most.
    long_url = "https://example.com/" + "a" * 100 + "/article-slug"
    assert len(long_url) > 100
    hashed = join_id(long_url)
    assert hashed != long_url
    assert len(hashed) < 30
    assert hashed.startswith("h:")
    # deterministic: same input -> same key, every run, both sides of the join
    assert join_id(long_url) == hashed


def test_repo_rows_id_uses_join_id_not_raw_slug_when_long():
    long_slug = "owner/" + "x" * 150
    rows = repo_rows([{"canonical_repo": long_slug, "name": long_slug, "url": "u",
                        "signal": {}, "meta": {}}])
    assert rows[0]["id"] == join_id(long_slug)
    assert rows[0]["id"] != long_slug


def test_news_rows_id_uses_join_id_for_long_article_urls():
    long_url = "https://simonwillison.net/2026/Jul/25/" + "a" * 120 + "#atom-everything"
    rows = news_rows([{"name": "A headline", "url": long_url, "entity_id": long_url,
                        "signal": {}, "meta": {}}])
    assert rows[0]["id"] == join_id(long_url)
    assert len(rows[0]["id"]) < len(long_url)
