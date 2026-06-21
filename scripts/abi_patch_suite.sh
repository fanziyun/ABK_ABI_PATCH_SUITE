#!/usr/bin/env bash

ABK_ABI_PATCH_SUITE_PUBLIC_CHILDREN=(
  display_release_spoof
  abi_bridge
  security_backport
  feature_porting_core
  feature_porting_backlog
)

abk_abi_patch_suite_mainline_repo_url() {
  printf '%s\n' "${ABK_MAINLINE_7012_REPO:-https://github.com/archlinux/linux}"
}

abk_abi_patch_suite_mainline_ref() {
  printf '%s\n' "${ABK_MAINLINE_7012_REF:-v7.0.12-arch1}"
}

abk_abi_patch_suite_clone_mainline_7012() {
  local mainline_repo="$1"
  local mainline_ref="$2"
  local mainline_root="$3"

  if git clone --depth 1 --branch "$mainline_ref" "$mainline_repo" "$mainline_root" 2>/dev/null; then
    return 0
  fi

  rm -rf "$mainline_root"
  mkdir -p "$mainline_root"
  (
    cd "$mainline_root" || exit 1
    git init -q
    git remote add origin "$mainline_repo"
    git config advice.detachedHead false
    git fetch --depth 1 origin "$mainline_ref" >/dev/null 2>&1
    git checkout -q FETCH_HEAD
  ) || return 1
}

abk_abi_patch_suite_mainline_root() {
  local module_parent
  local repo_local_linux

  if [ -n "${ABK_MAINLINE_7012_ROOT:-}" ]; then
    printf '%s\n' "$ABK_MAINLINE_7012_ROOT"
    return 0
  fi

  module_parent="$(cd "$MODULE_DIR/.." && pwd)"
  repo_local_linux="$module_parent/linux"
  if [ -d "$repo_local_linux" ]; then
    printf '%s\n' "$repo_local_linux"
    return 0
  fi

  if [ -n "${GITHUB_WORKSPACE:-}" ]; then
    printf '%s/reference/linux\n' "$GITHUB_WORKSPACE"
    return 0
  fi

  printf '%s\n' "$repo_local_linux"
}

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

abk_abi_patch_suite_prepare_mainline_7012_root() {
  local mainline_root
  local mainline_repo
  local mainline_ref
  local kernelversion

  mainline_root="$(abk_abi_patch_suite_mainline_root)"
  mainline_repo="$(abk_abi_patch_suite_mainline_repo_url)"
  mainline_ref="$(abk_abi_patch_suite_mainline_ref)"

  if [ ! -d "$mainline_root" ]; then
    if [ -n "${GITHUB_WORKSPACE:-}" ]; then
      mkdir -p "$(dirname "$mainline_root")"
      abk_log "prepare 7.0.12 reference tree for ABK CI: $mainline_repo @ $mainline_ref -> $mainline_root" >&2
      abk_abi_patch_suite_clone_mainline_7012 "$mainline_repo" "$mainline_ref" "$mainline_root" \
        || abk_die "failed to clone 7.0.12 reference tree from $mainline_repo @ $mainline_ref into $mainline_root"
    else
      abk_die "7.0.12 reference tree not found: $mainline_root. Set ABK_MAINLINE_7012_ROOT to a checked-out 7.0.12-family linux tree or place one at ./linux relative to the repo root."
    fi
  fi

  abk_require_file "$mainline_root/Makefile"
  kernelversion="$(make -s -C "$mainline_root" kernelversion 2>/dev/null || true)"
  [ -n "$kernelversion" ] || abk_die "unable to resolve kernelversion for mainline tree: $mainline_root"
  case "$kernelversion" in
    7.0.12|7.0.12-*)
      export ABK_MAINLINE_7012_ROOT="$mainline_root"
      printf '%s\n' "$mainline_root"
      return 0
      ;;
    *)
      abk_die "expected 7.0.12-family tree, found $kernelversion at $mainline_root"
      ;;
  esac
}

abk_abi_patch_suite_require_mainline_7012() {
  abk_abi_patch_suite_prepare_mainline_7012_root >/dev/null
}

abk_abi_patch_suite_bridge_report_dir() {
  if [ -n "${ABK_ABI_BRIDGE_REPORT_DIR:-}" ]; then
    printf '%s\n' "$ABK_ABI_BRIDGE_REPORT_DIR"
  else
    printf '%s/abk_abi_patch_suite_reports/abi_bridge\n' "$KERNEL_ROOT"
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

  abk_log "apply child: abi_bridge (bridge preflight + loader bridge)"
  common_dir="$(abk_abi_patch_suite_common_dir)"
  mainline_root="$(abk_abi_patch_suite_prepare_mainline_7012_root)"
  report_dir="$(abk_abi_patch_suite_bridge_report_dir)"

  abk_require_file "$common_dir/kernel/module/version.c"
  abk_require_file "$common_dir/kernel/module/main.c"
  abk_require_file "$common_dir/include/linux/vermagic.h"
  abk_require_file "$common_dir/include/linux/module.h"
  abk_require_file "$DEFCONFIG"
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
  abk_log "ABI bridge report: $report_dir"
  abk_log "ABI bridge loader policy applied ($(abk_abi_patch_suite_bridge_policy))"
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
    printf '%s/abk_abi_patch_suite_reports/security_backport\n' "$KERNEL_ROOT"
  fi
}

abk_abi_patch_suite_feature_porting_report_dir() {
  if [ -n "${ABK_FEATURE_PORTING_REPORT_DIR:-}" ]; then
    printf '%s\n' "$ABK_FEATURE_PORTING_REPORT_DIR"
  else
    printf '%s/abk_abi_patch_suite_reports/feature_porting_core\n' "$KERNEL_ROOT"
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
    printf '%s/abk_abi_patch_suite_reports/feature_porting_backlog\n' "$KERNEL_ROOT"
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

  abk_log "apply child: security_backport"
  common_dir="$(abk_abi_patch_suite_common_dir)"
  output_dir="$(abk_abi_patch_suite_security_report_dir)"
  mkdir -p "$output_dir"
  python3 "$MODULE_DIR/scripts/abk_security_update_backport.py" \
    "$common_dir" \
    "$output_dir"
  abk_log "security backport batch applied and reported: $output_dir"
}

abk_abi_patch_suite_apply_feature_porting() {
  local common_dir
  local output_dir

  abk_log "apply child: feature_porting_core"
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
  abk_log "feature porting core migration applied: $output_dir"
}

abk_abi_patch_suite_apply_feature_porting_phase2() {
  local common_dir
  local output_dir

  abk_log "apply child: feature_porting_backlog"
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
  abk_log "feature porting backlog convergence applied: $output_dir"
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

abk_abi_patch_suite_apply_abi_bridge() {
  abk_abi_patch_suite_apply_dual_abi_kmi_bridge
  abk_abi_patch_suite_apply_abi_fixups
  abk_log "ABI bridge child completed: bridge preflight, loader policy, and loader-adjacent fixups"
}

abk_abi_patch_suite_child_migration_error() {
  local child_id="$1"

  case "$child_id" in
    dual_abi_kmi_bridge|abi_fixups)
      abk_die "ABK module-set child id '$child_id' was reorganized into 'abi_bridge'. Use set:https://github.com/xingguangcuican6666/ABK_ABI_PATCH_SUITE.git#abi_bridge;after_patch"
      ;;
    security_update_backport)
      abk_die "ABK module-set child id '$child_id' was reorganized into 'security_backport'. Use set:https://github.com/xingguangcuican6666/ABK_ABI_PATCH_SUITE.git#security_backport;after_patch"
      ;;
    feature_porting)
      abk_die "ABK module-set child id '$child_id' was reorganized into 'feature_porting_core'. Use set:https://github.com/xingguangcuican6666/ABK_ABI_PATCH_SUITE.git#feature_porting_core;after_patch"
      ;;
    feature_porting_phase2)
      abk_die "ABK module-set child id '$child_id' was reorganized into 'feature_porting_backlog'. Use set:https://github.com/xingguangcuican6666/ABK_ABI_PATCH_SUITE.git#feature_porting_backlog;after_patch"
      ;;
    network_porting|framebuffer_bootlog)
      abk_die "ABK module-set child id '$child_id' is paused and no longer publicly injectable from module.conf. Its implementation remains in-tree, but the default module_set catalog does not expose it."
      ;;
    *)
      abk_die "unsupported ABK module-set child id: $child_id. Supported child ids: ${ABK_ABI_PATCH_SUITE_PUBLIC_CHILDREN[*]}"
      ;;
  esac
}

abk_abi_patch_suite_apply_child() {
  local child_id="$1"

  case "$child_id" in
    display_release_spoof)
      abk_abi_patch_suite_apply_display_release_spoof
      ;;
    abi_bridge)
      abk_abi_patch_suite_apply_abi_bridge
      ;;
    security_backport)
      abk_abi_patch_suite_apply_security_update_backport
      ;;
    feature_porting_core)
      abk_abi_patch_suite_apply_feature_porting
      ;;
    feature_porting_backlog)
      abk_abi_patch_suite_apply_feature_porting_phase2
      ;;
    *)
      abk_abi_patch_suite_child_migration_error "$child_id"
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
