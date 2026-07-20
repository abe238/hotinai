"""The intentionally small L0 command dispatcher."""

import argparse
import json
import math
import os
import sys
from typing import List, Optional

from . import engine, health
from .cache import open_cache
from .config import env_path, load_config
from .render import sanitize


COMMANDS = {
    "hot": "show the hottest AI tools",
    "hn": "show Hacker News signals",
    "npm": "show npm signals",
    "stars": "show GitHub star growth",
    "trending": "show trending repositories",
    "reddit": "show Reddit signals",
    "youtube": "show YouTube signals",
    "search": "search cached tools",
    "show": "show one tool",
    "setup": "check local configuration",
    "update": "update hotin",
    "about": "show project information",
}


def _add_global_flags(parser: argparse.ArgumentParser, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument("--json", action="store_true", default=default, help="emit JSON output")
    parser.add_argument("--no-color", action="store_true", default=default, help="disable ANSI color")
    parser.add_argument("--quiet", action="store_true", default=default, help="reduce output")
    parser.add_argument("--verbose", action="store_true", default=default, help="increase output")
    parser.add_argument("--limit", type=int, default=argparse.SUPPRESS if suppress_defaults else None, metavar="N", help="limit results")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hotin", description="What's hot in AI, from your terminal.")
    _add_global_flags(parser)
    subcommands = parser.add_subparsers(dest="command", title="subcommands")
    for command, description in COMMANDS.items():
        subparser = subcommands.add_parser(command, help=description, description=description)
        _add_global_flags(subparser, suppress_defaults=True)
        if command == "setup":
            subparser.add_argument("--check", action="store_true", help="check local configuration")
    return parser


def _setup_check() -> int:
    config = load_config()
    print("config: {}".format(sanitize(str(env_path()))))
    print("configured entries: {}".format(len(config)))
    print("setup check passed")
    return 0


def _json_default(value: object) -> object:
    return sorted(value) if isinstance(value, set) else str(value)


def _sanitize_json(value: object) -> object:
    """Replace non-finite values while retaining the full machine-readable result."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, set):
        return sorted(_sanitize_json(item) for item in value)
    return value


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    command = arguments.command or "hot"
    if command == "setup" and arguments.check:
        return _setup_check()
    if command == "hot":
        limit = arguments.limit if arguments.limit is not None else 50
        if limit < 0:
            print("limit must be zero or greater", file=sys.stderr)
            return 2
        config = load_config()
        cache = open_cache()
        try:
            statuses = engine.fetch_all(config, limit=limit, cache=cache)
            ranked = engine.rank(engine.merge_by_repo(cache.get_all()), limit=limit)
            exit_code, message = health.summarize(statuses, cache_has_data=bool(cache.get_all()))
            if arguments.json:
                payload = {
                    "tools": ranked,
                    "sources": [
                        {"source": status.source, "status": status.status, "detail": status.detail}
                        for status in statuses
                    ],
                }
                try:
                    rendered = json.dumps(payload, default=_json_default, allow_nan=False)
                except ValueError:
                    rendered = json.dumps(_sanitize_json(payload), default=_json_default, allow_nan=False)
                print(rendered)
            else:
                for repo in ranked:
                    print("{:.2f}  {}  {}  {}".format(repo["score"], repo["name"], repo["category"], ",".join(repo["badges"])))
            if exit_code:
                print(message, file=sys.stderr)
        finally:
            cache.close()
        # The adapters run in non-daemon executor threads.  They may still be
        # blocked in a network call after fetch_all() has reached its deadline;
        # do not let CPython wait for those abandoned workers at process exit.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
        return exit_code  # Allows unit tests to substitute os._exit().
    print("{}: not yet implemented".format(command))
    return 0


if __name__ == "__main__":
    sys.exit(main())
