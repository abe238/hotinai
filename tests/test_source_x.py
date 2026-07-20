from hotin.sources import x


def test_x_is_an_honest_unconfigured_stub():
    result = x.fetch()
    assert result == {
        "records": [],
        "status": "empty",
        "detail": "the x source is not implemented (no public API available); bring-your-own-credentials only, not v1-core",
    }


def test_x_ignores_arguments_without_raising():
    assert x.fetch(query="anything", limit=5, config={"whatever": "value"})["status"] == "empty"
