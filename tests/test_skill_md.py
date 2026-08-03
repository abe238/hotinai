"""The skill is instructions to an agent, so a stale claim in it is a bug.

Every command it prints and every JSON field it teaches an agent to quote is
checked against the CLI here. A skill that names a field the board stopped
emitting sends the agent looking for something that is not there, and the agent
will quietly report less rather than complain.

Nothing here hits the network: the argument parser and the source constants are
enough to catch the failure this guards against, which is drift.
"""

from __future__ import annotations

import pathlib
import re

import pytest

SKILL = pathlib.Path(__file__).resolve().parents[1] / "skills" / "hotin" / "SKILL.md"


@pytest.fixture(scope="module")
def text():
    return SKILL.read_text(encoding="utf-8")


def test_frontmatter_is_present_and_named(text):
    assert text.startswith("---\n"), "a skill without frontmatter is never loaded"
    front = text.split("---", 2)[1]
    assert re.search(r"^name:\s*hotin\s*$", front, re.M), front
    description = re.search(r"^description:\s*(.+)$", front, re.M)
    assert description, "the description is what decides whether the skill fires"
    # Long enough to describe the trigger, short enough to stay in a listing.
    assert 60 < len(description.group(1)) < 500, len(description.group(1))


def test_every_subcommand_it_teaches_actually_exists(text):
    from hotin import cli

    # Only fenced code blocks. Scanning prose picks up the first word of any
    # sentence starting "hotin ..." and calls it a subcommand.
    blocks = "\n".join(re.findall(r"```(?:sh|bash)?\n(.*?)```", text, re.S))
    taught = set(re.findall(r"^hotin ([a-z]+)", blocks, re.M))
    taught |= set(re.findall(r"uvx hotin ([a-z]+)", blocks))
    taught.discard("mcp")  # `claude mcp add hotin -- uvx hotin mcp`, checked below
    assert taught, "the skill should show real commands"

    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    if parser is None:
        pytest.skip("no importable parser to check against")
    choices = set()
    for action in parser._actions:
        if getattr(action, "choices", None):
            choices |= {str(c) for c in action.choices}
    unknown = taught - choices
    assert not unknown, ("the skill teaches commands the CLI does not have", unknown)


def test_it_documents_the_mcp_subcommand_that_the_install_line_uses(text):
    from hotin import mcp

    assert "uvx hotin mcp" in text
    for tool in mcp.TOOLS:
        assert tool["name"] in text, ("the skill should name the MCP tools", tool["name"])


def test_the_tabs_it_lists_are_the_tabs_that_exist(text):
    from hotin import mcp

    for tab in mcp.TABS:
        assert re.search(r"\bhotin {}\b".format(tab), text), tab


def test_the_json_fields_it_tells_an_agent_to_quote_are_real(text):
    """The load-bearing half. These names came from real output; if the board
    renames one, the skill starts teaching a field that will never appear."""
    quoted = set(re.findall(r"`(?:signal\.)?([a-z_]+)`", text))
    # Only assert on the ones this skill leans on as evidence.
    evidence = {"sources", "velocity_per_day", "age_days", "insider_stars",
                "smartmoney_starrers", "corroboration", "hn_points"}
    assert evidence <= quoted, ("the skill dropped an evidence field", evidence - quoted)


def test_it_says_what_the_board_does_not_know(text):
    """A skill that only lists strengths produces an agent that overclaims. The
    absence-is-not-evidence line and the staleness bound are both load-bearing."""
    lowered = text.lower()
    assert "absence" in lowered and "not evidence" in lowered
    assert "3 hours" in lowered or "three hours" in lowered
    assert "github_token" in lowered, "the insiders tab's precondition must be stated"
