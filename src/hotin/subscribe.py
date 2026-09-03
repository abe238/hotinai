"""`hotin subscribe <email>`: opt in to the daily hotin bake email.

The only hotin command that talks to hotin.ai. It POSTs to the signup Worker,
which answers 202 whether or not the address is known (never reveals state) and
sends a confirmation link; nothing is subscribed until the user clicks it.
"""

import json
import re
import sys
import urllib.error
import urllib.request
from typing import Callable, Optional

from . import __version__

URL = "https://hotin.ai/api/subscribe"
TIMEOUT = 10
# ponytail: syntax sanity only, the Worker's confirmation email is the real check.
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
urlopen = urllib.request.urlopen  # swapped in tests


def run(email: str, opener: Optional[Callable] = None) -> int:
    """POST the address; 0 on accepted, 1 on failure, 2 on an invalid address."""
    email = (email or "").strip()
    if not _EMAIL.match(email):
        print("That does not look like an email address.", file=sys.stderr)
        return 2
    request = urllib.request.Request(
        URL,
        data=json.dumps({"email": email, "source": "cli"}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Hotin-Client": "cli",
            "User-Agent": "hotin-cli/{}".format(__version__),
        },
        method="POST",
    )
    try:
        with (opener or urlopen)(request, timeout=TIMEOUT) as response:
            status = getattr(response, "status", None) or response.getcode()
    except urllib.error.HTTPError as exc:
        print("Could not subscribe (HTTP {}). Try again later.".format(exc.code), file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as exc:
        reason = re.sub(r"[^\w .,:/'()-]", "", str(getattr(exc, "reason", exc)))[:80].strip()
        print("Could not reach hotin.ai ({}). Try again later.".format(reason or "network error"), file=sys.stderr)
        return 1
    if status in (200, 202):
        print("Check your inbox to confirm.")
        return 0
    print("Could not subscribe (HTTP {}). Try again later.".format(status), file=sys.stderr)
    return 1
