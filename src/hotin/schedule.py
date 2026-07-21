"""Install/remove a scheduled ``hotin refresh`` job to keep the store fresh.

Cross-platform and stdlib-only: a managed ``crontab`` block on Unix/macOS, a
set of ``schtasks`` entries on Windows. The scheduled command is
``<python> -m hotin refresh --quiet`` (an absolute interpreter path always resolves under
cron's minimal PATH). Everything here is best-effort and reports what it did;
the pure helpers (time spec, cron block editing, task names) are unit-tested,
the thin subprocess wrappers are not.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Optional, Tuple

# frequency -> the local wall-clock times (hour, minute) to run at.
FREQUENCIES = {
    "daily": [(8, 0)],
    "twice": [(8, 0), (20, 0)],
}
_MARK = "# hotin-managed"  # tags our crontab lines so we can find/replace them
_TASK_PREFIX = "hotin-ingest"  # Windows scheduled-task name prefix


def _command(python_exe: str) -> str:
    return "{} -m hotin refresh --quiet".format(python_exe)


def cron_line(frequency: str, python_exe: str) -> str:
    """The single crontab line for a frequency (all runs are at minute 0)."""
    hours = ",".join(str(hour) for hour, _minute in FREQUENCIES[frequency])
    return "0 {} * * * {} {}".format(hours, _command(python_exe), _MARK)


def strip_managed(crontab_text: str) -> str:
    """Remove any previously-installed hotin lines, leaving the user's own intact."""
    kept = [line for line in crontab_text.splitlines() if _MARK not in line]
    return "\n".join(kept)


def merged_crontab(existing: str, frequency: Optional[str], python_exe: str) -> str:
    """Existing crontab with hotin's block replaced (or removed when frequency is None)."""
    body = strip_managed(existing).strip()
    lines = [body] if body else []
    if frequency is not None:
        lines.append(cron_line(frequency, python_exe))
    return ("\n".join(lines) + "\n") if lines else ""


def task_specs(frequency: str, python_exe: str) -> List[Tuple[str, str]]:
    """Windows (task name, HH:MM start time) pairs — one task per run time."""
    specs = []
    for hour, minute in FREQUENCIES[frequency]:
        specs.append(("{}-{:02d}{:02d}".format(_TASK_PREFIX, hour, minute),
                      "{:02d}:{:02d}".format(hour, minute)))
    return specs


def _read_crontab() -> str:
    proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def _write_crontab(text: str) -> None:
    if text.strip():
        subprocess.run(["crontab", "-"], input=text, text=True, check=True)
    else:
        subprocess.run(["crontab", "-r"], check=False)  # nothing left → clear it


def _apply_unix(frequency: Optional[str], python_exe: str) -> None:
    _write_crontab(merged_crontab(_read_crontab(), frequency, python_exe))


def _apply_windows(frequency: Optional[str], python_exe: str) -> None:
    # Remove any prior hotin tasks first (covers a daily->twice or ->off change).
    for name in ("{}-0800".format(_TASK_PREFIX), "{}-2000".format(_TASK_PREFIX)):
        subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"],
                       capture_output=True, text=True)
    if frequency is None:
        return
    for name, start in task_specs(frequency, python_exe):
        subprocess.run(["schtasks", "/Create", "/TN", name, "/TR", _command(python_exe),
                        "/SC", "DAILY", "/ST", start, "/F"], check=True)


def install(frequency: str, python_exe: Optional[str] = None) -> str:
    """Install the schedule; returns a one-line human summary. Raises on failure."""
    if frequency not in FREQUENCIES:
        raise ValueError("unknown frequency: {}".format(frequency))
    python_exe = python_exe or sys.executable
    times = " & ".join("{:02d}:{:02d}".format(h, m) for h, m in FREQUENCIES[frequency])
    if os.name == "nt":
        _apply_windows(frequency, python_exe)
        where = "Windows Task Scheduler ({} tasks)".format(_TASK_PREFIX)
    else:
        _apply_unix(frequency, python_exe)
        where = "crontab"
    return "scheduled `hotin refresh` daily at {} via {}".format(times, where)


def remove() -> str:
    """Remove any hotin-managed schedule; returns a one-line human summary."""
    if os.name == "nt":
        _apply_windows(None, sys.executable)
        return "removed hotin scheduled tasks (if any)"
    _apply_unix(None, sys.executable)
    return "removed hotin crontab entry (if any)"


def demo() -> None:
    assert cron_line("daily", "/py").startswith("0 8 * * * /py -m hotin refresh --quiet")
    assert cron_line("twice", "/py").startswith("0 8,20 * * *")
    # our block replaces cleanly and never touches the user's own lines
    user = "0 5 * * * backup.sh"
    once = merged_crontab(user, "daily", "/py")
    assert user in once and _MARK in once and once.count(_MARK) == 1
    twice = merged_crontab(once, "twice", "/py")
    assert twice.count(_MARK) == 1 and "0 8,20" in twice and user in twice
    assert merged_crontab(twice, None, "/py").strip() == user  # ->off leaves user intact
    assert [n for n, _ in task_specs("twice", "/py")] == ["hotin-ingest-0800", "hotin-ingest-2000"]
    print("schedule demo: ok")


if __name__ == "__main__":
    demo()
