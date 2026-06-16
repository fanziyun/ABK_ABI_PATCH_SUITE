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

abk_abi_patch_suite_apply_display_release_spoof() {
  abk_log "apply child: display_release_spoof"
  abk_abi_patch_suite_validate_display_target
  python3 "$MODULE_DIR/scripts/abk_display_spoof.py" "$(abk_abi_patch_suite_common_dir)"
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
  printf '%s\n' "${ABK_ABI_BRIDGE_POLICY:-allowlist}"
}

abk_abi_patch_suite_bridge_apply_env() {
  case "$(abk_abi_patch_suite_bridge_policy)" in
    experimental)
      printf '%s\n' "ABK_DUAL_ABI_BRIDGE_CPPFLAGS=-DCONFIG_ABK_DUAL_ABI_BRIDGE -DCONFIG_ABK_DUAL_ABI_BRIDGE_EXPERIMENTAL"
      ;;
    allowlist|*)
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
      "$common_dir"
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
  abk_log "ABI fixups baseline applied"
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
  abk_log "security update queue exported: $output_dir"
}

abk_abi_patch_suite_apply_feature_porting() {
  local common_dir
  local output_dir

  abk_log "apply child: feature_porting"
  common_dir="$(abk_abi_patch_suite_common_dir)"
  output_dir="$(abk_abi_patch_suite_feature_porting_report_dir)"
  abk_abi_patch_suite_require_mainline_7012
  abk_require_file "$common_dir/include/linux/sched.h"
  abk_require_file "$common_dir/kernel/sched/fair.c"
  abk_require_file "$common_dir/kernel/pid.c"
  abk_require_file "$common_dir/kernel/fork.c"
  mkdir -p "$output_dir"
  python3 "$MODULE_DIR/scripts/abk_feature_porting.py" \
    "$common_dir" \
    "$output_dir"
  abk_log "feature porting phase-one migration applied: $output_dir"
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
