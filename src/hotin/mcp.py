"""Expose hotin to AI agents over the Model Context Protocol.

The question hotin answers -- "what is actually hot in AI right now, and why" --
is one an agent gets asked constantly and cannot answer: its training data has a
cutoff and a web search returns marketing. This makes hotin callable from inside
Claude Code, Cursor, Codex CLI, Gemini CLI, or anything else that speaks MCP, so
the answer arrives with receipts attached rather than as a guess.

    pip install hotin
    # then, in your MCP client config:
    #   "hotin": { "command": "hotin", "args": ["mcp"] }

ZERO DEPENDENCIES, like the rest of the package. MCP is JSON-RPC 2.0 over
newline-delimited stdio; that is a hundred lines of stdlib, and pulling in an SDK
to avoid writing them would cost the one property this package advertises.

WHY THIS SHELLS OUT INSTEAD OF IMPORTING
---------------------------------------
Two independent reasons, and the second one is fatal.

1. stdio transport means STDOUT IS THE PROTOCOL. Every byte written there must
   be a JSON-RPC frame, and hotin's commands print their results to stdout.
   Running in-process would interleave board output into the protocol stream.

2. `cli.main` ends several commands with `os._exit()`, on purpose: "adapters can
   leave network workers behind after the fetch deadline". `os._exit` skips
   `finally`, skips every exception handler, and skips `atexit`. Called
   in-process it does not return a result, it TERMINATES THE MCP SERVER
   mid-request. The client sees the connection vanish with no error.

The first version of this file did import it, and passed its own tests, because
the test monkeypatched `cli.main` with a lambda and therefore never exercised the
real one. It died on the first genuine call. Same lesson as everywhere else in
this project: a green test against a substitute proves nothing about the thing
it stands in for.

A subprocess respects the CLI's intent (a hard exit reaps its own strays), keeps
our stdout clean, and turns a crash into an exit code instead of a dead server.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from typing import Any, Dict, List, Optional

PROTOCOL_VERSION = "2024-11-05"
# A board query is cache-served and returns in about a second. Anything past
# this is a hung upstream, and an agent waiting on a tool call is a user
# watching a spinner.
TIMEOUT_SECONDS = 45
TABS = ("repos", "rising", "insiders", "models", "papers", "news")
DEFAULT_LIMIT, MAX_LIMIT = 15, 60

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "hotin_board",
        "description": (
            "What is hot in AI right now, ranked with receipts. Returns repos, "
            "models, papers or news ordered by cross-source consensus and "
            "freshness, each with the evidence for its position: growth rate, "
            "which notable developers backed it, where else it surfaced. Use "
            "this instead of guessing what is currently popular, and prefer it "
            "over a web search when the user asks what is new, trending or worth "
            "looking at in AI."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string", "enum": list(TABS), "default": "repos",
                    "description": (
                        "repos = the overall ranked board. rising = fastest "
                        "growing right now. insiders = repos several notable AI "
                        "developers independently starred. models = trending "
                        "open weights. papers = trending research. news = "
                        "lab announcements and commentary."
                    ),
                },
                "limit": {"type": "integer", "default": DEFAULT_LIMIT,
                          "minimum": 1, "maximum": MAX_LIMIT},
            },
        },
    },
    {
        "name": "hotin_brief",
        "description": (
            "A short digest of what happened across all of AI in the last day: "
            "rising repos, frontier-lab releases, trending models and papers. "
            "Use when the user wants a catch-up rather than one specific list."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _run(argv: List[str], timeout: int = TIMEOUT_SECONDS) -> Any:
    """Run the CLI in a child process. THE ONLY PLACE THAT INVOKES IT.

    Returns parsed JSON when the command emits it, otherwise the captured text.
    Never raises: an agent gets a readable error object rather than a dead
    server, because a dead MCP server takes the client's whole tool with it and
    explains nothing.
    """
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "hotin", *argv],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": "hotin timed out after {}s".format(timeout)}
    except OSError as exc:
        return {"error": "could not run hotin: {}".format(exc)}
    text = (completed.stdout or "").strip()
    if not text:
        detail = (completed.stderr or "").strip()[:300]
        return {"error": detail or "hotin produced no output",
                "exit_code": completed.returncode}
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text, "exit_code": completed.returncode}


def call_tool(name: str, arguments: Optional[dict]) -> Any:
    arguments = arguments or {}
    if name == "hotin_brief":
        return _run(["brief", "--json"])
    if name == "hotin_board":
        tab = arguments.get("tab") or "repos"
        if tab not in TABS:
            return {"error": "unknown tab {!r}; expected one of {}".format(
                tab, ", ".join(TABS))}
        try:
            limit = int(arguments.get("limit") or DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT
        limit = max(1, min(limit, MAX_LIMIT))
        return _run([tab, "--json", "--limit", str(limit)])
    return {"error": "unknown tool {!r}".format(name)}


def _is_error(payload: Any) -> bool:
    """True when the tool failed, however the failure was expressed.

    Two shapes exist: this module's own {"error": ...}, and the CLI's adapter
    contract {"status": "error", "detail": ...}. Checking only the first
    reported isError=False on a payload whose own status said "error", which is
    the kind of thing an agent then presents to a user as a result.
    """
    if not isinstance(payload, dict):
        return False
    return "error" in payload or payload.get("status") == "error"


def handle(message: dict) -> Optional[dict]:
    """One JSON-RPC message in, at most one response out.

    Notifications (no `id`) get no reply, per the spec. Replying to one is a
    common way to break a client that is strict about it.
    """
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    if method == "initialize":
        from hotin import __version__
        return ok({
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "hotin", "version": __version__},
        })
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        payload = call_tool(params.get("name"), params.get("arguments"))
        # Content blocks, not a bare value: every MCP client expects this shape,
        # and `isError` is how a tool failure is reported without killing the
        # connection.
        return ok({
            "content": [{"type": "text",
                         "text": json.dumps(payload, indent=2, default=str)}],
            "isError": _is_error(payload),
        })
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32601, "message": "method not found: {}".format(method)}}


def serve(stdin=None, stdout=None) -> int:
    """Read newline-delimited JSON-RPC forever. Streams are injectable for tests."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            # A malformed frame is the client's problem; dropping the whole
            # server over it would be ours.
            continue
        response = handle(message)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0


def selftest() -> int:
    def rpc(method, params=None, rid=1):
        return handle({"jsonrpc": "2.0", "id": rid, "method": method,
                       "params": params or {}})

    init = rpc("initialize")
    assert init["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert init["result"]["serverInfo"]["name"] == "hotin"

    tools = rpc("tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == {"hotin_board", "hotin_brief"}
    for tool in tools:
        assert tool["description"] and tool["inputSchema"]["type"] == "object"

    # A notification must produce NO response.
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    # An unknown method is an error object, not an exception.
    assert rpc("nope/nope")["error"]["code"] == -32601

    # Unknown tool and bad tab are reported, never raised.
    assert "error" in call_tool("not_a_tool", {})
    assert "error" in call_tool("hotin_board", {"tab": "banana"})

    # isError must catch BOTH failure shapes. The CLI's adapters report
    # {"status": "error", "detail": ...}; checking only for an "error" key
    # marked a failed insiders poll as a successful result.
    assert _is_error({"error": "x"}) and _is_error({"status": "error", "detail": "no token"})
    assert not _is_error({"repos": []}) and not _is_error("plain text")

    # THE REAL CLI, not a stand-in. The previous version of this test replaced
    # cli.main with a lambda, so it never met the os._exit() that killed the
    # server on the first genuine call.
    payload = _run(["about", "--json"])
    assert isinstance(payload, dict) and payload.get("name") == "hotin", payload

    # A bad invocation is an error object with the reason, never a crash.
    bad = _run(["definitely-not-a-command", "--json"])
    assert isinstance(bad, dict) and "error" in bad, bad

    # A timeout is reported rather than hanging the client forever.
    slow = _run(["about", "--json"], timeout=0)
    assert "timed out" in slow.get("error", ""), slow

    # serve() must round-trip a real frame and write exactly one line.
    out = io.StringIO()
    serve(io.StringIO('{"jsonrpc":"2.0","id":7,"method":"tools/list"}\n'
                      '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
                      'not json at all\n'), out)
    lines = [l for l in out.getvalue().splitlines() if l]
    assert len(lines) == 1 and json.loads(lines[0])["id"] == 7, lines

    print("mcp selftest ok")
    return 0
