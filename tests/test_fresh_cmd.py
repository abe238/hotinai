import json
import pytest

from hotin import cli, freshness
from hotin.cli import main


@pytest.fixture(autouse=True)
def prevent_hot_process_exit(monkeypatch):
    """Keep main() testable while production hot/update commands exit immediately."""
    monkeypatch.setattr(cli.os, "_exit", lambda exit_code: None)


def test_fresh_json_matches_freshness_module(capsys):
    """The --json output should match freshness module values exactly."""
    assert main(["fresh", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)

    # Compare against the module, NOT against copied literals
    assert output["schema_version"] == freshness.SCHEMA_VERSION
    assert output["policy_version"] == freshness.POLICY_VERSION
    assert output["policy"] == freshness.policy()


def test_fresh_text_mentions_all_windows(capsys):
    """The text output should exit 0 and mention each of the four window numbers."""
    assert main(["fresh"]) == 0
    output = capsys.readouterr().out

    # Check that each window number is mentioned
    policy = freshness.policy()
    assert str(policy["repo_max_age_days"]) in output
    assert str(policy["model_max_age_days"]) in output
    assert str(policy["paper_max_age_days"]) in output
    assert str(policy["news_max_age_days"]) in output
