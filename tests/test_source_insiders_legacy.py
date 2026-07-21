import json

from hotin.sources import insider_people


def _page(*flight_texts):
    # Real page ships each chunk as a JSON *string* whose value is flight text.
    chunks = "".join(
        "self.__next_f.push([1,{}])".format(json.dumps(text)) for text in flight_texts
    )
    return "<html><body>" + chunks + "</body></html>"


def test_parses_ranked_people_and_dedupes_by_rank():
    person = ('[{"rank":1,"followed_by_count":759,"score":759,"username":"karpathy",'
              '"display_name":"Andrej Karpathy","followers_count":3418679,'
              '"bio":"I like   nets.","category":"Research Engineer",'
              '"githubUrl":"https://github.com/karpathy","previousRank":2,"rankChange":1,"categoryRank":1}]')
    two = ('[{"rank":2,"followed_by_count":700,"score":700,"username":"JeffDean",'
           '"display_name":"Jeff Dean","followers_count":449078,"bio":"","category":"Researcher",'
           '"previousRank":2,"rankChange":0,"categoryRank":2}]')
    # first array repeated (the real page duplicates), plus a second person
    recs = insider_people.parse_rankings(_page(person, person, two))
    assert [r["rank"] for r in recs] == [1, 2]  # sorted, deduped
    k = recs[0]
    assert k["handle"] == "karpathy" and k["entity_type"] == "person"
    assert k["url"] == "https://x.com/karpathy" and k["github"] == "https://github.com/karpathy"
    assert k["signal"]["ai1000_followers"] == 759 and k["signal"]["rank_change"] == 1
    assert k["meta"]["previous_rank"] == 2 and k["meta"]["bio"] == "I like nets."


def test_hostile_and_empty_inputs_are_safe():
    assert insider_people.parse_rankings(None) == []
    assert insider_people.parse_rankings("not html at all") == []
    assert insider_people.parse_rankings("<html>self.__next_f.push([1,\"broken)</html>") == []


def test_fetch_error_when_request_fails(monkeypatch):
    monkeypatch.setattr(insider_people, "_request", lambda: None)
    assert insider_people.fetch(limit=5) == {"records": [], "status": "error", "detail": "insider rankings request failed"}


def test_fetch_ok_caps_to_limit(monkeypatch):
    person = ('[{"rank":1,"username":"a","display_name":"A","followed_by_count":9,"score":9,'
              '"followers_count":1,"bio":"x","category":"C","rankChange":0}]')
    two = ('[{"rank":2,"username":"b","display_name":"B","followed_by_count":8,"score":8,'
           '"followers_count":1,"bio":"y","category":"C","rankChange":0}]')
    monkeypatch.setattr(insider_people, "_request", lambda: _page(person, two))
    r = insider_people.fetch(limit=1)
    assert r["status"] == "ok" and len(r["records"]) == 1 and r["records"][0]["handle"] == "a"


def test_selftest():
    insider_people.selftest()
