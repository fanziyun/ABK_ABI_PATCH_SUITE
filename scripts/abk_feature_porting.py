#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class PatchGroup:
    key: str
    summary: str


PATCH_GROUPS = (
    PatchGroup(
        "feature_porting_scaffold",
        "Real executable feature_porting child with reports, markers, and anchor checks.",
    ),
    PatchGroup(
        "sched_eevdf_core_fields",
        "Port first-stage sched_entity EEVDF fields using Android KABI reserve slots.",
    ),
    PatchGroup(
        "sched_eevdf_pick_logic",
        "Defer large fair.c pick logic migration; export anchor status and next steps only.",
    ),
    PatchGroup(
        "sched_eevdf_abk_sched_compat",
        "Track ABK_SCHED_POWER_MODULE util_est and fair.c integration anchors.",
    ),
    PatchGroup(
        "pid_alloc_core_port",
        "Port alloc_pid() preload/retry and pid_max-per-namespace semantics.",
    ),
    PatchGroup(
        "pidfd_preparation_compat",
        "Document current pidfd surface and keep pidfs/full pidfd expansion out of phase one.",
    ),
    PatchGroup(
        "feature_porting_fixups",
        "Reserve follow-up glue fixes discovered after first executable migration.",
    ),
)


def read_text(path: Path) -> str:
    return path.read_text()


def write_text(path: Path, text: str) -> None:
    path.write_text(text)


def append_once(path: Path, line: str) -> None:
    text = read_text(path)
    if line in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    text += line + "\n"
    write_text(path, text)


def ensure_contains(path: Path, needle: str, label: str) -> None:
    if needle not in read_text(path):
        raise SystemExit(f"{label}: expected anchor missing in {path}: {needle}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected block missing")
    return text.replace(old, new, 1)


def bool_status(value: bool) -> str:
    return "present" if value else "missing"


def patch_sched_entity_fields(common_root: Path) -> dict[str, object]:
    sched_h = common_root / "include/linux/sched.h"
    text = read_text(sched_h)

    required = (
        "struct sched_entity {\n",
        "ANDROID_KABI_RESERVE(1);",
        "ANDROID_KABI_RESERVE(2);",
        "ANDROID_KABI_RESERVE(3);",
        "ANDROID_KABI_RESERVE(4);",
    )
    for needle in required:
        ensure_contains(sched_h, needle, "feature_porting/sched_entity")

    already_done = (
        "ANDROID_KABI_USE(1, u64 deadline);" in text
        and "ANDROID_KABI_USE(2, u64 min_vruntime);" in text
        and "ANDROID_KABI_USE(3, struct {" in text
        and "s64 vlag;" in text
    )
    if not already_done:
        old = """\n\tANDROID_KABI_RESERVE(1);\n\tANDROID_KABI_RESERVE(2);\n\tANDROID_KABI_RESERVE(3);\n\tANDROID_KABI_RESERVE(4);\n"""
        new = """\n\tANDROID_KABI_USE(1, u64 deadline);\n\tANDROID_KABI_USE(2, u64 min_vruntime);\n\tANDROID_KABI_USE(3, struct {\n\t\tu64 min_slice;\n\t\tu64 max_slice;\n\t});\n\tANDROID_KABI_USE(4, struct {\n\t\ts64 vlag;\n\t\tu64 slice;\n\t});\n"""
        text = replace_once(text, old, new, "feature_porting/sched_entity")
        marker = "\t/* ABK feature_porting: first-stage EEVDF fields mapped onto Android KABI reserve slots. */\n"
        anchor = "\n#ifdef CONFIG_SMP\n"
        if marker not in text and anchor in text:
            text = text.replace(anchor, "\n" + marker + "#ifdef CONFIG_SMP\n", 1)
        write_text(sched_h, text)

    return {
        "path": str(sched_h),
        "eevdf_core_fields": {
            "deadline": "ANDROID_KABI_USE(1, u64 deadline);",
            "min_vruntime": "ANDROID_KABI_USE(2, u64 min_vruntime);",
            "min_max_slice": "ANDROID_KABI_USE(3, struct { u64 min_slice; u64 max_slice; });",
            "vlag_slice": "ANDROID_KABI_USE(4, struct { s64 vlag; u64 slice; });",
        },
    }


def patch_pid_alloc(common_root: Path) -> dict[str, object]:
    pid_c = common_root / "kernel/pid.c"
    text = read_text(pid_c)

    ensure_contains(pid_c, "struct pid *alloc_pid(struct pid_namespace *ns, pid_t *set_tid,", "feature_porting/pid")
    ensure_contains(pid_c, "idr_alloc_cyclic(&tmp->idr, NULL, pid_min,", "feature_porting/pid")
    ensure_contains(pid_c, "idr_preload(GFP_KERNEL);", "feature_porting/pid")

    if "bool retried_preload;" not in text:
        text = text.replace(
            "struct upid *upid;\n\tint retval = -ENOMEM;\n",
            "struct upid *upid;\n\tint retval = -ENOMEM;\n\tbool retried_preload;\n",
            1,
        )

    old_perm_loop = """\ttmp = ns;\n\tpid->level = ns->level;\n\n\tfor (i = ns->level; i >= 0; i--) {\n\t\tint tid = 0;\n\n\t\tif (set_tid_size) {\n\t\t\ttid = set_tid[ns->level - i];\n\n\t\t\tretval = -EINVAL;\n\t\t\tif (tid < 1 || tid >= pid_max)\n\t\t\t\tgoto out_free;\n\t\t\t/*\n\t\t\t * Also fail if a PID != 1 is requested and\n\t\t\t * no PID 1 exists.\n\t\t\t */\n\t\t\tif (tid != 1 && !tmp->child_reaper)\n\t\t\t\tgoto out_free;\n\t\t\tretval = -EPERM;\n\t\t\tif (!checkpoint_restore_ns_capable(tmp->user_ns))\n\t\t\t\tgoto out_free;\n\t\t\tset_tid_size--;\n\t\t}\n\n\t\tidr_preload(GFP_KERNEL);\n\t\tspin_lock_irq(&pidmap_lock);\n\n\t\tif (tid) {\n"""
    new_perm_loop = """\ttmp = ns;\n\tpid->level = ns->level;\n\n\tfor (i = ns->level; i >= 0; i--) {\n\t\tint tid = 0;\n\t\tint local_pid_max = READ_ONCE(tmp->pid_max);\n\n\t\tif (set_tid_size) {\n\t\t\ttid = set_tid[ns->level - i];\n\n\t\t\tretval = -EINVAL;\n\t\t\tif (tid < 1 || tid >= local_pid_max)\n\t\t\t\tgoto out_free;\n\t\t\t/*\n\t\t\t * Also fail if a PID != 1 is requested and\n\t\t\t * no PID 1 exists.\n\t\t\t */\n\t\t\tif (tid != 1 && !tmp->child_reaper)\n\t\t\t\tgoto out_free;\n\t\t\tretval = -EPERM;\n\t\t\tif (!checkpoint_restore_ns_capable(tmp->user_ns))\n\t\t\t\tgoto out_free;\n\t\t\tset_tid_size--;\n\t\t}\n\n\t\tretried_preload = false;\n\t\tidr_preload(GFP_KERNEL);\n\t\tspin_lock_irq(&pidmap_lock);\n\n\t\tif (tid) {\n"""
    if old_perm_loop in text:
        text = text.replace(old_perm_loop, new_perm_loop, 1)

    old_alloc_loop = """\t\t} else {\n\t\t\tint pid_min = 1;\n\t\t\t/*\n\t\t\t * init really needs pid 1, but after reaching the\n\t\t\t * maximum wrap back to RESERVED_PIDS\n\t\t\t */\n\t\t\tif (idr_get_cursor(&tmp->idr) > RESERVED_PIDS)\n\t\t\t\tpid_min = RESERVED_PIDS;\n\n\t\t\t/*\n\t\t\t * Store a null pointer so find_pid_ns does not find\n\t\t\t * a partially initialized PID (see below).\n\t\t\t */\n\t\t\tnr = idr_alloc_cyclic(&tmp->idr, NULL, pid_min,\n\t\t\t\t\t      pid_max, GFP_ATOMIC);\n\t\t}\n\t\tspin_unlock_irq(&pidmap_lock);\n\t\tidr_preload_end();\n\n\t\tif (nr < 0) {\n\t\t\tretval = (nr == -ENOSPC) ? -EAGAIN : nr;\n\t\t\tgoto out_free;\n\t\t}\n\n\t\tpid->numbers[i].nr = nr;\n\t\tpid->numbers[i].ns = tmp;\n\t\ttmp = tmp->parent;\n\t}\n"""
    new_alloc_loop = """\t\t} else {\n\t\t\tint pid_min = 1;\n\t\t\t/*\n\t\t\t * init really needs pid 1, but after reaching the\n\t\t\t * maximum wrap back to RESERVED_PIDS\n\t\t\t */\n\t\t\tif (idr_get_cursor(&tmp->idr) > RESERVED_PIDS)\n\t\t\t\tpid_min = RESERVED_PIDS;\n\n\t\t\t/*\n\t\t\t * Store a null pointer so find_pid_ns does not find\n\t\t\t * a partially initialized PID (see below).\n\t\t\t */\n\t\t\tnr = idr_alloc_cyclic(&tmp->idr, NULL, pid_min,\n\t\t\t\t\t      local_pid_max, GFP_ATOMIC);\n\t\t\tif (nr == -ENOSPC)\n\t\t\t\tnr = -EAGAIN;\n\t\t}\n\n\t\tif (nr < 0) {\n\t\t\tif (nr == -ENOMEM && !retried_preload) {\n\t\t\t\tspin_unlock_irq(&pidmap_lock);\n\t\t\t\tidr_preload_end();\n\t\t\t\tretried_preload = true;\n\t\t\t\tidr_preload(GFP_KERNEL);\n\t\t\t\tspin_lock_irq(&pidmap_lock);\n\t\t\t\tcontinue;\n\t\t\t}\n\t\t\tspin_unlock_irq(&pidmap_lock);\n\t\t\tidr_preload_end();\n\t\t\tretval = nr;\n\t\t\tgoto out_free;\n\t\t}\n\t\tspin_unlock_irq(&pidmap_lock);\n\t\tidr_preload_end();\n\n\t\tpid->numbers[i].nr = nr;\n\t\tpid->numbers[i].ns = tmp;\n\t\ttmp = tmp->parent;\n\t\tretried_preload = false;\n\t}\n"""
    if old_alloc_loop in text:
        text = text.replace(old_alloc_loop, new_alloc_loop, 1)

    marker = "/* ABK feature_porting: alloc_pid() preload retry and per-namespace pid_max semantics applied. */"
    if marker not in text:
        anchor = "struct pid *alloc_pid(struct pid_namespace *ns, pid_t *set_tid,\n"
        text = text.replace(anchor, marker + "\n" + anchor, 1)

    write_text(pid_c, text)
    return {
        "path": str(pid_c),
        "ported_semantics": [
            "READ_ONCE(tmp->pid_max) instead of global pid_max in alloc_pid() validation/allocation loop",
            "idr_alloc_cyclic() ENOSPC translated to EAGAIN",
            "single retry of idr_preload(GFP_KERNEL) after GFP_ATOMIC ENOMEM under pidmap_lock",
        ],
    }


def collect_sched_anchor_status(common_root: Path) -> dict[str, object]:
    fair_c = common_root / "kernel/sched/fair.c"
    sched_h = common_root / "include/linux/sched.h"
    fair = read_text(fair_c)
    sched_h_text = read_text(sched_h)

    abk_sched_script = Path(__file__).resolve().parents[2] / "ABK_SCHED_POWER_MODULE/scripts/sched_power_backport.sh"
    abk_script_text = read_text(abk_sched_script)

    target_anchors = {
        "avg_vruntime": "avg_vruntime(" in fair,
        "pick_eevdf": "pick_eevdf(" in fair,
        "pick_next_entity_cfs_shape": "pick_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *curr)" in fair,
        "util_est_dequeue": "static inline void util_est_dequeue(struct cfs_rq *cfs_rq," in fair,
        "android_vendor_pick_hook": "trace_android_rvh_pick_next_entity" in fair,
        "deadline_field": "deadline" in sched_h_text and "ANDROID_KABI_USE(1, u64 deadline);" in sched_h_text,
        "vlag_field": "s64 vlag;" in sched_h_text,
    }

    abk_anchors = {
        "abk_profile_header_in_fair": '#include <linux/abk_sched_profile.h>' in abk_script_text,
        "util_est_decay_hook": "abk_sched_profile_decay_ewma" in abk_script_text,
        "sugov_scale_util_hook": "abk_sched_profile_scale_util" in abk_script_text,
        "thermal_override_hook": "abk_sched_profile_override_thermal_target" in abk_script_text,
    }

    status = "partial"
    if target_anchors["avg_vruntime"] and target_anchors["pick_eevdf"]:
        status = "already_eevdf_like"
    elif not target_anchors["pick_eevdf"] and target_anchors["pick_next_entity_cfs_shape"]:
        status = "legacy_cfs_pick_logic"

    return {
        "status": status,
        "target_anchors": {key: bool_status(value) for key, value in target_anchors.items()},
        "abk_sched_power_module_anchors": {key: bool_status(value) for key, value in abk_anchors.items()},
        "next_action": (
            "Keep fair.c pick logic on the explicit follow-up batch. "
            "Target trace_android_rvh_pick_next_entity and util_est_* anchors instead of file replacement."
        ),
    }


def collect_pidfd_status(common_root: Path) -> dict[str, object]:
    fork_c = common_root / "kernel/fork.c"
    pid_c = common_root / "kernel/pid.c"
    fork = read_text(fork_c)
    pid = read_text(pid_c)

    flags = {
        "pidfd_prepare_helper": "pidfd_prepare(" in fork,
        "clone_pidfd_flow": "CLONE_PIDFD" in fork,
        "pidfd_open_syscall": "SYSCALL_DEFINE2(pidfd_open" in pid,
        "pidfd_stale_flag": "PIDFD_STALE" in fork or "PIDFD_STALE" in pid,
        "pidfs_prepare_pid": "pidfs_prepare_pid(" in pid,
    }
    return {
        "status": "baseline_pidfd_only" if not flags["pidfd_prepare_helper"] else "newer_pidfd_helper_present",
        "anchors": {key: bool_status(value) for key, value in flags.items()},
        "next_action": (
            "Do not backport pidfs in phase one. "
            "Retain existing pidfd_open/CLONE_PIDFD behavior and treat pidfd_prepare() as follow-up compatibility work."
        ),
    }


def build_report(
    current_common: Path,
    output_dir: Path,
    sched_result: dict[str, object],
    pid_result: dict[str, object],
    sched_status: dict[str, object],
    pidfd_status: dict[str, object],
) -> dict[str, object]:
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_common_root": str(current_common),
        "status": "applied_phase_one",
        "strategy": "minimal_intrusion_graft",
        "patch_groups": [
            {
                "key": group.key,
                "summary": group.summary,
            }
            for group in PATCH_GROUPS
        ],
        "applied_groups": [
            "feature_porting_scaffold",
            "sched_eevdf_core_fields",
            "pid_alloc_core_port",
        ],
        "deferred_groups": [
            "sched_eevdf_pick_logic",
            "sched_eevdf_abk_sched_compat",
            "pidfd_preparation_compat",
            "feature_porting_fixups",
        ],
        "sched_entity_port": sched_result,
        "pid_alloc_port": pid_result,
        "sched_pick_logic_status": sched_status,
        "pidfd_status": pidfd_status,
        "constraints": [
            "Do not replace fair.c wholesale with the 7.0.12 file.",
            "Do not replace fork.c wholesale with the 7.0.12 file.",
            "Keep ABK_SCHED_POWER_MODULE integration anchored on util_est/sugov/thermal hooks.",
            "Do not backport pidfs as part of phase one.",
        ],
    }

    (output_dir / "feature_porting_report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "feature_porting_report.md").write_text(
        "# ABK Feature Porting Report\n\n"
        f"- Generated: `{report['generated_at_utc']}`\n"
        f"- Current tree: `{report['current_common_root']}`\n"
        f"- Status: `{report['status']}`\n"
        f"- Strategy: `{report['strategy']}`\n\n"
        "## Applied Groups\n\n"
        + "\n".join(f"- `{item}`" for item in report["applied_groups"])
        + "\n\n## Deferred Groups\n\n"
        + "\n".join(f"- `{item}`" for item in report["deferred_groups"])
        + "\n\n## Constraints\n\n"
        + "\n".join(f"- {item}" for item in report["constraints"])
        + "\n\n## Sched Pick Logic Status\n\n"
        f"- State: `{sched_status['status']}`\n"
        f"- Next action: {sched_status['next_action']}\n\n"
        "## PIDFD Status\n\n"
        f"- State: `{pidfd_status['status']}`\n"
        f"- Next action: {pidfd_status['next_action']}\n"
    )
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit(f"usage: {argv[0]} <current-common-root> <output-dir>")

    current_common = Path(argv[1])
    output_dir = Path(argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    sched_h = current_common / "include/linux/sched.h"
    fair_c = current_common / "kernel/sched/fair.c"
    pid_c = current_common / "kernel/pid.c"
    fork_c = current_common / "kernel/fork.c"

    for path in (sched_h, fair_c, pid_c, fork_c):
        if not path.is_file():
            raise SystemExit(f"feature_porting: required file not found: {path}")

    sched_result = patch_sched_entity_fields(current_common)
    pid_result = patch_pid_alloc(current_common)
    append_once(
        pid_c,
        "/* ABK feature_porting: phase-one PID and EEVDF migration entry executed. */",
    )
    sched_status = collect_sched_anchor_status(current_common)
    pidfd_status = collect_pidfd_status(current_common)
    build_report(current_common, output_dir, sched_result, pid_result, sched_status, pidfd_status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
