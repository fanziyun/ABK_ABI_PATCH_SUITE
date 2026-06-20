#!/usr/bin/env bash

abk_abi_patch_suite_common_dir() {
  abk_common_dir
}

abk_abi_patch_suite_validate_display_target() {
  local common_dir
  common_dir="$(abk_abi_patch_suite_common_dir)"

  abk_require_file "$common_dir/kernel/sys.c"
  abk_require_file "$common_dir/kernel/utsname_sysctl.c"
  abk_require_file "$common_dir/fs/proc/version.c"
}

abk_abi_patch_suite_patch_boot_image_logging_if_present() {
  local build_utils="$KERNEL_ROOT/build/kernel/build_utils.sh"

  if [ ! -f "$build_utils" ]; then
    return 0
  fi

  python3 "$MODULE_DIR/scripts/abk_boot_image_logging.py" "$build_utils"
}

abk_abi_patch_suite_apply_display_release_spoof() {
  abk_log "apply child: display_release_spoof"
  abk_abi_patch_suite_validate_display_target
  python3 "$MODULE_DIR/scripts/abk_display_spoof.py" "$(abk_abi_patch_suite_common_dir)"
  abk_abi_patch_suite_patch_boot_image_logging_if_present
}

abk_abi_patch_suite_require_mainline_7012() {
  local mainline_root="${ABK_MAINLINE_7012_ROOT:-/run/media/xingguangcuican/Project/testa/linux}"
  local kernelversion

  abk_require_dir "$mainline_root"
  abk_require_file "$mainline_root/Makefile"
  kernelversion="$(make -s -C "$mainline_root" kernelversion 2>/dev/null || true)"
  [ -n "$kernelversion" ] || abk_die "unable to resolve kernelversion for mainline tree: $mainline_root"
  case "$kernelversion" in
    7.0.12|7.0.12-*)
      return 0
      ;;
    *)
      abk_die "expected 7.0.12-family tree, found $kernelversion at $mainline_root"
      ;;
  esac
}

abk_abi_patch_suite_bridge_report_dir() {
  if [ -n "${ABK_ABI_BRIDGE_REPORT_DIR:-}" ]; then
    printf '%s\n' "$ABK_ABI_BRIDGE_REPORT_DIR"
  else
    printf '%s/abk_abi_patch_suite_reports/dual_abi_kmi_bridge\n' "$KERNEL_ROOT"
  fi
}

abk_abi_patch_suite_bridge_policy() {
  printf '%s\n' "${ABK_ABI_BRIDGE_POLICY:-global_7012}"
}

abk_abi_patch_suite_bridge_apply_env() {
  case "$(abk_abi_patch_suite_bridge_policy)" in
    experimental)
      printf '%s\n' "ABK_DUAL_ABI_BRIDGE_CPPFLAGS=-DCONFIG_ABK_DUAL_ABI_BRIDGE -DCONFIG_ABK_DUAL_ABI_BRIDGE_EXPERIMENTAL"
      ;;
    global_7012|allowlist|*)
      printf '%s\n' "ABK_DUAL_ABI_BRIDGE_CPPFLAGS=-DCONFIG_ABK_DUAL_ABI_BRIDGE"
      ;;
  esac
}

abk_abi_patch_suite_apply_dual_abi_kmi_bridge() {
  local common_dir
  local mainline_root
  local report_dir

  abk_log "apply child: dual_abi_kmi_bridge"
  common_dir="$(abk_abi_patch_suite_common_dir)"
  mainline_root="${ABK_MAINLINE_7012_ROOT:-/run/media/xingguangcuican/Project/testa/linux}"
  report_dir="$(abk_abi_patch_suite_bridge_report_dir)"

  abk_require_file "$common_dir/kernel/module/version.c"
  abk_require_file "$common_dir/kernel/module/main.c"
  abk_require_file "$common_dir/include/linux/vermagic.h"
  abk_require_file "$common_dir/include/linux/module.h"
  abk_require_file "$DEFCONFIG"
  abk_abi_patch_suite_require_mainline_7012

  mkdir -p "$report_dir"
  python3 "$MODULE_DIR/scripts/abk_dual_abi_bridge_report.py" \
    "$common_dir" \
    "$DEFCONFIG" \
    "$mainline_root" \
    "$report_dir"
  env "$(abk_abi_patch_suite_bridge_apply_env)" \
    python3 "$MODULE_DIR/scripts/abk_dual_abi_bridge_apply.py" \
      "$common_dir" \
      "$(abk_abi_patch_suite_bridge_policy)"
  abk_log "dual ABI/KMI bridge report: $report_dir"
  abk_log "dual ABI/KMI bridge patches applied ($(abk_abi_patch_suite_bridge_policy))"
}

abk_abi_patch_suite_apply_abi_fixups() {
  local common_dir

  abk_log "apply child: abi_fixups"
  common_dir="$(abk_abi_patch_suite_common_dir)"
  abk_require_file "$common_dir/kernel/module/version.c"
  abk_require_file "$common_dir/kernel/module/internal.h"
  python3 "$MODULE_DIR/scripts/abk_abi_fixups.py" "$common_dir"
  abk_log "ABI fixups compat batch applied"
}

abk_abi_patch_suite_security_report_dir() {
  if [ -n "${ABK_SECURITY_BACKPORT_REPORT_DIR:-}" ]; then
    printf '%s\n' "$ABK_SECURITY_BACKPORT_REPORT_DIR"
  else
    printf '%s/abk_abi_patch_suite_reports/security_update_backport\n' "$KERNEL_ROOT"
  fi
}

abk_abi_patch_suite_feature_porting_report_dir() {
  if [ -n "${ABK_FEATURE_PORTING_REPORT_DIR:-}" ]; then
    printf '%s\n' "$ABK_FEATURE_PORTING_REPORT_DIR"
  else
    printf '%s/abk_abi_patch_suite_reports/feature_porting\n' "$KERNEL_ROOT"
  fi
}

abk_abi_patch_suite_network_porting_report_dir() {
  if [ -n "${ABK_NETWORK_PORTING_REPORT_DIR:-}" ]; then
    printf '%s\n' "$ABK_NETWORK_PORTING_REPORT_DIR"
  else
    printf '%s/abk_abi_patch_suite_reports/network_porting\n' "$KERNEL_ROOT"
  fi
}

abk_abi_patch_suite_feature_porting_phase2_report_dir() {
  if [ -n "${ABK_FEATURE_PORTING_PHASE2_REPORT_DIR:-}" ]; then
    printf '%s\n' "$ABK_FEATURE_PORTING_PHASE2_REPORT_DIR"
  else
    printf '%s/abk_abi_patch_suite_reports/feature_porting_phase2\n' "$KERNEL_ROOT"
  fi
}

abk_abi_patch_suite_framebuffer_bootlog_report_dir() {
  if [ -n "${ABK_FRAMEBUFFER_BOOTLOG_REPORT_DIR:-}" ]; then
    printf '%s\n' "$ABK_FRAMEBUFFER_BOOTLOG_REPORT_DIR"
  else
    printf '%s/abk_abi_patch_suite_reports/framebuffer_bootlog\n' "$KERNEL_ROOT"
  fi
}

abk_abi_patch_suite_apply_security_update_backport() {
  local common_dir
  local output_dir

  abk_log "apply child: security_update_backport"
  common_dir="$(abk_abi_patch_suite_common_dir)"
  output_dir="$(abk_abi_patch_suite_security_report_dir)"
  mkdir -p "$output_dir"
  python3 "$MODULE_DIR/scripts/abk_security_update_backport.py" \
    "$common_dir" \
    "$output_dir"
  abk_log "security update backport batch applied and reported: $output_dir"
}

abk_abi_patch_suite_apply_feature_porting() {
  local common_dir
  local output_dir

  abk_log "apply child: feature_porting"
  common_dir="$(abk_abi_patch_suite_common_dir)"
  output_dir="$(abk_abi_patch_suite_feature_porting_report_dir)"
  abk_abi_patch_suite_require_mainline_7012
  abk_enable_config CONFIG_ZRAM_WRITEBACK
  abk_require_file "$common_dir/include/linux/sched.h"
  abk_require_file "$common_dir/include/linux/tick.h"
  abk_require_file "$common_dir/include/linux/sched/nohz.h"
  abk_require_file "$common_dir/kernel/sched/core.c"
  abk_require_file "$common_dir/kernel/sched/fair.c"
  abk_require_file "$common_dir/kernel/sched/idle.c"
  abk_require_file "$common_dir/kernel/sched/sched.h"
  abk_require_file "$common_dir/kernel/pid.c"
  abk_require_file "$common_dir/kernel/fork.c"
  abk_require_file "$common_dir/kernel/time/tick-sched.h"
  abk_require_file "$common_dir/kernel/time/tick-sched.c"
  abk_require_file "$common_dir/fs/file.c"
  abk_require_file "$common_dir/block/blk-mq.c"
  abk_require_file "$common_dir/block/blk-sysfs.c"
  abk_require_file "$common_dir/block/mq-deadline.c"
  abk_require_file "$common_dir/block/bfq-iosched.c"
  abk_require_file "$common_dir/block/kyber-iosched.c"
  abk_require_file "$common_dir/mm/slab.h"
  abk_require_file "$common_dir/mm/slub.c"
  abk_require_file "$common_dir/mm/slab_common.c"
  abk_require_file "$common_dir/mm/swap.h"
  abk_require_file "$common_dir/mm/swap_state.c"
  abk_require_file "$common_dir/mm/shmem.c"
  abk_require_file "$common_dir/mm/memory.c"
  abk_require_file "$common_dir/mm/huge_memory.c"
  abk_require_file "$common_dir/mm/vmstat.c"
  abk_require_file "$common_dir/drivers/block/zram/zram_drv.c"
  abk_require_file "$common_dir/drivers/block/zram/zram_drv.h"
  mkdir -p "$output_dir"
  python3 "$MODULE_DIR/scripts/abk_feature_porting.py" \
    "$common_dir" \
    "$output_dir"
  abk_log "feature porting runtime-state migration applied: $output_dir"
}

abk_abi_patch_suite_apply_feature_porting_phase2() {
  local common_dir
  local output_dir

  abk_log "apply child: feature_porting_phase2"
  common_dir="$(abk_abi_patch_suite_common_dir)"
  output_dir="$(abk_abi_patch_suite_feature_porting_phase2_report_dir)"
  abk_abi_patch_suite_require_mainline_7012
  abk_require_file "$common_dir/io_uring/io_uring.c"
  abk_require_file "$common_dir/io_uring/kbuf.c"
  abk_require_file "$common_dir/io_uring/net.c"
  abk_require_file "$common_dir/io_uring/sqpoll.c"
  abk_require_file "$common_dir/kernel/bpf/btf.c"
  abk_require_file "$common_dir/kernel/bpf/helpers.c"
  abk_require_file "$common_dir/kernel/bpf/syscall.c"
  abk_require_file "$common_dir/include/linux/btf.h"
  abk_require_file "$common_dir/include/linux/filter.h"
  abk_require_file "$common_dir/include/uapi/linux/bpf.h"
  abk_require_file "$common_dir/include/uapi/linux/filter.h"
  abk_require_file "$common_dir/include/net/sock.h"
  abk_require_file "$common_dir/include/net/tcp.h"
  abk_require_file "$common_dir/net/ipv4/tcp_output.c"
  abk_require_file "$common_dir/net/ipv6/ip6_output.c"
  abk_require_file "$common_dir/net/ipv6/inet6_connection_sock.c"
  mkdir -p "$output_dir"
  python3 "$MODULE_DIR/scripts/abk_feature_porting_phase2.py" \
    "$common_dir" \
    "$output_dir"
  abk_log "feature_porting_phase2 single-large-batch convergence applied: $output_dir"
}

abk_abi_patch_suite_apply_network_porting() {
  local common_dir
  local output_dir

  abk_log "apply child: network_porting"
  common_dir="$(abk_abi_patch_suite_common_dir)"
  output_dir="$(abk_abi_patch_suite_network_porting_report_dir)"
  abk_abi_patch_suite_require_mainline_7012
  abk_require_file "$common_dir/include/net/tcp.h"
  abk_require_file "$common_dir/include/net/sock.h"
  abk_require_file "$common_dir/include/net/ipv6.h"
  abk_require_file "$common_dir/include/net/ip6_route.h"
  abk_require_file "$common_dir/include/net/netns/ipv4.h"
  abk_require_file "$common_dir/include/uapi/linux/net_tstamp.h"
  abk_require_file "$common_dir/net/core/sock.c"
  abk_require_file "$common_dir/net/socket.c"
  abk_require_file "$common_dir/net/core/skbuff.c"
  abk_require_file "$common_dir/net/ipv4/tcp.c"
  abk_require_file "$common_dir/net/ipv4/tcp_output.c"
  abk_require_file "$common_dir/net/ipv4/tcp_input.c"
  abk_require_file "$common_dir/net/ipv4/tcp_minisocks.c"
  abk_require_file "$common_dir/net/ipv4/tcp_ipv4.c"
  abk_require_file "$common_dir/net/ipv4/sysctl_net_ipv4.c"
  abk_require_file "$common_dir/net/ipv6/ip6_output.c"
  abk_require_file "$common_dir/net/ipv6/inet6_connection_sock.c"
  abk_abi_patch_suite_patch_boot_image_logging_if_present
  mkdir -p "$output_dir"
  python3 "$MODULE_DIR/scripts/abk_network_porting.py" \
    "$common_dir" \
    "$output_dir"
  abk_log "network porting first-pass graft applied: $output_dir"
}

abk_abi_patch_suite_apply_framebuffer_bootlog() {
  local common_dir
  local output_dir
  local build_utils

  abk_log "apply child: framebuffer_bootlog"
  common_dir="$(abk_abi_patch_suite_common_dir)"
  output_dir="$(abk_abi_patch_suite_framebuffer_bootlog_report_dir)"
  build_utils="$KERNEL_ROOT/build/kernel/build_utils.sh"

  abk_require_file "$DEFCONFIG"
  abk_require_file "$build_utils"
  abk_abi_patch_suite_patch_boot_image_logging_if_present
  mkdir -p "$output_dir"
  python3 "$MODULE_DIR/scripts/abk_framebuffer_bootlog.py" \
    "$common_dir" \
    "$DEFCONFIG" \
    "$build_utils" \
    "$output_dir"
  abk_log "framebuffer bootlog baseline applied: $output_dir"
}

abk_abi_patch_suite_apply_child() {
  local child_id="$1"

  case "$child_id" in
    display_release_spoof)
      abk_abi_patch_suite_apply_display_release_spoof
      ;;
    dual_abi_kmi_bridge)
      abk_abi_patch_suite_apply_dual_abi_kmi_bridge
      ;;
    abi_fixups)
      abk_abi_patch_suite_apply_abi_fixups
      ;;
    security_update_backport)
      abk_abi_patch_suite_apply_security_update_backport
      ;;
    feature_porting)
      abk_abi_patch_suite_apply_feature_porting
      ;;
    feature_porting_phase2)
      abk_abi_patch_suite_apply_feature_porting_phase2
      ;;
    network_porting)
      abk_abi_patch_suite_apply_network_porting
      ;;
    framebuffer_bootlog)
      abk_abi_patch_suite_apply_framebuffer_bootlog
      ;;
    *)
      abk_die "unsupported ABK module-set child id: $child_id"
      ;;
  esac
}

abk_abi_patch_suite_apply_selected() {
  local child_id="${ABK_MODULE_CHILD_ID:-}"

  if [ -n "$child_id" ]; then
    abk_abi_patch_suite_apply_child "$child_id"
    return 0
  fi

  abk_log "no ABK_MODULE_CHILD_ID provided; apply default ABI Patch Suite children"
  abk_abi_patch_suite_apply_child "display_release_spoof"
}
