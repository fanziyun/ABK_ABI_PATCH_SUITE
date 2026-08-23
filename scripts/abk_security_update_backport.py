#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ABK_BACKUP_SUFFIX = ".abk-orig"

SOURCE_BASE = "7.0.12-first"
ALLOWED_APPLY_MODES = {
    "scoped helper graft",
    "in-function fixup",
    "guard tightening",
}
ALLOWED_STATUSES = {
    "applied",
    "partial",
    "blocked_by_bridge",
    "blocked_by_fixups",
    "missing_anchor",
}


@dataclass(frozen=True)
class Candidate:
    batch: str
    id: str
    summary: str
    target_paths: tuple[str, ...]
    anchor_preconditions: tuple[str, ...]
    apply_mode: str
    risk_class: str
    blocked_by: str | None


def read_text(path: Path) -> str:
    return path.read_text()


def write_text(path: Path, text: str) -> None:
    # Snapshot the original bytes once, so a run that hard-fails part-way can be
    # rolled back with abk_rollback.sh. Skip it when the file does not exist yet:
    # report output is created here, and there is nothing to restore.
    if path.exists():
        backup = path.with_suffix(path.suffix + ABK_BACKUP_SUFFIX)
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
    path.write_text(text)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise ValueError(f"{label}: expected block missing")
    return text.replace(old, new, 1)


def append_once(text: str, block: str) -> str:
    if block in text:
        return text
    if not text.endswith("\n"):
        text += "\n"
    return text + block


def bool_status(value: bool) -> str:
    return "present" if value else "missing"


def ensure_candidate_shape(candidate: Candidate) -> None:
    if candidate.apply_mode not in ALLOWED_APPLY_MODES:
        raise SystemExit(f"{candidate.id}: unsupported apply_mode {candidate.apply_mode}")
    if candidate.blocked_by not in {None, "bridge", "fixups"}:
        raise SystemExit(f"{candidate.id}: unsupported blocked_by {candidate.blocked_by}")


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        batch="sec_lowrisk_batch_001",
        id="sysctl_modules_disabled_minmax_guard",
        summary="Keep modules_disabled write-once at the proc/sysctl boundary via min/max enforcement.",
        target_paths=("kernel/sysctl.c",),
        anchor_preconditions=(
            'kernel/sysctl.c::\t\t.procname\t= "modules_disabled",',
            "kernel/sysctl.c::/* only handle a transition from default \"0\" to \"1\" */",
        ),
        apply_mode="guard tightening",
        risk_class="low",
        blocked_by=None,
    ),
    Candidate(
        batch="sec_lowrisk_batch_001",
        id="blk_sync_queue_timer_delete_sync",
        summary="Tighten block queue timeout teardown to the synchronized timer-delete helper used by the 7.0.12 tree.",
        target_paths=("block/blk-core.c",),
        anchor_preconditions=(
            "void blk_sync_queue(struct request_queue *q)\n{",
            "del_timer_sync(&q->timeout);",
        ),
        apply_mode="guard tightening",
        risk_class="low",
        blocked_by="fixups",
    ),
    Candidate(
        batch="sec_lowrisk_batch_002",
        id="pid_deferred_free_batching",
        summary="Defer final pid freeing outside tasklist_lock while changing SID/PGID references.",
        target_paths=("include/linux/pid.h", "kernel/pid.c", "kernel/sys.c"),
        anchor_preconditions=(
            "include/linux/pid.h::extern void attach_pid(struct task_struct *task, enum pid_type);",
            "kernel/pid.c::struct pid *alloc_pid(struct pid_namespace *ns,",
            "kernel/sys.c::SYSCALL_DEFINE2(setpgid, pid_t, pid, pid_t, pgid)",
        ),
        apply_mode="in-function fixup",
        risk_class="low",
        blocked_by="fixups",
    ),
    Candidate(
        batch="sec_lowrisk_batch_002",
        id="elevator_sysfs_dying_guard",
        summary="Block elevator sysfs show/store callbacks once the queue is tearing down.",
        target_paths=("block/elevator.c",),
        anchor_preconditions=(
            "block/elevator.c::int elv_register_queue(struct request_queue *q, bool uevent)",
            "block/elevator.c::error = e->type ? entry->show(e, page) : -ENOENT;",
            "block/elevator.c::error = e->type ? entry->store(e, page, length) : -ENOENT;",
        ),
        apply_mode="guard tightening",
        risk_class="low",
        blocked_by="fixups",
    ),
    Candidate(
        batch="sec_lowrisk_batch_002",
        id="module_extended_version_checks",
        summary="Adopt extended module version metadata checks for loader-side symbol validation.",
        target_paths=("kernel/module/version.c", "kernel/module/main.c"),
        anchor_preconditions=(
            "kernel/module/version.c::int check_version(const struct load_info *info,",
            "kernel/module/version.c::bool check_modstruct_version(const struct load_info *info, struct module *mod)",
        ),
        apply_mode="scoped helper graft",
        risk_class="low",
        blocked_by="bridge",
    ),
)


def apply_sysctl_modules_disabled_minmax_guard(common_root: Path) -> dict[str, object]:
    path = common_root / "kernel/sysctl.c"
    text = read_text(path)
    marker = "/* ABK security_update_backport: write-once modules_disabled guard. */"
    guarded = """\t{\n\t\t.procname\t= \"modules_disabled\",\n\t\t.data\t\t= &modules_disabled,\n\t\t.maxlen\t\t= sizeof(int),\n\t\t.mode\t\t= 0644,\n\t\t/* only handle a transition from default \"0\" to \"1\" */\n\t\t.proc_handler\t= proc_dointvec_minmax,\n\t\t.extra1\t\t= SYSCTL_ONE,\n\t\t.extra2\t\t= SYSCTL_ONE,\n\t},\n"""
    new = """\t{\n\t\t.procname\t= \"modules_disabled\",\n\t\t.data\t\t= &modules_disabled,\n\t\t.maxlen\t\t= sizeof(int),\n\t\t.mode\t\t= 0644,\n\t\t/* only handle a transition from default \"0\" to \"1\" */\n\t\t/* ABK security_update_backport: write-once modules_disabled guard. */\n\t\t.proc_handler\t= proc_dointvec_minmax,\n\t\t.extra1\t\t= SYSCTL_ONE,\n\t\t.extra2\t\t= SYSCTL_ONE,\n\t},\n"""

    if marker in text:
        return {
            "mode": "already_present",
            "path": str(path),
            "target_anchors": {
                "marker": "present",
                "proc_dointvec_minmax": bool_status("proc_dointvec_minmax" in text),
                "sysctl_one_min": bool_status(".extra1\t\t= SYSCTL_ONE," in text),
                "sysctl_one_max": bool_status(".extra2\t\t= SYSCTL_ONE," in text),
            },
        }

    text = replace_once(text, guarded, new, "security_update_backport/modules_disabled_guarded")
    write_text(path, text)
    return {
        "mode": "patched",
        "path": str(path),
        "target_anchors": {
            "marker": "present",
            "proc_dointvec_minmax": "present",
            "sysctl_one_min": "present",
            "sysctl_one_max": "present",
        },
    }


def apply_blk_sync_queue_timer_delete_sync(common_root: Path) -> dict[str, object]:
    path = common_root / "block/blk-core.c"
    text = read_text(path)
    marker = "/* ABK security_update_backport: synchronized queue timeout teardown. */"
    old = """void blk_sync_queue(struct request_queue *q)\n{\n\tdel_timer_sync(&q->timeout);\n\tcancel_work_sync(&q->timeout_work);\n}\n"""
    new = """void blk_sync_queue(struct request_queue *q)\n{\n\t/* ABK security_update_backport: synchronized queue timeout teardown. */\n\ttimer_delete_sync(&q->timeout);\n\tcancel_work_sync(&q->timeout_work);\n}\n"""

    if marker in text:
        return {
            "mode": "already_present",
            "path": str(path),
            "target_anchors": {
                "marker": "present",
                "timer_delete_sync": bool_status("timer_delete_sync(&q->timeout);" in text),
            },
        }

    text = replace_once(text, old, new, "security_update_backport/blk_sync_queue")
    write_text(path, text)
    return {
        "mode": "patched",
        "path": str(path),
        "target_anchors": {
            "marker": "present",
            "timer_delete_sync": "present",
        },
    }


def apply_pid_deferred_free_batching(common_root: Path) -> dict[str, object]:
    pid_h = common_root / "include/linux/pid.h"
    pid_c = common_root / "kernel/pid.c"
    sys_c = common_root / "kernel/sys.c"
    pid_h_text = read_text(pid_h)
    pid_c_text = read_text(pid_c)
    sys_c_text = read_text(sys_c)
    original_pid_h = pid_h_text
    original_pid_c = pid_c_text
    original_sys_c = sys_c_text
    marker = "/* ABK security_update_backport: defer final pid freeing outside tasklist_lock. */"

    already_present = (
        "void change_pid(struct pid **pids, struct task_struct *task, enum pid_type," in pid_c_text
        and "free_pids(pids);" in sys_c_text
        and "static void set_special_pids(struct pid **pids, struct pid *pid)" in sys_c_text
        and "void change_pid(struct pid **pids, struct task_struct *task, enum pid_type," in pid_h_text
    )
    if already_present and marker in pid_c_text:
        return {
            "mode": "already_present",
            "paths": [str(pid_h), str(pid_c), str(sys_c)],
            "target_anchors": {
                "marker": "present",
                "free_pids": "present",
                "change_pid_signature": "present",
                "set_special_pids_signature": "present",
            },
        }
    if already_present and marker not in pid_c_text:
        pid_c_text = pid_c_text.replace(
            "static void __change_pid(struct pid **pids, struct task_struct *task,\n",
            marker + "\nstatic void __change_pid(struct pid **pids, struct task_struct *task,\n",
            1,
        )
        write_text(pid_c, pid_c_text)
        return {
            "mode": "patched",
            "paths": [str(pid_h), str(pid_c), str(sys_c)],
            "target_anchors": {
                "marker": "present",
                "free_pids": "present",
                "change_pid_signature": "present",
                "set_special_pids_signature": "present",
            },
        }

    pid_h_old = """extern void attach_pid(struct task_struct *task, enum pid_type);\nextern void detach_pid(struct task_struct *task, enum pid_type);\nextern void change_pid(struct task_struct *task, enum pid_type,\n\t\t\tstruct pid *pid);\n"""
    pid_h_new = """extern void attach_pid(struct task_struct *task, enum pid_type);\nvoid detach_pid(struct pid **pids, struct task_struct *task, enum pid_type);\nvoid change_pid(struct pid **pids, struct task_struct *task, enum pid_type,\n\t\tstruct pid *pid);\n"""
    pid_c_old = """static void __change_pid(struct task_struct *task, enum pid_type type,\n\t\t\tstruct pid *new)\n{\n\tstruct pid **pid_ptr = task_pid_ptr(task, type);\n\tstruct pid *pid;\n\tint tmp;\n\n\tpid = *pid_ptr;\n\n\thlist_del_rcu(&task->pid_links[type]);\n\t*pid_ptr = new;\n\n\tfor (tmp = PIDTYPE_MAX; --tmp >= 0; )\n\t\tif (pid_has_task(pid, tmp))\n\t\t\treturn;\n\n\tfree_pid(pid);\n}\n\nvoid detach_pid(struct task_struct *task, enum pid_type type)\n{\n\t__change_pid(task, type, NULL);\n}\n\nvoid change_pid(struct task_struct *task, enum pid_type type,\n\t\tstruct pid *pid)\n{\n\t__change_pid(task, type, pid);\n\tattach_pid(task, type);\n}\n"""
    pid_c_new = """/* ABK security_update_backport: defer final pid freeing outside tasklist_lock. */\nstatic void __change_pid(struct pid **pids, struct task_struct *task,\n\t\t\t enum pid_type type, struct pid *new)\n{\n\tstruct pid **pid_ptr, *pid;\n\tint tmp;\n\n\tlockdep_assert_held_write(&tasklist_lock);\n\n\tpid_ptr = task_pid_ptr(task, type);\n\tpid = *pid_ptr;\n\n\thlist_del_rcu(&task->pid_links[type]);\n\t*pid_ptr = new;\n\n\tfor (tmp = PIDTYPE_MAX; --tmp >= 0; )\n\t\tif (pid_has_task(pid, tmp))\n\t\t\treturn;\n\n\tWARN_ON(pids[type]);\n\tpids[type] = pid;\n}\n\nvoid detach_pid(struct pid **pids, struct task_struct *task, enum pid_type type)\n{\n\t__change_pid(pids, task, type, NULL);\n}\n\nvoid change_pid(struct pid **pids, struct task_struct *task, enum pid_type type,\n\t\tstruct pid *pid)\n{\n\t__change_pid(pids, task, type, pid);\n\tattach_pid(task, type);\n}\n"""
    setpgid_old = """SYSCALL_DEFINE2(setpgid, pid_t, pid, pid_t, pgid)\n{\n\tstruct task_struct *p;\n\tstruct task_struct *group_leader = current->group_leader;\n\tstruct pid *pgrp;\n\tint err;\n"""
    setpgid_new = """SYSCALL_DEFINE2(setpgid, pid_t, pid, pid_t, pgid)\n{\n\tstruct task_struct *p;\n\tstruct task_struct *group_leader = current->group_leader;\n\tstruct pid *pids[PIDTYPE_MAX] = { 0 };\n\tstruct pid *pgrp;\n\tint err;\n"""
    setpgid_change_old = "if (task_pgrp(p) != pgrp)\n\t\tchange_pid(p, PIDTYPE_PGID, pgrp);\n"
    setpgid_change_new = "if (task_pgrp(p) != pgrp)\n\t\tchange_pid(pids, p, PIDTYPE_PGID, pgrp);\n"
    setpgid_out_old = """out:\n\t/* All paths lead to here, thus we are safe. -DaveM */\n\twrite_unlock_irq(&tasklist_lock);\n\trcu_read_unlock();\n\treturn err;\n}\n"""
    setpgid_out_new = """out:\n\t/* All paths lead to here, thus we are safe. -DaveM */\n\twrite_unlock_irq(&tasklist_lock);\n\trcu_read_unlock();\n\tfree_pids(pids);\n\treturn err;\n}\n"""
    setsid_helper_old = """static void set_special_pids(struct pid *pid)\n{\n\tstruct task_struct *curr = current->group_leader;\n\n\tif (task_session(curr) != pid)\n\t\tchange_pid(curr, PIDTYPE_SID, pid);\n\n\tif (task_pgrp(curr) != pid)\n\t\tchange_pid(curr, PIDTYPE_PGID, pid);\n}\n"""
    setsid_helper_new = """static void set_special_pids(struct pid **pids, struct pid *pid)\n{\n\tstruct task_struct *curr = current->group_leader;\n\n\tif (task_session(curr) != pid)\n\t\tchange_pid(pids, curr, PIDTYPE_SID, pid);\n\n\tif (task_pgrp(curr) != pid)\n\t\tchange_pid(pids, curr, PIDTYPE_PGID, pid);\n}\n"""
    setsid_head_old = """int ksys_setsid(void)\n{\n\tstruct task_struct *group_leader = current->group_leader;\n\tstruct pid *sid = task_pid(group_leader);\n\tpid_t session = pid_vnr(sid);\n\tint err = -EPERM;\n"""
    setsid_head_new = """int ksys_setsid(void)\n{\n\tstruct task_struct *group_leader = current->group_leader;\n\tstruct pid *sid = task_pid(group_leader);\n\tstruct pid *pids[PIDTYPE_MAX] = { 0 };\n\tpid_t session = pid_vnr(sid);\n\tint err = -EPERM;\n"""
    setsid_call_old = "\tgroup_leader->signal->leader = 1;\n\tset_special_pids(sid);\n"
    setsid_call_new = "\tgroup_leader->signal->leader = 1;\n\tset_special_pids(pids, sid);\n"
    setsid_out_old = """out:\n\twrite_unlock_irq(&tasklist_lock);\n\tif (err > 0) {\n\t\tproc_sid_connector(group_leader);\n\t\tsched_autogroup_create_attach(group_leader);\n\t}\n\treturn err;\n}\n"""
    setsid_out_new = """out:\n\twrite_unlock_irq(&tasklist_lock);\n\tfree_pids(pids);\n\tif (err > 0) {\n\t\tproc_sid_connector(group_leader);\n\t\tsched_autogroup_create_attach(group_leader);\n\t}\n\treturn err;\n}\n"""

    pid_h_text = replace_once(pid_h_text, pid_h_old, pid_h_new, "security_update_backport/pid_h")
    pid_c_text = replace_once(pid_c_text, pid_c_old, pid_c_new, "security_update_backport/pid_c")
    sys_c_text = replace_once(sys_c_text, setpgid_old, setpgid_new, "security_update_backport/sys_setpgid_head")
    sys_c_text = replace_once(sys_c_text, setpgid_change_old, setpgid_change_new, "security_update_backport/sys_setpgid_change")
    sys_c_text = replace_once(sys_c_text, setpgid_out_old, setpgid_out_new, "security_update_backport/sys_setpgid_out")
    sys_c_text = replace_once(sys_c_text, setsid_helper_old, setsid_helper_new, "security_update_backport/sys_setsid_helper")
    sys_c_text = replace_once(sys_c_text, setsid_head_old, setsid_head_new, "security_update_backport/sys_setsid_head")
    sys_c_text = replace_once(sys_c_text, setsid_call_old, setsid_call_new, "security_update_backport/sys_setsid_call")
    sys_c_text = replace_once(sys_c_text, setsid_out_old, setsid_out_new, "security_update_backport/sys_setsid_out")
    if marker not in pid_c_text:
        pid_c_text = pid_c_text.replace(
            "static void __change_pid(struct pid **pids, struct task_struct *task,\n",
            marker + "\nstatic void __change_pid(struct pid **pids, struct task_struct *task,\n",
            1,
        )

    if pid_h_text != original_pid_h:
        write_text(pid_h, pid_h_text)
    if pid_c_text != original_pid_c:
        write_text(pid_c, pid_c_text)
    if sys_c_text != original_sys_c:
        write_text(sys_c, sys_c_text)

    return {
        "mode": "patched",
        "paths": [str(pid_h), str(pid_c), str(sys_c)],
        "target_anchors": {
            "marker": "present",
            "free_pids": bool_status("free_pids(pids);" in sys_c_text and "void free_pids(struct pid **pids)" in pid_c_text),
            "change_pid_signature": bool_status("void change_pid(struct pid **pids, struct task_struct *task, enum pid_type," in pid_c_text),
            "set_special_pids_signature": bool_status("static void set_special_pids(struct pid **pids, struct pid *pid)" in sys_c_text),
        },
    }


def apply_elevator_sysfs_dying_guard(common_root: Path) -> dict[str, object]:
    path = common_root / "block/elevator.c"
    text = read_text(path)
    original = text
    marker = "/* ABK security_update_backport: reject sysfs iosched access while queue teardown is in progress. */"
    old_show = """\te = container_of(kobj, struct elevator_queue, kobj);\n\tmutex_lock(&e->sysfs_lock);\n\terror = e->type ? entry->show(e, page) : -ENOENT;\n\tmutex_unlock(&e->sysfs_lock);\n\treturn error;\n}\n"""
    new_show = """\te = container_of(kobj, struct elevator_queue, kobj);\n\tmutex_lock(&e->sysfs_lock);\n\t/* ABK security_update_backport: reject sysfs iosched access while queue teardown is in progress. */\n\terror = e->type ? entry->show(e, page) : -ENOENT;\n\tif (!e->registered)\n\t\terror = -ENODEV;\n\tmutex_unlock(&e->sysfs_lock);\n\treturn error;\n}\n"""
    old_store = """\te = container_of(kobj, struct elevator_queue, kobj);\n\tmutex_lock(&e->sysfs_lock);\n\terror = e->type ? entry->store(e, page, length) : -ENOENT;\n\tmutex_unlock(&e->sysfs_lock);\n\treturn error;\n}\n"""
    new_store = """\te = container_of(kobj, struct elevator_queue, kobj);\n\tmutex_lock(&e->sysfs_lock);\n\t/* ABK security_update_backport: reject sysfs iosched access while queue teardown is in progress. */\n\terror = e->type ? entry->store(e, page, length) : -ENOENT;\n\tif (!e->registered)\n\t\terror = -ENODEV;\n\tmutex_unlock(&e->sysfs_lock);\n\treturn error;\n}\n"""

    text = replace_once(text, old_show, new_show, "security_update_backport/elevator_show")
    text = replace_once(text, old_store, new_store, "security_update_backport/elevator_store")
    if text != original:
        write_text(path, text)

    return {
        "mode": "patched" if text != original else "already_present",
        "path": str(path),
        "target_anchors": {
            "marker": bool_status(marker in text),
            "show_guard": bool_status("if (!e->registered)\n\t\terror = -ENODEV;" in text),
            "store_guard": bool_status(text.count("if (!e->registered)\n\t\terror = -ENODEV;") >= 2),
        },
    }


def candidate_status(blocked_by: str | None, anchor_ok: bool, applied: bool, details: dict[str, object]) -> str:
    if blocked_by == "bridge":
        return "blocked_by_bridge"
    if blocked_by == "fixups":
        return "blocked_by_fixups"
    if not anchor_ok:
        return "missing_anchor"
    if applied:
        return "applied"
    if details.get("mode") == "already_present":
        return "applied"
    return "partial"


def check_anchors(common_root: Path, candidate: Candidate) -> tuple[bool, dict[str, str]]:
    results: dict[str, str] = {}
    missing = False
    for path_str in candidate.target_paths:
        path = common_root / path_str
        if not path.exists():
            results[path_str] = "missing_file"
            missing = True
            continue
        text = read_text(path)
        local_ok = True
        for anchor in candidate.anchor_preconditions:
            target_path = None
            needle = anchor
            if "::" in anchor:
                target_path, needle = anchor.split("::", 1)
            if target_path is not None and target_path != path_str:
                continue
            if needle in text:
                continue
            local_ok = False
            missing = True
            break
        results[path_str] = "present" if local_ok else "missing_anchor"
    return (not missing, results)


def apply_candidate(common_root: Path, candidate: Candidate) -> dict[str, object]:
    if candidate.id == "sysctl_modules_disabled_minmax_guard":
        return apply_sysctl_modules_disabled_minmax_guard(common_root)
    if candidate.id == "blk_sync_queue_timer_delete_sync":
        return apply_blk_sync_queue_timer_delete_sync(common_root)
    if candidate.id == "pid_deferred_free_batching":
        return apply_pid_deferred_free_batching(common_root)
    if candidate.id == "elevator_sysfs_dying_guard":
        return apply_elevator_sysfs_dying_guard(common_root)
    raise SystemExit(f"unsupported candidate id: {candidate.id}")


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# ABK Security Backport Report",
        "",
        f"- Generated: `{report['generated_at_utc']}`",
        f"- Current tree: `{report['current_common_root']}`",
        f"- Source base: `{report['source_base']}`",
        f"- Batch: `{report['batch']}`",
        f"- Status: `{report['status']}`",
        f"- Tree escalation required: `{str(report['tree_escalation_required']).lower()}`",
        "",
        "## Selected Candidates",
        "",
    ]
    for item in report["selected_candidates"]:
        lines.append(f"- `{item['id']}`: {item['summary']}")
    lines.extend(["", "## Applied Candidates", ""])
    for item in report["applied_candidates"]:
        lines.append(f"- `{item['id']}`")
    if not report["applied_candidates"]:
        lines.append("- none")
    lines.extend(["", "## Blocked Candidates", ""])
    for item in report["blocked_candidates"]:
        lines.append(f"- `{item['id']}`: `{item['status']}`")
    if not report["blocked_candidates"]:
        lines.append("- none")
    lines.extend(["", "## Candidate Details", ""])
    for item in report["results"]:
        lines.append(f"### `{item['id']}`")
        lines.append("")
        lines.append(f"- Status: `{item['status']}`")
        lines.append(f"- Apply mode: `{item['apply_mode']}`")
        lines.append(f"- Risk class: `{item['risk_class']}`")
        lines.append(f"- Target paths: `{', '.join(item['target_paths'])}`")
        lines.append(f"- Anchor status: `{json.dumps(item['anchor_status'], ensure_ascii=True, sort_keys=True)}`")
        if item.get("details"):
            lines.append(f"- Details: `{json.dumps(item['details'], ensure_ascii=True, sort_keys=True)}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_report(common_root: Path, output_dir: Path) -> dict[str, object]:
    for candidate in CANDIDATES:
        ensure_candidate_shape(candidate)

    results: list[dict[str, object]] = []
    batch_statuses: dict[str, list[str]] = {"sec_lowrisk_batch_001": [], "sec_lowrisk_batch_002": []}

    for candidate in CANDIDATES:
        anchors_ok, anchor_status = check_anchors(common_root, candidate)
        details: dict[str, object] = {}
        applied = False

        if candidate.blocked_by is None and anchors_ok:
            details = apply_candidate(common_root, candidate)
            applied = details.get("mode") in {"patched", "already_present"}

        status = candidate_status(candidate.blocked_by, anchors_ok, applied, details)
        batch_statuses[candidate.batch].append(status)
        results.append(
            {
                "batch": candidate.batch,
                "id": candidate.id,
                "summary": candidate.summary,
                "source_base": SOURCE_BASE,
                "target_paths": list(candidate.target_paths),
                "anchor_preconditions": list(candidate.anchor_preconditions),
                "anchor_status": anchor_status,
                "apply_mode": candidate.apply_mode,
                "risk_class": candidate.risk_class,
                "blocked_by": candidate.blocked_by,
                "status": status,
                "details": details,
            }
        )

    overall_batch = "sec_lowrisk_batch_001"
    status = "applied"
    if any(value != "applied" for value in batch_statuses[overall_batch]):
        status = "partial"

    selected = [item for item in results if item["batch"] == overall_batch]
    applied_candidates = [item for item in results if item["status"] == "applied"]
    blocked_candidates = [item for item in results if item["status"] != "applied"]
    tree_escalation_required = any(
        item["status"] in {"blocked_by_bridge", "blocked_by_fixups"} for item in results
    )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_common_root": str(common_root),
        "source_base": SOURCE_BASE,
        "batch": overall_batch,
        "status": status,
        "selected_candidates": [
            {"id": item["id"], "summary": item["summary"], "apply_mode": item["apply_mode"]}
            for item in selected
        ],
        "applied_candidates": [
            {"id": item["id"], "batch": item["batch"], "status": item["status"]}
            for item in applied_candidates
        ],
        "blocked_candidates": [
            {"id": item["id"], "batch": item["batch"], "status": item["status"]}
            for item in blocked_candidates
        ],
        "tree_escalation_required": tree_escalation_required,
        "results": results,
        "batches": {
            batch: {
                "candidate_count": len([item for item in results if item["batch"] == batch]),
                "statuses": statuses,
            }
            for batch, statuses in batch_statuses.items()
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_text(
        output_dir / "security_backport_queue.json",
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
    )
    write_text(output_dir / "security_backport_queue.md", render_markdown(report))
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit(f"usage: {argv[0]} <current-common-root> <output-dir>")

    current_common = Path(argv[1])
    output_dir = Path(argv[2])
    build_report(current_common, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
