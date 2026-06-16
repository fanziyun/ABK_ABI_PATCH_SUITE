#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

DISPLAY_RELEASE = "7.0.12"


def replace_any(path: Path, candidates: list[str], replacement: str, label: str) -> None:
    text = path.read_text()
    if replacement in text:
        return

    for candidate in candidates:
        if candidate in text:
            path.write_text(text.replace(candidate, replacement, 1))
            return

    raise SystemExit(f"{label}: expected block not found in {path}")


def ensure_after(path: Path, anchor: str, snippet: str, label: str) -> None:
    text = path.read_text()
    if snippet in text:
        return
    if anchor not in text:
        raise SystemExit(f"{label}: anchor not found in {path}")
    path.write_text(text.replace(anchor, anchor + snippet, 1))


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

static int override_release(char __user *release, size_t len)
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
        "#include <generated/utsrelease.h>\n#include <linux/kernel.h>\n",
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

static void *get_uts(struct ctl_table *table)
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
\tif (uts_table_is_osrelease(table))
\t\tscnprintf(tmp_data, sizeof(tmp_data), "{DISPLAY_RELEASE}%s",
\t\t\t  abk_display_release_suffix(UTS_RELEASE));
\telse
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
    replace_any(path, candidates, replacement, "kernel/utsname_sysctl.c")


def patch_proc_version(path: Path) -> None:
    ensure_after(
        path,
        "#include <linux/fs.h>\n",
        "#include <generated/utsrelease.h>\n",
        "fs/proc/version.c",
    )
    ensure_after(
        path,
        '#include "internal.h"\n\n',
        "static const char *abk_display_release_suffix(const char *release)\n"
        "{\n"
        "\twhile (*release) {\n"
        "\t\tif ((*release < '0' || *release > '9') && *release != '.')\n"
        "\t\t\tbreak;\n"
        "\t\trelease++;\n"
        "\t}\n\n"
        "\treturn release;\n"
        "}\n\n",
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

\tscnprintf(release, sizeof(release), "{DISPLAY_RELEASE}%s",
\t\t  abk_display_release_suffix(UTS_RELEASE));
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
