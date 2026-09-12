#!/usr/bin/env python3
"""Small, dependency-free path and privacy guards shared by the CLI scripts.

The public package must behave the same on Windows, macOS and Linux.  In
particular, a Windows drive path may use either slash direction and a
directory junction is a reparse point rather than a Python symlink.  Keeping
these checks in one module prevents one entry point from silently accepting a
path another entry point rejects.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


# Match the beginning of a local path, not only a drive-rooted user path.  The broad
# remainder intentionally extends to a line/field delimiter so redaction does
# not leave a username or share name visible in a version string or metadata.
LOCAL_PATH = re.compile(
    r"(?ix)"
    r"(?<![A-Za-z0-9])"
    r"(?:"
    r"[A-Z]:[\\/][^\x00\r\n;|]*"
    # Require ordinary server/share tokens so the scanner does not treat an
    # escaped backslash in source code as a UNC path.
    r"|\\\\[A-Za-z0-9._-]+[\\/][^\\/\x00\r\n;|\"']+"
    r"|/(?:private/tmp|var/folders|home|Users|tmp)(?:/[^\x00\r\n;|]*)?"
    r")"
)

_REPARSE_POINT = 0x0400


def is_link_or_junction(path: Path) -> bool:
    """Return whether *path* is a symlink, junction, or Windows reparse point."""

    try:
        if path.is_symlink():
            return True
    except OSError:
        return True

    try:
        if bool(os.path.isjunction(path)):
            return True
    except (AttributeError, OSError, TypeError):
        pass

    # Python versions/platforms without ``os.path.isjunction`` still expose
    # the Windows reparse-point attribute through lstat/stat(follow_symlinks=False).
    if os.name == "nt":
        try:
            stat = path.stat(follow_symlinks=False)
        except (FileNotFoundError, OSError):
            return False
        return bool(getattr(stat, "st_file_attributes", 0) & _REPARSE_POINT)
    return False


def first_link_component(path: Path) -> Path | None:
    """Return the first link-like component in an unresolved path, if any."""

    current = Path(path).expanduser()
    while True:
        if is_link_or_junction(current):
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def contains_local_path(value: Any) -> bool:
    """Detect local drive, UNC, or home/temp paths in text or metadata."""

    return bool(LOCAL_PATH.search(str(value)))


def redact_local_paths(value: Any, replacement: str = "<local-path>") -> str:
    """Remove the complete local-path token before a value is shown publicly."""

    return LOCAL_PATH.sub(replacement, str(value))
