"""Small, deliberately non-magical configuration helpers."""

import os
import tempfile
from pathlib import Path
from typing import Dict, Mapping, Optional


def config_dir() -> Path:
    """Return the private hotin configuration directory, creating it if needed."""
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    directory = root / "hotin"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    # mkdir honours umask and does not adjust an already-existing directory.
    # Config credentials should never make the directory less private.
    try:
        os.chmod(directory, 0o700)
    except OSError:
        # Loading configuration should remain possible on filesystems that do
        # not expose POSIX modes.
        pass
    return directory


def env_path() -> Path:
    return config_dir() / ".env"


def load_config() -> Dict[str, str]:
    """Load literal KEY=value entries, with process environment taking priority."""
    values: Dict[str, str] = {}
    path = env_path()
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key:
                    values[key] = value.strip()
    except FileNotFoundError:
        pass

    # Only overlay keys the file declared.  This keeps load_config() a generic
    # config loader rather than returning every variable in the process.
    for key in list(values):
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def get(config: Mapping[str, str], key: str, default: Optional[str] = None) -> Optional[str]:
    """Fetch a configuration value without teaching callers any key names."""
    return config.get(key, default)


def write_config(values: Mapping[str, str]) -> None:
    """Atomically replace .env with literal values, using restrictive permissions."""
    path = env_path()
    if os.path.lexists(path) and os.path.islink(path):
        raise RuntimeError("refusing to write configuration through symlink: {}".format(path))

    fd, temporary_name = tempfile.mkstemp(prefix=".env.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        # os.fchmod is Unix-only; on Windows file privacy comes from the
        # user-profile ACLs the config dir already inherits, not POSIX modes.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for key, value in values.items():
                if "\n" in key or "\r" in key or "=" in key or "\n" in value or "\r" in value:
                    raise ValueError("configuration keys and values must be single-line literals")
                handle.write("{}={}\n".format(key, value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
