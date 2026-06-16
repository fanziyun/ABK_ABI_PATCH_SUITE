#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def ensure_contains(path: Path, needle: str, label: str) -> None:
    text = path.read_text()
    if needle not in text:
        raise SystemExit(f"{label}: expected marker missing in {path}")


def append_once(path: Path, line: str) -> None:
    text = path.read_text()
    if line in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    text += line + "\n"
    path.write_text(text)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit(f"usage: {argv[0]} <current-common-root>")

    common_root = Path(argv[1])
    version_c = common_root / "kernel/module/version.c"
    internal_h = common_root / "kernel/module/internal.h"

    ensure_contains(version_c, "abk_dual_abi_bridge_module_allowed", "abi_fixups")
    ensure_contains(version_c, "ABK dual ABI bridge: allow symbol CRC mismatch", "abi_fixups")
    ensure_contains(internal_h, "abk_dual_abi_bridge_module_allowed", "abi_fixups")

    append_once(version_c, "/* ABK ABI fixups: bridge glue baseline applied. */")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
