#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _abk_common():
    """Load abk_common from this script's directory.

    ABK runs each child as `python3 .../scripts/abk_child.py`, so a plain import
    works there; loading by path keeps it working when a caller imports this
    module under another name.
    """
    spec = importlib.util.spec_from_file_location(
        "abk_common", Path(__file__).resolve().parent / "abk_common.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_common = _abk_common()
write_text = _common.write_text


def resolve_layout(common_root: Path) -> dict[str, object]:
    """Locate the module loader, whichever layout this tree uses.

    6.1 split kernel/module.c into kernel/module/{main.c,version.c,internal.h}.
    5.15 still has the single file, and it holds the same three functions the
    bridge rewrites -- same_magic(), check_version() and
    check_modstruct_version() -- so the split is a matter of where the code
    lives, not whether it exists.

    On the single-file layout all three passes target that one file, and the
    declarations 6.1 needs in internal.h are unnecessary: the helpers are
    defined in the same translation unit as their callers.
    """
    split_main = common_root / "kernel/module/main.c"
    if split_main.is_file():
        return {
            "single_file": False,
            "internal_h": common_root / "kernel/module/internal.h",
            "version_c": common_root / "kernel/module/version.c",
            "main_c": split_main,
        }

    single = common_root / "kernel/module.c"
    if single.is_file():
        return {
            "single_file": True,
            "internal_h": None,
            "version_c": single,
            "main_c": single,
        }

    raise SystemExit(
        "abi_bridge: no module loader found; expected kernel/module/main.c "
        f"or kernel/module.c under {common_root}"
    )


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"{label}: expected block not found in {path}")
    write_text(path, text.replace(old, new, 1))


def ensure_after(path: Path, anchor: str, snippet: str, label: str) -> None:
    text = path.read_text()
    if snippet in text:
        return
    if anchor not in text:
        raise SystemExit(f"{label}: anchor not found in {path}")
    write_text(path, text.replace(anchor, anchor + snippet, 1))


def ensure_after_any(path: Path, anchors: list[str], snippet: str, label: str) -> None:
    """Insert after the first anchor present.

    The helper block goes after a different landmark depending on layout: 6.1's
    kernel/module/version.c opens with #include "internal.h", while 5.15's
    single kernel/module.c has no such include. There the vermagic[] definition
    serves -- it sits ahead of try_to_force_load() and of every call site the
    bridge hooks, so the helpers are declared before use.
    """
    text = path.read_text()
    if snippet in text:
        return

    for anchor in anchors:
        if anchor in text:
            write_text(path, text.replace(anchor, anchor + snippet, 1))
            return

    raise SystemExit(f"{label}: no known anchor found in {path}")


def replace_policy_header(path: Path, policy_define: str) -> None:
    text = path.read_text()
    old = '#define ABK_DUAL_ABI_BRIDGE_ALLOWLIST "kernelsu,sukisu,resukisu,ksu"\n'
    current_global = '#define ABK_DUAL_ABI_BRIDGE_POLICY "global_7012"\n'
    current_experimental = '#define ABK_DUAL_ABI_BRIDGE_POLICY "experimental"\n'
    release_prefix = '#define ABK_DUAL_ABI_BRIDGE_RELEASE_PREFIX "7.0.12"\n'

    if policy_define in text:
        return
    if old in text:
        write_text(path, text.replace(old, policy_define, 1))
        return
    if current_global in text:
        write_text(path, text.replace(current_global, policy_define, 1))
        return
    if current_experimental in text:
        write_text(path, text.replace(current_experimental, policy_define, 1))
        return
    if release_prefix not in text:
        return
    raise SystemExit(f"kernel/module/version.c_header_upgrade: expected policy header not found in {path}")


def upgrade_internal_h_decls(path: Path) -> None:
    text = path.read_text()
    old = (
        "bool abk_dual_abi_bridge_is_enabled(void);\n"
        "bool abk_dual_abi_bridge_is_experimental(void);\n"
        "bool abk_dual_abi_bridge_module_allowed(const struct load_info *info);\n"
        "bool abk_dual_abi_bridge_vermagic_ok(const struct load_info *info,\n"
        "\t\t\t\t    const char *amagic,\n"
        "\t\t\t\t    const char *bmagic);\n"
    )
    new = (
        "bool abk_dual_abi_bridge_is_enabled(void);\n"
        "bool abk_dual_abi_bridge_is_experimental(void);\n"
        "bool abk_dual_abi_bridge_is_global_7012(void);\n"
        "bool abk_dual_abi_bridge_module_allowed(const struct load_info *info);\n"
        "bool abk_dual_abi_bridge_release_allowed(const char *release);\n"
        "bool abk_dual_abi_bridge_vermagic_ok(const struct load_info *info,\n"
        "\t\t\t\t    const char *amagic,\n"
        "\t\t\t\t    const char *bmagic);\n"
    )
    if new in text:
        return
    if old in text:
        write_text(path, text.replace(old, new, 1))


def patch_internal_h(path: Path) -> None:
    upgrade_internal_h_decls(path)
    ensure_after(
        path,
        "int try_to_force_load(struct module *mod, const char *reason);\n",
        "bool abk_dual_abi_bridge_is_enabled(void);\n"
        "bool abk_dual_abi_bridge_is_experimental(void);\n"
        "bool abk_dual_abi_bridge_is_global_7012(void);\n"
        "bool abk_dual_abi_bridge_module_allowed(const struct load_info *info);\n"
        "bool abk_dual_abi_bridge_release_allowed(const char *release);\n"
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


def patch_version_c(path: Path, policy: str) -> None:
    if policy == "experimental":
        policy_define = '#define ABK_DUAL_ABI_BRIDGE_POLICY "experimental"\n'
    else:
        policy_define = '#define ABK_DUAL_ABI_BRIDGE_POLICY "global_7012"\n'

    replace_policy_header(path, policy_define)
    helper_block = (
        '#define ABK_DUAL_ABI_BRIDGE_RELEASE_PREFIX "7.0.12"\n'
        + policy_define
        + "\n"
        + "static const char *abk_dual_abi_bridge_get_modinfo(const struct load_info *info,\n"
        "\t\t\t\t\t   const char *tag)\n"
        "{\n"
        "\tElf_Shdr *infosec;\n"
        "\tconst char *modinfo;\n"
        "\tconst char *p;\n"
        "\tsize_t taglen;\n"
        "\tunsigned long size;\n"
        "\n"
        "\tif (!info || !info->index.info || !info->sechdrs || !info->hdr)\n"
        "\t\treturn NULL;\n"
        "\n"
        "\tinfosec = &info->sechdrs[info->index.info];\n"
        "\tmodinfo = (const char *)info->hdr + infosec->sh_offset;\n"
        "\tsize = infosec->sh_size;\n"
        "\ttaglen = strlen(tag);\n"
        "\n"
        "\tfor (p = modinfo; p && size; ) {\n"
        "\t\tsize_t len = strnlen(p, size);\n"
        "\n"
        "\t\tif (!len)\n"
        "\t\t\tbreak;\n"
        "\t\tif (len > taglen && !strncmp(p, tag, taglen) && p[taglen] == '=')\n"
        "\t\t\treturn p + taglen + 1;\n"
        "\t\tif (len >= size)\n"
        "\t\t\tbreak;\n"
        "\t\tsize -= len + 1;\n"
        "\t\tp += len + 1;\n"
        "\t}\n"
        "\n"
        "\treturn NULL;\n"
        "}\n\n"
        + "bool abk_dual_abi_bridge_is_enabled(void)\n"
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
        "bool abk_dual_abi_bridge_is_global_7012(void)\n"
        "{\n"
        '\treturn !strcmp(ABK_DUAL_ABI_BRIDGE_POLICY, "global_7012");\n'
        "}\n\n"
        "static bool abk_dual_abi_bridge_is_7012_family(const char *release)\n"
        "{\n"
        "\treturn release && !strncmp(release, ABK_DUAL_ABI_BRIDGE_RELEASE_PREFIX,\n"
        "\t\t\t\t       strlen(ABK_DUAL_ABI_BRIDGE_RELEASE_PREFIX));\n"
        "}\n\n"
        "bool abk_dual_abi_bridge_release_allowed(const char *release)\n"
        "{\n"
        "\tif (!abk_dual_abi_bridge_is_enabled())\n"
        "\t\treturn false;\n"
        "\tif (abk_dual_abi_bridge_is_experimental())\n"
        "\t\treturn true;\n"
        "\tif (abk_dual_abi_bridge_is_global_7012())\n"
        "\t\treturn abk_dual_abi_bridge_is_7012_family(release);\n"
        "\treturn false;\n"
        "}\n\n"
        "bool abk_dual_abi_bridge_module_allowed(const struct load_info *info)\n"
        "{\n"
        "\tconst char *modmagic;\n"
        "\tconst char *release;\n"
        "\n"
        "\tif (!abk_dual_abi_bridge_is_enabled())\n"
        "\t\treturn false;\n"
        "\tif (abk_dual_abi_bridge_is_experimental())\n"
        "\t\treturn true;\n"
        "\tif (!info || !info->index.mod)\n"
        "\t\treturn false;\n"
        '\tmodmagic = abk_dual_abi_bridge_get_modinfo(info, "vermagic");\n'
        "\tif (!modmagic || !*modmagic)\n"
        "\t\treturn false;\n"
        "\trelease = modmagic;\n"
        "\treturn abk_dual_abi_bridge_release_allowed(release);\n"
        "}\n\n"
        "bool abk_dual_abi_bridge_vermagic_ok(const struct load_info *info,\n"
        "\t\t\t\t    const char *amagic,\n"
        "\t\t\t\t    const char *bmagic)\n"
        "{\n"
        "\tif (!abk_dual_abi_bridge_release_allowed(amagic))\n"
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
        '\tpr_warn("ABK dual ABI bridge: allow 7.0.12-family vermagic mismatch for %s (%s vs %s)%s\\n",\n'
        '\t\tinfo->name ?: "(unknown)", modmagic ?: "(none)", kernel_magic ?: "(none)",\n'
        '\t\tabk_dual_abi_bridge_is_experimental() ? " [experimental]" : "");\n'
        "}\n\n"
        "void abk_dual_abi_bridge_note_modstruct(const struct load_info *info)\n"
        "{\n"
        '\tpr_warn("ABK dual ABI bridge: allow 7.0.12-family module_layout mismatch for %s%s\\n",\n'
        '\t\tinfo->name ?: "(unknown)",\n'
        '\t\tabk_dual_abi_bridge_is_experimental() ? " [experimental]" : "");\n'
        "}\n\n"
        "void abk_dual_abi_bridge_note_symbol_crc(const struct load_info *info,\n"
        "\t\t\t\t\t const char *symname,\n"
        "\t\t\t\t\t u32 kernel_crc,\n"
        "\t\t\t\t\t u32 module_crc)\n"
        "{\n"
        '\tpr_warn("ABK dual ABI bridge: allow 7.0.12-family symbol CRC mismatch for %s symbol %s (%x vs %x)%s\\n",\n'
        '\t\tinfo->name ?: "(unknown)", symname ?: "(unknown)", kernel_crc, module_crc,\n'
        '\t\tabk_dual_abi_bridge_is_experimental() ? " [experimental]" : "");\n'
        "}\n\n"
    )

    ensure_after_any(
        path,
        [
            '#include "internal.h"\n',
            "static const char vermagic[] = VERMAGIC_STRING;\n",
        ],
        helper_block,
        "kernel/module/version.c",
    )

    replace_once(
        path,
        """bool abk_dual_abi_bridge_module_allowed(const struct load_info *info)\n{\n\tconst char *name;\n\tconst char *cursor;\n\tsize_t len;\n\n\tif (!abk_dual_abi_bridge_is_enabled())\n\t\treturn false;\n\tif (abk_dual_abi_bridge_is_experimental())\n\t\treturn true;\n\tname = info->name;\n\tif (!name || !*name)\n\t\treturn false;\n\tfor (cursor = ABK_DUAL_ABI_BRIDGE_ALLOWLIST; *cursor; ) {\n\t\tconst char *comma = strchr(cursor, ',');\n\t\tlen = comma ? (size_t)(comma - cursor) : strlen(cursor);\n\t\tif (strlen(name) >= len && !strncmp(name, cursor, len))\n\t\t\treturn true;\n\t\tif (!comma)\n\t\t\tbreak;\n\t\tcursor = comma + 1;\n\t}\n\treturn false;\n}\n""",
        """bool abk_dual_abi_bridge_module_allowed(const struct load_info *info)\n{\n\tconst char *modmagic;\n\tconst char *release;\n\n\tif (!abk_dual_abi_bridge_is_enabled())\n\t\treturn false;\n\tif (abk_dual_abi_bridge_is_experimental())\n\t\treturn true;\n\tif (!info || !info->index.mod)\n\t\treturn false;\n\tmodmagic = abk_dual_abi_bridge_get_modinfo(info, "vermagic");\n\tif (!modmagic || !*modmagic)\n\t\treturn false;\n\trelease = modmagic;\n\treturn abk_dual_abi_bridge_release_allowed(release);\n}\n""",
        "kernel/module/version.c_module_allowed_upgrade",
    )
    replace_once(
        path,
        """bool abk_dual_abi_bridge_vermagic_ok(const struct load_info *info,\n\t\t\t\t    const char *amagic,\n\t\t\t\t    const char *bmagic)\n{\n\tif (!abk_dual_abi_bridge_module_allowed(info))\n\t\treturn false;\n\tif (!amagic || !bmagic)\n\t\treturn false;\n\tif (strcmp(amagic, bmagic) == 0)\n\t\treturn true;\n\treturn abk_dual_abi_bridge_is_7012_family(amagic);\n}\n""",
        """bool abk_dual_abi_bridge_vermagic_ok(const struct load_info *info,\n\t\t\t\t    const char *amagic,\n\t\t\t\t    const char *bmagic)\n{\n\tif (!abk_dual_abi_bridge_release_allowed(amagic))\n\t\treturn false;\n\tif (!amagic || !bmagic)\n\t\treturn false;\n\tif (strcmp(amagic, bmagic) == 0)\n\t\treturn true;\n\treturn abk_dual_abi_bridge_is_7012_family(amagic);\n}\n""",
        "kernel/module/version.c_vermagic_upgrade",
    )
    replace_once(
        path,
        'pr_warn("ABK dual ABI bridge: allow vermagic mismatch for %s (%s vs %s)%s\\n",\n',
        'pr_warn("ABK dual ABI bridge: allow 7.0.12-family vermagic mismatch for %s (%s vs %s)%s\\n",\n',
        "kernel/module/version.c_vermagic_warn_upgrade",
    )
    replace_once(
        path,
        'pr_warn("ABK dual ABI bridge: allow module_layout mismatch for %s%s\\n",\n',
        'pr_warn("ABK dual ABI bridge: allow 7.0.12-family module_layout mismatch for %s%s\\n",\n',
        "kernel/module/version.c_modstruct_warn_upgrade",
    )
    replace_once(
        path,
        'pr_warn("ABK dual ABI bridge: allow symbol CRC mismatch for %s symbol %s (%x vs %x)%s\\n",\n',
        'pr_warn("ABK dual ABI bridge: allow 7.0.12-family symbol CRC mismatch for %s symbol %s (%x vs %x)%s\\n",\n',
        "kernel/module/version.c_crc_warn_upgrade",
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
    if len(argv) != 3:
        raise SystemExit(f"usage: {argv[0]} <current-common-root> <policy>")

    common_root = Path(argv[1])
    policy = argv[2]
    layout = resolve_layout(common_root)

    if layout["single_file"]:
        print(
            "::warning::abi_bridge: single-file kernel/module.c layout; the "
            "bridge lands there and needs no internal.h declarations"
        )
    else:
        patch_internal_h(layout["internal_h"])

    patch_version_c(layout["version_c"], policy)
    patch_main_c(layout["main_c"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
