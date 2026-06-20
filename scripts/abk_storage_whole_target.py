#!/usr/bin/env python3
from __future__ import annotations

"""
Archived experimental storage/F2FS line.

This script is intentionally kept in-tree as a historical prototype, but it is
not part of the active ABK_ABI_PATCH_SUITE child set and should not be treated
as a current implementation path.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text()


def write_text(path: Path, text: str) -> None:
    path.write_text(text)


def ensure_contains(path: Path, needle: str, label: str) -> None:
    if needle not in read_text(path):
        raise SystemExit(f"{label}: expected anchor missing in {path}: {needle}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected block missing")
    return text.replace(old, new, 1)


def insert_before(text: str, anchor: str, block: str, label: str) -> str:
    if block in text:
        return text
    if anchor not in text:
        raise SystemExit(f"{label}: expected anchor missing")
    return text.replace(anchor, block + anchor, 1)


def bool_status(value: bool) -> str:
    return "present" if value else "missing"


def run_kernelversion(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["make", "-s", "-C", str(root), "kernelversion"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def usage(
    *,
    hard_port_possible: bool,
    semantic_port_used: bool,
    max_function_port_used: bool,
    sidecar_state_used: bool,
    sidecar_state_scope: str,
    new_interface_used: bool,
    new_interface_scope: str,
) -> dict[str, object]:
    return {
        "hard_port_possible": hard_port_possible,
        "semantic_port_used": semantic_port_used,
        "max_function_port_used": max_function_port_used,
        "sidecar_state_used": sidecar_state_used,
        "sidecar_state_scope": sidecar_state_scope,
        "new_interface_used": new_interface_used,
        "new_interface_scope": new_interface_scope,
    }


def patch_ufs_surface(common_root: Path) -> dict[str, object]:
    ufshcd_c = common_root / "drivers/ufs/core/ufshcd.c"
    ufs_mcq_c = common_root / "drivers/ufs/core/ufs-mcq.c"
    ufshcd_crypto_c = common_root / "drivers/ufs/core/ufshcd-crypto.c"
    ufs_qcom_c = common_root / "drivers/ufs/host/ufs-qcom.c"

    anchors = {
        "use_mcq_mode": "static bool use_mcq_mode = true;",
        "prepare_lrbp_crypto": "ufshcd_prepare_lrbp_crypto(scsi_cmd_to_rq(cmd), lrbp);",
        "crypto_register": "ufshcd_crypto_register(hba, q);",
        "mcq_req_to_hwq": "struct ufs_hw_queue *ufshcd_mcq_req_to_hwq(struct ufs_hba *hba,",
        "mcq_config_mac": "void ufshcd_mcq_config_mac(struct ufs_hba *hba, u32 max_active_cmds)",
        "mcq_make_queues_operational": "void ufshcd_mcq_make_queues_operational(struct ufs_hba *hba)",
        "qcom_mcq_resource": "static int ufs_qcom_mcq_config_resource(struct ufs_hba *hba)",
    }

    ensure_contains(ufshcd_c, anchors["use_mcq_mode"], "storage_whole_target/ufs")
    ensure_contains(ufshcd_c, anchors["prepare_lrbp_crypto"], "storage_whole_target/ufs")
    ensure_contains(ufshcd_c, anchors["crypto_register"], "storage_whole_target/ufs")
    ensure_contains(ufs_mcq_c, anchors["mcq_req_to_hwq"], "storage_whole_target/ufs")
    ensure_contains(ufs_mcq_c, anchors["mcq_config_mac"], "storage_whole_target/ufs")
    ensure_contains(ufs_mcq_c, anchors["mcq_make_queues_operational"], "storage_whole_target/ufs")
    ensure_contains(ufshcd_crypto_c, "void ufshcd_crypto_register(struct ufs_hba *hba, struct request_queue *q)", "storage_whole_target/ufs")
    ensure_contains(ufs_qcom_c, anchors["qcom_mcq_resource"], "storage_whole_target/ufs")

    marker = "/* ABK storage_whole_target: verified UFS MCQ + crypto whole-target surface. */\n"
    text = read_text(ufshcd_c)
    updated = insert_before(text, anchors["use_mcq_mode"], marker, "storage_whole_target/ufs_marker")
    if updated != text:
        write_text(ufshcd_c, updated)

    return {
        **usage(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=False,
            new_interface_scope="none",
        ),
        "marker": marker.strip(),
        "marker_path": str(ufshcd_c),
        "anchors": {key: bool_status(True) for key in anchors},
        "status": "validated_with_marker",
    }


def patch_block_surface(common_root: Path) -> dict[str, object]:
    blk_mq_c = common_root / "block/blk-mq.c"
    bio_c = common_root / "block/bio.c"

    blk_text = read_text(blk_mq_c)

    old_shape = {
        "account_io_start": "static inline void blk_account_io_start(struct request *req)",
        "cached_request": "static bool blk_mq_can_use_cached_rq(struct request *rq, struct blk_plug *plug,",
        "submit_path": "if (blk_mq_can_use_cached_rq(rq, plug, bio))",
        "queue_enter": "if (unlikely(bio_queue_enter(bio)))",
    }
    new_shape = {
        "account_io_start": "static void __blk_account_io_start(struct request *rq)",
        "cached_request": "static inline struct request *blk_mq_get_cached_request(",
        "submit_path": "rq = blk_mq_get_cached_request(",
        "queue_enter": "if (unlikely(bio_queue_enter(bio)))",
        "bio_set_ioprio": "static void bio_set_ioprio(struct bio *bio)",
    }
    bio_text = read_text(bio_c)
    bio_anchor_new = "if (bv->bv_len + len > queue_max_segment_size(q))"
    bio_anchor_legacy = "if (len > queue_max_segment_size(q) - bv->bv_len)"

    if new_shape["account_io_start"] in blk_text:
        anchors = {
            "shape": "new",
            "account_io_start": bool_status(True),
            "cached_request": bool_status(new_shape["cached_request"] in blk_text),
            "submit_path": bool_status(new_shape["submit_path"] in blk_text),
            "queue_enter": bool_status(new_shape["queue_enter"] in blk_text),
            "bio_set_ioprio": bool_status(new_shape["bio_set_ioprio"] in blk_text),
            "merge_guard": bool_status(bio_anchor_new in bio_text or bio_anchor_legacy in bio_text),
        }
        marker_anchor = new_shape["cached_request"]
    elif old_shape["account_io_start"] in blk_text:
        anchors = {
            "shape": "legacy",
            "account_io_start": bool_status(True),
            "cached_request": bool_status(old_shape["cached_request"] in blk_text),
            "submit_path": bool_status(old_shape["submit_path"] in blk_text),
            "queue_enter": bool_status(old_shape["queue_enter"] in blk_text),
            "bio_set_ioprio": bool_status(False),
            "merge_guard": bool_status(bio_anchor_new in bio_text or bio_anchor_legacy in bio_text),
        }
        marker_anchor = old_shape["cached_request"]
    else:
        raise SystemExit(
            "storage_whole_target/block: unsupported blk-mq.c surface, neither legacy nor 7.0.12-style anchors were found"
        )

    if anchors["merge_guard"] != bool_status(True):
        raise SystemExit(
            "storage_whole_target/block: unsupported bio.c surface, neither legacy nor tightened merge guard anchor was found"
        )

    marker = "/* ABK storage_whole_target: verified block queue lifecycle surface. */\n"
    updated = insert_before(blk_text, marker_anchor, marker, "storage_whole_target/block_marker")
    if updated != blk_text:
        write_text(blk_mq_c, updated)

    return {
        **usage(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=False,
            new_interface_scope="none",
        ),
        "marker": marker.strip(),
        "marker_path": str(blk_mq_c),
        "anchors": anchors,
        "status": "validated_with_marker",
    }


def patch_dm_surface(common_root: Path) -> dict[str, object]:
    dm_c = common_root / "drivers/md/dm.c"
    anchor = "/*\n * A target may call dm_accept_partial_bio only from the map routine."

    ensure_contains(dm_c, "void dm_accept_partial_bio(struct bio *bio, unsigned int n_sectors)", "storage_whole_target/dm")
    ensure_contains(dm_c, "EXPORT_SYMBOL_GPL(dm_accept_partial_bio);", "storage_whole_target/dm")

    marker = "/* ABK storage_whole_target: verified dm partial-bio request-flow surface. */\n"
    text = read_text(dm_c)
    updated = insert_before(text, anchor, marker, "storage_whole_target/dm_marker")
    if updated != text:
        write_text(dm_c, updated)

    return {
        **usage(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=False,
            new_interface_scope="none",
        ),
        "marker": marker.strip(),
        "marker_path": str(dm_c),
        "anchors": {
            "dm_accept_partial_bio": bool_status(True),
            "dm_accept_partial_bio_exported": bool_status(True),
        },
        "status": "validated_with_marker",
    }


def patch_fscrypt_surface(common_root: Path) -> dict[str, object]:
    fname_c = common_root / "fs/crypto/fname.c"
    anchor = "int fscrypt_setup_filename(struct inode *dir, const struct qstr *iname,\n"

    ensure_contains(fname_c, "int fscrypt_fname_encrypt(const struct inode *inode, const struct qstr *iname,", "storage_whole_target/fscrypt")
    ensure_contains(fname_c, anchor, "storage_whole_target/fscrypt")

    marker = "/* ABK storage_whole_target: verified fscrypt filename surface. */\n"
    text = read_text(fname_c)
    updated = insert_before(text, anchor, marker, "storage_whole_target/fscrypt_marker")
    if updated != text:
        write_text(fname_c, updated)

    return {
        **usage(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=False,
            new_interface_scope="none",
        ),
        "marker": marker.strip(),
        "marker_path": str(fname_c),
        "anchors": {
            "fscrypt_fname_encrypt": bool_status(True),
            "fscrypt_setup_filename": bool_status(True),
        },
        "status": "validated_with_marker",
    }


def patch_f2fs_lock_trace_compat(common_root: Path) -> dict[str, object]:
    f2fs_h = common_root / "fs/f2fs/f2fs.h"
    checkpoint_c = common_root / "fs/f2fs/checkpoint.c"
    super_c = common_root / "fs/f2fs/super.c"
    data_c = common_root / "fs/f2fs/data.c"
    trace_h = common_root / "include/trace/events/f2fs.h"

    f2fs_text = read_text(f2fs_h)
    trace_text = read_text(trace_h)
    checkpoint_text = read_text(checkpoint_c)
    super_text = read_text(super_c)
    data_text = read_text(data_c)

    if (
        "init_f2fs_rwsem(&sbi->gc_lock);" not in super_text
        and "init_f2fs_rwsem_trace(&sbi->gc_lock, sbi, LOCK_NAME_GC_LOCK);" not in super_text
    ):
        raise SystemExit(
            f"storage_whole_target/f2fs: expected gc_lock init anchor missing in {super_c}"
        )
    if (
        "init_f2fs_rwsem(&sbi->cp_rwsem);" not in super_text
        and "init_f2fs_rwsem_trace(&sbi->cp_rwsem, sbi, LOCK_NAME_CP_RWSEM);" not in super_text
    ):
        raise SystemExit(
            f"storage_whole_target/f2fs: expected cp_rwsem init anchor missing in {super_c}"
        )
    if (
        "init_f2fs_rwsem(&sbi->write_io[i][j].io_rwsem);" not in data_text
        and "init_f2fs_rwsem_trace(&sbi->write_io[i][j].io_rwsem, sbi, LOCK_NAME_IO_RWSEM);" not in data_text
    ):
        raise SystemExit(
            f"storage_whole_target/f2fs: expected io_rwsem init anchor missing in {data_c}"
        )

    header_anchor = "/*\n * An implementation of an rwsem that is explicitly unfair to readers. This\n"
    header_block = """/* ABK storage_whole_target: f2fs lock-trace compatibility shim. */
enum f2fs_lock_name {
\tLOCK_NAME_NONE,
\tLOCK_NAME_CP_RWSEM,
\tLOCK_NAME_NODE_CHANGE,
\tLOCK_NAME_NODE_WRITE,
\tLOCK_NAME_GC_LOCK,
\tLOCK_NAME_CP_GLOBAL,
\tLOCK_NAME_IO_RWSEM,
\tLOCK_NAME_MAX,
};

enum f2fs_timeout_type {
\tTIMEOUT_TYPE_NONE,
\tTIMEOUT_TYPE_RUNNING,
\tTIMEOUT_TYPE_IO_SLEEP,
\tTIMEOUT_TYPE_NONIO_SLEEP,
\tTIMEOUT_TYPE_RUNNABLE,
\tTIMEOUT_TYPE_MAX,
};

struct f2fs_time_stat {
\tunsigned long long total_time;
#ifdef CONFIG_64BIT
\tunsigned long long running_time;
#endif
#if defined(CONFIG_SCHED_INFO) && defined(CONFIG_SCHEDSTATS)
\tunsigned long long runnable_time;
#endif
#ifdef CONFIG_TASK_DELAY_ACCT
\tunsigned long long io_sleep_time;
#endif
};

struct f2fs_lock_context {
\tstruct f2fs_time_stat ts;
\tint orig_nice;
\tint new_nice;
\tbool lock_trace;
\tbool need_restore;
};

"""
    lock_trace_show_name = """#define show_lock_name(lock)\t\t\t\t\t\\
\t__print_symbolic(lock,\t\t\t\t\t\\
\t\t{ LOCK_NAME_CP_RWSEM,\t\t"cp_rwsem" },\t\t\\
\t\t{ LOCK_NAME_NODE_CHANGE,\t"node_change" },\t\t\\
\t\t{ LOCK_NAME_NODE_WRITE,\t\t"node_write" },\t\t\\
\t\t{ LOCK_NAME_GC_LOCK,\t\t"gc_lock" },\t\t\\
\t\t{ LOCK_NAME_CP_GLOBAL,\t\t"cp_global" },\t\t\\
\t\t{ LOCK_NAME_IO_RWSEM,\t\t"io_rwsem" })

"""
    lock_trace_events = """TRACE_EVENT(f2fs_lock_elapsed_time,

\tTP_PROTO(struct f2fs_sb_info *sbi, enum f2fs_lock_name lock_name,
\t\tbool is_write, struct task_struct *p, int ioprio,
\t\tunsigned long long total_time,
\t\tunsigned long long running_time,
\t\tunsigned long long runnable_time,
\t\tunsigned long long io_sleep_time,
\t\tunsigned long long other_time),

\tTP_ARGS(sbi, lock_name, is_write, p, ioprio, total_time, running_time,
\t\trunnable_time, io_sleep_time, other_time),

\tTP_STRUCT__entry(
\t\t__field(dev_t, dev)
\t\t__array(char, comm, TASK_COMM_LEN)
\t\t__field(pid_t, pid)
\t\t__field(int, prio)
\t\t__field(int, ioprio_class)
\t\t__field(int, ioprio_data)
\t\t__field(unsigned int, lock_name)
\t\t__field(bool, is_write)
\t\t__field(unsigned long long, total_time)
\t\t__field(unsigned long long, running_time)
\t\t__field(unsigned long long, runnable_time)
\t\t__field(unsigned long long, io_sleep_time)
\t\t__field(unsigned long long, other_time)
\t),

\tTP_fast_assign(
\t\t__entry->dev\t\t= sbi->sb->s_dev;
\t\tmemcpy(__entry->comm, p->comm, TASK_COMM_LEN);
\t\t__entry->pid\t\t= p->pid;
\t\t__entry->prio\t\t= p->prio;
\t\t__entry->ioprio_class\t= IOPRIO_PRIO_CLASS(ioprio);
\t\t__entry->ioprio_data\t= IOPRIO_PRIO_DATA(ioprio);
\t\t__entry->lock_name\t= lock_name;
\t\t__entry->is_write\t= is_write;
\t\t__entry->total_time\t= total_time;
\t\t__entry->running_time\t= running_time;
\t\t__entry->runnable_time\t= runnable_time;
\t\t__entry->io_sleep_time\t= io_sleep_time;
\t\t__entry->other_time\t= other_time;
\t),

\tTP_printk("dev = (%d,%d), comm: %s, pid: %d, prio: %d, "
\t\t"ioprio_class: %d, ioprio_data: %d, lock_name: %s, "
\t\t"lock_type: %s, total: %llu, running: %llu, "
\t\t"runnable: %llu, io_sleep: %llu, other: %llu",
\t\tshow_dev(__entry->dev),
\t\t__entry->comm,
\t\t__entry->pid,
\t\t__entry->prio,
\t\t__entry->ioprio_class,
\t\t__entry->ioprio_data,
\t\tshow_lock_name(__entry->lock_name),
\t\t__entry->is_write ? "wlock" : "rlock",
\t\t__entry->total_time,
\t\t__entry->running_time,
\t\t__entry->runnable_time,
\t\t__entry->io_sleep_time,
\t\t__entry->other_time)
);

DECLARE_EVENT_CLASS(f2fs_priority_update,

\tTP_PROTO(struct f2fs_sb_info *sbi, enum f2fs_lock_name lock_name,
\t\tbool is_write, struct task_struct *p, int orig_prio,
\t\tint new_prio),

\tTP_ARGS(sbi, lock_name, is_write, p, orig_prio, new_prio),

\tTP_STRUCT__entry(
\t\t__field(dev_t, dev)
\t\t__array(char, comm, TASK_COMM_LEN)
\t\t__field(pid_t, pid)
\t\t__field(unsigned int, lock_name)
\t\t__field(bool, is_write)
\t\t__field(int, orig_prio)
\t\t__field(int, new_prio)
\t),

\tTP_fast_assign(
\t\t__entry->dev\t\t= sbi->sb->s_dev;
\t\tmemcpy(__entry->comm, p->comm, TASK_COMM_LEN);
\t\t__entry->pid\t\t= p->pid;
\t\t__entry->lock_name\t= lock_name;
\t\t__entry->is_write\t= is_write;
\t\t__entry->orig_prio\t= orig_prio;
\t\t__entry->new_prio\t= new_prio;
\t),

\tTP_printk("dev = (%d,%d), comm: %s, pid: %d, lock_name: %s, "
\t\t"lock_type: %s, orig_prio: %d, new_prio: %d",
\t\tshow_dev(__entry->dev),
\t\t__entry->comm,
\t\t__entry->pid,
\t\tshow_lock_name(__entry->lock_name),
\t\t__entry->is_write ? "wlock" : "rlock",
\t\t__entry->orig_prio,
\t\t__entry->new_prio)
);

DEFINE_EVENT(f2fs_priority_update, f2fs_priority_uplift,

\tTP_PROTO(struct f2fs_sb_info *sbi, enum f2fs_lock_name lock_name,
\t\tbool is_write, struct task_struct *p, int orig_prio,
\t\tint new_prio),

\tTP_ARGS(sbi, lock_name, is_write, p, orig_prio, new_prio)
);

DEFINE_EVENT(f2fs_priority_update, f2fs_priority_restore,

\tTP_PROTO(struct f2fs_sb_info *sbi, enum f2fs_lock_name lock_name,
\t\tbool is_write, struct task_struct *p, int orig_prio,
\t\tint new_prio),

\tTP_ARGS(sbi, lock_name, is_write, p, orig_prio, new_prio)
);

"""
    if "enum f2fs_lock_name {" not in f2fs_text:
        f2fs_text = insert_before(f2fs_text, header_anchor, header_block, "storage_whole_target/f2fs_header")

    compat_anchor = "static inline void f2fs_lock_op(struct f2fs_sb_info *sbi)\n"
    compat_block = """/* ABK storage_whole_target: trace helper compatibility shims keep legacy 6.1 lock semantics. */
#define init_f2fs_rwsem_trace(sem, sbi, name) init_f2fs_rwsem(sem)

static inline void f2fs_down_read_trace(struct f2fs_rwsem *sem,
\t\t\t\t\tstruct f2fs_lock_context *lc)
{
\t(void)lc;
\tf2fs_down_read(sem);
}

static inline int f2fs_down_read_trylock_trace(struct f2fs_rwsem *sem,
\t\t\t\t\t       struct f2fs_lock_context *lc)
{
\t(void)lc;
\treturn f2fs_down_read_trylock(sem);
}

static inline void f2fs_up_read_trace(struct f2fs_rwsem *sem,
\t\t\t\t      struct f2fs_lock_context *lc)
{
\t(void)lc;
\tf2fs_up_read(sem);
}

static inline void f2fs_down_write_trace(struct f2fs_rwsem *sem,
\t\t\t\t\t struct f2fs_lock_context *lc)
{
\t(void)lc;
\tf2fs_down_write(sem);
}

static inline int f2fs_down_write_trylock_trace(struct f2fs_rwsem *sem,
\t\t\t\t\t        struct f2fs_lock_context *lc)
{
\t(void)lc;
\treturn f2fs_down_write_trylock(sem);
}

static inline void f2fs_up_write_trace(struct f2fs_rwsem *sem,
\t\t\t\t       struct f2fs_lock_context *lc)
{
\t(void)lc;
\tf2fs_up_write(sem);
}

"""
    if "init_f2fs_rwsem_trace(sem, sbi, name)" not in f2fs_text:
        f2fs_text = insert_before(f2fs_text, compat_anchor, compat_block, "storage_whole_target/f2fs_compat")

    trace_marker = "/* ABK storage_whole_target: f2fs lock-name trace events consume the compatibility shim in fs/f2fs/f2fs.h. */\n"
    if "#define show_lock_name(lock)" not in trace_text:
        trace_text = insert_before(
            trace_text,
            "#define show_victim_policy(type)",
            lock_trace_show_name,
            "storage_whole_target/f2fs_trace_show_name",
        )
    if "TRACE_EVENT(f2fs_lock_elapsed_time," not in trace_text:
        trace_text = insert_before(
            trace_text,
            "\n#endif /* _TRACE_F2FS_H */\n",
            "\n" + lock_trace_events,
            "storage_whole_target/f2fs_trace_events",
        )
    if trace_marker not in trace_text:
        trace_text = insert_before(
            trace_text,
            "#define show_lock_name(lock)",
            trace_marker,
            "storage_whole_target/f2fs_trace_marker",
        )

    checkpoint_marker = "/* ABK storage_whole_target: keep legacy checkpoint lock runtime semantics while satisfying trace/header whole-target dependencies. */\n"
    if checkpoint_marker not in checkpoint_text:
        checkpoint_text = insert_before(checkpoint_text, "#define DEFAULT_CHECKPOINT_IOPRIO", checkpoint_marker, "storage_whole_target/f2fs_checkpoint")

    super_marker = "\t/* ABK storage_whole_target: named F2FS lock init surface kept compatible with trace-only backports. */\n"
    if super_marker.strip() not in super_text:
        super_text = insert_before(
            super_text,
            "\tinit_f2fs_rwsem(&sbi->gc_lock);\n",
            super_marker,
            "storage_whole_target/f2fs_super_marker",
        )
    if (
        "init_f2fs_rwsem(&sbi->gc_lock);" in super_text
        and "init_f2fs_rwsem_trace(&sbi->gc_lock, sbi, LOCK_NAME_GC_LOCK);" not in super_text
    ):
        super_text = replace_once(
            super_text,
            "init_f2fs_rwsem(&sbi->gc_lock);",
            "init_f2fs_rwsem_trace(&sbi->gc_lock, sbi, LOCK_NAME_GC_LOCK);",
            "storage_whole_target/f2fs_super_gc_lock",
        )
    if (
        "init_f2fs_rwsem(&sbi->cp_global_sem);" in super_text
        and "init_f2fs_rwsem_trace(&sbi->cp_global_sem, sbi, LOCK_NAME_CP_GLOBAL);" not in super_text
    ):
        super_text = replace_once(
            super_text,
            "init_f2fs_rwsem(&sbi->cp_global_sem);",
            "init_f2fs_rwsem_trace(&sbi->cp_global_sem, sbi, LOCK_NAME_CP_GLOBAL);",
            "storage_whole_target/f2fs_super_cp_global",
        )
    if (
        "init_f2fs_rwsem(&sbi->node_write);" in super_text
        and "init_f2fs_rwsem_trace(&sbi->node_write, sbi, LOCK_NAME_NODE_WRITE);" not in super_text
    ):
        super_text = replace_once(
            super_text,
            "init_f2fs_rwsem(&sbi->node_write);",
            "init_f2fs_rwsem_trace(&sbi->node_write, sbi, LOCK_NAME_NODE_WRITE);",
            "storage_whole_target/f2fs_super_node_write",
        )
    if (
        "init_f2fs_rwsem(&sbi->node_change);" in super_text
        and "init_f2fs_rwsem_trace(&sbi->node_change, sbi, LOCK_NAME_NODE_CHANGE);" not in super_text
    ):
        super_text = replace_once(
            super_text,
            "init_f2fs_rwsem(&sbi->node_change);",
            "init_f2fs_rwsem_trace(&sbi->node_change, sbi, LOCK_NAME_NODE_CHANGE);",
            "storage_whole_target/f2fs_super_node_change",
        )
    if (
        "init_f2fs_rwsem(&sbi->cp_rwsem);" in super_text
        and "init_f2fs_rwsem_trace(&sbi->cp_rwsem, sbi, LOCK_NAME_CP_RWSEM);" not in super_text
    ):
        super_text = replace_once(
            super_text,
            "init_f2fs_rwsem(&sbi->cp_rwsem);",
            "init_f2fs_rwsem_trace(&sbi->cp_rwsem, sbi, LOCK_NAME_CP_RWSEM);",
            "storage_whole_target/f2fs_super_cp_rwsem",
        )

    data_marker = "\t\t\t/* ABK storage_whole_target: IO lock init surface kept compatible with trace-only backports. */\n"
    if data_marker.strip() not in data_text:
        data_text = insert_before(
            data_text,
            "\t\t\tinit_f2fs_rwsem(&sbi->write_io[i][j].io_rwsem);\n",
            data_marker,
            "storage_whole_target/f2fs_data_marker",
        )
    if (
        "init_f2fs_rwsem(&sbi->write_io[i][j].io_rwsem);" in data_text
        and "init_f2fs_rwsem_trace(&sbi->write_io[i][j].io_rwsem, sbi, LOCK_NAME_IO_RWSEM);" not in data_text
    ):
        data_text = replace_once(
            data_text,
            "init_f2fs_rwsem(&sbi->write_io[i][j].io_rwsem);",
            "init_f2fs_rwsem_trace(&sbi->write_io[i][j].io_rwsem, sbi, LOCK_NAME_IO_RWSEM);",
            "storage_whole_target/f2fs_data_io_rwsem",
        )

    if f2fs_text != read_text(f2fs_h):
        write_text(f2fs_h, f2fs_text)
    if trace_text != read_text(trace_h):
        write_text(trace_h, trace_text)
    if checkpoint_text != read_text(checkpoint_c):
        write_text(checkpoint_c, checkpoint_text)
    if super_text != read_text(super_c):
        write_text(super_c, super_text)
    if data_text != read_text(data_c):
        write_text(data_c, data_text)

    return {
        **usage(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="macro_compat_shim",
        ),
        "status": "compat_shims_applied",
        "marker_paths": [
            str(f2fs_h),
            str(trace_h),
            str(checkpoint_c),
            str(super_c),
            str(data_c),
        ],
        "anchors": {
            "enum_f2fs_lock_name": bool_status("enum f2fs_lock_name {" in read_text(f2fs_h)),
            "init_f2fs_rwsem_trace_macro": bool_status("init_f2fs_rwsem_trace(sem, sbi, name)" in read_text(f2fs_h)),
            "trace_helper_wrappers": bool_status("f2fs_down_read_trace(struct f2fs_rwsem *sem," in read_text(f2fs_h)),
            "trace_event_header": bool_status("TRACE_EVENT(f2fs_lock_elapsed_time," in read_text(trace_h)),
            "named_super_init": bool_status("init_f2fs_rwsem_trace(&sbi->cp_rwsem, sbi, LOCK_NAME_CP_RWSEM);" in read_text(super_c)),
            "named_io_init": bool_status("init_f2fs_rwsem_trace(&sbi->write_io[i][j].io_rwsem, sbi, LOCK_NAME_IO_RWSEM);" in read_text(data_c)),
            "checkpoint_marker": bool_status(checkpoint_marker.strip() in read_text(checkpoint_c)),
        },
        "compatibility_shims": [
            "enum f2fs_lock_name and enum f2fs_timeout_type backfilled into fs/f2fs/f2fs.h",
            "struct f2fs_time_stat and struct f2fs_lock_context added as compatibility-only definitions",
            "init_f2fs_rwsem_trace(sem, sbi, name) mapped onto legacy init_f2fs_rwsem(sem)",
            "f2fs_*_trace lock wrappers added as no-op compatibility helpers over legacy rwsem semantics",
            "super.c and data.c named lock init sites switched to the compatibility macro surface",
        ],
        "remaining_runtime_risk": [
            "Legacy 6.1 lock runtime semantics are preserved; full 7.0.12 elapsed-time tracing and priority uplift behavior is not ported by this shim.",
            "This child closes the current trace/header/init dependency gap but does not claim full 7.0.12 checkpoint lock instrumentation parity.",
        ],
    }


def build_report(
    *,
    current_common: Path,
    output_dir: Path,
    mainline_root: Path,
    coverage_root: Path,
    ufs_result: dict[str, object],
    block_result: dict[str, object],
    dm_result: dict[str, object],
    fscrypt_result: dict[str, object],
    f2fs_result: dict[str, object],
) -> dict[str, object]:
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_common_root": str(current_common),
        "status": "storage_whole_target_applied",
        "strategy": "dependency_closed_storage_transition",
        "reference_source": {
            "path": str(mainline_root),
            "kernelversion": run_kernelversion(mainline_root),
            "family": "7.0.12",
        },
        "coverage_map_source": {
            "path": str(coverage_root),
            "mode": "read_only",
        },
        "subsystems_covered": [
            "ufs",
            "block",
            "dm_core",
            "fscrypt_fname",
            "f2fs",
        ],
        "applied_groups": [
            "storage_whole_target_scaffold",
            "storage_ufs_surface_validation",
            "storage_block_surface_validation",
            "storage_dm_core_surface_validation",
            "storage_fscrypt_fname_surface_validation",
            "storage_f2fs_lock_trace_compat",
        ],
        "helper_sidecar_new_interface_usage": {
            "helper_graft_used": True,
            "sidecar_state_used": False,
            "new_interface_used": True,
            "new_interface_scope": [
                "marker_only_validation",
                "macro_compat_shim",
            ],
        },
        "compatibility_shims": f2fs_result["compatibility_shims"],
        "remaining_compile_runtime_risk": f2fs_result["remaining_runtime_risk"],
        "constraints": [
            "Keep ABK_F2FS_FIX_MODULE read-only and use it only as a coverage map.",
            "Do not replace whole storage files when an anchored helper or compatibility shim is enough.",
            "Do not change userspace-visible storage syscall or ioctl behavior in this child.",
            "Keep compatibility glue inside ABK_ABI_PATCH_SUITE ownership.",
        ],
        "subsystems": {
            "ufs": ufs_result,
            "block": block_result,
            "dm_core": dm_result,
            "fscrypt_fname": fscrypt_result,
            "f2fs": f2fs_result,
        },
    }

    (output_dir / "storage_whole_target_report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "storage_whole_target_report.md").write_text(
        "# ABK Storage Whole-Target Report\n\n"
        f"- Generated: `{report['generated_at_utc']}`\n"
        f"- Current tree: `{report['current_common_root']}`\n"
        f"- Status: `{report['status']}`\n"
        f"- Strategy: `{report['strategy']}`\n"
        f"- Reference source: `{report['reference_source']['kernelversion']}` at `{report['reference_source']['path']}`\n"
        f"- Coverage map: `{report['coverage_map_source']['path']}` ({report['coverage_map_source']['mode']})\n\n"
        "## Subsystems Covered\n\n"
        + "\n".join(f"- `{item}`" for item in report["subsystems_covered"])
        + "\n\n## Compatibility Shims\n\n"
        + "\n".join(f"- {item}" for item in report["compatibility_shims"])
        + "\n\n## Remaining Risk\n\n"
        + "\n".join(f"- {item}" for item in report["remaining_compile_runtime_risk"])
        + "\n"
    )
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        raise SystemExit(
            f"usage: {argv[0]} <current-common-root> <output-dir> <mainline-7012-root> <coverage-map-root>"
        )

    current_common = Path(argv[1])
    output_dir = Path(argv[2])
    mainline_root = Path(argv[3])
    coverage_root = Path(argv[4])
    output_dir.mkdir(parents=True, exist_ok=True)

    for path in (
        current_common / "drivers/ufs/core/ufshcd.c",
        current_common / "drivers/ufs/core/ufs-mcq.c",
        current_common / "drivers/ufs/core/ufshcd-crypto.c",
        current_common / "drivers/ufs/host/ufs-qcom.c",
        current_common / "block/blk-mq.c",
        current_common / "block/bio.c",
        current_common / "drivers/md/dm.c",
        current_common / "fs/crypto/fname.c",
        current_common / "fs/f2fs/f2fs.h",
        current_common / "fs/f2fs/checkpoint.c",
        current_common / "fs/f2fs/super.c",
        current_common / "fs/f2fs/data.c",
        current_common / "include/trace/events/f2fs.h",
    ):
        if not path.is_file():
            raise SystemExit(f"storage_whole_target: required file not found: {path}")

    if not mainline_root.is_dir():
        raise SystemExit(f"storage_whole_target: mainline reference root not found: {mainline_root}")
    if not coverage_root.is_dir():
        raise SystemExit(f"storage_whole_target: coverage map root not found: {coverage_root}")

    ufs_result = patch_ufs_surface(current_common)
    block_result = patch_block_surface(current_common)
    dm_result = patch_dm_surface(current_common)
    fscrypt_result = patch_fscrypt_surface(current_common)
    f2fs_result = patch_f2fs_lock_trace_compat(current_common)
    build_report(
        current_common=current_common,
        output_dir=output_dir,
        mainline_root=mainline_root,
        coverage_root=coverage_root,
        ufs_result=ufs_result,
        block_result=block_result,
        dm_result=dm_result,
        fscrypt_result=fscrypt_result,
        f2fs_result=f2fs_result,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
