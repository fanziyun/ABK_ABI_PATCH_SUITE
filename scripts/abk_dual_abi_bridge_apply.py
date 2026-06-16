#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"{label}: expected block not found in {path}")
    path.write_text(text.replace(old, new, 1))


def ensure_after(path: Path, anchor: str, snippet: str, label: str) -> None:
    text = path.read_text()
    if snippet in text:
        return
    if anchor not in text:
        raise SystemExit(f"{label}: anchor not found in {path}")
    path.write_text(text.replace(anchor, anchor + snippet, 1))


def patch_internal_h(path: Path) -> None:
    ensure_after(
        path,
        "int try_to_force_load(struct module *mod, const char *reason);\n",
        "bool abk_dual_abi_bridge_is_enabled(void);\n"
        "bool abk_dual_abi_bridge_is_experimental(void);\n"
        "bool abk_dual_abi_bridge_module_allowed(const struct load_info *info);\n"
        "bool abk_dual_abi_bridge_vermagic_ok(const struct load_info *info,\n"
        "\t\t\t\t    const char *amagic,\n"
        "\t\t\t\t    const char *bmagic);\n"
        "void abk_dual_abi_bridge_note_vermagic(const struct load_info *info,\n"
        "\t\t\t\t      const char *modmagic,\n"
        "\t\t\t\t      const char *kernel_magic);\n"
        "void abk_dual_abi_bridge_note_modstruct(const struct load_info *info);\n"
        "void abk_dual_abi_bridge_note_symbol_crc(const struct load_info *info,\n"
        "\t\t\t\t\t const char *symname,\n"
        "\t\t\t\t\t u32 kernel_crc,\n"
        "\t\t\t\t\t u32 module_crc);\n",
        "kernel/module/internal.h",
    )


def patch_version_c(path: Path) -> None:
    ensure_after(
        path,
        '#include "internal.h"\n',
        '#define ABK_DUAL_ABI_BRIDGE_RELEASE_PREFIX "7.0.12"\n'
        '#define ABK_DUAL_ABI_BRIDGE_ALLOWLIST "kernelsu,sukisu,resukisu,ksu"\n\n'
        "bool abk_dual_abi_bridge_is_enabled(void)\n"
        "{\n"
        "#ifdef CONFIG_ABK_DUAL_ABI_BRIDGE\n"
        "\treturn true;\n"
        "#else\n"
        "\treturn false;\n"
        "#endif\n"
        "}\n\n"
        "bool abk_dual_abi_bridge_is_experimental(void)\n"
        "{\n"
        "#ifdef CONFIG_ABK_DUAL_ABI_BRIDGE_EXPERIMENTAL\n"
        "\treturn true;\n"
        "#else\n"
        "\treturn false;\n"
        "#endif\n"
        "}\n\n"
        "static bool abk_dual_abi_bridge_is_7012_family(const char *release)\n"
        "{\n"
        "\treturn release && !strncmp(release, ABK_DUAL_ABI_BRIDGE_RELEASE_PREFIX,\n"
        "\t\t\t\t       strlen(ABK_DUAL_ABI_BRIDGE_RELEASE_PREFIX));\n"
        "}\n\n"
        "bool abk_dual_abi_bridge_module_allowed(const struct load_info *info)\n"
        "{\n"
        "\tconst char *name;\n"
        "\tconst char *cursor;\n"
        "\tsize_t len;\n"
        "\n"
        "\tif (!abk_dual_abi_bridge_is_enabled())\n"
        "\t\treturn false;\n"
        "\tif (abk_dual_abi_bridge_is_experimental())\n"
        "\t\treturn true;\n"
        "\tname = info->name;\n"
        "\tif (!name || !*name)\n"
        "\t\treturn false;\n"
        "\tfor (cursor = ABK_DUAL_ABI_BRIDGE_ALLOWLIST; *cursor; ) {\n"
        "\t\tconst char *comma = strchr(cursor, ',');\n"
        "\t\tlen = comma ? (size_t)(comma - cursor) : strlen(cursor);\n"
        "\t\tif (strlen(name) >= len && !strncmp(name, cursor, len))\n"
        "\t\t\treturn true;\n"
        "\t\tif (!comma)\n"
        "\t\t\tbreak;\n"
        "\t\tcursor = comma + 1;\n"
        "\t}\n"
        "\treturn false;\n"
        "}\n\n"
        "bool abk_dual_abi_bridge_vermagic_ok(const struct load_info *info,\n"
        "\t\t\t\t    const char *amagic,\n"
        "\t\t\t\t    const char *bmagic)\n"
        "{\n"
        "\tif (!abk_dual_abi_bridge_module_allowed(info))\n"
        "\t\treturn false;\n"
        "\tif (!amagic || !bmagic)\n"
        "\t\treturn false;\n"
        "\tif (strcmp(amagic, bmagic) == 0)\n"
        "\t\treturn true;\n"
        "\treturn abk_dual_abi_bridge_is_7012_family(amagic);\n"
        "}\n\n"
        "void abk_dual_abi_bridge_note_vermagic(const struct load_info *info,\n"
        "\t\t\t\t      const char *modmagic,\n"
        "\t\t\t\t      const char *kernel_magic)\n"
        "{\n"
        '\tpr_warn("ABK dual ABI bridge: allow vermagic mismatch for %s (%s vs %s)%s\\n",\n'
        '\t\tinfo->name ?: "(unknown)", modmagic ?: "(none)", kernel_magic ?: "(none)",\n'
        '\t\tabk_dual_abi_bridge_is_experimental() ? " [experimental]" : "");\n'
        "}\n\n"
        "void abk_dual_abi_bridge_note_modstruct(const struct load_info *info)\n"
        "{\n"
        '\tpr_warn("ABK dual ABI bridge: allow module_layout mismatch for %s%s\\n",\n'
        '\t\tinfo->name ?: "(unknown)",\n'
        '\t\tabk_dual_abi_bridge_is_experimental() ? " [experimental]" : "");\n'
        "}\n\n"
        "void abk_dual_abi_bridge_note_symbol_crc(const struct load_info *info,\n"
        "\t\t\t\t\t const char *symname,\n"
        "\t\t\t\t\t u32 kernel_crc,\n"
        "\t\t\t\t\t u32 module_crc)\n"
        "{\n"
        '\tpr_warn("ABK dual ABI bridge: allow symbol CRC mismatch for %s symbol %s (%x vs %x)%s\\n",\n'
        '\t\tinfo->name ?: "(unknown)", symname ?: "(unknown)", kernel_crc, module_crc,\n'
        '\t\tabk_dual_abi_bridge_is_experimental() ? " [experimental]" : "");\n'
        "}\n\n",
        "kernel/module/version.c",
    )

    replace_once(
        path,
        """\t\tcrcval = *crc;
\t\tif (versions[i].crc == crcval)
\t\t\treturn 1;
\t\tpr_debug("Found checksum %X vs module %lX\\n",
\t\t\t crcval, versions[i].crc);
\t\tgoto bad_version;
""",
        """\t\tcrcval = *crc;
\t\tif (versions[i].crc == crcval)
\t\t\treturn 1;
\t\tpr_debug("Found checksum %X vs module %lX\\n",
\t\t\t crcval, versions[i].crc);
\t\tif (abk_dual_abi_bridge_module_allowed(info)) {
\t\t\tabk_dual_abi_bridge_note_symbol_crc(info, symname, crcval, versions[i].crc);
\t\t\treturn 1;
\t\t}
\t\tgoto bad_version;
""",
        "kernel/module/version.c",
    )

    replace_once(
        path,
        """\tpreempt_enable();
\treturn check_version(info, "module_layout", mod, fsa.crc);
}
""",
        """\tpreempt_enable();
\tif (!check_version(info, "module_layout", mod, fsa.crc)) {
\t\tif (abk_dual_abi_bridge_module_allowed(info)) {
\t\t\tabk_dual_abi_bridge_note_modstruct(info);
\t\t\treturn 1;
\t\t}
\t\treturn 0;
\t}
\treturn 1;
}
""",
        "kernel/module/version.c",
    )

    replace_once(
        path,
        """\tif (has_crcs) {
\t\tamagic += strcspn(amagic, " ");
\t\tbmagic += strcspn(bmagic, " ");
\t}
\treturn strcmp(amagic, bmagic) == 0;
}
""",
        """\tif (has_crcs) {
\t\tamagic += strcspn(amagic, " ");
\t\tbmagic += strcspn(bmagic, " ");
\t}
\tif (strcmp(amagic, bmagic) == 0)
\t\treturn 1;
\tif (abk_dual_abi_bridge_vermagic_ok(NULL, amagic, bmagic))
\t\treturn 1;
\treturn 0;
}
""",
        "kernel/module/version.c",
    )


def patch_main_c(path: Path) -> None:
    replace_once(
        path,
        """\t} else if (!same_magic(modmagic, vermagic, info->index.vers)) {
\t\tpr_err("%s: version magic '%s' should be '%s'\\n",
\t\t       info->name, modmagic, vermagic);
\t\treturn -ENOEXEC;
\t}
""",
        """\t} else if (!same_magic(modmagic, vermagic, info->index.vers)) {
\t\tif (abk_dual_abi_bridge_vermagic_ok(info, modmagic, vermagic)) {
\t\t\tabk_dual_abi_bridge_note_vermagic(info, modmagic, vermagic);
\t\t} else {
\t\t\tpr_err("%s: version magic '%s' should be '%s'\\n",
\t\t\t       info->name, modmagic, vermagic);
\t\t\treturn -ENOEXEC;
\t\t}
\t}
""",
        "kernel/module/main.c",
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit(f"usage: {argv[0]} <current-common-root>")

    common_root = Path(argv[1])
    patch_internal_h(common_root / "kernel/module/internal.h")
    patch_version_c(common_root / "kernel/module/version.c")
    patch_main_c(common_root / "kernel/module/main.c")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
