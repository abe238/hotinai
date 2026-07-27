"""The README-description gate, pinned against the READMEs that motivated it.

The failure this guards is not "no description" -- it is a *wrong* one: a
board row reading "Open to Work ·" or "click the Fork button", which looks
like a description and tells a visitor nothing. Every fixture here is a real
README from a repo that shipped blank on the live board.
"""

import pytest

from hotin.sources._readme_desc import (build_query, derive_description,
                                        fill_missing_descriptions,
                                        _descriptions)
from fixtures_readmes import READMES


def _d(slug):
    return derive_description(READMES[slug])


# --- the seven real repos ------------------------------------------------

def test_every_fixture_yields_something_usable_or_nothing():
    """No fixture may produce markup, a URL, or a stub."""
    for slug, readme in READMES.items():
        got = derive_description(readme)
        if got is None:
            continue
        assert "http" not in got.lower(), slug
        assert "<" not in got and "&nbsp;" not in got, slug
        assert len(got.split()) >= 5, slug
        assert got[0].isalpha(), slug


def test_it_skips_the_badge_and_logo_preamble():
    """KSI opens with an <a><img> arXiv badge; the description must be prose."""
    got = _d("recursive-knowledge/KSI")
    assert got.startswith("KSI runs a population of disposable agents")


def test_it_skips_an_open_to_work_banner():
    """esp32-ai's first non-blank line is a profile banner, not a description."""
    got = _d("slvDev/esp32-ai")
    assert "Open to Work" not in got
    assert "28.9 million parameter language model" in got


def test_it_skips_a_download_link_row():
    """openworker opens with **[site](url)** · [Download](#download)."""
    got = _d("andrewyng/openworker")
    assert "Download" not in got
    assert got.startswith("It runs on your machine")


def test_it_reads_a_plain_lead_paragraph():
    got = _d("doordash-oss/doordash-cli")
    assert got.startswith("DoorDash CLI (dd-cli) is a terminal tool")


def test_it_strips_markdown_emphasis_and_links_to_their_text():
    got = _d("withmarbleapp/os-taxonomy")
    assert got.startswith("An open, structured taxonomy of what children learn")
    assert "**" not in got and "](" not in got


# --- the wrap bug this was rebuilt to fix --------------------------------

def test_a_hard_wrapped_sentence_is_reassembled():
    """Taking the matched LINE alone ended this at '...experiments from'.

    READMEs hard-wrap, so a one-line read truncates mid-sentence. The
    scanner must absorb the rest of the paragraph.
    """
    got = _d("burtenshaw/rlm-general-harness")
    assert not got.endswith("from")
    assert len(got.split()) > 8


def test_it_stops_at_the_first_sentence():
    text = "Alpha beta gamma delta epsilon. Zeta eta theta iota kappa."
    assert derive_description(text) == "Alpha beta gamma delta epsilon."


def test_it_does_not_run_past_a_blank_line():
    text = "Alpha beta gamma delta epsilon\n\nlambda mu nu xi omicron pi"
    assert derive_description(text) == "Alpha beta gamma delta epsilon"


# --- the rejection rules -------------------------------------------------

@pytest.mark.parametrize("readme", [
    "",
    "   \n\n  ",
    "# Just A Heading",
    "![badge](https://img.shields.io/x)",
    "<img src='logo.png'>",
    "> a blockquote with plenty of words in it",
    "- a bullet list item with plenty of words",
    "| a | table | row | with | words |",
    "Too few words",
    "https://example.com/this/is/just/a/link/row/here",
    "&nbsp; &nbsp; spacer entities and some words here",
    "123 starts with a digit and has many words",
])
def test_junk_never_becomes_a_description(readme):
    assert derive_description(readme) is None


@pytest.mark.parametrize("bad", [None, 42, [], {}, b"bytes"])
def test_non_string_input_is_survivable(bad):
    assert derive_description(bad) is None


def test_a_fenced_code_block_is_not_prose():
    text = "```\npip install something and then run it now\n```\nActual prose line goes right here"
    assert derive_description(text) == "Actual prose line goes right here"


# --- the batch query -----------------------------------------------------

def test_the_query_batches_every_repo_into_one_request():
    q = build_query(["a/b", "c/d", "e/f"])
    assert q.count("repository(") == 3
    assert q.count("query {") == 1


def test_the_query_quotes_owner_and_name():
    """A slug is attacker-influenced text; it must not be able to break out."""
    q = build_query(['ow"ner/na"me'])
    assert 'ow"ner' not in q.replace('\\"', "")


def test_the_join_is_case_insensitive():
    """GraphQL echoes GitHub's canonical casing, not the board's."""
    payload = {"data": {"r0": {
        "nameWithOwner": "x4gKing/X4G",
        "a": {"text": "Alpha beta gamma delta epsilon zeta."},
    }}}
    assert _descriptions(payload) == {"x4gking/x4g": "Alpha beta gamma delta epsilon zeta."}


def test_a_malformed_payload_yields_no_descriptions():
    for payload in (None, {}, {"data": None}, {"data": {"r0": None}},
                    {"data": {"r0": {"nameWithOwner": None}}},
                    {"errors": [{"message": "boom"}]}):
        assert _descriptions(payload) == {}


# --- the fill pass -------------------------------------------------------

def test_records_with_a_description_are_left_alone(monkeypatch):
    called = []
    monkeypatch.setattr("hotin.sources._readme_desc._post",
                        lambda q, t: called.append(q) or None)
    rec = {"canonical_repo": "a/b", "meta": {"description": "already here"}}
    assert fill_missing_descriptions([[rec]], "tok") == 0
    assert called == [], "must not spend a request when nothing is missing"
    assert rec["meta"]["description"] == "already here"


def test_a_blank_description_is_filled(monkeypatch):
    monkeypatch.setattr("hotin.sources._readme_desc._post", lambda q, t: {
        "data": {"r0": {"nameWithOwner": "A/B",
                        "a": {"text": "Alpha beta gamma delta epsilon zeta."}}}})
    rec = {"canonical_repo": "a/b", "meta": {"description": None}}
    assert fill_missing_descriptions([[rec]], "tok") == 1
    assert rec["meta"]["description"] == "Alpha beta gamma delta epsilon zeta."


def test_the_same_repo_on_two_tabs_costs_one_lookup(monkeypatch):
    """repos and repos7 share rows; the batch must not ask twice."""
    queries = []
    monkeypatch.setattr("hotin.sources._readme_desc._post", lambda q, t: (
        queries.append(q) or {"data": {"r0": {
            "nameWithOwner": "a/b",
            "a": {"text": "Alpha beta gamma delta epsilon zeta."}}}}))
    a = {"canonical_repo": "a/b", "meta": {}}
    b = {"canonical_repo": "a/b", "meta": {}}
    assert fill_missing_descriptions([[a], [b]], "tok") == 2
    assert len(queries) == 1
    assert queries[0].count("repository(") == 1
    assert a["meta"]["description"] == b["meta"]["description"]


def test_no_token_means_no_request(monkeypatch):
    monkeypatch.setattr("hotin.sources._readme_desc._post",
                        lambda q, t: pytest.fail("must not fetch without a token"))
    rec = {"canonical_repo": "a/b", "meta": {}}
    for token in (None, "", "   ", 42):
        assert fill_missing_descriptions([[rec]], token) == 0


def test_a_failed_request_leaves_the_board_untouched(monkeypatch):
    monkeypatch.setattr("hotin.sources._readme_desc._post", lambda q, t: None)
    rec = {"canonical_repo": "a/b", "meta": {}}
    assert fill_missing_descriptions([[rec]], "tok") == 0
    assert rec["meta"].get("description") is None


def test_a_readme_that_fails_the_gate_leaves_the_row_blank(monkeypatch):
    """Blank beats wrong: an unusable README must not produce a stub."""
    monkeypatch.setattr("hotin.sources._readme_desc._post", lambda q, t: {
        "data": {"r0": {"nameWithOwner": "a/b",
                        "a": {"text": "![badge](https://img.shields.io/x)"}}}})
    rec = {"canonical_repo": "a/b", "meta": {}}
    assert fill_missing_descriptions([[rec]], "tok") == 0
    assert rec["meta"].get("description") is None


def test_malformed_records_never_raise(monkeypatch):
    monkeypatch.setattr("hotin.sources._readme_desc._post", lambda q, t: None)
    junk = [None, 42, "string", {}, {"name": "no-slash"},
            {"name": "too/many/slashes"}, {"canonical_repo": "/b"},
            {"canonical_repo": "a/"}]
    assert fill_missing_descriptions([junk, None, []], "tok") == 0
