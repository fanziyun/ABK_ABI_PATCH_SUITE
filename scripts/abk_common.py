"""Shared helpers for the ABK ABI patch suite children.

Kept deliberately small: ABK invokes each child as a standalone script, so
anything here has to work without package installation.

Children import this via _abk_common(), which tolerates being loaded either as a
script (the scripts directory is on sys.path) or through importlib with a custom
module name (it is not).
"""
from __future__ import annotations

from pathlib import Path

BACKUP_SUFFIX = ".abk-orig"


def read_text(path: Path) -> str:
    return path.read_text()


def write_text(path: Path, text: str) -> None:
    """Write a file, snapshotting the original bytes once beforehand.

    The children rewrite one file at a time with no transaction, so a hard
    failure part-way leaves earlier files already modified. The snapshot is what
    scripts/abk_rollback.sh restores from.

    Skipped when the file does not exist yet -- report output is created through
    here too, and there is nothing to restore.
    """
    if path.exists():
        backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
    path.write_text(text)
