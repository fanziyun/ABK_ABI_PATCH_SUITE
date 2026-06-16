#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMMON_DIR="${1:-}"
TMP_DIR="$(mktemp -d "$MODULE_DIR/.tmp-smoke.XXXXXX")"
trap 'rm -rf "$TMP_DIR" "$MODULE_DIR/scripts/__pycache__"' EXIT

if [ -z "$COMMON_DIR" ]; then
  printf 'usage: %s <kernel-common-dir>\n' "$0" >&2
  exit 1
fi

if [ ! -d "$COMMON_DIR" ]; then
  printf 'kernel common dir not found: %s\n' "$COMMON_DIR" >&2
  exit 1
fi

bash -n "$MODULE_DIR/setup.sh" "$MODULE_DIR/scripts/libabk.sh" "$MODULE_DIR/scripts/abi_patch_suite.sh"

mkdir -p \
  "$TMP_DIR/kernel/common/kernel" \
  "$TMP_DIR/kernel/common/kernel/module" \
  "$TMP_DIR/kernel/common/kernel/sched" \
  "$TMP_DIR/kernel/common/fs/proc" \
  "$TMP_DIR/kernel/common/include/linux" \
  "$TMP_DIR/kernel/common/android"
cp -a "$COMMON_DIR/Makefile" "$TMP_DIR/kernel/common/Makefile"
cp -a "$COMMON_DIR/kernel/sys.c" "$TMP_DIR/kernel/common/kernel/sys.c"
cp -a "$COMMON_DIR/kernel/utsname_sysctl.c" "$TMP_DIR/kernel/common/kernel/utsname_sysctl.c"
cp -a "$COMMON_DIR/kernel/module/main.c" "$TMP_DIR/kernel/common/kernel/module/main.c"
cp -a "$COMMON_DIR/kernel/module/version.c" "$TMP_DIR/kernel/common/kernel/module/version.c"
cp -a "$COMMON_DIR/kernel/sched/fair.c" "$TMP_DIR/kernel/common/kernel/sched/fair.c"
cp -a "$COMMON_DIR/kernel/pid.c" "$TMP_DIR/kernel/common/kernel/pid.c"
cp -a "$COMMON_DIR/kernel/fork.c" "$TMP_DIR/kernel/common/kernel/fork.c"
cp -a "$COMMON_DIR/fs/proc/version.c" "$TMP_DIR/kernel/common/fs/proc/version.c"
cp -a "$COMMON_DIR/include/linux/vermagic.h" "$TMP_DIR/kernel/common/include/linux/vermagic.h"
cp -a "$COMMON_DIR/include/linux/module.h" "$TMP_DIR/kernel/common/include/linux/module.h"
cp -a "$COMMON_DIR/include/linux/sched.h" "$TMP_DIR/kernel/common/include/linux/sched.h"
cp -a "$COMMON_DIR/kernel/module/internal.h" "$TMP_DIR/kernel/common/kernel/module/internal.h"
[ ! -d "$COMMON_DIR/android" ] || cp -a "$COMMON_DIR/android"/abi_gki_aarch64* "$TMP_DIR/kernel/common/android/" 2>/dev/null || true
: > "$TMP_DIR/defconfig"

KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
  bash "$MODULE_DIR/setup.sh" >/dev/null

KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
  bash "$MODULE_DIR/setup.sh" >/dev/null

grep -Fq '7.0.12%s' "$TMP_DIR/kernel/common/kernel/sys.c"
grep -Fq 'abk_display_release_suffix(UTS_RELEASE)' "$TMP_DIR/kernel/common/kernel/sys.c"
grep -Fq 'scnprintf(release, sizeof(release), "7.0.12%s"' "$TMP_DIR/kernel/common/fs/proc/version.c"
grep -Fq 'abk_display_release_suffix(UTS_RELEASE)' "$TMP_DIR/kernel/common/fs/proc/version.c"
grep -Fq 'scnprintf(tmp_data, sizeof(tmp_data), "7.0.12%s"' "$TMP_DIR/kernel/common/kernel/utsname_sysctl.c"
grep -Fq 'abk_display_release_suffix(UTS_RELEASE)' "$TMP_DIR/kernel/common/kernel/utsname_sysctl.c"

REPORT_DIR="$TMP_DIR/reports"
KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
ABK_MODULE_CHILD_ID=dual_abi_kmi_bridge \
ABK_MAINLINE_7012_ROOT="$MODULE_DIR/../linux" \
ABK_ABI_BRIDGE_REPORT_DIR="$REPORT_DIR" \
  bash "$MODULE_DIR/setup.sh" >/dev/null

[ -f "$REPORT_DIR/bridge_report.md" ]
[ -f "$REPORT_DIR/bridge_report.json" ]
grep -Fq 'ABK Dual ABI/KMI Bridge Report' "$REPORT_DIR/bridge_report.md"
grep -Fq '7.0.12-arch1' "$REPORT_DIR/bridge_report.md"
grep -Fq '"shared_symbol_count"' "$REPORT_DIR/bridge_report.json"
grep -Fq 'ABK_DUAL_ABI_BRIDGE_RELEASE_PREFIX' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'ABK_DUAL_ABI_BRIDGE_ALLOWLIST' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'abk_dual_abi_bridge_module_allowed' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'abk_dual_abi_bridge_vermagic_ok' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'abk_dual_abi_bridge_note_modstruct' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'abk_dual_abi_bridge_note_vermagic' "$TMP_DIR/kernel/common/kernel/module/main.c"
grep -Fq 'allow symbol CRC mismatch' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'CONFIG_ABK_DUAL_ABI_BRIDGE' "$TMP_DIR/kernel/common/kernel/module/version.c"

REPORT_DIR="$TMP_DIR/reports-experimental"
KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
ABK_MODULE_CHILD_ID=dual_abi_kmi_bridge \
ABK_MAINLINE_7012_ROOT="$MODULE_DIR/../linux" \
ABK_ABI_BRIDGE_REPORT_DIR="$REPORT_DIR" \
ABK_ABI_BRIDGE_POLICY=experimental \
  bash "$MODULE_DIR/setup.sh" >/dev/null

grep -Fq 'CONFIG_ABK_DUAL_ABI_BRIDGE_EXPERIMENTAL' "$TMP_DIR/kernel/common/kernel/module/version.c"

KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
ABK_MODULE_CHILD_ID=abi_fixups \
  bash "$MODULE_DIR/setup.sh" >/dev/null

grep -Fq 'ABK ABI fixups: bridge glue baseline applied.' "$TMP_DIR/kernel/common/kernel/module/version.c"

SECURITY_DIR="$TMP_DIR/security"
KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
ABK_MODULE_CHILD_ID=security_update_backport \
ABK_SECURITY_BACKPORT_REPORT_DIR="$SECURITY_DIR" \
  bash "$MODULE_DIR/setup.sh" >/dev/null

[ -f "$SECURITY_DIR/security_backport_queue.md" ]
[ -f "$SECURITY_DIR/security_backport_queue.json" ]
grep -Fq 'sec_meta_batch_001' "$SECURITY_DIR/security_backport_queue.md"
grep -Fq '"batch": "sec_meta_batch_001"' "$SECURITY_DIR/security_backport_queue.json"

FEATURE_DIR="$TMP_DIR/feature"
KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
ABK_MODULE_CHILD_ID=feature_porting \
ABK_MAINLINE_7012_ROOT="$MODULE_DIR/../linux" \
ABK_FEATURE_PORTING_REPORT_DIR="$FEATURE_DIR" \
  bash "$MODULE_DIR/setup.sh" >/dev/null

[ -f "$FEATURE_DIR/feature_porting_report.md" ]
[ -f "$FEATURE_DIR/feature_porting_report.json" ]
grep -Fq 'ABK Feature Porting Report' "$FEATURE_DIR/feature_porting_report.md"
grep -Fq '"strategy": "minimal_intrusion_graft"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq 'ANDROID_KABI_USE(1, u64 deadline);' "$TMP_DIR/kernel/common/include/linux/sched.h"
grep -Fq 'ANDROID_KABI_USE(4, struct {' "$TMP_DIR/kernel/common/include/linux/sched.h"
grep -Fq 'bool retried_preload;' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'local_pid_max = READ_ONCE(tmp->pid_max);' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'alloc_pid() preload retry and per-namespace pid_max semantics applied' "$TMP_DIR/kernel/common/kernel/pid.c"

printf 'smoke ok\n'
