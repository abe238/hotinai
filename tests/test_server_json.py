"""server.json, the README marker and the package version must agree.

Three separate files encode the same two facts, and the registry only tells you
they disagree at publish time, in a generic "registry validation failed for
package". Worse, the README marker only reaches the registry via PyPI, so an
edit here is invisible until the NEXT release fails. Pin all of it locally.
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.json"
README = ROOT / "README.md"


def _server():
    return json.loads(SERVER.read_text(encoding="utf-8"))


def test_the_server_name_is_under_the_namespace_github_auth_grants():
    """GitHub OIDC only authenticates io.github.<user>/*. Any other name is
    rejected, and the error does not say which field is wrong."""
    assert _server()["name"] == "io.github.abe238/hotin"


def test_the_readme_carries_the_ownership_marker_the_registry_looks_for():
    """The registry proves we own the PyPI package by finding this exact string
    in the README that renders on PyPI. It must match server.json's name, and
    the token needs a boundary after it -- glued to a trailing character it will
    not match."""
    name = _server()["name"]
    marker = re.search(r"mcp-name:\s*(\S+?)(?:\s|-->|$)", README.read_text(encoding="utf-8"))
    assert marker, "the README lost the mcp-name marker; the next publish will fail"
    assert marker.group(1) == name, (marker.group(1), name)


def test_the_versions_move_together():
    from hotin import __version__

    server = _server()
    assert server["version"] == __version__, (server["version"], __version__)
    for package in server["packages"]:
        assert package["version"] == __version__, package


def test_the_description_fits_the_registry_limit():
    description = _server()["description"]
    assert 0 < len(description) <= 100, len(description)


def test_the_package_points_at_the_real_pypi_distribution():
    package = _server()["packages"][0]
    assert package["registryType"] == "pypi"
    assert package["identifier"] == "hotin"
    assert package["transport"]["type"] == "stdio"


def test_clients_are_told_the_mcp_subcommand():
    """Without it a client runs bare `hotin`, which prints usage and exits. The
    server would appear installed and answer nothing."""
    args = _server()["packages"][0].get("packageArguments") or []
    assert [a.get("value") for a in args] == ["mcp"], args


def test_the_token_is_declared_optional():
    """Marking it required turns a one-click install into a scavenger hunt, and
    is untrue: every tab except insiders works with no key at all."""
    env = _server()["packages"][0].get("environmentVariables") or []
    token = [e for e in env if e["name"] == "GITHUB_TOKEN"]
    assert token, env
    assert token[0]["isRequired"] is False
    assert token[0]["isSecret"] is True
    # No placeholder credentials survived from `mcp-publisher init`, which
    # scaffolds a required YOUR_API_KEY.
    assert not [e for e in env if "YOUR_" in e["name"]], env
