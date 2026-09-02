#!/usr/bin/env python3
"""ABK Display Release Spoof.

Spoofs the visible kernel release strings (uname(), /proc/sys/kernel/osrelease,
/proc/version) to 7.0.12 while preserving the real UTS release suffix, vermagic
and every other ABI-sensitive build input, so module loading is unaffected.

Exemption: processes that branch on the kernel release must keep seeing the
real value. Android's vold parses the release to pick the fscrypt key path; a
spoofed 7.0.12 on a 5.15 kernel makes it take the HW_WRAPPED path the kernel
rejects, so cryptfs enablefilecrypto fails and init reboots into recovery
(enablefilecrypto_failed). f2fs-tools (fsck./mkfs./resize.f2fs) gate features
on /proc/version the same way. Those processes see the real release; everyone
else sees the spoof.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

DISPLAY_RELEASE = "7.0.12"
DISPLAY_SECURITY_PATCH = "2026-06"


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


def replace_any(path: Path, candidates: list[str], replacement: str, label: str) -> None:
    text = path.read_text()
    if replacement in text:
        return

    for candidate in candidates:
        if candidate in text:
            write_text(path, text.replace(candidate, replacement, 1))
            return

    raise SystemExit(f"{label}: expected block not found in {path}")


def ensure_after(path: Path, anchor: str, snippet: str, label: str) -> None:
    text = path.read_text()
    if snippet in text:
        return
    if anchor not in text:
        raise SystemExit(f"{label}: anchor not found in {path}")
    write_text(path, text.replace(anchor, anchor + snippet, 1))


def ensure_after_any(path: Path, anchors: list[str], snippet: str, label: str) -> None:
    """Insert after the first anchor present.

    Insertion points drift between target families even when the code being
    patched does not: fs/proc/version.c includes "internal.h" on 6.1 but not on
    5.15. Take the first anchor that exists rather than pinning one release.
    """
    text = path.read_text()
    if snippet in text:
        return

    for anchor in anchors:
        if anchor in text:
            write_text(path, text.replace(anchor, anchor + snippet, 1))
            return

    raise SystemExit(f"{label}: no known anchor found in {path}")


KEEP_REAL_HELPER = """/*
 * Processes that branch on the kernel release must see the real value:
 * vold picks the fscrypt key path from the parsed release, and fsck/mkfs/
 * resize tools gate f2fs features on /proc/version. A spoofed 7.0.12 on a
 * 5.15 kernel breaks both (enablefilecrypto_failed -> reboot to recovery).
 *
 * vold's threads are all renamed to "binder:<pid>_<n>" by libbinder, so
 * current->comm never equals "vold". Match on the executable name instead
 * (current->mm->exe_file), which is stable regardless of thread naming.
 * get_mm_exe_file()/fput() keep the file reference safe under RCU.
 */
static bool abk_display_release_keep_real(void)
{
\tconst char *name = "";
\tstruct file *exe_file;
\tbool keep = false;

\tif (current->mm) {
\t\texe_file = get_mm_exe_file(current->mm);
\t\tif (exe_file) {
\t\t\tname = exe_file->f_path.dentry->d_name.name;
\t\t\tif (!strcmp(name, "vold") ||
\t\t\t    !strncmp(name, "fsck.", 5) ||
\t\t\t    !strncmp(name, "mkfs.", 5) ||
\t\t\t    !strncmp(name, "resize.", 7) ||
\t\t\t    !strncmp(name, "e2fsck", 6))
\t\t\t\tkeep = true;
\t\t\tfput(exe_file);
\t\t}
\t}
\treturn keep;
}

"""


def patch_build_utils(path: Path) -> None:
    """Stamp boot-image metadata, where the build actually uses build_utils.sh.

    Both blocks below only affect mkbootimg arguments -- os_version, patch level
    and the GKI SPL date -- so neither has any bearing on the release strings the
    kernel itself reports. build_utils.sh also differs across target families,
    and some builders (ABK among them) never source it at all: it is referenced
    nowhere in ABK's build.yml, which assembles boot images itself.

    So a missing block here is not a failure. Warn and leave that stamp alone
    rather than aborting a run whose kernel-side patches already applied.
    """
    text = path.read_text()
    os_version_block = """  BOOT_IMAGE_HEADER_VERSION=${BOOT_IMAGE_HEADER_VERSION:-3}\n  MKBOOTIMG_ARGS=(\"--header_version\" \"${BOOT_IMAGE_HEADER_VERSION}\")\n"""
    os_version_new = f"""  BOOT_IMAGE_HEADER_VERSION=${{BOOT_IMAGE_HEADER_VERSION:-3}}\n  BOOT_IMAGE_OS_VERSION=${{ABK_BOOT_IMAGE_OS_VERSION:-16.0.0}}\n  BOOT_IMAGE_OS_PATCH_LEVEL=${{ABK_BOOT_IMAGE_OS_PATCH_LEVEL:-{DISPLAY_SECURITY_PATCH}}}\n  MKBOOTIMG_ARGS=(\"--header_version\" \"${{BOOT_IMAGE_HEADER_VERSION}}\")\n  MKBOOTIMG_ARGS+=(\"--os_version\" \"${{BOOT_IMAGE_OS_VERSION}}\")\n  MKBOOTIMG_ARGS+=(\"--os_patch_level\" \"${{BOOT_IMAGE_OS_PATCH_LEVEL}}\")\n"""
    if "--os_patch_level" not in text:
        if os_version_block in text:
            text = text.replace(os_version_block, os_version_new, 1)
        else:
            print(
                "::warning::display_release_spoof: mkbootimg header block not found "
                f"in {path}, leaving boot-image os_version/patch_level unchanged"
            )

    gki_spl_old = """      local spl_date=$(printf \"%d-%02d-05\\n\" ${spl_year} ${spl_month})\n\n      gki_add_avb_footer \"${boot_image_path}\" \\\n"""
    gki_spl_new = """      local spl_date=${ABK_GKI_SPL_DATE:-$(printf \"%d-%02d-05\\n\" ${spl_year} ${spl_month})}\n\n      gki_add_avb_footer \"${boot_image_path}\" \\\n"""
    if "ABK_GKI_SPL_DATE" not in text:
        if gki_spl_old in text:
            text = text.replace(gki_spl_old, gki_spl_new, 1)
        else:
            print(
                "::warning::display_release_spoof: gki SPL block not found in "
                f"{path}, leaving the GKI SPL date unchanged"
            )

    write_text(path, text)


def patch_sys_c(path: Path) -> None:
    candidates = [
        """/*
 * Work around broken programs that cannot handle \"Linux 3.0\".
 * Instead we map 3.x to 2.6.40+x, so e.g. 3.0 would be 2.6.40
 * And we map 4.x and later versions to 2.6.60+x, so 4.0/5.0/6.0/... would be
 * 2.6.60.
 */
static int override_release(char __user *release, size_t len)
{
\tint ret = 0;

\tif (current->personality & UNAME26) {
\t\tconst char *rest = UTS_RELEASE;
\t\tchar buf[65] = { 0 };
\t\tint ndots = 0;
\t\tunsigned v;
\t\tsize_t copy;

\t\twhile (*rest) {
\t\t\tif (*rest == '.' && ++ndots >= 3)
\t\t\t\tbreak;
\t\t\tif (!isdigit(*rest) && *rest != '.')
\t\t\t\tbreak;
\t\t\trest++;
\t\t}
\t\tv = LINUX_VERSION_PATCHLEVEL + 60;
\t\tcopy = clamp_t(size_t, len, 1, sizeof(buf));
\t\tcopy = scnprintf(buf, copy, \"2.6.%u%s\", v, rest);
\t\tret = copy_to_user(release, buf, copy + 1);
\t}
\treturn ret;
}
""",
        """/*
 * Keep ABI-sensitive release values intact while spoofing display output.
 */
static int override_release(char __user *release, size_t len)
{
\tchar buf[__NEW_UTS_LEN + 1] = { 0 };
\tsize_t copy;

\tif (current->personality & UNAME26) {
\t\tconst char *rest = UTS_RELEASE;
\t\tint ndots = 0;
\t\tunsigned v;

\t\twhile (*rest) {
\t\t\tif (*rest == '.' && ++ndots >= 3)
\t\t\t\tbreak;
\t\t\tif (!isdigit(*rest) && *rest != '.')
\t\t\t\tbreak;
\t\t\trest++;
\t\t}
\t\tv = LINUX_VERSION_PATCHLEVEL + 60;
\t\tcopy = clamp_t(size_t, len, 1, sizeof(buf));
\t\tcopy = scnprintf(buf, copy, \"2.6.%u%s\", v, rest);
\t\treturn copy_to_user(release, buf, copy + 1);
\t}

\tcopy = clamp_t(size_t, len, 1, sizeof(buf));
\tcopy = scnprintf(buf, copy, \"%s\", \"7.0.12\");
\treturn copy_to_user(release, buf, copy + 1);
}
""",
    ]
    replacement = f"""/*
 * Keep ABI-sensitive release values intact while spoofing display output.
 */
static const char *abk_display_release_suffix(const char *release)
{{
\twhile (*release) {{
\t\tif ((*release < '0' || *release > '9') && *release != '.')
\t\t\tbreak;
\t\trelease++;
\t}}

\treturn release;
}}

{KEEP_REAL_HELPER}static int override_release(char __user *release, size_t len)
{{
\tchar buf[__NEW_UTS_LEN + 1] = {{ 0 }};
\tsize_t copy;

\tif (current->personality & UNAME26) {{
\t\tunsigned v;

\t\tv = LINUX_VERSION_PATCHLEVEL + 60;
\t\tcopy = clamp_t(size_t, len, 1, sizeof(buf));
\t\tcopy = scnprintf(buf, copy, "2.6.%u%s", v,
\t\t\t\t abk_display_release_suffix(UTS_RELEASE));
\t\treturn copy_to_user(release, buf, copy + 1);
\t}}

\tif (abk_display_release_keep_real()) {{
\t\tcopy = clamp_t(size_t, len, 1, sizeof(buf));
\t\tcopy = scnprintf(buf, copy, "%s", UTS_RELEASE);
\t\treturn copy_to_user(release, buf, copy + 1);
\t}}

\tcopy = clamp_t(size_t, len, 1, sizeof(buf));
\tcopy = scnprintf(buf, copy, "{DISPLAY_RELEASE}%s",
\t\t\t abk_display_release_suffix(UTS_RELEASE));
\treturn copy_to_user(release, buf, copy + 1);
}}
"""
    replace_any(path, candidates, replacement, "kernel/sys.c")


def patch_utsname_sysctl(path: Path) -> None:
    ensure_after(
        path,
        "#include <linux/export.h>\n",
        "#include <generated/utsrelease.h>\n#include <linux/sched.h>\n#include <linux/kernel.h>\n#include <linux/mm.h>\n#include <linux/fs.h>\n",
        "kernel/utsname_sysctl.c",
    )

    candidates = [
        """#ifdef CONFIG_PROC_SYSCTL

static void *get_uts(struct ctl_table *table)
{
\tchar *which = table->data;
\tstruct uts_namespace *uts_ns;

\tuts_ns = current->nsproxy->uts_ns;
\twhich = (which - (char *)&init_uts_ns) + (char *)uts_ns;

\treturn which;
}

/*
 *\tSpecial case of dostring for the UTS structure. This has locks
 *\tto observe. Should this be in kernel/sys.c ????
 */
static int proc_do_uts_string(struct ctl_table *table, int write,
\t\t  void *buffer, size_t *lenp, loff_t *ppos)
{
\tstruct ctl_table uts_table;
\tint r;
\tchar tmp_data[__NEW_UTS_LEN + 1];

\tmemcpy(&uts_table, table, sizeof(uts_table));
\tuts_table.data = tmp_data;

\t/*
\t * Buffer the value in tmp_data so that proc_dostring() can be called
\t * without holding any locks.
\t * We also need to read the original value in the write==1 case to
\t * support partial writes.
\t */
\tdown_read(&uts_sem);
\tmemcpy(tmp_data, get_uts(table), sizeof(tmp_data));
\tup_read(&uts_sem);
\tr = proc_dostring(&uts_table, write, buffer, lenp, ppos);

\tif (write) {
\t\t/*
\t\t * Write back the new value.
\t\t * Note that, since we dropped uts_sem, the result can
\t\t * theoretically be incorrect if there are two parallel writes
\t\t * at non-zero offsets to the same sysctl.
\t\t */
\t\tadd_device_randomness(tmp_data, sizeof(tmp_data));
\t\tdown_write(&uts_sem);
\t\tmemcpy(get_uts(table), tmp_data, sizeof(tmp_data));
\t\tup_write(&uts_sem);
\t\tproc_sys_poll_notify(table->poll);
\t}

\treturn r;
}
#else
#define proc_do_uts_string NULL
#endif
""",
        """#ifdef CONFIG_PROC_SYSCTL

static bool uts_table_is_osrelease(struct ctl_table *table)
{
\treturn table->data == init_uts_ns.name.release;
}

static void *get_uts(struct ctl_table *table)
{
\tchar *which = table->data;
\tstruct uts_namespace *uts_ns;

\tuts_ns = current->nsproxy->uts_ns;
\twhich = (which - (char *)&init_uts_ns) + (char *)uts_ns;

\treturn which;
}

/*
 *\tSpecial case of dostring for the UTS structure. This has locks
 *\tto observe. Should this be in kernel/sys.c ????
 */
static int proc_do_uts_string(struct ctl_table *table, int write,
\t\t  void *buffer, size_t *lenp, loff_t *ppos)
{
\tstruct ctl_table uts_table;
\tint r;
\tchar tmp_data[__NEW_UTS_LEN + 1];

\tif (write && uts_table_is_osrelease(table))
\t\treturn -EPERM;

\tmemcpy(&uts_table, table, sizeof(uts_table));
\tuts_table.data = tmp_data;

\t/*
\t * Buffer the value in tmp_data so that proc_dostring() can be called
\t * without holding any locks.
\t * We also need to read the original value in the write==1 case to
\t * support partial writes.
\t */
\tdown_read(&uts_sem);
\tif (uts_table_is_osrelease(table))
\t\tmemcpy(tmp_data, "7.0.12", sizeof("7.0.12"));
\telse
\t\tmemcpy(tmp_data, get_uts(table), sizeof(tmp_data));
\tup_read(&uts_sem);
\tr = proc_dostring(&uts_table, write, buffer, lenp, ppos);

\tif (write) {
\t\t/*
\t\t * Write back the new value.
\t\t * Note that, since we dropped uts_sem, the result can
\t\t * theoretically be incorrect if there are two parallel writes
\t\t * at non-zero offsets to the same sysctl.
\t\t */
\t\tadd_device_randomness(tmp_data, sizeof(tmp_data));
\t\tdown_write(&uts_sem);
\t\tmemcpy(get_uts(table), tmp_data, sizeof(tmp_data));
\t\tup_write(&uts_sem);
\t\tproc_sys_poll_notify(table->poll);
\t}

\treturn r;
}
#else
#define proc_do_uts_string NULL
#endif
""",
    ]

    # 5.15 predates commit "random: add_device_randomness() on uts write", so the
    # write-back block there has no add_device_randomness() line. Derive that
    # shape from each candidate instead of pinning a second literal copy.
    randomness_line = "\t\tadd_device_randomness(tmp_data, sizeof(tmp_data));\n"
    candidates = [
        variant
        for candidate in candidates
        for variant in (candidate, candidate.replace(randomness_line, "", 1))
    ]
    replacement = f"""#ifdef CONFIG_PROC_SYSCTL

static bool uts_table_is_osrelease(struct ctl_table *table)
{{
\treturn table->data == init_uts_ns.name.release;
}}

static const char *abk_display_release_suffix(const char *release)
{{
\twhile (*release) {{
\t\tif ((*release < '0' || *release > '9') && *release != '.')
\t\t\tbreak;
\t\trelease++;
\t}}

\treturn release;
}}

{KEEP_REAL_HELPER}static void *get_uts(struct ctl_table *table)
{{
\tchar *which = table->data;
\tstruct uts_namespace *uts_ns;

\tuts_ns = current->nsproxy->uts_ns;
\twhich = (which - (char *)&init_uts_ns) + (char *)uts_ns;

\treturn which;
}}

/*
 *\tSpecial case of dostring for the UTS structure. This has locks
 *\tto observe. Should this be in kernel/sys.c ????
 */
static int proc_do_uts_string(struct ctl_table *table, int write,
\t\t  void *buffer, size_t *lenp, loff_t *ppos)
{{
\tstruct ctl_table uts_table;
\tint r;
\tchar tmp_data[__NEW_UTS_LEN + 1];

\tif (write && uts_table_is_osrelease(table))
\t\treturn -EPERM;

\tmemcpy(&uts_table, table, sizeof(uts_table));
\tuts_table.data = tmp_data;

\t/*
\t * Buffer the value in tmp_data so that proc_dostring() can be called
\t * without holding any locks.
\t * We also need to read the original value in the write==1 case to
\t * support partial writes.
\t */
\tdown_read(&uts_sem);
\tif (uts_table_is_osrelease(table)) {{
\t\tif (abk_display_release_keep_real())
\t\t\tmemcpy(tmp_data, get_uts(table), sizeof(tmp_data));
\t\telse
\t\t\tscnprintf(tmp_data, sizeof(tmp_data), "{DISPLAY_RELEASE}%s",
\t\t\t\t  abk_display_release_suffix(UTS_RELEASE));
\t}} else
\t\tmemcpy(tmp_data, get_uts(table), sizeof(tmp_data));
\tup_read(&uts_sem);
\tr = proc_dostring(&uts_table, write, buffer, lenp, ppos);

\tif (write) {{
\t\t/*
\t\t * Write back the new value.
\t\t * Note that, since we dropped uts_sem, the result can
\t\t * theoretically be incorrect if there are two parallel writes
\t\t * at non-zero offsets to the same sysctl.
\t\t */
\t\tadd_device_randomness(tmp_data, sizeof(tmp_data));
\t\tdown_write(&uts_sem);
\t\tmemcpy(get_uts(table), tmp_data, sizeof(tmp_data));
\t\tup_write(&uts_sem);
\t\tproc_sys_poll_notify(table->poll);
\t}}

\treturn r;
}}
#else
#define proc_do_uts_string NULL
#endif
"""
    # Keep add_device_randomness() only where the tree already called it;
    # emitting it on 5.15 would be an implicit declaration and fail the build.
    if randomness_line not in path.read_text():
        replacement = replacement.replace(randomness_line, "", 1)
    replace_any(path, candidates, replacement, "kernel/utsname_sysctl.c")


def patch_proc_version(path: Path) -> None:
    ensure_after(
        path,
        "#include <linux/fs.h>\n",
        "#include <generated/utsrelease.h>\n#include <linux/sched.h>\n#include <linux/mm.h>\n",
        "fs/proc/version.c",
    )
    ensure_after_any(
        path,
        [
            # 6.1 carries a proc-local internal.h; 5.15 does not, and there the
            # utsname.h include is the last one before version_proc_show().
            '#include "internal.h"\n\n',
            "#include <linux/utsname.h>\n\n",
            "#include <linux/utsname.h>\n",
        ],
        "static const char *abk_display_release_suffix(const char *release)\n"
        "{\n"
        "\twhile (*release) {\n"
        "\t\tif ((*release < '0' || *release > '9') && *release != '.')\n"
        "\t\t\tbreak;\n"
        "\t\trelease++;\n"
        "\t}\n\n"
        "\treturn release;\n"
        "}\n\n"
        + KEEP_REAL_HELPER,
        "fs/proc/version.c",
    )

    candidates = [
        """static int version_proc_show(struct seq_file *m, void *v)
{
\tseq_printf(m, linux_proc_banner,
\t\tutsname()->sysname,
\t\tutsname()->release,
\t\tutsname()->version);
\treturn 0;
}
""",
        """static int version_proc_show(struct seq_file *m, void *v)
{
\tseq_printf(m, linux_proc_banner,
\t\tutsname()->sysname,
\t\t\"7.0.12\",
\t\tutsname()->version);
\treturn 0;
}
""",
    ]
    replacement = f"""static int version_proc_show(struct seq_file *m, void *v)
{{
\tchar release[__NEW_UTS_LEN + 1];

\tif (abk_display_release_keep_real())
\t\tscnprintf(release, sizeof(release), "%s", UTS_RELEASE);
\telse
\t\tscnprintf(release, sizeof(release), "{DISPLAY_RELEASE}%s",
\t\t\t  abk_display_release_suffix(UTS_RELEASE));
\tseq_printf(m, linux_proc_banner,
\t\tutsname()->sysname,
\t\trelease,
\t\tutsname()->version);
\treturn 0;
}}
"""
    replace_any(path, candidates, replacement, "fs/proc/version.c")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <kernel-common-dir>")

    common_dir = Path(sys.argv[1])
    if not common_dir.is_dir():
        raise SystemExit(f"kernel common dir not found: {common_dir}")

    patch_sys_c(common_dir / "kernel/sys.c")
    patch_utsname_sysctl(common_dir / "kernel/utsname_sysctl.c")
    patch_proc_version(common_dir / "fs/proc/version.c")
    kernel_root = common_dir.parent
    build_utils = kernel_root / "build/kernel/build_utils.sh"
    if build_utils.exists():
        patch_build_utils(build_utils)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
