#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMMON_DIR="${1:-}"
TMP_DIR="$(mktemp -d "$MODULE_DIR/.tmp-smoke.XXXXXX")"
REFERENCE_ROOT="$MODULE_DIR/../linux"
export TMPDIR="$TMP_DIR"
trap 'rm -rf "$TMP_DIR" "$MODULE_DIR/scripts/__pycache__"' EXIT

if [ -z "$COMMON_DIR" ]; then
  printf 'usage: %s <kernel-common-dir>\n' "$0" >&2
  exit 1
fi

if [ ! -d "$COMMON_DIR" ]; then
  printf 'kernel common dir not found: %s\n' "$COMMON_DIR" >&2
  exit 1
fi

if [ ! -d "$REFERENCE_ROOT" ]; then
  printf 'reference linux tree not found: %s\n' "$REFERENCE_ROOT" >&2
  exit 1
fi

assert_child_rejected() {
  local child_id="$1"
  local expected_fragment="$2"
  local stderr_file="$TMP_DIR/${child_id}.stderr"

  if KERNEL_ROOT="$TMP_DIR/kernel" \
    DEFCONFIG="$TMP_DIR/defconfig" \
    CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
    ABK_MODULE_CHILD_ID="$child_id" \
    bash "$MODULE_DIR/setup.sh" >/dev/null 2>"$stderr_file"; then
    printf 'expected child id to be rejected: %s\n' "$child_id" >&2
    exit 1
  fi

  grep -Fq "$expected_fragment" "$stderr_file"
}

bash -n "$MODULE_DIR/setup.sh" "$MODULE_DIR/scripts/libabk.sh" "$MODULE_DIR/scripts/abi_patch_suite.sh"

mkdir -p \
  "$TMP_DIR/kernel/common/kernel" \
  "$TMP_DIR/kernel/common/kernel/module" \
  "$TMP_DIR/kernel/common/kernel/bpf" \
  "$TMP_DIR/kernel/common/kernel/sched" \
  "$TMP_DIR/kernel/common/kernel/time" \
  "$TMP_DIR/kernel/common/block" \
  "$TMP_DIR/kernel/common/mm" \
  "$TMP_DIR/kernel/common/net" \
  "$TMP_DIR/kernel/common/net/core" \
  "$TMP_DIR/kernel/common/net/ipv4" \
  "$TMP_DIR/kernel/common/net/ipv6" \
  "$TMP_DIR/kernel/common/io_uring" \
  "$TMP_DIR/kernel/common/drivers/block/zram" \
  "$TMP_DIR/kernel/common/fs" \
  "$TMP_DIR/kernel/common/fs/proc" \
  "$TMP_DIR/kernel/common/include/net/netns" \
  "$TMP_DIR/kernel/common/include/net" \
  "$TMP_DIR/kernel/common/include/linux/sched" \
  "$TMP_DIR/kernel/common/include/linux" \
  "$TMP_DIR/kernel/common/include/uapi/linux" \
  "$TMP_DIR/kernel/common/android" \
  "$TMP_DIR/kernel/build/kernel"
cp -a "$COMMON_DIR/Makefile" "$TMP_DIR/kernel/common/Makefile"
cp -a "$COMMON_DIR/kernel/sys.c" "$TMP_DIR/kernel/common/kernel/sys.c"
cp -a "$COMMON_DIR/kernel/sysctl.c" "$TMP_DIR/kernel/common/kernel/sysctl.c"
cp -a "$COMMON_DIR/kernel/utsname_sysctl.c" "$TMP_DIR/kernel/common/kernel/utsname_sysctl.c"
cp -a "$COMMON_DIR/kernel/module/main.c" "$TMP_DIR/kernel/common/kernel/module/main.c"
cp -a "$COMMON_DIR/kernel/module/version.c" "$TMP_DIR/kernel/common/kernel/module/version.c"
cp -a "$COMMON_DIR/kernel/bpf/btf.c" "$TMP_DIR/kernel/common/kernel/bpf/btf.c"
cp -a "$COMMON_DIR/kernel/bpf/helpers.c" "$TMP_DIR/kernel/common/kernel/bpf/helpers.c"
cp -a "$COMMON_DIR/kernel/bpf/syscall.c" "$TMP_DIR/kernel/common/kernel/bpf/syscall.c"
cp -a "$COMMON_DIR/kernel/bpf/verifier.c" "$TMP_DIR/kernel/common/kernel/bpf/verifier.c"
cp -a "$COMMON_DIR/kernel/sched/core.c" "$TMP_DIR/kernel/common/kernel/sched/core.c"
cp -a "$COMMON_DIR/kernel/sched/fair.c" "$TMP_DIR/kernel/common/kernel/sched/fair.c"
cp -a "$COMMON_DIR/kernel/sched/idle.c" "$TMP_DIR/kernel/common/kernel/sched/idle.c"
cp -a "$COMMON_DIR/kernel/sched/sched.h" "$TMP_DIR/kernel/common/kernel/sched/sched.h"
cp -a "$COMMON_DIR/kernel/time/tick-sched.c" "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
cp -a "$COMMON_DIR/kernel/time/tick-sched.h" "$TMP_DIR/kernel/common/kernel/time/tick-sched.h"
cp -a "$COMMON_DIR/kernel/pid.c" "$TMP_DIR/kernel/common/kernel/pid.c"
cp -a "$COMMON_DIR/kernel/fork.c" "$TMP_DIR/kernel/common/kernel/fork.c"
cp -a "$COMMON_DIR/block/blk-core.c" "$TMP_DIR/kernel/common/block/blk-core.c"
cp -a "$COMMON_DIR/block/blk-mq.c" "$TMP_DIR/kernel/common/block/blk-mq.c"
cp -a "$COMMON_DIR/block/blk-mq-sched.c" "$TMP_DIR/kernel/common/block/blk-mq-sched.c"
cp -a "$COMMON_DIR/block/blk-sysfs.c" "$TMP_DIR/kernel/common/block/blk-sysfs.c"
cp -a "$COMMON_DIR/block/elevator.c" "$TMP_DIR/kernel/common/block/elevator.c"
cp -a "$COMMON_DIR/block/mq-deadline.c" "$TMP_DIR/kernel/common/block/mq-deadline.c"
cp -a "$COMMON_DIR/block/bfq-iosched.c" "$TMP_DIR/kernel/common/block/bfq-iosched.c"
cp -a "$COMMON_DIR/block/kyber-iosched.c" "$TMP_DIR/kernel/common/block/kyber-iosched.c"
cp -a "$COMMON_DIR/mm/slab.h" "$TMP_DIR/kernel/common/mm/slab.h"
cp -a "$COMMON_DIR/mm/slub.c" "$TMP_DIR/kernel/common/mm/slub.c"
cp -a "$COMMON_DIR/mm/slab_common.c" "$TMP_DIR/kernel/common/mm/slab_common.c"
cp -a "$COMMON_DIR/mm/swap.h" "$TMP_DIR/kernel/common/mm/swap.h"
cp -a "$COMMON_DIR/mm/swap_state.c" "$TMP_DIR/kernel/common/mm/swap_state.c"
cp -a "$COMMON_DIR/mm/shmem.c" "$TMP_DIR/kernel/common/mm/shmem.c"
cp -a "$COMMON_DIR/mm/memory.c" "$TMP_DIR/kernel/common/mm/memory.c"
cp -a "$COMMON_DIR/mm/huge_memory.c" "$TMP_DIR/kernel/common/mm/huge_memory.c"
cp -a "$COMMON_DIR/mm/vmstat.c" "$TMP_DIR/kernel/common/mm/vmstat.c"
cp -a "$COMMON_DIR/io_uring"/. "$TMP_DIR/kernel/common/io_uring/"
cp -a "$COMMON_DIR/drivers/block/zram/zram_drv.c" "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"
cp -a "$COMMON_DIR/drivers/block/zram/zram_drv.h" "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.h"
cp -a "$COMMON_DIR/fs/file.c" "$TMP_DIR/kernel/common/fs/file.c"
cp -a "$COMMON_DIR/fs/proc/version.c" "$TMP_DIR/kernel/common/fs/proc/version.c"
cp -a "$COMMON_DIR/net/socket.c" "$TMP_DIR/kernel/common/net/socket.c"
cp -a "$COMMON_DIR/net/core/sock.c" "$TMP_DIR/kernel/common/net/core/sock.c"
cp -a "$COMMON_DIR/net/core/skbuff.c" "$TMP_DIR/kernel/common/net/core/skbuff.c"
cp -a "$COMMON_DIR/net/ipv4/tcp.c" "$TMP_DIR/kernel/common/net/ipv4/tcp.c"
cp -a "$COMMON_DIR/net/ipv4/tcp_input.c" "$TMP_DIR/kernel/common/net/ipv4/tcp_input.c"
cp -a "$COMMON_DIR/net/ipv4/tcp_output.c" "$TMP_DIR/kernel/common/net/ipv4/tcp_output.c"
cp -a "$COMMON_DIR/net/ipv4/tcp_minisocks.c" "$TMP_DIR/kernel/common/net/ipv4/tcp_minisocks.c"
cp -a "$COMMON_DIR/net/ipv4/tcp_ipv4.c" "$TMP_DIR/kernel/common/net/ipv4/tcp_ipv4.c"
cp -a "$COMMON_DIR/net/ipv4/syncookies.c" "$TMP_DIR/kernel/common/net/ipv4/syncookies.c"
cp -a "$COMMON_DIR/net/ipv4/tcp_timer.c" "$TMP_DIR/kernel/common/net/ipv4/tcp_timer.c"
cp -a "$COMMON_DIR/net/ipv4/sysctl_net_ipv4.c" "$TMP_DIR/kernel/common/net/ipv4/sysctl_net_ipv4.c"
cp -a "$COMMON_DIR/net/ipv6/ip6_output.c" "$TMP_DIR/kernel/common/net/ipv6/ip6_output.c"
cp -a "$COMMON_DIR/net/ipv6/inet6_connection_sock.c" "$TMP_DIR/kernel/common/net/ipv6/inet6_connection_sock.c"
cp -a "$COMMON_DIR/net/ipv6/ipv6_sockglue.c" "$TMP_DIR/kernel/common/net/ipv6/ipv6_sockglue.c"
cp -a "$(dirname "$COMMON_DIR")/build/kernel/build_utils.sh" "$TMP_DIR/kernel/build/kernel/build_utils.sh"
cp -a "$COMMON_DIR/include/linux/blkdev.h" "$TMP_DIR/kernel/common/include/linux/blkdev.h"
cp -a "$COMMON_DIR/include/linux/btf.h" "$TMP_DIR/kernel/common/include/linux/btf.h"
cp -a "$COMMON_DIR/include/linux/filter.h" "$TMP_DIR/kernel/common/include/linux/filter.h"
cp -a "$COMMON_DIR/include/linux/io_uring_types.h" "$TMP_DIR/kernel/common/include/linux/io_uring_types.h"
cp -a "$COMMON_DIR/include/linux/tcp.h" "$TMP_DIR/kernel/common/include/linux/tcp.h"
cp -a "$COMMON_DIR/include/linux/vermagic.h" "$TMP_DIR/kernel/common/include/linux/vermagic.h"
cp -a "$COMMON_DIR/include/linux/module.h" "$TMP_DIR/kernel/common/include/linux/module.h"
cp -a "$COMMON_DIR/include/linux/sched.h" "$TMP_DIR/kernel/common/include/linux/sched.h"
cp -a "$COMMON_DIR/include/linux/tick.h" "$TMP_DIR/kernel/common/include/linux/tick.h"
cp -a "$COMMON_DIR/include/linux/sched/nohz.h" "$TMP_DIR/kernel/common/include/linux/sched/nohz.h"
cp -a "$COMMON_DIR/include/net/tcp.h" "$TMP_DIR/kernel/common/include/net/tcp.h"
cp -a "$COMMON_DIR/include/net/sock.h" "$TMP_DIR/kernel/common/include/net/sock.h"
cp -a "$COMMON_DIR/include/net/ipv6.h" "$TMP_DIR/kernel/common/include/net/ipv6.h"
cp -a "$COMMON_DIR/include/net/ip6_route.h" "$TMP_DIR/kernel/common/include/net/ip6_route.h"
cp -a "$COMMON_DIR/include/net/netns/ipv4.h" "$TMP_DIR/kernel/common/include/net/netns/ipv4.h"
cp -a "$COMMON_DIR/include/uapi/linux/net_tstamp.h" "$TMP_DIR/kernel/common/include/uapi/linux/net_tstamp.h"
cp -a "$COMMON_DIR/include/uapi/linux/bpf.h" "$TMP_DIR/kernel/common/include/uapi/linux/bpf.h"
cp -a "$COMMON_DIR/include/uapi/linux/filter.h" "$TMP_DIR/kernel/common/include/uapi/linux/filter.h"
cp -a "$COMMON_DIR/kernel/module/internal.h" "$TMP_DIR/kernel/common/kernel/module/internal.h"
[ ! -d "$COMMON_DIR/android" ] || cp -a "$COMMON_DIR/android"/abi_gki_aarch64* "$TMP_DIR/kernel/common/android/" 2>/dev/null || true
cp -a "$TMP_DIR/kernel" "$TMP_DIR/kernel-local-injected"
cat > "$TMP_DIR/defconfig" <<'EOF'
CONFIG_CMDLINE="console=ttynull stack_depot_disable=on cgroup_disable=pressure bootconfig"
CONFIG_CMDLINE_EXTEND=y
EOF

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
grep -Fq 'BOOT_IMAGE_OS_VERSION=${ABK_BOOT_IMAGE_OS_VERSION:-16.0.0}' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'BOOT_IMAGE_OS_PATCH_LEVEL=${ABK_BOOT_IMAGE_OS_PATCH_LEVEL:-2026-06}' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'MKBOOTIMG_ARGS+=("--os_version" "${BOOT_IMAGE_OS_VERSION}")' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'MKBOOTIMG_ARGS+=("--os_patch_level" "${BOOT_IMAGE_OS_PATCH_LEVEL}")' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'local spl_date=${ABK_GKI_SPL_DATE:-$(printf "%d-%02d-05\n" ${spl_year} ${spl_month})}' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'ABK_BOOT_IMAGE_LOGGING_ARGS=${ABK_BOOT_IMAGE_LOGGING_ARGS:-"ignore_loglevel panic=30 oops=panic"}' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'ABK_BOOTLOG_CONSOLE=${ABK_BOOTLOG_CONSOLE:-}' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'ABK_BOOTLOG_EARLYCON=${ABK_BOOTLOG_EARLYCON:-}' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'ABK_BOOT_IMAGE_LOGGING_APPLY_TO_BOOT_CMDLINE=${ABK_BOOT_IMAGE_LOGGING_APPLY_TO_BOOT_CMDLINE:-1}' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'KERNEL_VENDOR_CMDLINE+=" ${ABK_BOOT_IMAGE_LOGGING_CMDLINE}"' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'KERNEL_CMDLINE+=" ${ABK_BOOT_IMAGE_LOGGING_CMDLINE}"' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'console=${ABK_BOOTLOG_CONSOLE}' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'earlycon=${ABK_BOOTLOG_EARLYCON}' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'ABK_VENDOR_BOOTCONFIG_PARAMS' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'ABK_GKI_BOOT_IMAGE_LOGGING_ARGS=${ABK_GKI_BOOT_IMAGE_LOGGING_ARGS:-${ABK_BOOT_IMAGE_LOGGING_ARGS:-"ignore_loglevel panic=30 oops=panic"}}' "$TMP_DIR/kernel/build/kernel/build_utils.sh"
grep -Fq 'GKI_KERNEL_CMDLINE+=" ${ABK_GKI_BOOT_IMAGE_LOGGING_CMDLINE}"' "$TMP_DIR/kernel/build/kernel/build_utils.sh"

REPORT_DIR="$TMP_DIR/reports"
KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
ABK_MODULE_CHILD_ID=abi_bridge \
ABK_MAINLINE_7012_ROOT="$REFERENCE_ROOT" \
ABK_ABI_BRIDGE_REPORT_DIR="$REPORT_DIR" \
  bash "$MODULE_DIR/setup.sh" >/dev/null

[ -f "$REPORT_DIR/bridge_report.md" ]
[ -f "$REPORT_DIR/bridge_report.json" ]
grep -Fq 'ABK Dual ABI/KMI Bridge Report' "$REPORT_DIR/bridge_report.md"
grep -Fq '7.0.12-arch1' "$REPORT_DIR/bridge_report.md"
grep -Fq '"shared_symbol_count"' "$REPORT_DIR/bridge_report.json"
grep -Fq '"default_mode": "global_7012"' "$REPORT_DIR/bridge_report.json"
grep -Fq '"default_scope": "all_7_0_12_family_modules"' "$REPORT_DIR/bridge_report.json"
grep -Fq '"bridge_global_7012_enabled": true' "$REPORT_DIR/bridge_report.json"
grep -Fq 'ABK_DUAL_ABI_BRIDGE_RELEASE_PREFIX' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'ABK_DUAL_ABI_BRIDGE_POLICY "global_7012"' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'abk_dual_abi_bridge_is_global_7012' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'abk_dual_abi_bridge_module_allowed' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'abk_dual_abi_bridge_release_allowed' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'abk_dual_abi_bridge_vermagic_ok' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'abk_dual_abi_bridge_note_modstruct' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'abk_dual_abi_bridge_note_vermagic' "$TMP_DIR/kernel/common/kernel/module/main.c"
grep -Fq 'allow 7.0.12-family vermagic mismatch' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'allow 7.0.12-family module_layout mismatch' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'allow 7.0.12-family symbol CRC mismatch' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'CONFIG_ABK_DUAL_ABI_BRIDGE' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'ABK ABI fixups: basic loader compat applied for global 7.0.12-family bridge.' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'ABK ABI fixups: runtime ABI followups remain deferred beyond loader-adjacent glue.' "$TMP_DIR/kernel/common/kernel/module/version.c"
grep -Fq 'ABK ABI fixups: basic loader compat is global for 7.0.12-family modules.' "$TMP_DIR/kernel/common/kernel/module/version.c"

INJECTED_MODULE_DIR="$TMP_DIR/workspace/custom_modules/ABK_ABI_PATCH_SUITE"
mkdir -p "$INJECTED_MODULE_DIR"
rsync -a --delete --exclude='.git' "$MODULE_DIR"/ "$INJECTED_MODULE_DIR"/
LOCAL_INJECTED_REPORT_DIR="$TMP_DIR/reports-local-injected"
KERNEL_ROOT="$TMP_DIR/kernel-local-injected" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
ABK_MODULE_CHILD_ID=abi_bridge \
ABK_MODULE_GROUP_REPO_URL="$MODULE_DIR" \
ABK_ABI_BRIDGE_REPORT_DIR="$LOCAL_INJECTED_REPORT_DIR" \
  bash "$INJECTED_MODULE_DIR/setup.sh" >/dev/null

[ -f "$LOCAL_INJECTED_REPORT_DIR/bridge_report.md" ]
[ -f "$LOCAL_INJECTED_REPORT_DIR/bridge_report.json" ]
grep -Fq 'ABK Dual ABI/KMI Bridge Report' "$LOCAL_INJECTED_REPORT_DIR/bridge_report.md"
grep -Fq '7.0.12-arch1' "$LOCAL_INJECTED_REPORT_DIR/bridge_report.md"
grep -Fq '"bridge_global_7012_enabled": true' "$LOCAL_INJECTED_REPORT_DIR/bridge_report.json"

REPORT_DIR="$TMP_DIR/reports-experimental"
KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
ABK_MODULE_CHILD_ID=abi_bridge \
ABK_MAINLINE_7012_ROOT="$REFERENCE_ROOT" \
ABK_ABI_BRIDGE_REPORT_DIR="$REPORT_DIR" \
ABK_ABI_BRIDGE_POLICY=experimental \
  bash "$MODULE_DIR/setup.sh" >/dev/null

grep -Fq 'CONFIG_ABK_DUAL_ABI_BRIDGE_EXPERIMENTAL' "$TMP_DIR/kernel/common/kernel/module/version.c"

assert_child_rejected dual_abi_kmi_bridge "reorganized into 'abi_bridge'"
assert_child_rejected abi_fixups "reorganized into 'abi_bridge'"
assert_child_rejected security_update_backport "reorganized into 'security_backport'"
assert_child_rejected feature_porting "reorganized into 'feature_porting_core'"
assert_child_rejected feature_porting_phase2 "reorganized into 'feature_porting_backlog'"
assert_child_rejected network_porting "paused and no longer publicly injectable"
assert_child_rejected framebuffer_bootlog "paused and no longer publicly injectable"

SECURITY_DIR="$TMP_DIR/security"
KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
ABK_MODULE_CHILD_ID=security_backport \
ABK_SECURITY_BACKPORT_REPORT_DIR="$SECURITY_DIR" \
  bash "$MODULE_DIR/setup.sh" >/dev/null

[ -f "$SECURITY_DIR/security_backport_queue.md" ]
[ -f "$SECURITY_DIR/security_backport_queue.json" ]
grep -Fq 'sec_lowrisk_batch_001' "$SECURITY_DIR/security_backport_queue.md"
grep -Fq '"batch": "sec_lowrisk_batch_001"' "$SECURITY_DIR/security_backport_queue.json"
grep -Fq '"source_base": "7.0.12-first"' "$SECURITY_DIR/security_backport_queue.json"
grep -Fq '"status": "applied"' "$SECURITY_DIR/security_backport_queue.json" || \
grep -Fq '"status": "partial"' "$SECURITY_DIR/security_backport_queue.json"
grep -Fq '"selected_candidates"' "$SECURITY_DIR/security_backport_queue.json"
grep -Fq '"applied_candidates"' "$SECURITY_DIR/security_backport_queue.json"
grep -Fq '"blocked_candidates"' "$SECURITY_DIR/security_backport_queue.json"
grep -Fq '"tree_escalation_required"' "$SECURITY_DIR/security_backport_queue.json"
grep -Fq 'ABK security_update_backport: write-once modules_disabled guard.' "$TMP_DIR/kernel/common/kernel/sysctl.c"
! grep -Fq 'ABK security_update_backport: synchronized queue timeout teardown.' "$TMP_DIR/kernel/common/block/blk-core.c"
! grep -Fq 'timer_delete_sync(&q->timeout);' "$TMP_DIR/kernel/common/block/blk-core.c"
grep -Fq '"blk_sync_queue_timer_delete_sync"' "$SECURITY_DIR/security_backport_queue.json"
grep -Fq '"status": "blocked_by_fixups"' "$SECURITY_DIR/security_backport_queue.json"

FEATURE_DIR="$TMP_DIR/feature"
KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
ABK_MODULE_CHILD_ID=feature_porting_core \
ABK_MAINLINE_7012_ROOT="$REFERENCE_ROOT" \
ABK_FEATURE_PORTING_REPORT_DIR="$FEATURE_DIR" \
  bash "$MODULE_DIR/setup.sh" >/dev/null

[ -f "$FEATURE_DIR/feature_porting_report.md" ]
[ -f "$FEATURE_DIR/feature_porting_report.json" ]
grep -Fq 'ABK Feature Porting Report' "$FEATURE_DIR/feature_porting_report.md"
grep -Fq '"strategy": "minimal_intrusion_graft"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"sched_eevdf_pick_logic"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"sched_eevdf_runtime_state_phase3"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"pid_alloc_hotpath_phase2"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"fd_alloc_hotpath"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"close_range_hotpath"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"blk_mq_async_depth"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"zram_compressed_writeback"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"nohz_field_refinement"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"avg_idle_preemption_mode"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"pidfd_preparation_compat"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"swap_table_phase2_large_folios"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"slab_alloc_free_hotpath"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"hugepage_fault_alloc_fastpath"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"io_uring_nowait_core"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"io_uring_nowait_rw_net"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"io_uring_support_modules"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"io_uring_feature_porting_fixups"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"status": "runtime_state_phase3_stable"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"phase": "scan_based_runtime_phase3"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"delayed_path_status": "delayed_path_deferred"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"milestones": [' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"status": "queue_depth_policy_tracked"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"phase": "queue_depth_policy_parity"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"policy_scope": "block_queue_depth_not_storage_whole_target"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"zram_compressed_writeback_port"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"status": "writeback_policy_tracked"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"phase": "compressed_writeback_parity"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"mode": "already_present"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"nohz_field_refinement_port"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"status": "nohz_state_fields_grafted"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"phase": "legacy_tick_sched_state_consistent"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"tick_sched_shape": "legacy_bitfield_triplet"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"idle_entry_exit_consistent": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"tick_stop_consistent": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"idle_calls_consistent": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"policy_scope": "kernel_time_and_sched_nohz_only"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"avg_idle_preemption_mode_port"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"status": "avg_idle_thresholds_simplified"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"phase": "wake_side_prediction_removed"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"target_shape": "idle_exit_avg_idle_only"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"wake_avg_idle_retained": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"sis_prop_simplified": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"newidle_threshold_simplified": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"runtime_state_extended": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"runtime_state_phase3_stable": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"slice_lifecycle_consistent": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"cfs_rq_augmentation_used": false' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"tree_escalation_required": false' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"sidecar_state_used": false' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"sidecar_state_scope": "none"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"new_interface_used": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"new_interface_scope": "file_local_helper"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"new_interface_scope": "internal_static_api"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"swap_table_phase2_large_folios_port"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"slab_alloc_free_hotpath_port"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"status": "swap_folio_path_grafted"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"phase": "swapin_swapcache_phase2"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"target_shape": "folio_swapcache_helper_split"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"folio_surface_used": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"public_surface_retained": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"swapcache_helper_grafted": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"swap_readahead_simplified": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"shmem_escalation_required": false' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"status": "slub_hotpath_grafted"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"phase": "alloc_free_hotpath_phase1"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"target_shape": "slub_alloc_free_helper_split"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"alloc_path_tightened": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"free_path_tightened": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"bulk_path_touched": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"hugepage_fault_alloc_fastpath_port"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"status": "thp_fault_alloc_grafted"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"phase": "anon_thp_fault_fastpath"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"target_shape": "fault_alloc_helper_split"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"fault_alloc_helper_grafted": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"fault_fallback_tracked": true' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"khugepaged_escalation_required": false' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"status": "issue_path_and_flag_bookkeeping_grafted"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"status": "partial"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"io_uring_nowait_core_port"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"io_uring_nowait_rw_net_port"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"io_uring_support_modules_status"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq 'avg_idle preemption mode simplification' "$TMP_DIR/kernel/common/kernel/sched/core.c"
grep -Fq 'update_rq_avg_idle(rq);' "$TMP_DIR/kernel/common/kernel/sched/idle.c"
grep -Fq 'wake_avg_idle/SIS_PROP prediction path' "$TMP_DIR/kernel/common/kernel/sched/fair.c"
grep -Fq 'extern void update_rq_avg_idle(struct rq *rq);' "$TMP_DIR/kernel/common/kernel/sched/sched.h"
grep -Fq 'io_uring NOWAIT core issue path graft' "$TMP_DIR/kernel/common/io_uring/io_uring.c"
grep -Fq 'io_uring fixed-file NOWAIT bookkeeping graft' "$TMP_DIR/kernel/common/io_uring/filetable.h"
grep -Fq 'io_uring NOWAIT retry-policy helper graft' "$TMP_DIR/kernel/common/io_uring/rw.c"
grep -Fq 'recv/send poll-first and force_nonblock share the same upfront NOWAIT gate' "$TMP_DIR/kernel/common/io_uring/net.c"
grep -Fq 'io_uring NOWAIT stays explicitly deferred for this helper-only path' "$TMP_DIR/kernel/common/io_uring/fs.c"
grep -Fq '"status": "pidfd_helper_grafted"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"surface_status": "pidfd_surface_tracked"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq '"pidfs_status": "pidfs_deferred"' "$FEATURE_DIR/feature_porting_report.json"
grep -Fq 'CONFIG_ZRAM_WRITEBACK=y' "$TMP_DIR/defconfig"
grep -Fq 'ANDROID_KABI_USE(1, u64 deadline);' "$TMP_DIR/kernel/common/include/linux/sched.h"
grep -Fq 'ANDROID_KABI_USE(3, s64 vlag);' "$TMP_DIR/kernel/common/include/linux/sched.h"
grep -Fq 'ANDROID_KABI_USE(4, u64 slice);' "$TMP_DIR/kernel/common/include/linux/sched.h"
grep -Fq 'scan-based EEVDF runtime-state graft' "$TMP_DIR/kernel/common/kernel/sched/fair.c"
grep -Fq 'return abk_pick_eevdf(cfs_rq, curr);' "$TMP_DIR/kernel/common/kernel/sched/fair.c"
grep -Fq 'ABK_EEVDF_REL_DEADLINE_BIT' "$TMP_DIR/kernel/common/kernel/sched/fair.c"
grep -Fq 'abk_eevdf_preserved_lag(cfs_rq, se)' "$TMP_DIR/kernel/common/kernel/sched/fair.c"
grep -Fq 'abk_eevdf_store_rel_deadline(se);' "$TMP_DIR/kernel/common/kernel/sched/fair.c"
grep -Fq 'phase-3 preserve lag/deadline across both current and queued reweight paths' "$TMP_DIR/kernel/common/kernel/sched/fair.c"
grep -Fq 'se->vlag = div_s64(se->vlag * (s64)old_weight, new_weight);' "$TMP_DIR/kernel/common/kernel/sched/fair.c"
grep -Fq 'if (abk_eevdf_refresh_deadline(cfs_rq, curr)) {' "$TMP_DIR/kernel/common/kernel/sched/fair.c"
grep -Fq 'abk_eevdf_refresh_deadline(cfs_rq, se);' "$TMP_DIR/kernel/common/kernel/sched/fair.c"
grep -Fq 'abk_eevdf_refresh_deadline(cfs_rq, prev);' "$TMP_DIR/kernel/common/kernel/sched/fair.c"
grep -Fq 'bool retried_preload;' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'if (nr == -ENOSPC)' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'nr = -EAGAIN;' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'alloc_pid() preload retry and 6.1-compatible pid allocation semantics applied' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'pidfd compat helper graft' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'abk_pidfd_has_forbidden_flags' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'if (abk_pidfd_has_forbidden_flags(flags, PIDFD_NONBLOCK))' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'if (abk_pidfd_has_forbidden_flags(flags, 0))' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'phase-three scan-based EEVDF runtime-state and pidfd compat entry executed' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'keep CLONE_PIDFD on legacy pidfd plumbing; pidfs remains deferred' "$TMP_DIR/kernel/common/kernel/fork.c"
grep -Fq 'pidfd_open' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'pidfd_getfd' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'CLONE_PIDFD' "$TMP_DIR/kernel/common/kernel/fork.c"
grep -Fq 'pidfd_create' "$TMP_DIR/kernel/common/kernel/pid.c"
grep -Fq 'pidfd_fops' "$TMP_DIR/kernel/common/kernel/fork.c"
grep -Fq 'fd allocation hotpath helper graft' "$TMP_DIR/kernel/common/fs/file.c"
grep -Fq 'abk_fdtable_slots_wanted' "$TMP_DIR/kernel/common/fs/file.c"
grep -Fq 'abk_expand_files_needed' "$TMP_DIR/kernel/common/fs/file.c"
grep -Fq 'if (abk_expand_files_needed(fdt, fd)) {' "$TMP_DIR/kernel/common/fs/file.c"
grep -Fq 'close_range() bitmap hotpath graft' "$TMP_DIR/kernel/common/fs/file.c"
grep -Fq 'abk_pick_file_for_close' "$TMP_DIR/kernel/common/fs/file.c"
grep -Fq 'find_next_bit(fdt->open_fds, max_fd + 1, fd)' "$TMP_DIR/kernel/common/fs/file.c"
grep -Fq 'hugepage fault alloc fastpath helper graft' "$TMP_DIR/kernel/common/mm/huge_memory.c"
grep -Fq 'static vm_fault_t abk_thp_fault_prepare(struct vm_fault *vmf,' "$TMP_DIR/kernel/common/mm/huge_memory.c"
grep -Fq 'static struct folio *abk_thp_fault_alloc_folio(struct vm_area_struct *vma,' "$TMP_DIR/kernel/common/mm/huge_memory.c"
grep -Fq 'static vm_fault_t abk_thp_fault_charge_folio(struct folio *folio,' "$TMP_DIR/kernel/common/mm/huge_memory.c"
grep -Fq 'static void abk_map_anon_folio_pmd(struct folio *folio, pgtable_t pgtable,' "$TMP_DIR/kernel/common/mm/huge_memory.c"
grep -Fq 'return abk_thp_fault_fallback(true);' "$TMP_DIR/kernel/common/mm/huge_memory.c"
grep -Fq 'return abk_thp_fault_fallback(false);' "$TMP_DIR/kernel/common/mm/huge_memory.c"
grep -Fq 'ret = abk_thp_fault_prepare(vmf, haddr);' "$TMP_DIR/kernel/common/mm/huge_memory.c"
grep -Fq 'folio = abk_thp_fault_alloc_folio(vma, haddr, &gfp);' "$TMP_DIR/kernel/common/mm/huge_memory.c"
grep -Fq 'return __do_huge_pmd_anonymous_page(vmf, folio, gfp);' "$TMP_DIR/kernel/common/mm/huge_memory.c"
grep -Fq 'hugepage fault alloc fastpath routing helper' "$TMP_DIR/kernel/common/mm/memory.c"
grep -Fq 'return abk_create_anonymous_huge_pmd(vmf);' "$TMP_DIR/kernel/common/mm/memory.c"
grep -Fq '"thp_fault_alloc"' "$TMP_DIR/kernel/common/mm/vmstat.c"
grep -Fq '"thp_fault_fallback"' "$TMP_DIR/kernel/common/mm/vmstat.c"
grep -Fq 'ANDROID_KABI_USE(1, unsigned int' "$TMP_DIR/kernel/common/include/linux/blkdev.h"
grep -Fq 'q->async_depth = BLKDEV_DEFAULT_RQ;' "$TMP_DIR/kernel/common/block/blk-core.c"
grep -Fq 'static void blk_mq_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)' "$TMP_DIR/kernel/common/block/blk-mq.c"
grep -Fq 'preserve relative async_depth across nr_requests resize' "$TMP_DIR/kernel/common/block/blk-mq.c"
grep -Fq 'q->async_depth = set->queue_depth;' "$TMP_DIR/kernel/common/block/blk-mq.c"
grep -Fq 'q->async_depth = q->tag_set->queue_depth;' "$TMP_DIR/kernel/common/block/blk-mq-sched.c"
grep -Fq 'queue_async_depth_store(struct request_queue *q, const char *page, size_t count)' "$TMP_DIR/kernel/common/block/blk-sysfs.c"
grep -Fq 'q->async_depth = min_t(unsigned long, q->nr_requests, nr);' "$TMP_DIR/kernel/common/block/blk-sysfs.c"
grep -Fq 'QUEUE_RW_ENTRY(queue_async_depth, "async_depth");' "$TMP_DIR/kernel/common/block/blk-sysfs.c"
grep -Fq 'static void dd_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)' "$TMP_DIR/kernel/common/block/mq-deadline.c"
grep -Fq 'static int dd_to_word_depth(struct blk_mq_hw_ctx *hctx, unsigned int qdepth)' "$TMP_DIR/kernel/common/block/mq-deadline.c"
grep -Fq 'data->shallow_depth = dd_to_word_depth(data->hctx, dd->async_depth);' "$TMP_DIR/kernel/common/block/mq-deadline.c"
grep -Fq 'static void bfq_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)' "$TMP_DIR/kernel/common/block/bfq-iosched.c"
grep -Fq 'unsigned int depth = bfqd->queue->async_depth;' "$TMP_DIR/kernel/common/block/bfq-iosched.c"
grep -Fq 'q->async_depth = (q->nr_requests * 3) >> 2;' "$TMP_DIR/kernel/common/block/bfq-iosched.c"
grep -Fq 'static void kyber_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)' "$TMP_DIR/kernel/common/block/kyber-iosched.c"
grep -Fq 'kqd->async_depth = q->async_depth;' "$TMP_DIR/kernel/common/block/kyber-iosched.c"
grep -Fq 'q->async_depth = q->nr_requests * KYBER_ASYNC_PERCENT / 100;' "$TMP_DIR/kernel/common/block/kyber-iosched.c"
grep -Fq 'swap table phase2 large folios helper graft' "$TMP_DIR/kernel/common/mm/swap_state.c"
grep -Fq 'static void swap_update_readahead_info(struct folio *folio,' "$TMP_DIR/kernel/common/mm/swap_state.c"
grep -Fq 'static struct folio *__swap_cache_prepare_and_add(swp_entry_t entry,' "$TMP_DIR/kernel/common/mm/swap_state.c"
grep -Fq 'struct folio *swap_cache_alloc_folio(swp_entry_t entry, gfp_t gfp_mask,' "$TMP_DIR/kernel/common/mm/swap_state.c"
grep -Fq 'struct folio *swapin_folio(swp_entry_t entry, struct folio *folio,' "$TMP_DIR/kernel/common/mm/swap_state.c"
grep -Fq 'struct folio *read_swap_cache_async_folio(swp_entry_t entry, gfp_t gfp_mask,' "$TMP_DIR/kernel/common/mm/swap_state.c"
grep -Fq 'folio = read_swap_cache_async_folio(entry, gfp_mask, vma, addr, plug);' "$TMP_DIR/kernel/common/mm/swap_state.c"
grep -Fq 'folio = swap_cache_alloc_folio(swp_entry(swp_type(entry), offset),' "$TMP_DIR/kernel/common/mm/swap_state.c"
grep -Fq 'folio = swap_cache_alloc_folio(entry, gfp_mask, vma, vmf->address,' "$TMP_DIR/kernel/common/mm/swap_state.c"
grep -Fq 'folio_set_readahead(folio);' "$TMP_DIR/kernel/common/mm/swap_state.c"
grep -Fq 'struct folio *swap_cache_alloc_folio(swp_entry_t entry, gfp_t gfp_mask,' "$TMP_DIR/kernel/common/mm/swap.h"
grep -Fq 'struct folio *read_swap_cache_async_folio(swp_entry_t entry, gfp_t gfp_mask,' "$TMP_DIR/kernel/common/mm/swap.h"
grep -Fq 'slab alloc/free hotpath helper graft' "$TMP_DIR/kernel/common/mm/slub.c"
grep -Fq 'static __always_inline void *abk_slab_next_object(struct kmem_cache *s,' "$TMP_DIR/kernel/common/mm/slub.c"
grep -Fq 'void *next_object = abk_slab_next_object(s, object);' "$TMP_DIR/kernel/common/mm/slub.c"
grep -Fq 'struct slab *slab = virt_to_slab(x);' "$TMP_DIR/kernel/common/mm/slub.c"
grep -Fq 'df->slab = slab;' "$TMP_DIR/kernel/common/mm/slub.c"
grep -Fq 'enum nohz_cpu_state {' "$TMP_DIR/kernel/common/include/linux/sched/nohz.h"
grep -Fq 'NOHZ_CPU_STATE_TICK_STOPPED = 1U << 2,' "$TMP_DIR/kernel/common/include/linux/sched/nohz.h"
grep -Fq 'extern unsigned int nohz_cpu_state_flags(int cpu);' "$TMP_DIR/kernel/common/include/linux/sched/nohz.h"
grep -Fq 'extern unsigned long nohz_cpu_idle_calls(int cpu);' "$TMP_DIR/kernel/common/include/linux/sched/nohz.h"
grep -Fq 'static inline bool nohz_cpu_tick_stopped(int cpu)' "$TMP_DIR/kernel/common/include/linux/sched/nohz.h"
grep -Fq 'extern unsigned long tick_nohz_get_idle_calls(void);' "$TMP_DIR/kernel/common/include/linux/tick.h"
grep -Fq 'static inline void tick_nohz_idle_stop_tick_protected(void)' "$TMP_DIR/kernel/common/include/linux/tick.h"
grep -Fq 'nohz state field consistency helpers' "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
grep -Fq 'static unsigned int abk_tick_nohz_state_flags(const struct tick_sched *ts)' "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
grep -Fq 'unsigned int nohz_cpu_state_flags(int cpu)' "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
grep -Fq 'unsigned long nohz_cpu_idle_calls(int cpu)' "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
grep -Fq 'return !!(abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_TICK_STOPPED);' "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
grep -Fq 'if (abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_INIDLE)' "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
grep -Fq 'WARN_ON_ONCE(!(abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_INIDLE));' "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
grep -Fq 'return nohz_cpu_idle_calls(cpu);' "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
grep -Fq 'return nohz_cpu_idle_calls(smp_processor_id());' "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
grep -Fq 'idle_active = !!(nohz_state & NOHZ_CPU_STATE_IDLE_ACTIVE);' "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
grep -Fq 'tick_stopped = !!(nohz_state & NOHZ_CPU_STATE_TICK_STOPPED);' "$TMP_DIR/kernel/common/kernel/time/tick-sched.c"
grep -Fq 'struct file *backing_dev;' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.h"
grep -Fq 'ZRAM_WB' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.h"
grep -Fq 'ZRAM_UNDER_WB' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.h"
grep -Fq 'static ssize_t idle_store(struct device *dev,' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"
grep -Fq 'static ssize_t writeback_store(struct device *dev,' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"
grep -Fq 'static ssize_t writeback_limit_enable_store(struct device *dev,' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"
grep -Fq 'static ssize_t writeback_limit_store(struct device *dev,' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"
grep -Fq 'static ssize_t backing_dev_store(struct device *dev,' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"
grep -Fq 'static DEVICE_ATTR_RW(backing_dev);' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"
grep -Fq 'static DEVICE_ATTR_WO(writeback);' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"
grep -Fq 'static DEVICE_ATTR_RW(compressed_writeback);' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"
grep -Fq '&dev_attr_compressed_writeback.attr,' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"
grep -Fq 'bool compressed_wb;' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.h"
grep -Fq 'static ssize_t compressed_writeback_store(struct device *dev,' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"
grep -Fq 'static ssize_t compressed_writeback_show(struct device *dev,' "$TMP_DIR/kernel/common/drivers/block/zram/zram_drv.c"

FEATURE_PHASE2_DIR="$TMP_DIR/feature-phase2"
KERNEL_ROOT="$TMP_DIR/kernel" \
DEFCONFIG="$TMP_DIR/defconfig" \
CUSTOM_EXTERNAL_MODULE_STAGE=after_patch \
ABK_MODULE_CHILD_ID=feature_porting_backlog \
ABK_MAINLINE_7012_ROOT="$REFERENCE_ROOT" \
ABK_FEATURE_PORTING_PHASE2_REPORT_DIR="$FEATURE_PHASE2_DIR" \
  bash "$MODULE_DIR/setup.sh" >/dev/null

[ -f "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.md" ]
[ -f "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json" ]
grep -Fq 'ABK Feature Porting Backlog Report' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.md"
grep -Fq '"status": "single_large_batch_structured_convergence"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"strategy": "single_large_batch_with_layered_landings"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"phase": "feature_porting_backlog_batch2"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"allowed_statuses": [' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"batch_items": [' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"active_follow_up_items": [' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"planned_batch_layers": {' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"batch_layers": {' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"feature_porting_backlog_batch2"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"tcp_socket_layout_reduction"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"ipv6_tcp_output_path"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"io_uring_cbpf_filters"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"io_uring_non_circular_sq"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"io_uring_large_rx_buffer_zcrx"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"bpf_timer_bpf_wq_lockless"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"status": "blocked_by_layout"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"status": "report_only"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"status": "partial"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json" || \
grep -Fq '"status": "blocked_by_missing_anchor"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"phase": "bounded_anchor_tracking_only"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"status_counts": {' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"excluded_backlog": [' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"AccECN"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"false-sharing \u6d88\u9664"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"paused_children": [' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"network_porting"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"framebuffer_bootlog"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"executable_items": [' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
grep -Fq '"io_uring_cbpf_filters"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
if [ -f "$TMP_DIR/kernel/common/io_uring/register.c" ] && [ -f "$TMP_DIR/kernel/common/io_uring/bpf_filter.c" ]; then
  grep -Fq '"phase": "ring_level_filter_wiring_grafted"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
  grep -Fq '"phase": "sq_array_gate_helper_split_only"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
  grep -Fq '"phase": "preparatory_rx_anchor_bounded"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json" || \
  grep -Fq '"phase": "legacy_io_uring_layout_without_zcrx_surface"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
  grep -Fq '"phase": "helper_side_async_routing_tightened"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json" || \
  grep -Fq '"phase": "legacy_bpf_timer_only"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
  grep -Fq '"executable": true' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
  grep -Fq 'ABK feature_porting_phase2: bounded io_uring cBPF filter activation keeps' "$TMP_DIR/kernel/common/io_uring/io_uring.h"
  grep -Fq 'io_activate_bpf_filters(ctx, &ctx->restrictions);' "$TMP_DIR/kernel/common/io_uring/register.c"
  grep -Fq 'io_activate_bpf_filters(ctx, dst);' "$TMP_DIR/kernel/common/io_uring/io_uring.c"
  grep -Fq 'ABK feature_porting_phase2: non-circular SQ stays bounded to existing' "$TMP_DIR/kernel/common/io_uring/io_uring.c"
  grep -Fq 'if (io_sqring_uses_sq_array(ctx)) {' "$TMP_DIR/kernel/common/io_uring/io_uring.c"
  if [ -f "$TMP_DIR/kernel/common/io_uring/zcrx.c" ]; then
    grep -Fq 'ABK feature_porting_phase2: zcrx stays in preparatory io_uring receive wiring only;' "$TMP_DIR/kernel/common/io_uring/net.c"
  fi
  if rg -n 'bpf_wq_start' "$TMP_DIR/kernel/common/kernel/bpf/helpers.c" >/dev/null; then
    grep -Fq 'ABK feature_porting_phase2: helper-side bpf_timer/bpf_wq lockless follow-up' "$TMP_DIR/kernel/common/kernel/bpf/helpers.c"
    grep -Fq 'if (bpf_async_use_direct_start()) {' "$TMP_DIR/kernel/common/kernel/bpf/helpers.c"
  fi
else
  grep -Fq '"phase": "legacy_io_uring_layout_without_support_module"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
  grep -Fq '"phase": "legacy_io_uring_layout_without_sqarray_gate"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
  grep -Fq '"phase": "legacy_io_uring_layout_without_zcrx_surface"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
  grep -Fq '"phase": "legacy_bpf_timer_only"' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
  grep -Fq '"blocked_by_missing_anchor": true' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json"
fi
! rg -n 'page_pool|netdev|drivers/net' "$FEATURE_PHASE2_DIR/feature_porting_backlog_report.json" >/dev/null

printf 'smoke ok\n'
