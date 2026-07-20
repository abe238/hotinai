"""The intentionally small L0 command dispatcher."""

import argparse
import sys
from typing import List, Optional

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


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    command = arguments.command or "hot"
    if command == "setup" and arguments.check:
        return _setup_check()
    print("{}: not yet implemented".format(command))
    return 0


if __name__ == "__main__":
    sys.exit(main())
