"""Enable ``python -m hotin`` — the portable invocation a scheduler can rely on."""

import sys

from hotin.cli import main

if __name__ == "__main__":
    sys.exit(main())
