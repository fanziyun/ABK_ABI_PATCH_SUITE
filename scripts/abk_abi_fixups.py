#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def ensure_contains(path: Path, needle: str, label: str) -> None:
    text = path.read_text()
    if needle not in text:
        raise SystemExit(f"{label}: expected marker missing in {path}")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"{label}: expected block missing in {path}")
    path.write_text(text.replace(old, new, 1))


def replace_first_existing(path: Path, replacements: list[tuple[str, str]], label: str) -> None:
    text = path.read_text()
    for old, new in replacements:
        if new in text:
            return
        if old in text:
            path.write_text(text.replace(old, new, 1))
            return
    raise SystemExit(f"{label}: expected block missing in {path}")


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
    main_c = common_root / "kernel/module/main.c"

    ensure_contains(version_c, "abk_dual_abi_bridge_module_allowed", "abi_fixups")
    ensure_contains(version_c, "abk_dual_abi_bridge_release_allowed", "abi_fixups")
    ensure_contains(version_c, "ABK dual ABI bridge: allow 7.0.12-family symbol CRC mismatch", "abi_fixups")
    ensure_contains(internal_h, "abk_dual_abi_bridge_module_allowed", "abi_fixups")
    ensure_contains(main_c, "abk_dual_abi_bridge_note_vermagic", "abi_fixups")

    replace_first_existing(
        version_c,
        [
            (
                """bool abk_dual_abi_bridge_module_allowed(const struct load_info *info)\n{\n\tconst char *modmagic;\n\tconst char *release;\n\n\tif (!abk_dual_abi_bridge_is_enabled())\n\t\treturn false;\n\tif (abk_dual_abi_bridge_is_experimental())\n\t\treturn true;\n\tif (!info || !info->index.mod)\n\t\treturn false;\n\tmodmagic = get_modinfo(info, "vermagic");\n\tif (!modmagic || !*modmagic)\n\t\treturn false;\n\trelease = modmagic;\n\treturn abk_dual_abi_bridge_release_allowed(release);\n}\n""",
                """bool abk_dual_abi_bridge_module_allowed(const struct load_info *info)\n{\n\tconst char *modmagic;\n\tconst char *release;\n\n\tif (!abk_dual_abi_bridge_is_enabled())\n\t\treturn false;\n\tif (abk_dual_abi_bridge_is_experimental())\n\t\treturn true;\n\tif (!info || !info->index.mod)\n\t\treturn false;\n\tmodmagic = get_modinfo(info, "vermagic");\n\tif (!modmagic || !*modmagic)\n\t\treturn false;\n\trelease = modmagic;\n\t/* ABK ABI fixups: basic loader compat is global for 7.0.12-family modules. */\n\treturn abk_dual_abi_bridge_release_allowed(release);\n}\n""",
            ),
            (
                """bool abk_dual_abi_bridge_module_allowed(const struct load_info *info)\n{\n\tconst char *modmagic;\n\tconst char *release;\n\n\tif (!abk_dual_abi_bridge_is_enabled())\n\t\treturn false;\n\tif (abk_dual_abi_bridge_is_experimental())\n\t\treturn true;\n\tif (!info || !info->index.mod)\n\t\treturn false;\n\tmodmagic = abk_dual_abi_bridge_get_modinfo(info, "vermagic");\n\tif (!modmagic || !*modmagic)\n\t\treturn false;\n\trelease = modmagic;\n\treturn abk_dual_abi_bridge_release_allowed(release);\n}\n""",
                """bool abk_dual_abi_bridge_module_allowed(const struct load_info *info)\n{\n\tconst char *modmagic;\n\tconst char *release;\n\n\tif (!abk_dual_abi_bridge_is_enabled())\n\t\treturn false;\n\tif (abk_dual_abi_bridge_is_experimental())\n\t\treturn true;\n\tif (!info || !info->index.mod)\n\t\treturn false;\n\tmodmagic = abk_dual_abi_bridge_get_modinfo(info, "vermagic");\n\tif (!modmagic || !*modmagic)\n\t\treturn false;\n\trelease = modmagic;\n\t/* ABK ABI fixups: basic loader compat is global for 7.0.12-family modules. */\n\treturn abk_dual_abi_bridge_release_allowed(release);\n}\n""",
            ),
        ],
        "abi_fixups/module_allowed_marker",
    )
    append_once(version_c, "/* ABK ABI fixups: basic loader compat applied for global 7.0.12-family bridge. */")
    append_once(version_c, "/* ABK ABI fixups: runtime ABI followups remain deferred beyond loader-adjacent glue. */")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
