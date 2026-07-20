import pytest

from hotin.canonical import RESERVED_TOP_LEVEL, canonicalize


@pytest.mark.parametrize(
    "value",
    [
        "https://github.com/Owner/Repo",
        "https://github.com/Owner/Repo.git",
        "github.com/Owner/Repo/",
        "www.github.com/Owner/Repo",
        "Owner/Repo",
        "oWnEr/rEpO/",
    ],
)
def test_url_variants_normalize(value):
    assert canonicalize(value) == "owner/repo"


@pytest.mark.parametrize("reserved", sorted(RESERVED_TOP_LEVEL))
def test_reserved_paths_cannot_be_owners(reserved):
    assert canonicalize("https://github.com/{}/not-a-repo".format(reserved)) is None
