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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://github.com/Owner/Repo?tab=readme-ov-file", "owner/repo"),
        ("https://github.com/Owner/Repo#readme", "owner/repo"),
        ("git@github.com:Owner/Repo.git", "owner/repo"),
        ("git@github.com:Owner/Repo", "owner/repo"),
    ],
)
def test_query_fragment_and_scp_style_variants_normalize(value, expected):
    assert canonicalize(value) == expected


def test_organizations_path_cannot_be_an_owner():
    assert canonicalize("https://github.com/organizations/acme/settings/profile") is None
