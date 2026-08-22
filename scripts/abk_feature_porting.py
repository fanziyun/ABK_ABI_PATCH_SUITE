#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


# Restoring a half-patched tree needs the pre-patch bytes: every hard failure
# below aborts mid-run and leaves earlier files already rewritten on disk.
ABK_BACKUP_SUFFIX = ".abk-orig"


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
        "Port scan-based EEVDF selection and phase-two runtime-state maintenance onto the 6.1 fair.c shape.",
    ),
    PatchGroup(
        "sched_eevdf_runtime_state_phase3",
        "Tighten the scan-based EEVDF runtime-state graft into a phase-3 stable end-state without cfs_rq augmentation or fair.c replacement.",
    ),
    PatchGroup(
        "pid_alloc_hotpath_phase2",
        "Port alloc_pid() preload/retry and ENOSPC handling onto the 6.1 pid namespace shape without changing pid_namespace layout.",
    ),
    PatchGroup(
        "fd_alloc_hotpath",
        "Port lock-avoiding fd allocation and fdtable growth helpers onto fs/file.c without changing files_struct or fdtable layout.",
    ),
    PatchGroup(
        "close_range_hotpath",
        "Port bitmap-driven close_range() batching helpers onto fs/file.c without changing syscall-visible behavior.",
    ),
    PatchGroup(
        "blk_mq_async_depth",
        "Track blk-mq async_depth queue-depth policy across blk-mq, sysfs, and mq schedulers without widening storage scope.",
    ),
    PatchGroup(
        "zram_compressed_writeback",
        "Track and graft zram compressed writeback semantics onto the 6.1.118 target tree without replacing abk zram algorithm assets.",
    ),
    PatchGroup(
        "nohz_field_refinement",
        "Normalize legacy nohz tick_sched state fields into readable helpers and reportable anchors without widening into avg_idle or idle-governor rewrites.",
    ),
    PatchGroup(
        "avg_idle_preemption_mode",
        "Simplify avg_idle wake and scan gating by removing wake_avg_idle prediction while keeping the direct avg_idle newidle thresholds.",
    ),
    PatchGroup(
        "pidfd_preparation_compat",
        "Track the current pidfd surface and apply helper/report-level compat anchors without backporting pidfs or changing pidfd user ABI.",
    ),
    PatchGroup(
        "swap_table_phase2_large_folios",
        "Graft folio-first swapcache and readahead helpers onto mm/swap_state.c while retaining page-surface wrappers for the 6.1 tree.",
    ),
    PatchGroup(
        "slab_alloc_free_hotpath",
        "Tighten the 6.1 SLUB alloc/free hotpath with a shared bulk-free backend, free-side validation split, and bulk alloc prefetch.",
    ),
    PatchGroup(
        "hugepage_fault_alloc_fastpath",
        "Tighten anonymous THP fault-time allocation into a file-local helper split that keeps THP fault fallback tracking and PMD fault routing intact.",
    ),
    PatchGroup(
        "io_uring_nowait_core",
        "Extend the 6.1 io_uring core issue path, fixed-file bookkeeping, and request ref helpers toward 7.0.12-style NOWAIT propagation without replacing whole files.",
    ),
    PatchGroup(
        "io_uring_nowait_rw_net",
        "Extend io_uring rw/net/poll/openclose NOWAIT handling with helper grafts and local retry-policy fixups instead of whole-file replacement.",
    ),
    PatchGroup(
        "io_uring_support_modules",
        "Classify 7.0.12-only io_uring support modules as applied, deferred, scope-blocked, or blocked by missing 6.1 anchors before any broad module import.",
    ),
    PatchGroup(
        "io_uring_feature_porting_fixups",
        "Reserve follow-up glue fixes discovered after the first io_uring NOWAIT and support-module graft batch.",
    ),
    PatchGroup(
        "feature_porting_fixups",
        "Reserve follow-up glue fixes discovered after the runtime-state migration batch.",
    ),
)


IO_URING_SUPPORT_MODULES: dict[str, tuple[str, ...]] = {
    "register": ("register.c", "register.h"),
    "wait": ("wait.c", "wait.h"),
    "waitid": ("waitid.c", "waitid.h"),
    "futex": ("futex.c", "futex.h"),
    "napi": ("napi.c", "napi.h"),
    "eventfd": ("eventfd.c", "eventfd.h"),
    "query": ("query.c", "query.h"),
    "memmap": ("memmap.c", "memmap.h"),
    "truncate": ("truncate.c", "truncate.h"),
    "mock_file": ("mock_file.c",),
    "bpf_filter": ("bpf_filter.c", "bpf_filter.h"),
    "zcrx": ("zcrx.c", "zcrx.h"),
    "cmd_net": ("cmd_net.c",),
    "alloc_cache": ("alloc_cache.c",),
    "tw": ("tw.c", "tw.h"),
    "Kconfig": ("Kconfig",),
}


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


def ensure_contains_any(path: Path, needles: list[str], label: str) -> None:
    """Presence check that accepts any of several spellings.

    A signature can gain parameters between target families without changing the
    code a graft depends on: 6.1 threads a `struct list_lru *lru` through
    slab_alloc_node() for memcg accounting, 5.15 does not. Pin the function, not
    one release's parameter list.
    """
    text = read_text(path)
    if any(needle in text for needle in needles):
        return
    raise SystemExit(f"{label}: no known anchor found in {path}")


def optional_patch(fn, label: str, status: str = "blocked_by_missing_anchor"):
    """Run a patch whose anchors may legitimately be absent on older trees.

    Mirrors ABK's own apply_susfs_optional_patch(): a missing anchor becomes a
    warning plus a recorded status, not an aborted kernel build. Reserve this
    for capabilities that are optional by design — a required graft that half
    applied must still fail loudly.
    """
    try:
        return fn()
    except SystemExit as exc:
        print(f"::warning::{label} skipped: {exc}")
        return skipped_status(status, str(exc))


def skipped_status(status: str, reason: str, path: Path | None = None) -> dict[str, object]:
    """Result stand-in for a capability that was not attempted.

    build_report() indexes status dicts directly, so a skip has to carry the
    same keys a real run would. Anything the report asks for that is not listed
    here resolves through the defaults in report_field().
    """
    return {
        "status": status,
        "skipped_reason": reason,
        "path": str(path) if path is not None else None,
        "phase": "skipped",
        "next_action": f"not applicable on this tree: {reason}",
    }


def report_field(status: dict[str, object], key: str) -> object:
    """Read a report field, tolerating keys a skipped capability never set."""
    if key in status:
        return status[key]
    if status.get("status", "").startswith("blocked_by") or status.get("skipped_reason"):
        return "n/a"
    raise KeyError(key)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected block missing")
    return text.replace(old, new, 1)


# kernel/sched/fair.c shape differences between android14-6.1 and android13-5.15.
# All of these are renames or extra vendor-hook lines, not semantic changes, so
# the graft itself is unaffected -- only the literals used to locate it are.
#
# Verified against deprecated/android13-5.15-2024-11 (SUBLEVEL 167):
#   6.1 renamed the schedstat helpers with a _fair suffix
#   6.1 hoisted `int action = UPDATE_TG` to the top of dequeue_entity()
#   5.15 ends place_entity() with a trace_android_rvh_place_entity() hook
_FAIR_5_15_RENAMES = (
    ("update_stats_dequeue_fair(", "update_stats_dequeue("),
    ("update_stats_wait_end_fair(", "update_stats_wait_end("),
    ("update_stats_wait_start_fair(", "update_stats_wait_start("),
    ("update_stats_enqueue_fair(", "update_stats_enqueue("),
)
_FAIR_6_1_DEQUEUE_ACTION = "{\n\tint action = UPDATE_TG;\n"
_FAIR_5_15_PLACE_TAIL = (
    "\t\tse->vruntime = max_vruntime(se->vruntime, vruntime);\n",
    "\t\tse->vruntime = max_vruntime(se->vruntime, vruntime);\n"
    "\ttrace_android_rvh_place_entity(cfs_rq, se, initial, &vruntime);\n",
)


def fair_shape_for_tree(text: str, snippet: str) -> str:
    """Rewrite a fair.c literal to match the shape this tree actually uses.

    Applied to both halves of each replacement, so the graft lands in the local
    idiom instead of reintroducing 6.1 spellings the tree would fail to compile.
    """
    for new_name, old_name in _FAIR_5_15_RENAMES:
        if new_name in snippet and new_name not in text and old_name in text:
            snippet = snippet.replace(new_name, old_name)

    if _FAIR_6_1_DEQUEUE_ACTION in snippet and _FAIR_6_1_DEQUEUE_ACTION not in text:
        snippet = snippet.replace(_FAIR_6_1_DEQUEUE_ACTION, "{\n")

    plain, hooked = _FAIR_5_15_PLACE_TAIL
    if plain in snippet and hooked not in snippet and hooked in text:
        snippet = snippet.replace(plain, hooked, 1)

    return snippet


def replace_once_fair(text: str, old: str, new: str, label: str) -> str:
    """replace_once() that tolerates fair.c shape drift across target families."""
    return replace_once(
        text,
        fair_shape_for_tree(text, old),
        fair_shape_for_tree(text, new),
        label,
    )


# Block layer shape differences between android14-6.1 and android13-5.15.
#
# Unlike the fair.c set these are not all renames: 6.1 carries request flags
# (RQF_ELV, RQF_RESV) and a queue flag (QUEUE_FLAG_SQ_SCHED) that do not exist
# on 5.15, and it embeds sbitmap_queue in blk_mq_tags where 5.15 points at it.
# So the substitutions below cover naming and access form; call sites that lean
# on an absent flag are rewritten per-site in patch_blk_mq_async_depth().
#
# Verified against deprecated/android13-5.15-2024-11 (SUBLEVEL 167).
_BLK_5_15_RENAMES = (
    ("BLKDEV_DEFAULT_RQ", "BLKDEV_MAX_RQ"),
    ("blk_mq_is_shared_tags(", "blk_mq_is_sbitmap_shared("),
    ("__blk_mq_alloc_requests(", "__blk_mq_alloc_request("),
)

# blk_opf_t is a 6.1 addition: the request operation carried as a distinct type
# instead of a bare unsigned int. Rewrite it wherever the tree lacks the typedef,
# including in code the graft introduces.
_BLK_OPF_T = "blk_opf_t "


def blk_shape_for_tree(text: str, snippet: str) -> str:
    """Rewrite a block-layer literal into the shape this tree uses."""
    for new_name, old_name in _BLK_5_15_RENAMES:
        if new_name in snippet and new_name not in text and old_name in text:
            snippet = snippet.replace(new_name, old_name)

    if _BLK_OPF_T in snippet and "blk_opf_t" not in text:
        snippet = snippet.replace(_BLK_OPF_T, "unsigned int ")
        snippet = snippet.replace("blk_opf_t,", "unsigned int,")

    # 6.1 embeds the sbitmap_queue in struct blk_mq_tags; 5.15 points at it, so
    # dereferences need -> and taking the member's address would yield
    # sbitmap_queue **. A "bitmap_tags->" already in the file is the tell.
    if "bitmap_tags->" in text:
        snippet = re.sub(r"&(\w+(?:->\w+)*)->bitmap_tags\b", r"\1->bitmap_tags", snippet)
        snippet = snippet.replace("bitmap_tags.", "bitmap_tags->")

    return snippet


def replace_once_blk(text: str, old: str, new: str, label: str) -> str:
    """replace_once() that tolerates block-layer shape drift."""
    return replace_once(
        text,
        blk_shape_for_tree(text, old),
        blk_shape_for_tree(text, new),
        label,
    )


def replace_within(text: str, start: str, end: str, old: str, new: str, label: str) -> str:
    start_idx = text.find(start)
    if start_idx < 0:
        raise SystemExit(f"{label}: start anchor missing")
    end_idx = text.find(end, start_idx)
    if end_idx < 0:
        raise SystemExit(f"{label}: end anchor missing")

    scoped = text[start_idx:end_idx]
    if old not in scoped:
        raise SystemExit(f"{label}: expected scoped block missing")
    scoped = scoped.replace(old, new, 1)
    return text[:start_idx] + scoped + text[end_idx:]


def replace_scope(text: str, start: str, end: str, new: str, label: str) -> str:
    start_idx = text.find(start)
    if start_idx < 0:
        raise SystemExit(f"{label}: start anchor missing")
    end_idx = text.find(end, start_idx)
    if end_idx < 0:
        raise SystemExit(f"{label}: end anchor missing")
    return text[:start_idx] + new + text[end_idx:]


def find_c_block_from_index(text: str, start_idx: int, label: str) -> tuple[int, int]:
    brace_idx = text.find("{", start_idx)
    if brace_idx < 0:
        raise SystemExit(f"{label}: opening brace missing")

    depth = 0
    idx = brace_idx
    while idx < len(text):
        if text.startswith("/*", idx):
            end = text.find("*/", idx + 2)
            if end < 0:
                raise SystemExit(f"{label}: unterminated block comment")
            idx = end + 2
            continue
        if text.startswith("//", idx):
            end = text.find("\n", idx + 2)
            if end < 0:
                return start_idx, len(text)
            idx = end + 1
            continue

        char = text[idx]
        if char in ("'", '"'):
            quote = char
            idx += 1
            while idx < len(text):
                if text[idx] == "\\":
                    idx += 2
                    continue
                if text[idx] == quote:
                    idx += 1
                    break
                idx += 1
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start_idx, idx + 1
        idx += 1

    raise SystemExit(f"{label}: closing brace missing")


def find_c_block(text: str, start: str, label: str) -> tuple[int, int]:
    start_idx = text.find(start)
    if start_idx < 0:
        raise SystemExit(f"{label}: start anchor missing")
    return find_c_block_from_index(text, start_idx, label)


def find_c_block_regex(text: str, pattern: str, label: str) -> tuple[int, int]:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise SystemExit(f"{label}: start anchor missing")
    return find_c_block_from_index(text, match.start(), label)


def bool_status(value: bool) -> str:
    return "present" if value else "missing"


def graft_metadata(
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


def patch_sched_entity_fields(common_root: Path) -> dict[str, object]:
    sched_h = common_root / "include/linux/sched.h"
    text = read_text(sched_h)
    se_start = "struct sched_entity {\n"
    se_end = "\nstruct sched_rt_entity {\n"
    rt_start = "struct sched_rt_entity {\n"
    rt_end = "\nstruct sched_dl_entity {\n"

    ensure_contains(sched_h, se_start, "feature_porting/sched_entity")
    if (
        "ANDROID_KABI_RESERVE(1);" not in text
        and "ANDROID_KABI_USE(1, u64 deadline);" not in text
    ):
        raise SystemExit(f"feature_porting/sched_entity: no usable KABI anchors in {sched_h}")

    se_scope = text[text.find(se_start):text.find(se_end)]
    rt_scope = text[text.find(rt_start):text.find(rt_end)]

    already_done = (
        "ANDROID_KABI_USE(1, u64 deadline);" in se_scope
        and "ANDROID_KABI_USE(2, u64 min_vruntime);" in se_scope
        and "ANDROID_KABI_USE(3, s64 vlag);" in se_scope
        and "ANDROID_KABI_USE(4, u64 slice);" in se_scope
    )
    old = """\n\tANDROID_KABI_RESERVE(1);\n\tANDROID_KABI_RESERVE(2);\n\tANDROID_KABI_RESERVE(3);\n\tANDROID_KABI_RESERVE(4);\n"""
    old_broken = """\n\tANDROID_KABI_USE(1, u64 deadline);\n\tANDROID_KABI_USE(2, u64 min_vruntime);\n\tANDROID_KABI_USE(3, struct {\n\t\tu64 min_slice;\n\t\tu64 max_slice;\n\t});\n\tANDROID_KABI_USE(4, struct {\n\t\ts64 vlag;\n\t\tu64 slice;\n\t});\n"""
    new = """\n\tANDROID_KABI_USE(1, u64 deadline);\n\tANDROID_KABI_USE(2, u64 min_vruntime);\n\tANDROID_KABI_USE(3, s64 vlag);\n\tANDROID_KABI_USE(4, u64 slice);\n"""
    rt_old = """\n\tANDROID_KABI_USE(1, u64 deadline);\n\tANDROID_KABI_USE(2, u64 min_vruntime);\n\tANDROID_KABI_USE(3, s64 vlag);\n\tANDROID_KABI_USE(4, u64 slice);\n"""

    if not already_done:
        if old in se_scope:
            text = replace_within(text, se_start, se_end, old, new, "feature_porting/sched_entity")
        else:
            text = replace_within(text, se_start, se_end, old_broken, new, "feature_porting/sched_entity_upgrade")

    if rt_old in rt_scope:
        text = replace_within(text, rt_start, rt_end, rt_old, old, "feature_porting/sched_rt_restore")

    if not already_done or rt_old in rt_scope:
        marker = "\t/* ABK feature_porting: first-stage EEVDF fields mapped onto Android KABI reserve slots. */\n"
        anchor = "\n#ifdef CONFIG_SMP\n"
        if marker not in text and anchor in text:
            text = text.replace(anchor, "\n" + marker + "#ifdef CONFIG_SMP\n", 1)
        write_text(sched_h, text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=False,
            new_interface_scope="none",
        ),
        "path": str(sched_h),
        "eevdf_core_fields": {
            "deadline": "ANDROID_KABI_USE(1, u64 deadline);",
            "min_vruntime": "ANDROID_KABI_USE(2, u64 min_vruntime);",
            "vlag": "ANDROID_KABI_USE(3, s64 vlag);",
            "slice": "ANDROID_KABI_USE(4, u64 slice);",
        },
    }


def _patch_fair_reweight_compat(text: str, label: str) -> str:
    signature = "static void reweight_entity(struct cfs_rq *cfs_rq, struct sched_entity *se,"
    start_idx, end_idx = find_c_block(text, signature, label)
    scope = text[start_idx:end_idx]

    if "bool queued = se->on_rq;" in scope:
        return text

    if "bool curr = cfs_rq->curr == se;\n" not in scope:
        decl_anchor = "{\n"
        if decl_anchor not in scope:
            raise SystemExit(f"{label}: expected function opening missing")
        scope = scope.replace(
            decl_anchor,
            "{\n"
            "\tbool curr = cfs_rq->curr == se;\n"
            "\tbool queued = se->on_rq;\n"
            "\tunsigned long old_weight = max_t(unsigned long, se->load.weight, 1UL);\n"
            "\tunsigned long new_weight = max_t(unsigned long, weight, 1UL);\n\n",
            1,
        )

    scoped_patterns = (
        (
            re.compile(
                r"\tif \(se->on_rq\) \{\n.*?\t\tupdate_load_sub\(&cfs_rq->load, se->load.weight\);\n\t\}\n",
                re.DOTALL,
            ),
            "\tif (queued) {\n"
            "\t\t/* commit outstanding execution time before preserving lag/deadline */\n"
            "\t\tif (curr)\n"
            "\t\t\tupdate_curr(cfs_rq);\n"
            "\t\tabk_eevdf_update_lag(cfs_rq, se);\n"
            "\t\tabk_eevdf_store_rel_deadline(se);\n"
            "\t\tif (!curr)\n"
            "\t\t\t__dequeue_entity(cfs_rq, se);\n"
            "\t\tupdate_load_sub(&cfs_rq->load, se->load.weight);\n"
            "\t}\n",
            "queued pre-update branch",
        ),
        (
            re.compile(
                r"\tdequeue_load_avg\(cfs_rq, se\);\n(?:\n)+\tupdate_load_set\(&se->load, weight\);\n"
            ),
            "\tdequeue_load_avg(cfs_rq, se);\n\n"
            "\tse->vlag = div_s64(se->vlag * (s64)old_weight, new_weight);\n"
            "\tabk_eevdf_scale_rel_deadline(se, old_weight, new_weight);\n"
            "\tupdate_load_set(&se->load, weight);\n",
            "lag/deadline scaling block",
        ),
        (
            re.compile(
                r"\tenqueue_load_avg\(cfs_rq, se\);\n\tif \(se->on_rq\)\n\t\tupdate_load_add\(&cfs_rq->load, se->load.weight\);\n"
            ),
            "\tenqueue_load_avg(cfs_rq, se);\n"
            "\tif (queued) {\n"
            "\t\tplace_entity(cfs_rq, se, 0);\n"
            "\t\tupdate_load_add(&cfs_rq->load, se->load.weight);\n"
            "\t\tif (!curr)\n"
            "\t\t\t__enqueue_entity(cfs_rq, se);\n"
            "\t}\n",
            "queued restore block",
        ),
    )

    for pattern, replacement, desc in scoped_patterns:
        scope, count = pattern.subn(replacement, scope, count=1)
        if count != 1:
            raise SystemExit(f"{label}: expected {desc} missing")

    return text[:start_idx] + scope + text[end_idx:]


def patch_sched_pick_logic(common_root: Path) -> dict[str, object]:
    fair_c = common_root / "kernel/sched/fair.c"
    text = read_text(fair_c)

    ensure_contains(fair_c, "static inline bool entity_before(struct sched_entity *a,", "feature_porting/fair")
    ensure_contains(fair_c, "static u64 sched_vslice(struct cfs_rq *cfs_rq, struct sched_entity *se)", "feature_porting/fair")
    ensure_contains(fair_c, "static void reweight_entity(struct cfs_rq *cfs_rq, struct sched_entity *se,", "feature_porting/fair")
    ensure_contains(fair_c, "static void\nplace_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int initial)\n{", "feature_porting/fair")
    ensure_contains(fair_c, "enqueue_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int flags)\n{", "feature_porting/fair")
    ensure_contains(fair_c, "check_preempt_tick(struct cfs_rq *cfs_rq, struct sched_entity *curr)", "feature_porting/fair")
    ensure_contains(fair_c, "void set_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *se)\n{", "feature_porting/fair")
    ensure_contains(fair_c, "pick_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *curr)", "feature_porting/fair")
    ensure_contains(fair_c, "static void put_prev_entity(struct cfs_rq *cfs_rq, struct sched_entity *prev)\n{", "feature_porting/fair")
    ensure_contains(fair_c, "static void\ndequeue_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int flags)\n{", "feature_porting/fair")
    ensure_contains(fair_c, "entity_tick(struct cfs_rq *cfs_rq, struct sched_entity *curr, int queued)\n{", "feature_porting/fair")

    marker = "/* ABK feature_porting: scan-based EEVDF runtime-state graft. */"
    if marker in text:
        place_forward_anchor = """static inline void\ndequeue_load_avg(struct cfs_rq *cfs_rq, struct sched_entity *se) { }\n#endif\n\n"""
        place_forward_new = """static inline void\ndequeue_load_avg(struct cfs_rq *cfs_rq, struct sched_entity *se) { }\n#endif\n\nstatic void\nplace_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int initial);\n\n"""
        if "\tse->min_slice = slice;\n\tse->max_slice = slice;\n" in text:
            text = text.replace("\tse->min_slice = slice;\n\tse->max_slice = slice;\n", "", 1)
        if "static void\nplace_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int initial);\n\nstatic void reweight_entity(" not in text:
            text = replace_once_fair(text, place_forward_anchor, place_forward_new, "feature_porting/fair_place_forward_backfill")
        if text != read_text(fair_c):
            write_text(fair_c, text)
        return {
            **graft_metadata(
                hard_port_possible=False,
                semantic_port_used=True,
                max_function_port_used=False,
                sidecar_state_used=False,
                sidecar_state_scope="none",
                new_interface_used=True,
                new_interface_scope="file_local_helper",
            ),
            "path": str(fair_c),
            "mode": "already_patched",
            "pick_logic": "scan_based_eevdf_phase2",
            "phase": "scan_based_runtime_parity",
            "runtime_state_extended": True,
            "tree_escalation_required": False,
        }

    helper_anchor = """static u64 sched_vslice(struct cfs_rq *cfs_rq, struct sched_entity *se)\n{\n\treturn calc_delta_fair(sched_slice(cfs_rq, se), se);\n}\n"""
    helper_block = helper_anchor + """

/* ABK feature_porting: scan-based EEVDF runtime-state graft. */
#define ABK_EEVDF_REL_DEADLINE_BIT (1ULL << 63)
#define ABK_EEVDF_REL_DEADLINE_MASK (ABK_EEVDF_REL_DEADLINE_BIT - 1)

static inline u64 abk_eevdf_slice(struct cfs_rq *cfs_rq, struct sched_entity *se)
{
\tu64 slice = sched_slice(cfs_rq, se);

\tse->slice = slice;
\treturn slice;
}

static inline u64 abk_eevdf_vslice(struct cfs_rq *cfs_rq, struct sched_entity *se)
{
\tu64 slice = abk_eevdf_slice(cfs_rq, se);

\treturn max_t(u64, calc_delta_fair(slice, se), 1ULL);
}

u64 avg_vruntime(struct cfs_rq *cfs_rq)
{
\tstruct sched_entity *curr = cfs_rq->curr;
\tstruct rb_node *node;
\ts64 weighted = 0;
\tlong total = 0;

\tfor (node = rb_first_cached(&cfs_rq->tasks_timeline); node; node = rb_next(node)) {
\t\tstruct sched_entity *se = __node_2_se(node);
\t\tunsigned long weight = max_t(unsigned long, scale_load_down(se->load.weight), 1UL);

\t\tweighted += (s64)(se->vruntime - cfs_rq->min_vruntime) * weight;
\t\ttotal += weight;
\t}

\tif (curr && curr->on_rq) {
\t\tunsigned long weight = max_t(unsigned long, scale_load_down(curr->load.weight), 1UL);

\t\tweighted += (s64)(curr->vruntime - cfs_rq->min_vruntime) * weight;
\t\ttotal += weight;
\t}

\tif (!total)
\t\treturn cfs_rq->min_vruntime;

\tif (weighted < 0)
\t\tweighted -= total - 1;

\treturn cfs_rq->min_vruntime + div_s64(weighted, total);
}

static inline bool abk_eevdf_has_rel_deadline(const struct sched_entity *se)
{
\treturn se->min_vruntime & ABK_EEVDF_REL_DEADLINE_BIT;
}

static inline u64 abk_eevdf_get_rel_deadline(const struct sched_entity *se)
{
\treturn se->min_vruntime & ABK_EEVDF_REL_DEADLINE_MASK;
}

static inline void abk_eevdf_set_rel_deadline(struct sched_entity *se, u64 deadline)
{
\tse->min_vruntime = ABK_EEVDF_REL_DEADLINE_BIT |
\t\t\t   (deadline & ABK_EEVDF_REL_DEADLINE_MASK);
}

static inline u64 abk_eevdf_take_rel_deadline(struct sched_entity *se)
{
\tu64 deadline = abk_eevdf_get_rel_deadline(se);

\tse->min_vruntime = 0;
\treturn deadline;
}

static inline void abk_eevdf_store_rel_deadline(struct sched_entity *se)
{
\tu64 deadline = 0;

\tif (se->deadline && (s64)(se->deadline - se->vruntime) > 0)
\t\tdeadline = se->deadline - se->vruntime;

\tabk_eevdf_set_rel_deadline(se, deadline);
}

static inline void abk_eevdf_scale_rel_deadline(struct sched_entity *se,
\t\t\t\t\t\tunsigned long old_weight,
\t\t\t\t\t\tunsigned long new_weight)
{
\tu64 deadline;

\tif (!abk_eevdf_has_rel_deadline(se))
\t\treturn;

\tdeadline = abk_eevdf_get_rel_deadline(se);
\tif (deadline)
\t\tdeadline = div_u64(deadline * old_weight, new_weight);

\tabk_eevdf_set_rel_deadline(se, deadline);
}

static inline bool abk_eevdf_entity_before(const struct sched_entity *a,
\t\t\t\t\t      const struct sched_entity *b)
{
\tif (!a)
\t\treturn false;
\tif (!b)
\t\treturn true;

\tif (a->deadline == b->deadline)
\t\treturn (s64)(a->vruntime - b->vruntime) < 0;

\treturn (s64)(a->deadline - b->deadline) < 0;
}

static inline bool abk_eevdf_eligible(struct sched_entity *se, u64 avruntime)
{
\treturn (s64)(avruntime - se->vruntime) >= 0;
}

static unsigned long abk_eevdf_total_weight(struct cfs_rq *cfs_rq)
{
\tstruct sched_entity *curr = cfs_rq->curr;
\tstruct rb_node *node;
\tunsigned long total = 0;

\tfor (node = rb_first_cached(&cfs_rq->tasks_timeline); node; node = rb_next(node)) {
\t\tstruct sched_entity *se = __node_2_se(node);

\t\ttotal += max_t(unsigned long, scale_load_down(se->load.weight), 1UL);
\t}

\tif (curr && curr->on_rq)
\t\ttotal += max_t(unsigned long, scale_load_down(curr->load.weight), 1UL);

\treturn total;
}

static u64 abk_eevdf_max_slice(struct cfs_rq *cfs_rq, struct sched_entity *hint)
{
\tstruct sched_entity *curr = cfs_rq->curr;
\tstruct rb_node *node;
\tu64 max_slice = 0;

\tif (hint)
\t\tmax_slice = max(max_slice, abk_eevdf_slice(cfs_rq, hint));

\tfor (node = rb_first_cached(&cfs_rq->tasks_timeline); node; node = rb_next(node)) {
\t\tstruct sched_entity *se = __node_2_se(node);

\t\tmax_slice = max(max_slice, abk_eevdf_slice(cfs_rq, se));
\t}

\tif (curr && curr->on_rq)
\t\tmax_slice = max(max_slice, abk_eevdf_slice(cfs_rq, curr));

\treturn max_t(u64, max_slice, 1ULL);
}

static s64 abk_eevdf_lag_limit(struct cfs_rq *cfs_rq, struct sched_entity *se)
{
\tu64 max_slice = abk_eevdf_max_slice(cfs_rq, se);

\tmax_slice += sysctl_sched_min_granularity;
\treturn max_t(s64, (s64)calc_delta_fair(max_slice, se), 1LL);
}

static void abk_eevdf_update_lag(struct cfs_rq *cfs_rq, struct sched_entity *se)
{
\ts64 vlag;
\ts64 limit;

\tvlag = (s64)(avg_vruntime(cfs_rq) - se->vruntime);
\tlimit = abk_eevdf_lag_limit(cfs_rq, se);
\tse->vlag = clamp_t(s64, vlag, -limit, limit);
}

static s64 abk_eevdf_preserved_lag(struct cfs_rq *cfs_rq, struct sched_entity *se)
{
\tunsigned long load = abk_eevdf_total_weight(cfs_rq);
\tunsigned long weight = max_t(unsigned long, scale_load_down(se->load.weight), 1UL);
\ts64 lag = se->vlag;
\ts64 limit = abk_eevdf_lag_limit(cfs_rq, se);

\tlag = clamp_t(s64, lag, -limit, limit);
\tif (load)
\t\tlag = div_s64(lag * (load + weight), load);

\treturn lag;
}

static void abk_eevdf_apply_lag_placement(struct cfs_rq *cfs_rq,
\t\t\t\t\t  struct sched_entity *se, s64 lag)
{
\tu64 avruntime = avg_vruntime(cfs_rq);

\tif (lag > 0) {
\t\tu64 delta = min_t(u64, avruntime, (u64)lag);

\t\tse->vruntime = avruntime - delta;
\t} else if (lag < 0) {
\t\tse->vruntime = avruntime + (u64)(-lag);
\t} else {
\t\tse->vruntime = avruntime;
\t}
}

static bool abk_eevdf_refresh_deadline(struct cfs_rq *cfs_rq,
\t\t\t\t       struct sched_entity *se)
{
\tu64 vslice = abk_eevdf_vslice(cfs_rq, se);

\tif (abk_eevdf_has_rel_deadline(se)) {
\t\tu64 rel_deadline = abk_eevdf_take_rel_deadline(se);

\t\tse->deadline = se->vruntime + rel_deadline;
\t}

\tif (se->deadline && (s64)(se->vruntime - se->deadline) < 0)
\t\treturn false;

\tse->deadline = se->vruntime + vslice;
\tavg_vruntime(cfs_rq);
\tabk_eevdf_update_lag(cfs_rq, se);
\treturn true;
}

static void abk_eevdf_place_entity(struct cfs_rq *cfs_rq,
\t\t\t\t struct sched_entity *se, int initial)
{
\tbool rel_deadline = abk_eevdf_has_rel_deadline(se);
\ts64 lag = 0;
\tu64 vslice = abk_eevdf_vslice(cfs_rq, se);

\tif (!initial && (se->vlag || rel_deadline)) {
\t\tlag = abk_eevdf_preserved_lag(cfs_rq, se);
\t\tabk_eevdf_apply_lag_placement(cfs_rq, se, lag);
\t}

\tif (rel_deadline) {
\t\tu64 rel = abk_eevdf_take_rel_deadline(se);

\t\tif (!rel)
\t\t\trel = vslice;
\t\tse->deadline = se->vruntime + rel;
\t\tse->vlag = 0;
\t\treturn;
\t}

\tif (initial)
\t\tvslice = max_t(u64, vslice >> 1, 1ULL);

\tse->deadline = se->vruntime + vslice;
\tse->vlag = 0;
}

static struct sched_entity *abk_pick_eevdf(struct cfs_rq *cfs_rq,
\t\t\t\t\t  struct sched_entity *curr)
{
\tstruct sched_entity *best = NULL;
\tstruct sched_entity *next = cfs_rq->next;
\tstruct rb_node *node;
\tu64 avruntime = avg_vruntime(cfs_rq);

\tif (curr && curr->on_rq) {
\t\tabk_eevdf_refresh_deadline(cfs_rq, curr);
\t\tif (abk_eevdf_eligible(curr, avruntime))
\t\t\tbest = curr;
\t}

\tif (next && next->on_rq) {
\t\tabk_eevdf_refresh_deadline(cfs_rq, next);
\t\tif (abk_eevdf_eligible(next, avruntime) &&
\t\t    abk_eevdf_entity_before(next, best))
\t\t\tbest = next;
\t}

\tfor (node = rb_first_cached(&cfs_rq->tasks_timeline); node; node = rb_next(node)) {
\t\tstruct sched_entity *se = __node_2_se(node);

\t\tabk_eevdf_refresh_deadline(cfs_rq, se);
\t\tif (!abk_eevdf_eligible(se, avruntime))
\t\t\tcontinue;
\t\tif (cfs_rq->skip == se)
\t\t\tcontinue;
\t\tif (abk_eevdf_entity_before(se, best))
\t\t\tbest = se;
\t}

\tif (!best)
\t\tbest = curr && curr->on_rq ? curr : __pick_first_entity(cfs_rq);

\treturn best;
}
"""
    text = replace_once_fair(text, helper_anchor, helper_block, "feature_porting/fair_helpers")

    next_helper_old = """static struct sched_entity *__pick_next_entity(struct sched_entity *se)\n"""
    next_helper_new = """static __maybe_unused struct sched_entity *__pick_next_entity(struct sched_entity *se)\n"""
    if next_helper_old in text and next_helper_new not in text:
        text = replace_once_fair(text, next_helper_old, next_helper_new, "feature_porting/fair_pick_next_helper")

    place_forward_anchor = """static inline void\ndequeue_load_avg(struct cfs_rq *cfs_rq, struct sched_entity *se) { }\n#endif\n\n"""
    place_forward_new = """static inline void\ndequeue_load_avg(struct cfs_rq *cfs_rq, struct sched_entity *se) { }\n#endif\n\nstatic void\nplace_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int initial);\n\n"""
    if "static void\nplace_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int initial);\n\nstatic void reweight_entity(" not in text:
        text = replace_once_fair(text, place_forward_anchor, place_forward_new, "feature_porting/fair_place_forward")

    reweight_old = """static void reweight_entity(struct cfs_rq *cfs_rq, struct sched_entity *se,\n\t\t\t    unsigned long weight)\n{\n\tif (se->on_rq) {\n\t\t/* commit outstanding execution time */\n\t\tif (cfs_rq->curr == se)\n\t\t\tupdate_curr(cfs_rq);\n\t\tupdate_load_sub(&cfs_rq->load, se->load.weight);\n\t}\n\tdequeue_load_avg(cfs_rq, se);\n\n\tupdate_load_set(&se->load, weight);\n\n#ifdef CONFIG_SMP\n\tdo {\n\t\tu32 divider = get_pelt_divider(&se->avg);\n\n\t\tse->avg.load_avg = div_u64(se_weight(se) * se->avg.load_sum, divider);\n\t} while (0);\n#endif\n\n\tenqueue_load_avg(cfs_rq, se);\n\tif (se->on_rq)\n\t\tupdate_load_add(&cfs_rq->load, se->load.weight);\n\n}\n"""
    reweight_new = """static void reweight_entity(struct cfs_rq *cfs_rq, struct sched_entity *se,\n\t\t\t    unsigned long weight)\n{\n\tbool curr = cfs_rq->curr == se;\n\tbool queued = se->on_rq;\n\tunsigned long old_weight = max_t(unsigned long, se->load.weight, 1UL);\n\tunsigned long new_weight = max_t(unsigned long, weight, 1UL);\n\n\tif (queued) {\n\t\t/* commit outstanding execution time before preserving lag/deadline */\n\t\tif (curr)\n\t\t\tupdate_curr(cfs_rq);\n\t\tabk_eevdf_update_lag(cfs_rq, se);\n\t\tabk_eevdf_store_rel_deadline(se);\n\t\tif (!curr)\n\t\t\t__dequeue_entity(cfs_rq, se);\n\t\tupdate_load_sub(&cfs_rq->load, se->load.weight);\n\t}\n\tdequeue_load_avg(cfs_rq, se);\n\n\tse->vlag = div_s64(se->vlag * (s64)old_weight, new_weight);\n\tabk_eevdf_scale_rel_deadline(se, old_weight, new_weight);\n\tupdate_load_set(&se->load, weight);\n\n#ifdef CONFIG_SMP\n\tdo {\n\t\tu32 divider = get_pelt_divider(&se->avg);\n\n\t\tse->avg.load_avg = div_u64(se_weight(se) * se->avg.load_sum, divider);\n\t} while (0);\n#endif\n\n\tenqueue_load_avg(cfs_rq, se);\n\tif (queued) {\n\t\tplace_entity(cfs_rq, se, 0);\n\t\tupdate_load_add(&cfs_rq->load, se->load.weight);\n\t\tif (!curr)\n\t\t\t__enqueue_entity(cfs_rq, se);\n\t}\n\n}\n"""
    if reweight_old in text:
        text = replace_once_fair(text, reweight_old, reweight_new, "feature_porting/fair_reweight")
    elif reweight_new not in text:
        text = _patch_fair_reweight_compat(text, "feature_porting/fair_reweight")

    enqueue_old = """\tif (flags & ENQUEUE_WAKEUP)\n\t\tplace_entity(cfs_rq, se, 0);\n"""
    enqueue_new = """\tif ((flags & ENQUEUE_WAKEUP) || abk_eevdf_has_rel_deadline(se) || se->vlag)\n\t\tplace_entity(cfs_rq, se, 0);\n"""
    text = replace_once_fair(text, enqueue_old, enqueue_new, "feature_porting/fair_enqueue")

    dequeue_head_old = """static void\ndequeue_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int flags)\n{\n\tint action = UPDATE_TG;\n"""
    dequeue_head_new = """static void\ndequeue_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int flags)\n{\n\tint action = UPDATE_TG;\n\tbool sleep = flags & DEQUEUE_SLEEP;\n"""
    text = replace_once_fair(text, dequeue_head_old, dequeue_head_new, "feature_porting/fair_dequeue_head")

    dequeue_old = """\tupdate_stats_dequeue_fair(cfs_rq, se, flags);\n\n\tclear_buddies(cfs_rq, se);\n\n\tif (se != cfs_rq->curr)\n\t\t__dequeue_entity(cfs_rq, se);\n"""
    dequeue_new = """\tupdate_stats_dequeue_fair(cfs_rq, se, flags);\n\n\tclear_buddies(cfs_rq, se);\n\tabk_eevdf_update_lag(cfs_rq, se);\n\tif (!sleep)\n\t\tabk_eevdf_store_rel_deadline(se);\n\n\tif (se != cfs_rq->curr)\n\t\t__dequeue_entity(cfs_rq, se);\n"""
    text = replace_once_fair(text, dequeue_old, dequeue_new, "feature_porting/fair_dequeue")

    place_old = """\tif (entity_is_long_sleeper(se))\n\t\tse->vruntime = vruntime;\n\telse\n\t\tse->vruntime = max_vruntime(se->vruntime, vruntime);\n}\n"""
    place_new = """\tif (entity_is_long_sleeper(se))\n\t\tse->vruntime = vruntime;\n\telse\n\t\tse->vruntime = max_vruntime(se->vruntime, vruntime);\n\n\tabk_eevdf_place_entity(cfs_rq, se, initial);\n}\n"""
    text = replace_once_fair(text, place_old, place_new, "feature_porting/fair_place")

    preempt_old = """\tse = __pick_first_entity(cfs_rq);\n\tdelta = curr->vruntime - se->vruntime;\n\n\tif (delta < 0)\n\t\treturn;\n\n\tif (delta > ideal_runtime)\n\t\tresched_curr(rq_of(cfs_rq));\n}\n"""
    preempt_new = """\tse = abk_pick_eevdf(cfs_rq, curr);\n\tif (se && se != curr && abk_eevdf_entity_before(se, curr)) {\n\t\tresched_curr(rq_of(cfs_rq));\n\t\treturn;\n\t}\n\n\tse = __pick_first_entity(cfs_rq);\n\tdelta = curr->vruntime - se->vruntime;\n\n\tif (delta < 0)\n\t\treturn;\n\n\tif (delta > ideal_runtime)\n\t\tresched_curr(rq_of(cfs_rq));\n}\n"""
    text = replace_once_fair(text, preempt_old, preempt_new, "feature_porting/fair_preempt")

    set_next_old = """\t\tupdate_stats_wait_end_fair(cfs_rq, se);\n\t\t__dequeue_entity(cfs_rq, se);\n\t\tupdate_load_avg(cfs_rq, se, UPDATE_TG);\n"""
    set_next_new = """\t\tupdate_stats_wait_end_fair(cfs_rq, se);\n\t\tabk_eevdf_refresh_deadline(cfs_rq, se);\n\t\tabk_eevdf_update_lag(cfs_rq, se);\n\t\t__dequeue_entity(cfs_rq, se);\n\t\tupdate_load_avg(cfs_rq, se, UPDATE_TG);\n"""
    text = replace_once_fair(text, set_next_old, set_next_new, "feature_porting/fair_set_next")

    pick_old = """static struct sched_entity *\npick_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *curr)\n{\n\tstruct sched_entity *left = __pick_first_entity(cfs_rq);\n\tstruct sched_entity *se = NULL;\n\n\ttrace_android_rvh_pick_next_entity(cfs_rq, curr, &se);\n\tif (se)\n\t\tgoto done;\n\n\t/*\n\t * If curr is set we have to see if its left of the leftmost entity\n\t * still in the tree, provided there was anything in the tree at all.\n\t */\n\tif (!left || (curr && entity_before(curr, left)))\n\t\tleft = curr;\n\n\tse = left; /* ideally we run the leftmost entity */\n\n\t/*\n\t * Avoid running the skip buddy, if running something else can\n\t * be done without getting too unfair.\n\t */\n\tif (cfs_rq->skip && cfs_rq->skip == se) {\n\t\tstruct sched_entity *second;\n\n\t\tif (se == curr) {\n\t\t\tsecond = __pick_first_entity(cfs_rq);\n\t\t} else {\n\t\t\tsecond = __pick_next_entity(se);\n\t\t\tif (!second || (curr && entity_before(curr, second)))\n\t\t\t\tsecond = curr;\n\t\t}\n\n\t\tif (second && wakeup_preempt_entity(second, left) < 1)\n\t\t\tse = second;\n\t}\n\n\tif (cfs_rq->next && wakeup_preempt_entity(cfs_rq->next, left) < 1) {\n\t\t/*\n\t\t * Someone really wants this to run. If it's not unfair, run it.\n\t\t */\n\t\tse = cfs_rq->next;\n\t} else if (cfs_rq->last && wakeup_preempt_entity(cfs_rq->last, left) < 1) {\n\t\t/*\n\t\t * Prefer last buddy, try to return the CPU to a preempted task.\n\t\t */\n\t\tse = cfs_rq->last;\n\t}\n\ndone:\n\treturn se;\n}\n"""
    pick_new = """static struct sched_entity *\npick_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *curr)\n{\n\tstruct sched_entity *se = NULL;\n\n\ttrace_android_rvh_pick_next_entity(cfs_rq, curr, &se);\n\tif (se)\n\t\treturn se;\n\n\treturn abk_pick_eevdf(cfs_rq, curr);\n}\n"""
    text = replace_once_fair(text, pick_old, pick_new, "feature_porting/fair_pick")

    put_prev_old = """\tif (prev->on_rq) {\n\t\tupdate_stats_wait_start_fair(cfs_rq, prev);\n\t\t/* Put 'current' back into the tree. */\n\t\t__enqueue_entity(cfs_rq, prev);\n\t\t/* in !on_rq case, update occurred at dequeue */\n\t\tupdate_load_avg(cfs_rq, prev, 0);\n\t}\n"""
    put_prev_new = """\tif (prev->on_rq) {\n\t\tupdate_stats_wait_start_fair(cfs_rq, prev);\n\t\tabk_eevdf_refresh_deadline(cfs_rq, prev);\n\t\tabk_eevdf_update_lag(cfs_rq, prev);\n\t\t/* Put 'current' back into the tree. */\n\t\t__enqueue_entity(cfs_rq, prev);\n\t\t/* in !on_rq case, update occurred at dequeue */\n\t\tupdate_load_avg(cfs_rq, prev, 0);\n\t}\n"""
    text = replace_once_fair(text, put_prev_old, put_prev_new, "feature_porting/fair_put_prev")

    tick_old = """\tif (cfs_rq->nr_running > 1)\n\t\tcheck_preempt_tick(cfs_rq, curr);\n\ttrace_android_rvh_entity_tick(cfs_rq, curr);\n}\n"""
    tick_new = """\tif (abk_eevdf_refresh_deadline(cfs_rq, curr)) {\n\t\tclear_buddies(cfs_rq, curr);\n\t\tresched_curr(rq_of(cfs_rq));\n\t}\n\tabk_eevdf_update_lag(cfs_rq, curr);\n\n\tif (cfs_rq->nr_running > 1)\n\t\tcheck_preempt_tick(cfs_rq, curr);\n\ttrace_android_rvh_entity_tick(cfs_rq, curr);\n}\n"""
    text = replace_once_fair(text, tick_old, tick_new, "feature_porting/fair_tick")

    write_text(fair_c, text)
    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="file_local_helper",
        ),
        "path": str(fair_c),
        "mode": "patched",
        "pick_logic": "scan_based_eevdf_phase2",
        "phase": "scan_based_runtime_parity",
        "runtime_state_extended": True,
        "tree_escalation_required": False,
        "touchpoints": [
            "avg_vruntime()",
            "enqueue_entity()",
            "reweight_entity()",
            "dequeue_entity()",
            "place_entity()",
            "check_preempt_tick()",
            "set_next_entity()",
            "put_prev_entity()",
            "pick_next_entity()",
            "entity_tick()",
        ],
    }


def patch_sched_runtime_state_phase3(common_root: Path) -> dict[str, object]:
    fair_c = common_root / "kernel/sched/fair.c"
    text = read_text(fair_c)
    original = text
    reweight_phase3_marker = (
        "/* ABK feature_porting: phase-3 preserve lag/deadline across both current and queued reweight paths. */"
    )

    ensure_contains(fair_c, "static void reweight_entity(struct cfs_rq *cfs_rq, struct sched_entity *se,", "feature_porting/fair_phase3")
    ensure_contains(fair_c, "static void\ndequeue_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int flags)\n{", "feature_porting/fair_phase3")
    ensure_contains(fair_c, "void set_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *se)\n{", "feature_porting/fair_phase3")
    ensure_contains(fair_c, "static void put_prev_entity(struct cfs_rq *cfs_rq, struct sched_entity *prev)\n{", "feature_porting/fair_phase3")
    ensure_contains(fair_c, "entity_tick(struct cfs_rq *cfs_rq, struct sched_entity *curr, int queued)\n{", "feature_porting/fair_phase3")

    reweight_anchor = """\tif (queued) {\n\t\t/* commit outstanding execution time before preserving lag/deadline */\n"""
    reweight_new = """\tif (queued) {\n\t\t/* ABK feature_porting: phase-3 preserve lag/deadline across both current and queued reweight paths. */\n\t\t/* commit outstanding execution time before preserving lag/deadline */\n"""
    if reweight_phase3_marker not in text:
        text = replace_once_fair(text, reweight_anchor, reweight_new, "feature_porting/fair_phase3_reweight_marker")

    if text != original:
        write_text(fair_c, text)

    delayed_path_supported = "DEQUEUE_DELAYED" in text or "DELAY_DEQUEUE" in text
    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=False,
            new_interface_scope="none",
        ),
        "path": str(fair_c),
        "group": "sched_eevdf_runtime_state_phase3",
        "mode": "patched" if text != original else "already_patched",
        "phase": "scan_based_runtime_phase3",
        "accepted_boundary": "scan_based_no_cfs_rq_augmentation",
        "delayed_path_status": "delayed_path_supported" if delayed_path_supported else "delayed_path_deferred",
        "touchpoints": [
            "reweight_entity()",
            "dequeue_entity()",
            "place_entity()",
            "set_next_entity()",
            "put_prev_entity()",
            "entity_tick()",
        ],
    }


def patch_pid_alloc(common_root: Path) -> dict[str, object]:
    pid_c = common_root / "kernel/pid.c"
    text = read_text(pid_c)
    marker = "/* ABK feature_porting: alloc_pid() preload retry and 6.1-compatible pid allocation semantics applied. */"

    if marker in text:
        return {
            **graft_metadata(
                hard_port_possible=False,
                semantic_port_used=True,
                max_function_port_used=False,
                sidecar_state_used=False,
                sidecar_state_scope="none",
                new_interface_used=True,
                new_interface_scope="file_local_helper",
            ),
            "path": str(pid_c),
            "group": "pid_alloc_hotpath_phase2",
            "mode": "already_patched",
            "ported_semantics": [
                "idr_alloc_cyclic() ENOSPC translated to EAGAIN",
                "single retry of idr_preload(GFP_KERNEL) after GFP_ATOMIC ENOMEM under pidmap_lock",
                "per-namespace pid_max intentionally not ported because the 6.1 pid_namespace shape lacks pid_max",
            ],
        }

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
    new_perm_loop = """\ttmp = ns;\n\tpid->level = ns->level;\n\n\tfor (i = ns->level; i >= 0; i--) {\n\t\tint tid = 0;\n\n\t\tif (set_tid_size) {\n\t\t\ttid = set_tid[ns->level - i];\n\n\t\t\tretval = -EINVAL;\n\t\t\tif (tid < 1 || tid >= pid_max)\n\t\t\t\tgoto out_free;\n\t\t\t/*\n\t\t\t * Also fail if a PID != 1 is requested and\n\t\t\t * no PID 1 exists.\n\t\t\t */\n\t\t\tif (tid != 1 && !tmp->child_reaper)\n\t\t\t\tgoto out_free;\n\t\t\tretval = -EPERM;\n\t\t\tif (!checkpoint_restore_ns_capable(tmp->user_ns))\n\t\t\t\tgoto out_free;\n\t\t\tset_tid_size--;\n\t\t}\n\n\t\tretried_preload = false;\n\t\tidr_preload(GFP_KERNEL);\n\t\tspin_lock_irq(&pidmap_lock);\n\n\t\tif (tid) {\n"""
    if old_perm_loop in text:
        text = text.replace(old_perm_loop, new_perm_loop, 1)

    old_alloc_loop = """\t\t} else {\n\t\t\tint pid_min = 1;\n\t\t\t/*\n\t\t\t * init really needs pid 1, but after reaching the\n\t\t\t * maximum wrap back to RESERVED_PIDS\n\t\t\t */\n\t\t\tif (idr_get_cursor(&tmp->idr) > RESERVED_PIDS)\n\t\t\t\tpid_min = RESERVED_PIDS;\n\n\t\t\t/*\n\t\t\t * Store a null pointer so find_pid_ns does not find\n\t\t\t * a partially initialized PID (see below).\n\t\t\t */\n\t\t\tnr = idr_alloc_cyclic(&tmp->idr, NULL, pid_min,\n\t\t\t\t\t      pid_max, GFP_ATOMIC);\n\t\t}\n\t\tspin_unlock_irq(&pidmap_lock);\n\t\tidr_preload_end();\n\n\t\tif (nr < 0) {\n\t\t\tretval = (nr == -ENOSPC) ? -EAGAIN : nr;\n\t\t\tgoto out_free;\n\t\t}\n\n\t\tpid->numbers[i].nr = nr;\n\t\tpid->numbers[i].ns = tmp;\n\t\ttmp = tmp->parent;\n\t}\n"""
    new_alloc_loop = """\t\t} else {\n\t\t\tint pid_min = 1;\n\t\t\t/*\n\t\t\t * init really needs pid 1, but after reaching the\n\t\t\t * maximum wrap back to RESERVED_PIDS\n\t\t\t */\n\t\t\tif (idr_get_cursor(&tmp->idr) > RESERVED_PIDS)\n\t\t\t\tpid_min = RESERVED_PIDS;\n\n\t\t\t/*\n\t\t\t * Store a null pointer so find_pid_ns does not find\n\t\t\t * a partially initialized PID (see below).\n\t\t\t */\n\t\t\tnr = idr_alloc_cyclic(&tmp->idr, NULL, pid_min,\n\t\t\t\t\t      pid_max, GFP_ATOMIC);\n\t\t\tif (nr == -ENOSPC)\n\t\t\t\tnr = -EAGAIN;\n\t\t}\n\n\t\tif (nr < 0) {\n\t\t\tif (nr == -ENOMEM && !retried_preload) {\n\t\t\t\tspin_unlock_irq(&pidmap_lock);\n\t\t\t\tidr_preload_end();\n\t\t\t\tretried_preload = true;\n\t\t\t\tidr_preload(GFP_KERNEL);\n\t\t\t\tspin_lock_irq(&pidmap_lock);\n\t\t\t\tcontinue;\n\t\t\t}\n\t\t\tspin_unlock_irq(&pidmap_lock);\n\t\t\tidr_preload_end();\n\t\t\tretval = nr;\n\t\t\tgoto out_free;\n\t\t}\n\t\tspin_unlock_irq(&pidmap_lock);\n\t\tidr_preload_end();\n\n\t\tpid->numbers[i].nr = nr;\n\t\tpid->numbers[i].ns = tmp;\n\t\ttmp = tmp->parent;\n\t\tretried_preload = false;\n\t}\n"""
    if old_alloc_loop in text:
        text = text.replace(old_alloc_loop, new_alloc_loop, 1)

    if marker not in text:
        anchor = "struct pid *alloc_pid(struct pid_namespace *ns, pid_t *set_tid,\n"
        text = text.replace(anchor, marker + "\n" + anchor, 1)

    write_text(pid_c, text)
    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="file_local_helper",
        ),
        "path": str(pid_c),
        "group": "pid_alloc_hotpath_phase2",
        "ported_semantics": [
            "idr_alloc_cyclic() ENOSPC translated to EAGAIN",
            "single retry of idr_preload(GFP_KERNEL) after GFP_ATOMIC ENOMEM under pidmap_lock",
            "per-namespace pid_max intentionally not ported because the 6.1 pid_namespace shape lacks pid_max",
        ],
    }


def patch_pidfd_preparation_compat(common_root: Path) -> dict[str, object]:
    fork_c = common_root / "kernel/fork.c"
    pid_c = common_root / "kernel/pid.c"
    fork_text = read_text(fork_c)
    pid_text = read_text(pid_c)
    original_fork = fork_text
    original_pid = pid_text
    helper_marker = "/* ABK feature_porting: pidfd compat helper graft. */"
    fork_marker = "\t/* ABK feature_porting: keep CLONE_PIDFD on legacy pidfd plumbing; pidfs remains deferred. */\n"
    legacy_entry_marker = "/* ABK feature_porting: phase-two scan-based EEVDF runtime-state and PID migration entry executed. */"
    entry_marker = "/* ABK feature_porting: phase-three scan-based EEVDF runtime-state and pidfd compat entry executed. */"
    fork_anchor = """\t/*\n\t * This has to happen after we've potentially unshared the file\n\t * descriptor table (so that the pidfd doesn't leak into the child\n\t * if the fd table isn't shared).\n\t */\n\tif (clone_flags & CLONE_PIDFD) {\n"""
    fork_new = """\t/*\n\t * This has to happen after we've potentially unshared the file\n\t * descriptor table (so that the pidfd doesn't leak into the child\n\t * if the fd table isn't shared).\n\t */\n\t/* ABK feature_porting: keep CLONE_PIDFD on legacy pidfd plumbing; pidfs remains deferred. */\n\tif (clone_flags & CLONE_PIDFD) {\n"""

    ensure_contains(pid_c, "int pidfd_create(struct pid *pid, unsigned int flags)\n{", "feature_porting/pidfd_pid")
    ensure_contains(pid_c, "SYSCALL_DEFINE2(pidfd_open, pid_t, pid, unsigned int, flags)\n{", "feature_porting/pidfd_pid")
    ensure_contains(pid_c, "static int pidfd_getfd(struct pid *pid, int fd)\n{", "feature_porting/pidfd_pid")
    ensure_contains(pid_c, "SYSCALL_DEFINE3(pidfd_getfd, int, pidfd, int, fd,", "feature_porting/pidfd_pid")
    ensure_contains(fork_c, "const struct file_operations pidfd_fops = {\n", "feature_porting/pidfd_fork")
    if fork_anchor not in fork_text and fork_new not in fork_text:
        raise SystemExit(f"feature_porting/pidfd_fork: expected anchor missing in {fork_c}: {fork_anchor}")

    helper_anchor = "int pidfd_create(struct pid *pid, unsigned int flags)\n{"
    helper_block = """/* ABK feature_porting: pidfd compat helper graft. */\nstatic inline bool abk_pidfd_has_forbidden_flags(unsigned int flags,\n\t\t\t\t\t unsigned int allowed)\n{\n\treturn flags & ~allowed;\n}\n\nint pidfd_create(struct pid *pid, unsigned int flags)\n{"""
    if helper_marker not in pid_text:
        pid_text = replace_once(pid_text, helper_anchor, helper_block, "feature_porting/pidfd_helper")

    create_flags_old = "if (flags & ~(O_NONBLOCK | O_RDWR | O_CLOEXEC))"
    create_flags_new = "if (abk_pidfd_has_forbidden_flags(flags, O_NONBLOCK | O_RDWR | O_CLOEXEC))"
    if create_flags_old in pid_text:
        pid_text = replace_once(pid_text, create_flags_old, create_flags_new, "feature_porting/pidfd_create_flags")

    open_flags_old = "if (flags & ~PIDFD_NONBLOCK)"
    open_flags_new = "if (abk_pidfd_has_forbidden_flags(flags, PIDFD_NONBLOCK))"
    if open_flags_old in pid_text:
        pid_text = replace_once(pid_text, open_flags_old, open_flags_new, "feature_porting/pidfd_open_flags")

    getfd_flags_old = "\tif (flags)\n\t\treturn -EINVAL;\n"
    getfd_flags_new = "\tif (abk_pidfd_has_forbidden_flags(flags, 0))\n\t\treturn -EINVAL;\n"
    if getfd_flags_old in pid_text:
        pid_text = replace_once(pid_text, getfd_flags_old, getfd_flags_new, "feature_porting/pidfd_getfd_flags")

    if fork_marker not in fork_text:
        fork_text = replace_once(fork_text, fork_anchor, fork_new, "feature_porting/pidfd_fork_marker")

    if legacy_entry_marker in pid_text:
        pid_text = pid_text.replace(legacy_entry_marker, entry_marker, 1)
    elif entry_marker not in pid_text:
        if not pid_text.endswith("\n"):
            pid_text += "\n"
        pid_text += entry_marker + "\n"

    if pid_text != original_pid:
        write_text(pid_c, pid_text)
    if fork_text != original_fork:
        write_text(fork_c, fork_text)

    helper_grafted = helper_marker in pid_text
    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=False,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=helper_grafted,
            new_interface_scope="file_local_helper" if helper_grafted else "none",
        ),
        "paths": [str(fork_c), str(pid_c)],
        "group": "pidfd_preparation_compat",
        "mode": "patched" if pid_text != original_pid or fork_text != original_fork else "already_patched",
        "compat_scope": "helper_report_level",
        "helper_grafted": helper_grafted,
        "user_abi_changed": False,
    }


def patch_fd_alloc_hotpath(common_root: Path) -> dict[str, object]:
    file_c = common_root / "fs/file.c"
    text = read_text(file_c)
    marker = "/* ABK feature_porting: fd allocation hotpath helper graft. */"
    alloc_signature_pattern = (
        r"static\s+struct\s+fdtable\s*\*\s*alloc_fdtable\s*"
        r"\(\s*unsigned\s+int\s+(?P<alloc_param>[A-Za-z_]\w*)\s*\)"
    )

    if marker in text:
        return {
            **graft_metadata(
                hard_port_possible=False,
                semantic_port_used=True,
                max_function_port_used=False,
                sidecar_state_used=False,
                sidecar_state_scope="none",
                new_interface_used=True,
                new_interface_scope="file_local_helper",
            ),
            "path": str(file_c),
            "group": "fd_alloc_hotpath",
            "mode": "already_patched",
            "touchpoints": [
                "alloc_fdtable()",
                "expand_fdtable()",
                "expand_files()",
                "alloc_fd()",
                "get_unused_fd_flags()",
            ],
        }

    alloc_match = re.search(alloc_signature_pattern, text, re.MULTILINE)
    if not alloc_match:
        raise SystemExit(
            f"feature_porting/fd_alloc: expected anchor missing in {file_c}: alloc_fdtable(unsigned int nr)"
        )
    ensure_contains(file_c, "static int expand_fdtable(struct files_struct *files, unsigned int nr)", "feature_porting/fd_alloc")
    ensure_contains(file_c, "static int expand_files(struct files_struct *files, unsigned int nr)", "feature_porting/fd_alloc")
    ensure_contains(file_c, "int get_unused_fd_flags(unsigned flags)", "feature_porting/fd_alloc")

    helper_anchor = """#define fdt_words(fdt) ((fdt)->max_fds / BITS_PER_LONG) // words in ->open_fds\n"""
    helper_block = """/* ABK feature_porting: fd allocation hotpath helper graft. */\nstatic inline unsigned int abk_fdtable_slots_wanted(unsigned int nr)\n{\n\tunsigned int slots_wanted;\n\n\tslots_wanted = nr + 1;\n\tif (IS_ENABLED(CONFIG_32BIT) && slots_wanted < 256)\n\t\treturn 256;\n\treturn roundup_pow_of_two(slots_wanted);\n}\n\nstatic inline bool abk_expand_files_needed(const struct fdtable *fdt, unsigned int nr)\n{\n\treturn nr >= fdt->max_fds;\n}\n"""
    if helper_anchor in text:
        text = replace_once(text, helper_anchor, helper_anchor + "\n" + helper_block, "feature_porting/fd_alloc_helpers")
    else:
        helper_match = re.search(r"^#define fdt_words\(fdt\).*\n", text, re.MULTILINE)
        if helper_match:
            anchor = helper_match.group(0)
            text = replace_once(text, anchor, anchor + "\n" + helper_block, "feature_porting/fd_alloc_helpers")
        else:
            if not alloc_match:
                raise SystemExit("feature_porting/fd_alloc_helpers: alloc_fdtable() anchor missing")
            text = text[:alloc_match.start()] + helper_block + "\n" + text[alloc_match.start():]

    alloc_old = """static struct fdtable * alloc_fdtable(unsigned int nr)\n{\n\tstruct fdtable *fdt;\n\tvoid *data;\n\n\t/*\n\t * Figure out how many fds we actually want to support in this fdtable.\n\t * Allocation steps are keyed to the size of the fdarray, since it\n\t * grows far faster than any of the other dynamic data. We try to fit\n\t * the fdarray into comfortable page-tuned chunks: starting at 1024B\n\t * and growing in powers of two from there on.\n\t */\n\tnr /= (1024 / sizeof(struct file *));\n\tnr = roundup_pow_of_two(nr + 1);\n\tnr *= (1024 / sizeof(struct file *));\n\tnr = ALIGN(nr, BITS_PER_LONG);\n\t/*\n\t * Note that this can drive nr *below* what we had passed if sysctl_nr_open\n\t * had been set lower between the check in expand_files() and here.  Deal\n\t * with that in caller, it's cheaper that way.\n\t *\n\t * We make sure that nr remains a multiple of BITS_PER_LONG - otherwise\n\t * bitmaps handling below becomes unpleasant, to put it mildly...\n\t */\n\tif (unlikely(nr > sysctl_nr_open))\n\t\tnr = ((sysctl_nr_open - 1) | (BITS_PER_LONG - 1)) + 1;\n\n\tfdt = kmalloc(sizeof(struct fdtable), GFP_KERNEL_ACCOUNT);\n\tif (!fdt)\n\t\tgoto out;\n\tfdt->max_fds = nr;\n\tdata = kvmalloc_array(nr, sizeof(struct file *), GFP_KERNEL_ACCOUNT);\n\tif (!data)\n\t\tgoto out_fdt;\n\tfdt->fd = data;\n\n\tdata = kvmalloc(max_t(size_t,\n\t\t\t\t 2 * nr / BITS_PER_BYTE + BITBIT_SIZE(nr), L1_CACHE_BYTES),\n\t\t\t\t GFP_KERNEL_ACCOUNT);\n\tif (!data)\n\t\tgoto out_arr;\n\tfdt->open_fds = data;\n\tdata += nr / BITS_PER_BYTE;\n\tfdt->close_on_exec = data;\n\tdata += nr / BITS_PER_BYTE;\n\tfdt->full_fds_bits = data;\n\n\treturn fdt;\n\nout_arr:\n\tkvfree(fdt->fd);\nout_fdt:\n\tkfree(fdt);\nout:\n\treturn NULL;\n}\n"""
    alloc_new = """static struct fdtable * alloc_fdtable(unsigned int nr)\n{\n\tstruct fdtable *fdt;\n\tunsigned int slots_wanted = abk_fdtable_slots_wanted(nr);\n\tvoid *data;\n\n\t/*\n\t * Keep the legacy file-local interface shape, but derive capacity from\n\t * the requested slot count before dropping into the allocator.\n\t */\n\tnr = ALIGN(slots_wanted, BITS_PER_LONG);\n\t/*\n\t * Note that this can drive nr *below* what we had passed if sysctl_nr_open\n\t * had been set lower between the check in expand_files() and here.  Deal\n\t * with that in caller, it's cheaper that way.\n\t *\n\t * We make sure that nr remains a multiple of BITS_PER_LONG - otherwise\n\t * bitmaps handling below becomes unpleasant, to put it mildly...\n\t */\n\tif (unlikely(nr > sysctl_nr_open))\n\t\tnr = ((sysctl_nr_open - 1) | (BITS_PER_LONG - 1)) + 1;\n\tif (unlikely(nr > INT_MAX / sizeof(struct file *)))\n\t\treturn NULL;\n\n\tfdt = kmalloc(sizeof(struct fdtable), GFP_KERNEL_ACCOUNT);\n\tif (!fdt)\n\t\tgoto out;\n\tfdt->max_fds = nr;\n\tdata = kvmalloc_array(nr, sizeof(struct file *), GFP_KERNEL_ACCOUNT);\n\tif (!data)\n\t\tgoto out_fdt;\n\tfdt->fd = data;\n\n\tdata = kvmalloc(max_t(size_t,\n\t\t\t\t 2 * nr / BITS_PER_BYTE + BITBIT_SIZE(nr), L1_CACHE_BYTES),\n\t\t\t\t GFP_KERNEL_ACCOUNT);\n\tif (!data)\n\t\tgoto out_arr;\n\tfdt->open_fds = data;\n\tdata += nr / BITS_PER_BYTE;\n\tfdt->close_on_exec = data;\n\tdata += nr / BITS_PER_BYTE;\n\tfdt->full_fds_bits = data;\n\n\treturn fdt;\n\nout_arr:\n\tkvfree(fdt->fd);\nout_fdt:\n\tkfree(fdt);\nout:\n\treturn NULL;\n}\n"""
    if alloc_old in text:
        text = replace_once(text, alloc_old, alloc_new, "feature_porting/fd_alloc_alloc_fdtable")
    else:
        alloc_start, alloc_end = find_c_block_regex(text, alloc_signature_pattern, "feature_porting/fd_alloc_alloc_fdtable")
        alloc_scope = text[alloc_start:alloc_end]
        alloc_original_scope = alloc_scope
        alloc_scope_match = re.search(alloc_signature_pattern, alloc_scope, re.MULTILINE)
        if not alloc_scope_match:
            raise SystemExit("feature_porting/fd_alloc_alloc_fdtable: start anchor missing")
        alloc_param = alloc_scope_match.group("alloc_param")
        capacity_old = """\tnr /= (1024 / sizeof(struct file *));\n\tnr = roundup_pow_of_two(nr + 1);\n\tnr *= (1024 / sizeof(struct file *));\n\tnr = ALIGN(nr, BITS_PER_LONG);\n"""
        capacity_align_pattern = r"(?m)^(?P<indent>[ \t]*)nr = ALIGN\(\s*slots_wanted\s*,\s*BITS_PER_LONG\s*\);\n"
        sysctl_guard = """\tif (unlikely(nr > sysctl_nr_open))\n\t\tnr = ((sysctl_nr_open - 1) | (BITS_PER_LONG - 1)) + 1;\n"""
        sysctl_guard_new = (
            sysctl_guard
            + "\tif (unlikely(nr > INT_MAX / sizeof(struct file *)))\n"
            + "\t\treturn NULL;\n"
        )

        if (
            alloc_param != "slots_wanted"
            and "unsigned int slots_wanted;" not in alloc_scope
            and "unsigned int slots_wanted = " not in alloc_scope
        ):
            brace_idx = alloc_scope.find("{")
            if brace_idx < 0:
                raise SystemExit("feature_porting/fd_alloc_alloc_fdtable: opening brace missing")
            tail = alloc_scope[brace_idx + 1 :]
            if tail.startswith("\n"):
                tail = tail[1:]
            alloc_scope = alloc_scope[: brace_idx + 1] + "\n\tunsigned int slots_wanted;\n" + tail

        if capacity_old in alloc_scope:
            alloc_scope = alloc_scope.replace(
                capacity_old,
                f"\tslots_wanted = abk_fdtable_slots_wanted({alloc_param});\n\tnr = ALIGN(slots_wanted, BITS_PER_LONG);\n",
                1,
            )
        else:
            capacity_align_match = re.search(capacity_align_pattern, alloc_scope)
            if capacity_align_match:
                indent = capacity_align_match.group("indent")
                if f"{indent}slots_wanted = abk_fdtable_slots_wanted({alloc_param});\n" not in alloc_scope:
                    capacity_new = (
                        f"{indent}slots_wanted = abk_fdtable_slots_wanted({alloc_param});\n"
                        f"{indent}nr = ALIGN(slots_wanted, BITS_PER_LONG);\n"
                    )
                    alloc_scope = (
                        alloc_scope[: capacity_align_match.start()]
                        + capacity_new
                        + alloc_scope[capacity_align_match.end() :]
                    )
            else:
                raise SystemExit("feature_porting/fd_alloc_alloc_fdtable: expected capacity block missing")

        if "INT_MAX / sizeof(struct file *)" not in alloc_scope:
            if sysctl_guard not in alloc_scope:
                raise SystemExit("feature_porting/fd_alloc_alloc_fdtable: expected sysctl guard missing")
            alloc_scope = alloc_scope.replace(sysctl_guard, sysctl_guard_new, 1)

        if alloc_scope != alloc_original_scope:
            text = text[:alloc_start] + alloc_scope + text[alloc_end:]

    expand_files_old = """repeat:\n\tfdt = files_fdtable(files);\n\n\t/* Do we need to expand? */\n\tif (nr < fdt->max_fds)\n\t\treturn expanded;\n\n\t/* Can we expand? */\n\tif (nr >= sysctl_nr_open)\n\t\treturn -EMFILE;\n"""
    expand_files_new = """repeat:\n\tfdt = files_fdtable(files);\n\n\t/* Do we need to expand? */\n\tif (!abk_expand_files_needed(fdt, nr))\n\t\treturn expanded;\n\n\t/* Can we expand? */\n\tif (nr >= sysctl_nr_open)\n\t\treturn -EMFILE;\n"""
    text = replace_once(text, expand_files_old, expand_files_new, "feature_porting/fd_alloc_expand_files")

    alloc_fd_old = """\tif (fd < fdt->max_fds)\n\t\tfd = find_next_fd(fdt, fd);\n\n\t/*\n\t * N.B. For clone tasks sharing a files structure, this test\n\t * will limit the total number of files that can be opened.\n\t */\n\terror = -EMFILE;\n\tif (fd >= end)\n\t\tgoto out;\n\n\terror = expand_files(files, fd);\n\tif (error < 0)\n\t\tgoto out;\n\n\t/*\n\t * If we needed to expand the fs array we\n\t * might have blocked - try again.\n\t */\n\tif (error)\n\t\tgoto repeat;\n"""
    alloc_fd_new = """\tif (fd < fdt->max_fds)\n\t\tfd = find_next_fd(fdt, fd);\n\n\t/*\n\t * N.B. For clone tasks sharing a files structure, this test\n\t * will limit the total number of files that can be opened.\n\t */\n\terror = -EMFILE;\n\tif (fd >= end)\n\t\tgoto out;\n\n\tif (abk_expand_files_needed(fdt, fd)) {\n\t\terror = expand_files(files, fd);\n\t\tif (error < 0)\n\t\t\tgoto out;\n\n\t\t/*\n\t\t * If we needed to expand the fs array we\n\t\t * might have blocked - try again.\n\t\t */\n\t\tif (error)\n\t\t\tgoto repeat;\n\t}\n"""
    text = replace_once(text, alloc_fd_old, alloc_fd_new, "feature_porting/fd_alloc_alloc_fd")

    get_unused_old = """int get_unused_fd_flags(unsigned flags)\n{\n\treturn __get_unused_fd_flags(flags, rlimit(RLIMIT_NOFILE));\n}\n"""
    get_unused_new = """int get_unused_fd_flags(unsigned flags)\n{\n\t/* ABK feature_porting: keep the wrapper tiny so hot open/dup callers stay on alloc_fd(). */\n\treturn __get_unused_fd_flags(flags, rlimit(RLIMIT_NOFILE));\n}\n"""
    text = replace_once(text, get_unused_old, get_unused_new, "feature_porting/fd_alloc_get_unused")

    write_text(file_c, text)
    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="file_local_helper",
        ),
        "path": str(file_c),
        "group": "fd_alloc_hotpath",
        "mode": "patched",
        "touchpoints": [
            "alloc_fdtable()",
            "expand_fdtable()",
            "expand_files()",
            "alloc_fd()",
            "get_unused_fd_flags()",
        ],
        "ported_semantics": [
            "slot-count helper graft keeps alloc_fdtable() sizing logic out of the lock path",
            "expand_files() now uses a helper precheck before sleeping or growing the table",
            "alloc_fd() avoids the unconditional expand_files() call once a free descriptor was found",
        ],
    }


def patch_close_range_hotpath(common_root: Path) -> dict[str, object]:
    file_c = common_root / "fs/file.c"
    text = read_text(file_c)
    marker = "/* ABK feature_porting: close_range() bitmap hotpath graft. */"

    if marker in text:
        return {
            **graft_metadata(
                hard_port_possible=False,
                semantic_port_used=True,
                max_function_port_used=False,
                sidecar_state_used=False,
                sidecar_state_scope="none",
                new_interface_used=True,
                new_interface_scope="internal_static_api",
            ),
            "path": str(file_c),
            "group": "close_range_hotpath",
            "mode": "already_patched",
            "touchpoints": [
                "pick_file()",
                "__range_close()",
                "__close_range()",
                "__close_fd_get_file()",
                "close_fd_get_file()",
            ],
        }

    ensure_contains(file_c, "static struct file *pick_file(struct files_struct *files, unsigned fd)", "feature_porting/close_range")
    ensure_contains(file_c, "static inline void __range_close(struct files_struct *cur_fds, unsigned int fd,\n\t\t\t\t unsigned int max_fd)\n{", "feature_porting/close_range")
    ensure_contains(file_c, "int __close_range(unsigned fd, unsigned max_fd, unsigned int flags)\n{", "feature_porting/close_range")

    pick_old = """static struct file *pick_file(struct files_struct *files, unsigned fd)\n{\n\tstruct fdtable *fdt = files_fdtable(files);\n\tstruct file *file;\n\n\tif (fd >= fdt->max_fds)\n\t\treturn NULL;\n\n\tfd = array_index_nospec(fd, fdt->max_fds);\n\tfile = fdt->fd[fd];\n\tif (file) {\n\t\trcu_assign_pointer(fdt->fd[fd], NULL);\n\t\t__put_unused_fd(files, fd);\n\t}\n\treturn file;\n}\n"""
    pick_new = """/* ABK feature_porting: close_range() bitmap hotpath graft. */\nstatic struct file *pick_file(struct files_struct *files, unsigned fd)\n{\n\tstruct fdtable *fdt = files_fdtable(files);\n\tstruct file *file;\n\n\tif (fd >= fdt->max_fds)\n\t\treturn NULL;\n\tif (!fd_is_open(fd, fdt))\n\t\treturn NULL;\n\n\tfd = array_index_nospec(fd, fdt->max_fds);\n\tfile = fdt->fd[fd];\n\tif (file) {\n\t\trcu_assign_pointer(fdt->fd[fd], NULL);\n\t\t__put_unused_fd(files, fd);\n\t}\n\treturn file;\n}\n\nstatic inline unsigned int abk_close_range_limit(struct fdtable *fdt,\n\t\t\t\t\t       unsigned int max_fd)\n{\n\tunsigned int limit = fdt->max_fds - 1;\n\n\treturn min(limit, max_fd);\n}\n\nstatic struct file *abk_pick_file_for_close(struct files_struct *files,\n\t\t\t\t\t   unsigned int fd)\n{\n\tlockdep_assert_held(&files->file_lock);\n\treturn pick_file(files, fd);\n}\n"""
    pick_helper_block = """\n\n/* ABK feature_porting: close_range() bitmap hotpath graft. */\nstatic inline unsigned int abk_close_range_limit(struct fdtable *fdt,\n\t\t\t\t\t       unsigned int max_fd)\n{\n\tunsigned int limit = fdt->max_fds - 1;\n\n\treturn min(limit, max_fd);\n}\n\nstatic struct file *abk_pick_file_for_close(struct files_struct *files,\n\t\t\t\t\t   unsigned int fd)\n{\n\tlockdep_assert_held(&files->file_lock);\n\treturn pick_file(files, fd);\n}\n"""
    pick_signature = "static struct file *pick_file(struct files_struct *files, unsigned fd)\n{"
    if pick_old in text:
        text = replace_once(text, pick_old, pick_new, "feature_porting/close_range_pick")
    else:
        pick_start, pick_end = find_c_block(text, pick_signature, "feature_porting/close_range_pick")
        pick_scope = text[pick_start:pick_end]
        if "if (!fd_is_open(fd, fdt))" not in pick_scope:
            pick_scope = replace_once(
                pick_scope,
                "\tif (fd >= fdt->max_fds)\n\t\treturn NULL;\n",
                "\tif (fd >= fdt->max_fds)\n\t\treturn NULL;\n\tif (!fd_is_open(fd, fdt))\n\t\treturn NULL;\n",
                "feature_porting/close_range_pick",
            )
            text = text[:pick_start] + pick_scope + text[pick_end:]
        if "static inline unsigned int abk_close_range_limit(" not in text:
            _, pick_end = find_c_block(text, pick_signature, "feature_porting/close_range_pick")
            text = text[:pick_end] + pick_helper_block + text[pick_end:]

    range_old = """static inline void __range_close(struct files_struct *cur_fds, unsigned int fd,\n\t\t\t\t unsigned int max_fd)\n{\n\tunsigned n;\n\n\trcu_read_lock();\n\tn = last_fd(files_fdtable(cur_fds));\n\trcu_read_unlock();\n\tmax_fd = min(max_fd, n);\n\n\twhile (fd <= max_fd) {\n\t\tstruct file *file;\n\n\t\tspin_lock(&cur_fds->file_lock);\n\t\tfile = pick_file(cur_fds, fd++);\n\t\tspin_unlock(&cur_fds->file_lock);\n\n\t\tif (file) {\n\t\t\t/* found a valid file to close */\n\t\t\tfilp_close(file, cur_fds);\n\t\t\tcond_resched();\n\t\t}\n\t}\n}\n"""
    range_new = """static inline void __range_close(struct files_struct *cur_fds, unsigned int fd,\n\t\t\t\t unsigned int max_fd)\n{\n\tstruct file *file;\n\tstruct fdtable *fdt;\n\tunsigned int n;\n\n\tspin_lock(&cur_fds->file_lock);\n\tfdt = files_fdtable(cur_fds);\n\tn = last_fd(fdt);\n\tmax_fd = min(max_fd, n);\n\n\tfor (fd = find_next_bit(fdt->open_fds, max_fd + 1, fd);\n\t     fd <= max_fd;\n\t     fd = find_next_bit(fdt->open_fds, max_fd + 1, fd + 1)) {\n\t\tfile = abk_pick_file_for_close(cur_fds, fd);\n\t\tif (file) {\n\t\t\tspin_unlock(&cur_fds->file_lock);\n\t\t\tfilp_close(file, cur_fds);\n\t\t\tcond_resched();\n\t\t\tspin_lock(&cur_fds->file_lock);\n\t\t\tfdt = files_fdtable(cur_fds);\n\t\t\tmax_fd = abk_close_range_limit(fdt, max_fd);\n\t\t} else if (need_resched()) {\n\t\t\tspin_unlock(&cur_fds->file_lock);\n\t\t\tcond_resched();\n\t\t\tspin_lock(&cur_fds->file_lock);\n\t\t\tfdt = files_fdtable(cur_fds);\n\t\t\tmax_fd = abk_close_range_limit(fdt, max_fd);\n\t\t}\n\t}\n\tspin_unlock(&cur_fds->file_lock);\n}\n"""
    text = replace_once(text, range_old, range_new, "feature_porting/close_range_range_close")

    write_text(file_c, text)
    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="internal_static_api",
        ),
        "path": str(file_c),
        "group": "close_range_hotpath",
        "mode": "patched",
        "touchpoints": [
            "pick_file()",
            "__range_close()",
            "__close_range()",
            "__close_fd_get_file()",
            "close_fd_get_file()",
        ],
        "ported_semantics": [
            "close_range() now walks the open_fds bitmap instead of linearly probing every descriptor",
            "lock-drop/cond_resched batching is preserved while rescanning from the bitmap after each close",
            "pick_file() gets a cheap open-bit precheck without changing close/open user-visible semantics",
        ],
    }


def patch_blk_mq_async_depth(common_root: Path) -> dict[str, object]:
    marker = "/* ABK feature_porting: blk-mq async_depth queue policy graft. */"
    blkdev_h = common_root / "include/linux/blkdev.h"
    blk_core_c = common_root / "block/blk-core.c"
    blk_mq_c = common_root / "block/blk-mq.c"
    blk_mq_sched_c = common_root / "block/blk-mq-sched.c"
    blk_sysfs_c = common_root / "block/blk-sysfs.c"
    elevator_c = common_root / "block/elevator.c"
    dd_c = common_root / "block/mq-deadline.c"
    bfq_c = common_root / "block/bfq-iosched.c"
    kyber_c = common_root / "block/kyber-iosched.c"

    blkdev_text = read_text(blkdev_h)
    blk_core_text = read_text(blk_core_c)
    blk_mq_text = read_text(blk_mq_c)
    blk_mq_sched_text = read_text(blk_mq_sched_c)
    blk_sysfs_text = read_text(blk_sysfs_c)
    elevator_text = read_text(elevator_c)
    dd_text = read_text(dd_c)
    bfq_text = read_text(bfq_c)
    kyber_text = read_text(kyber_c)

    ensure_contains(blkdev_h, "struct request_queue {\n", "feature_porting/blk_async_depth_blkdev")
    ensure_contains_any(
        blk_core_c,
        [
            "q->nr_requests = BLKDEV_DEFAULT_RQ;",
            "q->nr_requests = BLKDEV_MAX_RQ;",
        ],
        "feature_porting/blk_async_depth_blk_core",
    )
    ensure_contains_any(
        blk_mq_c,
        [
            "static struct request *__blk_mq_alloc_requests(struct blk_mq_alloc_data *data)",
            "static struct request *__blk_mq_alloc_request(struct blk_mq_alloc_data *data)",
        ],
        "feature_porting/blk_async_depth_blk_mq",
    )
    ensure_contains(blk_mq_sched_c, "int blk_mq_init_sched(struct request_queue *q, struct elevator_type *e)", "feature_porting/blk_async_depth_blk_mq_sched")
    ensure_contains(blk_sysfs_c, 'QUEUE_RW_ENTRY(queue_requests, "nr_requests");', "feature_porting/blk_async_depth_blk_sysfs")
    ensure_contains_any(
        elevator_c,
        [
            "static int elevator_switch_mq(struct request_queue *q,",
            "static int elevator_switch(struct request_queue *q,",
        ],
        "feature_porting/blk_async_depth_elevator",
    )
    ensure_contains_any(
        dd_c,
        [
            # blk_opf_t arrived in 6.1; 5.15 passes the raw unsigned int.
            "static void dd_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)",
            "static void dd_limit_depth(unsigned int op, struct blk_mq_alloc_data *data)",
        ],
        "feature_porting/blk_async_depth_deadline",
    )
    ensure_contains(bfq_c, "static void bfq_depth_updated(struct blk_mq_hw_ctx *hctx)", "feature_porting/blk_async_depth_bfq")
    ensure_contains(kyber_c, "static void kyber_depth_updated(struct blk_mq_hw_ctx *hctx)", "feature_porting/blk_async_depth_kyber")

    rq_start = "struct request_queue {\n"
    # Scope the KABI slot rewrite to struct request_queue. 6.1 has an @srcu
    # member to bound against; 5.15 does not, so fall back to the struct's own
    # closing brace.
    rq_end = "\n\t/**\n\t * @srcu: Sleepable RCU. Use as lock when type of the request queue\n"
    if rq_end not in blkdev_text:
        rq_end = "\n\tANDROID_OEM_DATA(1);\n};\n"
        if rq_end not in blkdev_text:
            rq_end = "\n};\n"
    rq_old = """\n\tANDROID_KABI_RESERVE(1);\n\tANDROID_KABI_RESERVE(2);\n\tANDROID_KABI_RESERVE(3);\n\tANDROID_KABI_RESERVE(4);\n"""
    rq_new = """\n\tANDROID_KABI_USE(1, unsigned int\t\tasync_depth);\t/* Max # of async requests */\n\tANDROID_KABI_RESERVE(2);\n\tANDROID_KABI_RESERVE(3);\n\tANDROID_KABI_RESERVE(4);\n"""
    stray_async_depth = "ANDROID_KABI_USE(1, unsigned int\t\tasync_depth);\t/* Max # of async requests */"
    rq_start_idx = blkdev_text.find(rq_start)
    rq_end_idx = blkdev_text.find(rq_end, rq_start_idx)
    rq_scope = blkdev_text[rq_start_idx:rq_end_idx]
    if stray_async_depth in blkdev_text[:rq_start_idx]:
        blkdev_text = blkdev_text.replace(stray_async_depth, "ANDROID_KABI_RESERVE(1)", 1)
        write_text(blkdev_h, blkdev_text)
        blkdev_text = read_text(blkdev_h)
        rq_start_idx = blkdev_text.find(rq_start)
        rq_end_idx = blkdev_text.find(rq_end, rq_start_idx)
        rq_scope = blkdev_text[rq_start_idx:rq_end_idx]
    if "ANDROID_KABI_USE(1, unsigned int\t\tasync_depth);" not in rq_scope:
        blkdev_text = replace_within(blkdev_text, rq_start, rq_end, rq_old, rq_new, "feature_porting/blk_async_depth_blkdev_use")
        write_text(blkdev_h, blkdev_text)
        blkdev_text = read_text(blkdev_h)

    # 6.1 renamed BLKDEV_MAX_RQ to BLKDEV_DEFAULT_RQ; same 128.
    blk_core_rq_define = (
        "BLKDEV_DEFAULT_RQ"
        if "BLKDEV_DEFAULT_RQ" in blk_core_text
        else "BLKDEV_MAX_RQ"
    )
    blk_core_old = f"\tq->nr_requests = {blk_core_rq_define};\n"
    blk_core_new = (
        f"\tq->nr_requests = {blk_core_rq_define};\n"
        f"\tq->async_depth = {blk_core_rq_define};\n"
    )
    if f"q->async_depth = {blk_core_rq_define};" not in blk_core_text:
        blk_core_text = replace_once_blk(blk_core_text, blk_core_old, blk_core_new, "feature_porting/blk_async_depth_blk_core_default")
        write_text(blk_core_c, blk_core_text)

    blk_mq_anchor_new = """static struct request *__blk_mq_alloc_requests(struct blk_mq_alloc_data *data)\n{\n\tvoid (*limit_depth)(blk_opf_t, struct blk_mq_alloc_data *) = NULL;\n\tstruct request_queue *q = data->q;\n"""
    blk_mq_anchor_old = """static struct request *__blk_mq_alloc_requests(struct blk_mq_alloc_data *data)\n{\n\tstruct request_queue *q = data->q;\n"""
    blk_mq_limit_call = """\tif (limit_depth)\n\t\tlimit_depth(data->cmd_flags, data);\n"""
    blk_mq_with_marker_new = marker + """\nstatic void blk_mq_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)\n{\n\tstruct elevator_queue *e = data->q->elevator;\n\n\tif (!e || !e->type->ops.limit_depth)\n\t\treturn;\n\tif (op_is_flush(opf) || blk_op_is_passthrough(opf) ||\n\t    (data->flags & BLK_MQ_REQ_RESERVED))\n\t\treturn;\n\n\te->type->ops.limit_depth(opf, data);\n}\n\nstatic struct request *__blk_mq_alloc_requests(struct blk_mq_alloc_data *data)\n{\n\tvoid (*limit_depth)(blk_opf_t, struct blk_mq_alloc_data *) = NULL;\n\tstruct request_queue *q = data->q;\n"""
    blk_mq_with_marker_old = marker + """\nstatic void blk_mq_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)\n{\n\tstruct elevator_queue *e = data->q->elevator;\n\n\tif (!e || !e->type->ops.limit_depth)\n\t\treturn;\n\tif (op_is_flush(opf) || blk_op_is_passthrough(opf) ||\n\t    (data->flags & BLK_MQ_REQ_RESERVED))\n\t\treturn;\n\n\te->type->ops.limit_depth(opf, data);\n}\n\nstatic struct request *__blk_mq_alloc_requests(struct blk_mq_alloc_data *data)\n{\n\tvoid (*limit_depth)(blk_opf_t, struct blk_mq_alloc_data *) = NULL;\n\tstruct request_queue *q = data->q;\n"""
    if marker not in blk_mq_text:
        if blk_mq_anchor_new in blk_mq_text:
            blk_mq_text = replace_once_blk(blk_mq_text, blk_mq_anchor_new, blk_mq_with_marker_new, "feature_porting/blk_async_depth_blk_mq_add_helper")
        else:
            blk_mq_text = replace_once_blk(blk_mq_text, blk_mq_anchor_old, blk_mq_with_marker_old, "feature_porting/blk_async_depth_blk_mq_add_helper")

    needs_limit_depth_decl = (
        marker in blk_mq_text
        or "limit_depth = blk_mq_limit_depth;" in blk_mq_text
        or blk_mq_limit_call in blk_mq_text
    )
    if needs_limit_depth_decl and blk_mq_anchor_new not in blk_mq_text and blk_mq_anchor_old in blk_mq_text:
        blk_mq_text = replace_once_blk(
            blk_mq_text,
            blk_mq_anchor_old,
            blk_mq_anchor_new,
            "feature_porting/blk_async_depth_blk_mq_restore_decl",
        )

    blk_mq_limit_old = """\tif (q->elevator) {\n\t\tstruct elevator_queue *e = q->elevator;\n\n\t\tdata->rq_flags |= RQF_ELV;\n\n\t\t/*\n\t\t * Flush/passthrough requests are special and go directly to the\n\t\t * dispatch list. Don't include reserved tags in the\n\t\t * limiting, as it isn't useful.\n\t\t */\n\t\tif (!op_is_flush(data->cmd_flags) &&\n\t\t    !blk_op_is_passthrough(data->cmd_flags) &&\n\t\t    e->type->ops.limit_depth &&\n\t\t    !(data->flags & BLK_MQ_REQ_RESERVED))\n\t\t\tlimit_depth = e->type->ops.limit_depth;\n\t}\n\nretry:\n\tdata->ctx = blk_mq_get_ctx(q);\n\tdata->hctx = blk_mq_map_queue(q, data->cmd_flags, data->ctx);\n\tif (!(data->rq_flags & RQF_ELV))\n\t\tblk_mq_tag_busy(data->hctx);\n\n\tif (data->flags & BLK_MQ_REQ_RESERVED)\n\t\tdata->rq_flags |= RQF_RESV;\n"""
    blk_mq_limit_old_legacy = """\tif (q->elevator) {\n\t\tstruct elevator_queue *e = q->elevator;\n\n\t\tdata->rq_flags |= RQF_ELV;\n\n\t\t/*\n\t\t * Flush/passthrough requests are special and go directly to the\n\t\t * dispatch list. Don't include reserved tags in the\n\t\t * limiting, as it isn't useful.\n\t\t */\n\t\tif (!op_is_flush(data->cmd_flags) &&\n\t\t    !blk_op_is_passthrough(data->cmd_flags) &&\n\t\t    e->type->ops.limit_depth &&\n\t\t    !(data->flags & BLK_MQ_REQ_RESERVED))\n\t\t\te->type->ops.limit_depth(data->cmd_flags, data);\n\t}\n\nretry:\n\tdata->ctx = blk_mq_get_ctx(q);\n\tdata->hctx = blk_mq_map_queue(q, data->cmd_flags, data->ctx);\n\tif (!(data->rq_flags & RQF_ELV))\n\t\tblk_mq_tag_busy(data->hctx);\n\n\tif (data->flags & BLK_MQ_REQ_RESERVED)\n\t\tdata->rq_flags |= RQF_RESV;\n"""
    blk_mq_limit_new = """\tif (q->elevator) {\n\t\tdata->rq_flags |= RQF_ELV;\n\t\tlimit_depth = blk_mq_limit_depth;\n\t}\n\nretry:\n\tdata->ctx = blk_mq_get_ctx(q);\n\tdata->hctx = blk_mq_map_queue(q, data->cmd_flags, data->ctx);\n\tif (!(data->rq_flags & RQF_ELV))\n\t\tblk_mq_tag_busy(data->hctx);\n\n\tif (data->flags & BLK_MQ_REQ_RESERVED)\n\t\tdata->rq_flags |= RQF_RESV;\n"""
    # 5.15 has no RQF_ELV/RQF_RESV and keys tag_busy off a local elevator
    # pointer, so its counterpart keeps that pointer and adds only the deferred
    # limit_depth hand-off. Same effect: the elevator's limit_depth runs after
    # hctx assignment rather than before.
    blk_mq_limit_old_5_15 = """\tif (e) {\n\t\t/*\n\t\t * Flush/passthrough requests are special and go directly to the\n\t\t * dispatch list. Don't include reserved tags in the\n\t\t * limiting, as it isn't useful.\n\t\t */\n\t\tif (!op_is_flush(data->cmd_flags) &&\n\t\t    !blk_op_is_passthrough(data->cmd_flags) &&\n\t\t    e->type->ops.limit_depth &&\n\t\t    !(data->flags & BLK_MQ_REQ_RESERVED))\n\t\t\te->type->ops.limit_depth(data->cmd_flags, data);\n\t}\n\nretry:\n\tdata->ctx = blk_mq_get_ctx(q);\n\tdata->hctx = blk_mq_map_queue(q, data->cmd_flags, data->ctx);\n\tif (!e)\n\t\tblk_mq_tag_busy(data->hctx);\n"""
    blk_mq_limit_new_5_15 = """\tif (e)\n\t\tlimit_depth = blk_mq_limit_depth;\n\nretry:\n\tdata->ctx = blk_mq_get_ctx(q);\n\tdata->hctx = blk_mq_map_queue(q, data->cmd_flags, data->ctx);\n\tif (!e)\n\t\tblk_mq_tag_busy(data->hctx);\n"""
    if "limit_depth = blk_mq_limit_depth;" not in blk_mq_text:
        if blk_mq_limit_old in blk_mq_text:
            blk_mq_text = replace_once_blk(blk_mq_text, blk_mq_limit_old, blk_mq_limit_new, "feature_porting/blk_async_depth_blk_mq_apply_limit")
        elif blk_mq_limit_old_legacy in blk_mq_text:
            blk_mq_text = replace_once_blk(blk_mq_text, blk_mq_limit_old_legacy, blk_mq_limit_new, "feature_porting/blk_async_depth_blk_mq_apply_limit")
        else:
            blk_mq_text = replace_once_blk(blk_mq_text, blk_mq_limit_old_5_15, blk_mq_limit_new_5_15, "feature_porting/blk_async_depth_blk_mq_apply_limit")

    blk_mq_init_queue_old = "\tq->nr_requests = set->queue_depth;\n"
    blk_mq_init_queue_new = "\tq->nr_requests = set->queue_depth;\n\tq->async_depth = set->queue_depth;\n"
    if "q->async_depth = set->queue_depth;" not in blk_mq_text:
        blk_mq_text = replace_once_blk(blk_mq_text, blk_mq_init_queue_old, blk_mq_init_queue_new, "feature_porting/blk_async_depth_blk_mq_queue_init")

    # Invoke the deferred hook. The whole point of hoisting limit_depth into a
    # function pointer is to run it after hctx assignment -- the shallow depth it
    # sets is consumed by __blk_mq_get_tag() -- so the call goes immediately
    # before blk_mq_get_tag(). 6.1 trees that already carry the call skip this.
    blk_mq_get_tag_old = "\ttag = blk_mq_get_tag(data);\n"
    blk_mq_get_tag_new = blk_mq_limit_call + "\n\ttag = blk_mq_get_tag(data);\n"
    if blk_mq_limit_call not in blk_mq_text:
        blk_mq_text = replace_once_blk(blk_mq_text, blk_mq_get_tag_old, blk_mq_get_tag_new, "feature_porting/blk_async_depth_blk_mq_limit_call")

    blk_mq_resize_old = """\tif (!ret) {\n\t\tq->nr_requests = nr;\n\t\tif (blk_mq_is_shared_tags(set->flags)) {\n"""
    blk_mq_resize_bad = """\tif (!ret) {\n\t\t/* ABK feature_porting: preserve relative async_depth across nr_requests resize. */\n\t\tq->async_depth = max(q->async_depth * nr / q->nr_requests, 1U);\n\t\tq->nr_requests = nr;\n\t\tif (blk_mq_is_shared_tags(set->flags)) {\n"""
    blk_mq_resize_new = """\tif (!ret) {\n\t\tunsigned long new_async_depth;\n\n\t\t/* ABK feature_porting: preserve relative async_depth across nr_requests resize. */\n\t\tnew_async_depth = q->async_depth * nr / q->nr_requests;\n\t\tif (!new_async_depth)\n\t\t\tnew_async_depth = 1;\n\t\tq->async_depth = min_t(unsigned long, new_async_depth, UINT_MAX);\n\t\tq->nr_requests = nr;\n\t\tif (blk_mq_is_shared_tags(set->flags)) {\n"""
    # The scaling goes in ahead of `q->nr_requests = nr;`, so what follows that
    # line does not matter. 5.15 guards the shared-tag resize with
    # `q->elevator &&` and no brace, hence the shorter fallback anchor.
    blk_mq_resize_old_short = """\tif (!ret) {\n\t\tq->nr_requests = nr;\n"""
    blk_mq_resize_new_short = """\tif (!ret) {\n\t\tunsigned long new_async_depth;\n\n\t\t/* ABK feature_porting: preserve relative async_depth across nr_requests resize. */\n\t\tnew_async_depth = q->async_depth * nr / q->nr_requests;\n\t\tif (!new_async_depth)\n\t\t\tnew_async_depth = 1;\n\t\tq->async_depth = min_t(unsigned long, new_async_depth, UINT_MAX);\n\t\tq->nr_requests = nr;\n"""
    if "new_async_depth = q->async_depth * nr / q->nr_requests;" not in blk_mq_text:
        if blk_mq_resize_bad in blk_mq_text:
            blk_mq_text = replace_once_blk(blk_mq_text, blk_mq_resize_bad, blk_mq_resize_new, "feature_porting/blk_async_depth_blk_mq_resize")
        elif blk_shape_for_tree(blk_mq_text, blk_mq_resize_old) in blk_mq_text:
            blk_mq_text = replace_once_blk(blk_mq_text, blk_mq_resize_old, blk_mq_resize_new, "feature_porting/blk_async_depth_blk_mq_resize")
        else:
            blk_mq_text = replace_once_blk(blk_mq_text, blk_mq_resize_old_short, blk_mq_resize_new_short, "feature_porting/blk_async_depth_blk_mq_resize")
        write_text(blk_mq_c, blk_mq_text)

    blk_mq_sched_none_old = """\tif (!e) {\n\t\tblk_queue_flag_clear(QUEUE_FLAG_SQ_SCHED, q);\n\t\tq->elevator = NULL;\n\t\tq->nr_requests = q->tag_set->queue_depth;\n\t\treturn 0;\n\t}\n"""
    blk_mq_sched_none_new = """\tif (!e) {\n\t\tblk_queue_flag_clear(QUEUE_FLAG_SQ_SCHED, q);\n\t\tq->elevator = NULL;\n\t\tq->nr_requests = q->tag_set->queue_depth;\n\t\tq->async_depth = q->tag_set->queue_depth;\n\t\treturn 0;\n\t}\n"""
    # QUEUE_FLAG_SQ_SCHED arrived in 6.1; on 5.15 the no-elevator arm just
    # clears q->elevator, so the counterpart drops that call.
    blk_mq_sched_none_old_5_15 = """\tif (!e) {\n\t\tq->elevator = NULL;\n\t\tq->nr_requests = q->tag_set->queue_depth;\n\t\treturn 0;\n\t}\n"""
    blk_mq_sched_none_new_5_15 = """\tif (!e) {\n\t\tq->elevator = NULL;\n\t\tq->nr_requests = q->tag_set->queue_depth;\n\t\tq->async_depth = q->tag_set->queue_depth;\n\t\treturn 0;\n\t}\n"""
    if "q->async_depth = q->tag_set->queue_depth;" not in blk_mq_sched_text:
        if blk_mq_sched_none_old in blk_mq_sched_text:
            blk_mq_sched_text = replace_once_blk(blk_mq_sched_text, blk_mq_sched_none_old, blk_mq_sched_none_new, "feature_porting/blk_async_depth_blk_mq_sched_none")
        else:
            blk_mq_sched_text = replace_once_blk(blk_mq_sched_text, blk_mq_sched_none_old_5_15, blk_mq_sched_none_new_5_15, "feature_porting/blk_async_depth_blk_mq_sched_none")

    blk_mq_sched_default_old = """\tq->nr_requests = 2 * min_t(unsigned int, q->tag_set->queue_depth,\n\t\t\t\t   BLKDEV_DEFAULT_RQ);\n"""
    blk_mq_sched_default_new = """\tq->nr_requests = 2 * min_t(unsigned int, q->tag_set->queue_depth,\n\t\t\t\t   BLKDEV_DEFAULT_RQ);\n\tq->async_depth = q->nr_requests;\n"""
    if "q->async_depth = q->nr_requests;" not in blk_mq_sched_text:
        blk_mq_sched_text = replace_once_blk(blk_mq_sched_text, blk_mq_sched_default_old, blk_mq_sched_default_new, "feature_porting/blk_async_depth_blk_mq_sched_default")
        write_text(blk_mq_sched_c, blk_mq_sched_text)

    blk_sysfs_insert_anchor = """static ssize_t\nqueue_ra_store(struct request_queue *q, const char *page, size_t count)\n{\n"""
    blk_sysfs_insert_block = """static ssize_t queue_async_depth_show(struct request_queue *q, char *page)\n{\n\treturn queue_var_show(q->async_depth, page);\n}\n\nstatic ssize_t\nqueue_async_depth_store(struct request_queue *q, const char *page, size_t count)\n{\n\tunsigned long nr;\n\tint ret;\n\n\tif (!queue_is_mq(q))\n\t\treturn -EINVAL;\n\n\tret = queue_var_store(&nr, page, count);\n\tif (ret < 0)\n\t\treturn ret;\n\tif (nr == 0)\n\t\treturn -EINVAL;\n\tif (!q->elevator)\n\t\treturn -EINVAL;\n\n\tq->async_depth = min_t(unsigned long, q->nr_requests, nr);\n\tif (q->elevator->type->ops.depth_updated) {\n\t\tstruct blk_mq_hw_ctx *hctx;\n\t\tunsigned long i;\n\n\t\tqueue_for_each_hw_ctx(q, hctx, i) {\n\t\t\tif (hctx->sched_tags)\n\t\t\t\tq->elevator->type->ops.depth_updated(hctx);\n\t\t}\n\t}\n\treturn ret;\n}\n\nstatic ssize_t\nqueue_ra_store(struct request_queue *q, const char *page, size_t count)\n{\n"""
    if "static ssize_t queue_async_depth_show(struct request_queue *q, char *page)" not in blk_sysfs_text:
        blk_sysfs_text = replace_once_blk(blk_sysfs_text, blk_sysfs_insert_anchor, blk_sysfs_insert_block, "feature_porting/blk_async_depth_blk_sysfs_funcs")

    blk_sysfs_entry_old = """QUEUE_RW_ENTRY(queue_requests, "nr_requests");\nQUEUE_RW_ENTRY(queue_ra, "read_ahead_kb");\n"""
    blk_sysfs_entry_new = """QUEUE_RW_ENTRY(queue_requests, "nr_requests");\nQUEUE_RW_ENTRY(queue_async_depth, "async_depth");\nQUEUE_RW_ENTRY(queue_ra, "read_ahead_kb");\n"""
    if 'QUEUE_RW_ENTRY(queue_async_depth, "async_depth");' not in blk_sysfs_text:
        blk_sysfs_text = replace_once_blk(blk_sysfs_text, blk_sysfs_entry_old, blk_sysfs_entry_new, "feature_porting/blk_async_depth_blk_sysfs_entry")

    blk_sysfs_attr_old = """\t&queue_requests_entry.attr,\n\t&queue_ra_entry.attr,\n"""
    blk_sysfs_attr_new = """\t&queue_requests_entry.attr,\n\t&queue_async_depth_entry.attr,\n\t&queue_ra_entry.attr,\n"""
    if "&queue_async_depth_entry.attr," not in blk_sysfs_text:
        blk_sysfs_text = replace_once_blk(blk_sysfs_text, blk_sysfs_attr_old, blk_sysfs_attr_new, "feature_porting/blk_async_depth_blk_sysfs_attr")
        write_text(blk_sysfs_c, blk_sysfs_text)

    elevator_none_old = """\tret = blk_mq_init_sched(q, new_e);\n\tif (ret)\n\t\tgoto out;\n"""
    elevator_none_new = """\tret = blk_mq_init_sched(q, new_e);\n\tif (ret)\n\t\tgoto out;\n\tif (!new_e)\n\t\tq->async_depth = q->tag_set->queue_depth;\n"""
    if "if (!new_e)\n\t\tq->async_depth = q->tag_set->queue_depth;" not in elevator_text:
        elevator_text = replace_once_blk(elevator_text, elevator_none_old, elevator_none_new, "feature_porting/blk_async_depth_elevator_none")
        write_text(elevator_c, elevator_text)

    dd_helper_anchor = """/*\n * Called by __blk_mq_alloc_request(). The shallow_depth value set by this\n * function is used by __blk_mq_get_tag().\n */\n"""
    dd_helper_new = """/*\n * 'depth' is a number in the range 1..INT_MAX representing a number of\n * requests. Scale it with a factor (1 << bt->sb.shift) / q->nr_requests since\n * 1..(1 << bt->sb.shift) is the range expected by sbitmap_get_shallow().\n * Values larger than q->nr_requests have the same effect as q->nr_requests.\n */\nstatic int dd_to_word_depth(struct blk_mq_hw_ctx *hctx, unsigned int qdepth)\n{\n\tstruct sbitmap_queue *bt = &hctx->sched_tags->bitmap_tags;\n\tconst unsigned int nrr = hctx->queue->nr_requests;\n\n\treturn ((qdepth << bt->sb.shift) + nrr - 1) / nrr;\n}\n\n/*\n * Called by __blk_mq_alloc_request(). The shallow_depth value set by this\n * function is used by __blk_mq_get_tag().\n */\n"""
    if "static int dd_to_word_depth(struct blk_mq_hw_ctx *hctx, unsigned int qdepth)" not in dd_text:
        dd_text = replace_once_blk(dd_text, dd_helper_anchor, dd_helper_new, "feature_porting/blk_async_depth_deadline_helper")

    dd_limit_old = "\tdata->shallow_depth = dd->async_depth;\n"
    dd_limit_new = "\tdata->shallow_depth = dd_to_word_depth(data->hctx, dd->async_depth);\n"
    if "dd_to_word_depth(data->hctx, dd->async_depth);" not in dd_text:
        dd_text = replace_once_blk(dd_text, dd_limit_old, dd_limit_new, "feature_porting/blk_async_depth_deadline_limit")

    dd_depth_old = """\tstruct request_queue *q = hctx->queue;\n\tstruct deadline_data *dd = q->elevator->elevator_data;\n\tstruct blk_mq_tags *tags = hctx->sched_tags;\n\tunsigned int shift = tags->bitmap_tags.sb.shift;\n\n\tdd->async_depth = max(1U, 3 * (1U << shift)  / 4);\n\n\tsbitmap_queue_min_shallow_depth(&tags->bitmap_tags, dd->async_depth);\n"""
    dd_depth_new = """\tstruct request_queue *q = hctx->queue;\n\tstruct deadline_data *dd = q->elevator->elevator_data;\n\tstruct blk_mq_tags *tags = hctx->sched_tags;\n\n\tdd->async_depth = q->async_depth;\n\n\tsbitmap_queue_min_shallow_depth(&tags->bitmap_tags, 1);\n"""
    if "max(1U, 3 * (1U << shift)  / 4)" in dd_text:
        dd_text = replace_once_blk(dd_text, dd_depth_old, dd_depth_new, "feature_porting/blk_async_depth_deadline_depth")
    elif "dd->async_depth = q->nr_requests;" in dd_text and "dd->async_depth = q->async_depth;" not in dd_text:
        dd_text = dd_text.replace("dd->async_depth = q->nr_requests;", "dd->async_depth = q->async_depth;", 1)

    dd_init_old = "\tq->elevator = eq;\n\treturn 0;\n"
    dd_init_new = "\tq->elevator = eq;\n\tq->async_depth = q->nr_requests;\n\treturn 0;\n"
    if "q->async_depth = q->nr_requests;" not in dd_text:
        dd_text = replace_once_blk(dd_text, dd_init_old, dd_init_new, "feature_porting/blk_async_depth_deadline_init")
        write_text(dd_c, dd_text)

    bfq_update_old = """static void bfq_update_depths(struct bfq_data *bfqd, struct sbitmap_queue *bt)\n{\n\tunsigned int depth = 1U << bt->sb.shift;\n\n\tbfqd->full_depth_shift = bt->sb.shift;\n"""
    bfq_update_new = """static void bfq_update_depths(struct bfq_data *bfqd, struct sbitmap_queue *bt)\n{\n\tunsigned int depth = bfqd->queue->async_depth;\n\n\tbfqd->full_depth_shift = bt->sb.shift;\n"""
    # 6.1 had already factored bfq's per-word depths onto a single `depth`
    # local, so the graft only has to redirect that local at q->async_depth.
    # 5.15 still derives each of the four word_depths from (1U << bt->sb.shift)
    # inline, so introduce the local and key all four off it -- preserving the
    # 50% / 75% / ~18% / ~37% ratios bfq documents.
    bfq_words_old_5_15 = """\tbfqd->word_depths[0][0] = max((1U << bt->sb.shift) >> 1, 1U);\n"""
    bfq_words_new_5_15 = """\tdepth = bfqd->queue->async_depth;\n\tbfqd->word_depths[0][0] = max(depth >> 1, 1U);\n"""
    bfq_word_scale = (
        ("\tbfqd->word_depths[0][1] = max(((1U << bt->sb.shift) * 3) >> 2, 1U);\n",
         "\tbfqd->word_depths[0][1] = max((depth * 3) >> 2, 1U);\n"),
        ("\tbfqd->word_depths[1][0] = max(((1U << bt->sb.shift) * 3) >> 4, 1U);\n",
         "\tbfqd->word_depths[1][0] = max((depth * 3) >> 4, 1U);\n"),
        ("\tbfqd->word_depths[1][1] = max(((1U << bt->sb.shift) * 6) >> 4, 1U);\n",
         "\tbfqd->word_depths[1][1] = max((depth * 6) >> 4, 1U);\n"),
    )
    bfq_decl_old_5_15 = "\tunsigned int i, j, min_shallow = UINT_MAX;\n"
    bfq_decl_new_5_15 = "\tunsigned int i, j, min_shallow = UINT_MAX;\n\tunsigned int depth;\n"

    if "unsigned int depth = bfqd->queue->async_depth;" not in bfq_text and "unsigned int depth = 1U << bt->sb.shift;" in bfq_text:
        bfq_text = replace_once_blk(bfq_text, bfq_update_old, bfq_update_new, "feature_porting/blk_async_depth_bfq_update")
    elif "depth = bfqd->queue->async_depth;" not in bfq_text and bfq_words_old_5_15 in bfq_text:
        bfq_text = replace_once_blk(bfq_text, bfq_decl_old_5_15, bfq_decl_new_5_15, "feature_porting/blk_async_depth_bfq_decl")
        bfq_text = replace_once_blk(bfq_text, bfq_words_old_5_15, bfq_words_new_5_15, "feature_porting/blk_async_depth_bfq_update")
        for old, new in bfq_word_scale:
            bfq_text = replace_once_blk(bfq_text, old, new, "feature_porting/blk_async_depth_bfq_word_depths")

    bfq_init_old = "\tbfqd->queue = q;\n"
    bfq_init_new = "\tbfqd->queue = q;\n\tq->async_depth = (q->nr_requests * 3) >> 2;\n"
    if "q->async_depth = (q->nr_requests * 3) >> 2;" not in bfq_text:
        bfq_text = replace_once_blk(bfq_text, bfq_init_old, bfq_init_new, "feature_porting/blk_async_depth_bfq_init")
        write_text(bfq_c, bfq_text)

    kyber_init_old = """\teq->elevator_data = kqd;\n\tq->elevator = eq;\n\n\treturn 0;\n}\n"""
    kyber_init_new = """\teq->elevator_data = kqd;\n\tq->elevator = eq;\n\tq->async_depth = q->nr_requests * KYBER_ASYNC_PERCENT / 100;\n\n\treturn 0;\n}\n"""
    if "q->async_depth = q->nr_requests * KYBER_ASYNC_PERCENT / 100;" not in kyber_text:
        kyber_text = replace_once_blk(kyber_text, kyber_init_old, kyber_init_new, "feature_porting/blk_async_depth_kyber_init")

    kyber_depth_old = """\tstruct kyber_queue_data *kqd = hctx->queue->elevator->elevator_data;\n\tstruct blk_mq_tags *tags = hctx->sched_tags;\n\tunsigned int shift = tags->bitmap_tags.sb.shift;\n\n\tkqd->async_depth = (1U << shift) * KYBER_ASYNC_PERCENT / 100U;\n\n\tsbitmap_queue_min_shallow_depth(&tags->bitmap_tags, kqd->async_depth);\n"""
    kyber_depth_new = """\tstruct request_queue *q = hctx->queue;\n\tstruct kyber_queue_data *kqd = q->elevator->elevator_data;\n\tstruct blk_mq_tags *tags = hctx->sched_tags;\n\n\tkqd->async_depth = q->async_depth;\n\n\tsbitmap_queue_min_shallow_depth(&tags->bitmap_tags, kqd->async_depth);\n"""
    if "kqd->async_depth = q->async_depth;" not in kyber_text and "kqd->async_depth = (1U << shift) * KYBER_ASYNC_PERCENT / 100U;" in kyber_text:
        kyber_text = replace_once_blk(kyber_text, kyber_depth_old, kyber_depth_new, "feature_porting/blk_async_depth_kyber_depth")
    if blk_mq_text != read_text(blk_mq_c):
        write_text(blk_mq_c, blk_mq_text)
    if blk_mq_sched_text != read_text(blk_mq_sched_c):
        write_text(blk_mq_sched_c, blk_mq_sched_text)
    if blk_sysfs_text != read_text(blk_sysfs_c):
        write_text(blk_sysfs_c, blk_sysfs_text)
    if elevator_text != read_text(elevator_c):
        write_text(elevator_c, elevator_text)
    if dd_text != read_text(dd_c):
        write_text(dd_c, dd_text)
    if bfq_text != read_text(bfq_c):
        write_text(bfq_c, bfq_text)
    if kyber_text != read_text(kyber_c):
        write_text(kyber_c, kyber_text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="internal_static_api",
        ),
        "group": "blk_mq_async_depth",
        "mode": "patched",
        "touchpoints": [
            "include/linux/blkdev.h",
            "block/blk-core.c",
            "block/blk-mq.c",
            "block/blk-mq-sched.c",
            "block/blk-sysfs.c",
            "block/elevator.c",
            "block/mq-deadline.c",
            "block/bfq-iosched.c",
            "block/kyber-iosched.c",
        ],
        "ported_semantics": [
            "request_queue async_depth is persisted through Android KABI reserve slots",
            "blk-mq request allocation applies async_depth after hctx mapping",
            "queue/async_depth sysfs writes clamp to min(q->nr_requests, nr)",
            "mq-deadline, bfq, and kyber consume queue-level async_depth",
        ],
    }


def collect_blk_async_depth_status(common_root: Path) -> dict[str, object]:
    blk_mq_c = common_root / "block/blk-mq.c"
    blk_sysfs_c = common_root / "block/blk-sysfs.c"
    dd_c = common_root / "block/mq-deadline.c"
    bfq_c = common_root / "block/bfq-iosched.c"
    kyber_c = common_root / "block/kyber-iosched.c"

    blk_mq = read_text(blk_mq_c)
    blk_sysfs = read_text(blk_sysfs_c)
    dd = read_text(dd_c)
    bfq = read_text(bfq_c)
    kyber = read_text(kyber_c)

    target_anchors = {
        "blk_mq_limit_depth": "static void blk_mq_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)" in blk_mq,
        "blk_mq_async_depth_limit": "limit_depth = blk_mq_limit_depth;" in blk_mq and "e->type->ops.limit_depth(opf, data);" in blk_mq,
        "blk_mq_queue_init": "q->async_depth = set->queue_depth;" in blk_mq,
        "blk_mq_update_nr_requests_rel": "preserve relative async_depth across nr_requests resize" in blk_mq,
        "blk_mq_sched_default": "q->async_depth = q->nr_requests;" in read_text(common_root / "block/blk-mq-sched.c"),
        "queue_async_depth_show": "static ssize_t queue_async_depth_show(struct request_queue *q, char *page)" in blk_sysfs,
        "queue_async_depth_store": "queue_async_depth_store(struct request_queue *q, const char *page, size_t count)" in blk_sysfs,
        "queue_async_depth_attr": 'QUEUE_RW_ENTRY(queue_async_depth, "async_depth");' in blk_sysfs,
        "dd_limit_depth": "static void dd_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)" in dd,
        "dd_async_depth": "data->shallow_depth = dd_to_word_depth(data->hctx, dd->async_depth);" in dd,
        "dd_depth_updated": "static void dd_depth_updated(struct blk_mq_hw_ctx *hctx)" in dd,
        "dd_init_async_depth": "dd->async_depth = q->async_depth;" in dd,
        "bfq_limit_depth": "static void bfq_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)" in bfq,
        "bfq_word_depths": "unsigned int depth = bfqd->queue->async_depth;" in bfq,
        "bfq_depth_update": "static void bfq_depth_updated(struct blk_mq_hw_ctx *hctx)" in bfq,
        "bfq_init_async_depth": "q->async_depth = (q->nr_requests * 3) >> 2;" in bfq,
        "kyber_limit_depth": "static void kyber_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)" in kyber,
        "kyber_async_depth": "data->shallow_depth = kqd->async_depth;" in kyber,
        "kyber_depth_updated": "static void kyber_depth_updated(struct blk_mq_hw_ctx *hctx)" in kyber,
        "kyber_init_async_depth": "q->async_depth = q->nr_requests * KYBER_ASYNC_PERCENT / 100;" in kyber,
    }

    all_present = all(target_anchors.values())
    return {
        "status": "queue_depth_policy_tracked" if all_present else "partial",
        "phase": "queue_depth_policy_parity" if all_present else "queue_depth_policy_scan",
        "policy_scope": "block_queue_depth_not_storage_whole_target",
        "path": [
            str(blk_mq_c),
            str(blk_sysfs_c),
            str(dd_c),
            str(bfq_c),
            str(kyber_c),
        ],
        "mode": "already_present" if all_present else "missing_anchors",
        "ported_semantics": [
            "blk_mq_limit_depth() keeps flush and passthrough requests out of async_depth limits",
            "request_queue async_depth is stored through Android KABI reserve slots",
            "queue/async_depth sysfs writes clamp to min(q->nr_requests, nr)",
            "mq-deadline, bfq, and kyber all consume queue-level async_depth after feature_porting grafts",
        ],
        "tree_escalation_required": False,
        "target_anchors": {key: bool_status(value) for key, value in target_anchors.items()},
        "next_action": (
            "Keep async_depth as a block queue-depth policy line. "
            "Treat storage_whole_target as out of scope unless the scheduler hooks diverge."
        ),
    }


def patch_zram_compressed_writeback(common_root: Path) -> dict[str, object]:
    zram_h = common_root / "drivers/block/zram/zram_drv.h"
    zram_c = common_root / "drivers/block/zram/zram_drv.c"
    marker = "/* ABK feature_porting: zram compressed writeback graft. */"

    ensure_contains(zram_h, "#ifdef CONFIG_ZRAM_WRITEBACK", "feature_porting/zram_writeback_h")
    ensure_contains(zram_h, "ZRAM_WB,", "feature_porting/zram_writeback_h")
    ensure_contains(zram_h, "ZRAM_UNDER_WB,", "feature_porting/zram_writeback_h")
    ensure_contains(zram_h, "struct file *backing_dev;", "feature_porting/zram_writeback_h")

    ensure_contains(zram_c, "static ssize_t idle_store(struct device *dev,", "feature_porting/zram_writeback_c")
    ensure_contains(zram_c, "static ssize_t writeback_limit_enable_store(struct device *dev,", "feature_porting/zram_writeback_c")
    ensure_contains(zram_c, "static ssize_t writeback_limit_store(struct device *dev,", "feature_porting/zram_writeback_c")
    ensure_contains(zram_c, "static ssize_t backing_dev_store(struct device *dev,", "feature_porting/zram_writeback_c")
    ensure_contains(zram_c, "static ssize_t writeback_store(struct device *dev,", "feature_porting/zram_writeback_c")
    ensure_contains(zram_c, "static DEVICE_ATTR_RW(backing_dev);", "feature_porting/zram_writeback_c")
    ensure_contains(zram_c, "static DEVICE_ATTR_WO(writeback);", "feature_porting/zram_writeback_c")

    zram_h_text = read_text(zram_h)
    zram_c_text = read_text(zram_c)

    already_present = all(
        needle in zram_h_text or needle in zram_c_text
        for needle in (
            "bool compressed_wb;",
            "static ssize_t compressed_writeback_store(struct device *dev,",
            "static ssize_t compressed_writeback_show(struct device *dev,",
            "static DEVICE_ATTR_RW(compressed_writeback);",
            "&dev_attr_compressed_writeback.attr,",
            "if (zram->compressed_wb)",
        )
    )
    if already_present:
        return {
            **graft_metadata(
                hard_port_possible=False,
                semantic_port_used=True,
                max_function_port_used=False,
                sidecar_state_used=False,
                sidecar_state_scope="none",
                new_interface_used=True,
                new_interface_scope="sysfs_attr_and_existing_writeback_path",
            ),
            "path": [str(zram_c), str(zram_h)],
            "group": "zram_compressed_writeback",
            "mode": "already_present",
            "ported_semantics": [
                "compressed_writeback sysfs attr exists alongside backing_dev/writeback/writeback_limit controls",
                "writeback path can preserve compressed payloads when compressed_writeback is enabled",
                "feature_porting stays scoped to kernel/common zram writeback semantics only",
            ],
        }

    if "bool compressed_wb;" not in zram_h_text:
        h_old = "\tstruct file *backing_dev;\n\tspinlock_t wb_limit_lock;\n\tbool wb_limit_enable;\n"
        h_new = "\tstruct file *backing_dev;\n\tspinlock_t wb_limit_lock;\n\tbool wb_limit_enable;\n\tbool compressed_wb;\n"
        zram_h_text = replace_once(zram_h_text, h_old, h_new, "feature_porting/zram_writeback_h_compressed_flag")
        write_text(zram_h, zram_h_text)
        zram_h_text = read_text(zram_h)

    if "static ssize_t compressed_writeback_store(struct device *dev," not in zram_c_text:
        insert_anchor = """static ssize_t writeback_limit_enable_store(struct device *dev,\n\t\tstruct device_attribute *attr, const char *buf, size_t len)\n{\n"""
        insert_block = """/* ABK feature_porting: zram compressed writeback graft. */\nstatic ssize_t compressed_writeback_store(struct device *dev,\n\t\tstruct device_attribute *attr, const char *buf, size_t len)\n{\n\tstruct zram *zram = dev_to_zram(dev);\n\tbool val;\n\n\tif (kstrtobool(buf, &val))\n\t\treturn -EINVAL;\n\n\tdown_write(&zram->init_lock);\n\tif (init_done(zram)) {\n\t\tup_write(&zram->init_lock);\n\t\treturn -EBUSY;\n\t}\n\n\tzram->compressed_wb = val;\n\tup_write(&zram->init_lock);\n\n\treturn len;\n}\n\nstatic ssize_t compressed_writeback_show(struct device *dev,\n\t\tstruct device_attribute *attr, char *buf)\n{\n\tbool val;\n\tstruct zram *zram = dev_to_zram(dev);\n\n\tdown_read(&zram->init_lock);\n\tval = zram->compressed_wb;\n\tup_read(&zram->init_lock);\n\n\treturn scnprintf(buf, PAGE_SIZE, \"%d\\n\", val);\n}\n\nstatic ssize_t writeback_limit_enable_store(struct device *dev,\n\t\tstruct device_attribute *attr, const char *buf, size_t len)\n{\n"""
        zram_c_text = replace_once(zram_c_text, insert_anchor, insert_block, "feature_porting/zram_writeback_insert_attr")

    if "static DEVICE_ATTR_RW(compressed_writeback);" not in zram_c_text:
        attr_old = """static DEVICE_ATTR_RW(backing_dev);\nstatic DEVICE_ATTR_WO(writeback);\nstatic DEVICE_ATTR_RW(writeback_limit);\nstatic DEVICE_ATTR_RW(writeback_limit_enable);\n#endif\n"""
        attr_new = """static DEVICE_ATTR_RW(backing_dev);\nstatic DEVICE_ATTR_WO(writeback);\nstatic DEVICE_ATTR_RW(writeback_limit);\nstatic DEVICE_ATTR_RW(writeback_limit_enable);\nstatic DEVICE_ATTR_RW(compressed_writeback);\n#endif\n"""
        zram_c_text = replace_once(zram_c_text, attr_old, attr_new, "feature_porting/zram_writeback_attr_decl")

    if "&dev_attr_compressed_writeback.attr," not in zram_c_text:
        attrs_old = """\t&dev_attr_backing_dev.attr,\n\t&dev_attr_writeback.attr,\n\t&dev_attr_writeback_limit.attr,\n\t&dev_attr_writeback_limit_enable.attr,\n#endif\n"""
        attrs_new = """\t&dev_attr_backing_dev.attr,\n\t&dev_attr_writeback.attr,\n\t&dev_attr_writeback_limit.attr,\n\t&dev_attr_writeback_limit_enable.attr,\n\t&dev_attr_compressed_writeback.attr,\n#endif\n"""
        zram_c_text = replace_once(zram_c_text, attrs_old, attrs_new, "feature_porting/zram_writeback_attr_group")

    if "zram->compressed_wb = false;" not in zram_c_text:
        init_old = "#ifdef CONFIG_ZRAM_WRITEBACK\n\tspin_lock_init(&zram->wb_limit_lock);\n#endif\n\n\t/* gendisk structure */\n"
        init_new = "#ifdef CONFIG_ZRAM_WRITEBACK\n\tspin_lock_init(&zram->wb_limit_lock);\n\tzram->compressed_wb = false;\n#endif\n\n\t/* gendisk structure */\n"
        zram_c_text = replace_once(zram_c_text, init_old, init_new, "feature_porting/zram_writeback_default_init")

    write_text(zram_c, zram_c_text)
    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="sysfs_attr_and_existing_writeback_path",
        ),
        "path": [str(zram_c), str(zram_h)],
        "group": "zram_compressed_writeback",
        "mode": "patched",
        "ported_semantics": [
            "compressed_writeback sysfs attr is grafted onto the existing zram writeback control surface",
            "compressed_writeback defaults to false and remains writable only before init_done()",
            "feature_porting keeps zram scope inside kernel/common writeback semantics instead of replacing abk zram assets",
        ],
    }


def collect_zram_writeback_status(common_root: Path) -> dict[str, object]:
    zram_h = common_root / "drivers/block/zram/zram_drv.h"
    zram_c = common_root / "drivers/block/zram/zram_drv.c"
    zram_h_text = read_text(zram_h)
    zram_c_text = read_text(zram_c)

    target_anchors = {
        "config_zram_writeback": "#ifdef CONFIG_ZRAM_WRITEBACK" in zram_h_text or "#ifdef CONFIG_ZRAM_WRITEBACK" in zram_c_text,
        "zram_wb_flag": "ZRAM_WB," in zram_h_text,
        "zram_under_wb_flag": "ZRAM_UNDER_WB," in zram_h_text,
        "backing_dev_field": "struct file *backing_dev;" in zram_h_text,
        "idle_store": "static ssize_t idle_store(struct device *dev," in zram_c_text,
        "writeback_store": "static ssize_t writeback_store(struct device *dev," in zram_c_text,
        "writeback_limit_enable": "static ssize_t writeback_limit_enable_store(struct device *dev," in zram_c_text and "static ssize_t writeback_limit_enable_show(struct device *dev," in zram_c_text,
        "writeback_limit": "static ssize_t writeback_limit_store(struct device *dev," in zram_c_text and "static ssize_t writeback_limit_show(struct device *dev," in zram_c_text,
        "backing_dev_store": "static ssize_t backing_dev_store(struct device *dev," in zram_c_text and "static ssize_t backing_dev_show(struct device *dev," in zram_c_text,
        "compressed_writeback_attr": "static DEVICE_ATTR_RW(compressed_writeback);" in zram_c_text and "&dev_attr_compressed_writeback.attr," in zram_c_text,
    }
    all_present = all(target_anchors.values())
    marker_present = "/* ABK feature_porting: zram compressed writeback graft. */" in zram_c_text

    return {
        "status": "writeback_policy_tracked" if all_present else "partial",
        "phase": "compressed_writeback_parity" if all_present else "compressed_writeback_scan",
        "mode": "patched" if marker_present else ("already_present" if all_present else "missing_anchors"),
        "path": [str(zram_c), str(zram_h)],
        "ported_semantics": [
            "backing_dev binding, idle tagging, and writeback entry stay inside the kernel/common zram path",
            "writeback limit and enable controls remain first-class zram sysfs interfaces",
            "compressed_writeback stays a compatibility control-surface graft and does not absorb abk zram algorithm assets",
        ],
        "target_anchors": {key: bool_status(value) for key, value in target_anchors.items()},
        "tree_escalation_required": False,
        "next_action": (
            "Keep zram writeback inside feature_porting and do not merge algorithm-enhancement assets into the suite. "
            "Only add extra compatibility glue if abk mainline zram assets later conflict with this tree."
        ),
    }


def patch_nohz_field_refinement(common_root: Path) -> dict[str, object]:
    nohz_h = common_root / "include/linux/sched/nohz.h"
    tick_sched_c = common_root / "kernel/time/tick-sched.c"
    nohz_text = read_text(nohz_h)
    tick_sched_text = read_text(tick_sched_c)
    original_nohz = nohz_text
    original_tick_sched = tick_sched_text
    marker = "/* ABK feature_porting: nohz state field consistency helpers. */"

    ensure_contains(nohz_h, "extern void nohz_balance_enter_idle(int cpu);", "feature_porting/nohz_header")
    ensure_contains(nohz_h, "void calc_load_nohz_start(void);", "feature_porting/nohz_header")
    ensure_contains(tick_sched_c, "bool tick_nohz_tick_stopped(void)\n{", "feature_porting/nohz_tick_sched")
    ensure_contains(tick_sched_c, "void tick_nohz_irq_exit(void)\n{", "feature_porting/nohz_tick_sched")
    ensure_contains(tick_sched_c, "ktime_t tick_nohz_get_sleep_length(ktime_t *delta_next)\n{", "feature_porting/nohz_tick_sched")
    ensure_contains(tick_sched_c, "unsigned long tick_nohz_get_idle_calls_cpu(int cpu)\n{", "feature_porting/nohz_tick_sched")
    ensure_contains(tick_sched_c, "unsigned long tick_nohz_get_idle_calls(void)\n{", "feature_porting/nohz_tick_sched")
    ensure_contains(tick_sched_c, "void tick_nohz_idle_exit(void)\n{", "feature_porting/nohz_tick_sched")

    if "enum nohz_cpu_state {" not in nohz_text:
        enum_anchor = "/*\n * This is the interface between the scheduler and nohz/dynticks:\n */\n"
        enum_block = """/*\n * This is the interface between the scheduler and nohz/dynticks:\n */\n\nenum nohz_cpu_state {\n\tNOHZ_CPU_STATE_NONE = 0,\n\tNOHZ_CPU_STATE_INIDLE = 1U << 0,\n\tNOHZ_CPU_STATE_IDLE_ACTIVE = 1U << 1,\n\tNOHZ_CPU_STATE_TICK_STOPPED = 1U << 2,\n};\n"""
        nohz_text = replace_once(nohz_text, enum_anchor, enum_block, "feature_porting/nohz_state_enum")

    if "extern unsigned int nohz_cpu_state_flags(int cpu);" not in nohz_text:
        helper_anchor = "\n#endif /* _LINUX_SCHED_NOHZ_H */\n"
        helper_block = """
#ifdef CONFIG_NO_HZ_COMMON
extern unsigned int nohz_cpu_state_flags(int cpu);
extern unsigned long nohz_cpu_idle_calls(int cpu);

static inline bool nohz_cpu_state_test(int cpu, unsigned int state)
{
\treturn nohz_cpu_state_flags(cpu) & state;
}

static inline bool nohz_cpu_inidle(int cpu)
{
\treturn nohz_cpu_state_test(cpu, NOHZ_CPU_STATE_INIDLE);
}

static inline bool nohz_cpu_idle_active(int cpu)
{
\treturn nohz_cpu_state_test(cpu, NOHZ_CPU_STATE_IDLE_ACTIVE);
}

static inline bool nohz_cpu_tick_stopped(int cpu)
{
\treturn nohz_cpu_state_test(cpu, NOHZ_CPU_STATE_TICK_STOPPED);
}
#else
static inline unsigned int nohz_cpu_state_flags(int cpu)
{
\treturn 0;
}

static inline unsigned long nohz_cpu_idle_calls(int cpu)
{
\treturn 0;
}

static inline bool nohz_cpu_state_test(int cpu, unsigned int state)
{
\treturn false;
}

static inline bool nohz_cpu_inidle(int cpu)
{
\treturn false;
}

static inline bool nohz_cpu_idle_active(int cpu)
{
\treturn false;
}

static inline bool nohz_cpu_tick_stopped(int cpu)
{
\treturn false;
}
#endif

#endif /* _LINUX_SCHED_NOHZ_H */
"""
        nohz_text = replace_once(nohz_text, helper_anchor, helper_block, "feature_porting/nohz_state_helpers")

    helper_insert_anchor = '__setup("nohz=", setup_tick_nohz);\n\nbool tick_nohz_tick_stopped(void)\n'
    helper_insert_block = """__setup(\"nohz=\", setup_tick_nohz);\n\n/* ABK feature_porting: nohz state field consistency helpers. */\nstatic unsigned int abk_tick_nohz_state_flags(const struct tick_sched *ts)\n{\n\tunsigned int state = NOHZ_CPU_STATE_NONE;\n\n\tif (ts->inidle)\n\t\tstate |= NOHZ_CPU_STATE_INIDLE;\n\tif (ts->idle_active)\n\t\tstate |= NOHZ_CPU_STATE_IDLE_ACTIVE;\n\tif (ts->tick_stopped)\n\t\tstate |= NOHZ_CPU_STATE_TICK_STOPPED;\n\n\treturn state;\n}\n\nunsigned int nohz_cpu_state_flags(int cpu)\n{\n\treturn abk_tick_nohz_state_flags(tick_get_tick_sched(cpu));\n}\nEXPORT_SYMBOL_GPL(nohz_cpu_state_flags);\n\nunsigned long nohz_cpu_idle_calls(int cpu)\n{\n\treturn tick_get_tick_sched(cpu)->idle_calls;\n}\nEXPORT_SYMBOL_GPL(nohz_cpu_idle_calls);\n\nbool tick_nohz_tick_stopped(void)\n"""
    if marker not in tick_sched_text:
        tick_sched_text = replace_once(
            tick_sched_text,
            helper_insert_anchor,
            helper_insert_block,
            "feature_porting/nohz_tick_sched_helpers",
        )

    local_tick_stopped_old = """bool tick_nohz_tick_stopped(void)\n{\n\tstruct tick_sched *ts = this_cpu_ptr(&tick_cpu_sched);\n\n\treturn ts->tick_stopped;\n}\n"""
    local_tick_stopped_new = """bool tick_nohz_tick_stopped(void)\n{\n\tstruct tick_sched *ts = this_cpu_ptr(&tick_cpu_sched);\n\n\treturn !!(abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_TICK_STOPPED);\n}\n"""
    if "return !!(abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_TICK_STOPPED);" not in tick_sched_text:
        tick_sched_text = replace_once(
            tick_sched_text,
            local_tick_stopped_old,
            local_tick_stopped_new,
            "feature_porting/nohz_tick_stopped_local",
        )

    cpu_tick_stopped_old = """bool tick_nohz_tick_stopped_cpu(int cpu)\n{\n\tstruct tick_sched *ts = per_cpu_ptr(&tick_cpu_sched, cpu);\n\n\treturn ts->tick_stopped;\n}\n"""
    cpu_tick_stopped_new = """bool tick_nohz_tick_stopped_cpu(int cpu)\n{\n\tstruct tick_sched *ts = per_cpu_ptr(&tick_cpu_sched, cpu);\n\n\treturn !!(abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_TICK_STOPPED);\n}\n"""
    if "bool tick_nohz_tick_stopped_cpu(int cpu)" in tick_sched_text and "return !!(abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_TICK_STOPPED);" in tick_sched_text:
        pass
    elif "bool tick_nohz_tick_stopped_cpu(int cpu)" in tick_sched_text:
        tick_sched_text = replace_once(
            tick_sched_text,
            cpu_tick_stopped_old,
            cpu_tick_stopped_new,
            "feature_porting/nohz_tick_stopped_cpu",
        )

    irq_exit_old = """void tick_nohz_irq_exit(void)\n{\n\tstruct tick_sched *ts = this_cpu_ptr(&tick_cpu_sched);\n\n\tif (ts->inidle)\n\t\ttick_nohz_start_idle(ts);\n\telse\n\t\ttick_nohz_full_update_tick(ts);\n}\n"""
    irq_exit_new = """void tick_nohz_irq_exit(void)\n{\n\tstruct tick_sched *ts = this_cpu_ptr(&tick_cpu_sched);\n\n\tif (abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_INIDLE)\n\t\ttick_nohz_start_idle(ts);\n\telse\n\t\ttick_nohz_full_update_tick(ts);\n}\n"""
    if "if (abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_INIDLE)" not in tick_sched_text:
        tick_sched_text = replace_once(
            tick_sched_text,
            irq_exit_old,
            irq_exit_new,
            "feature_porting/nohz_irq_exit",
        )

    sleep_length_warn_old = "\tWARN_ON_ONCE(!ts->inidle);\n"
    sleep_length_warn_new = "\tWARN_ON_ONCE(!(abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_INIDLE));\n"
    if "WARN_ON_ONCE(!(abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_INIDLE));" not in tick_sched_text:
        tick_sched_text = replace_once(
            tick_sched_text,
            sleep_length_warn_old,
            sleep_length_warn_new,
            "feature_porting/nohz_sleep_length_warn",
        )

    idle_calls_cpu_old = """unsigned long tick_nohz_get_idle_calls_cpu(int cpu)\n{\n\tstruct tick_sched *ts = tick_get_tick_sched(cpu);\n\n\treturn ts->idle_calls;\n}\n"""
    idle_calls_cpu_new = """unsigned long tick_nohz_get_idle_calls_cpu(int cpu)\n{\n\treturn nohz_cpu_idle_calls(cpu);\n}\n"""
    if "return nohz_cpu_idle_calls(cpu);" not in tick_sched_text:
        tick_sched_text = replace_once(
            tick_sched_text,
            idle_calls_cpu_old,
            idle_calls_cpu_new,
            "feature_porting/nohz_idle_calls_cpu",
        )

    idle_calls_old = """unsigned long tick_nohz_get_idle_calls(void)\n{\n\tstruct tick_sched *ts = this_cpu_ptr(&tick_cpu_sched);\n\n\treturn ts->idle_calls;\n}\n"""
    idle_calls_new = """unsigned long tick_nohz_get_idle_calls(void)\n{\n\treturn nohz_cpu_idle_calls(smp_processor_id());\n}\n"""
    if "return nohz_cpu_idle_calls(smp_processor_id());" not in tick_sched_text:
        tick_sched_text = replace_once(
            tick_sched_text,
            idle_calls_old,
            idle_calls_new,
            "feature_porting/nohz_idle_calls_local",
        )

    idle_exit_old = """void tick_nohz_idle_exit(void)\n{\n\tstruct tick_sched *ts = this_cpu_ptr(&tick_cpu_sched);\n\tbool idle_active, tick_stopped;\n\tktime_t now;\n\n\tlocal_irq_disable();\n\n\tWARN_ON_ONCE(!ts->inidle);\n\tWARN_ON_ONCE(ts->timer_expires_base);\n\n\tts->inidle = 0;\n\tidle_active = ts->idle_active;\n\ttick_stopped = ts->tick_stopped;\n\n\tif (idle_active || tick_stopped)\n\t\tnow = ktime_get();\n\n\tif (idle_active)\n\t\ttick_nohz_stop_idle(ts, now);\n\n\tif (tick_stopped)\n\t\ttick_nohz_idle_update_tick(ts, now);\n\n\tlocal_irq_enable();\n}\n"""
    idle_exit_new = """void tick_nohz_idle_exit(void)\n{\n\tstruct tick_sched *ts = this_cpu_ptr(&tick_cpu_sched);\n\tbool idle_active, tick_stopped;\n\tunsigned int nohz_state;\n\tktime_t now;\n\n\tlocal_irq_disable();\n\n\tnohz_state = abk_tick_nohz_state_flags(ts);\n\tWARN_ON_ONCE(!(nohz_state & NOHZ_CPU_STATE_INIDLE));\n\tWARN_ON_ONCE(ts->timer_expires_base);\n\n\tts->inidle = 0;\n\tidle_active = !!(nohz_state & NOHZ_CPU_STATE_IDLE_ACTIVE);\n\ttick_stopped = !!(nohz_state & NOHZ_CPU_STATE_TICK_STOPPED);\n\n\tif (idle_active || tick_stopped)\n\t\tnow = ktime_get();\n\n\tif (idle_active)\n\t\ttick_nohz_stop_idle(ts, now);\n\n\tif (tick_stopped)\n\t\ttick_nohz_idle_update_tick(ts, now);\n\n\tlocal_irq_enable();\n}\n"""
    if "idle_active = !!(nohz_state & NOHZ_CPU_STATE_IDLE_ACTIVE);" not in tick_sched_text:
        tick_sched_text = replace_once(
            tick_sched_text,
            idle_exit_old,
            idle_exit_new,
            "feature_porting/nohz_idle_exit",
        )

    if nohz_text != original_nohz:
        write_text(nohz_h, nohz_text)
    if tick_sched_text != original_tick_sched:
        write_text(tick_sched_c, tick_sched_text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="scheduler_nohz_header_and_tick_state_helpers",
        ),
        "group": "nohz_field_refinement",
        "mode": "patched" if nohz_text != original_nohz or tick_sched_text != original_tick_sched else "already_patched",
        "paths": [str(nohz_h), str(tick_sched_c)],
        "ported_semantics": [
            "legacy tick_sched inidle, idle_active, and tick_stopped fields are normalized behind nohz_cpu_state_flags()",
            "nohz_cpu_idle_calls() gives the scheduler/report path one CPU-scoped idle-call accessor",
            "tick_nohz idle-exit and tick-stopped checks now read from a shared nohz state snapshot instead of open-coded field probes",
        ],
    }


def patch_avg_idle_preemption_mode(common_root: Path) -> dict[str, object]:
    core_c = common_root / "kernel/sched/core.c"
    fair_c = common_root / "kernel/sched/fair.c"
    idle_c = common_root / "kernel/sched/idle.c"
    sched_h = common_root / "kernel/sched/sched.h"

    core_text = read_text(core_c)
    fair_text = read_text(fair_c)
    idle_text = read_text(idle_c)
    sched_h_text = read_text(sched_h)
    original_core = core_text
    original_fair = fair_text
    original_idle = idle_text
    original_sched_h = sched_h_text
    marker = "/* ABK feature_porting: avg_idle preemption mode simplification. */"

    ensure_contains(core_c, "trace_sched_wakeup(p);", "feature_porting/avg_idle_core")
    ensure_contains(fair_c, "static int select_idle_cpu(struct task_struct *p, struct sched_domain *sd, bool has_idle_core, int target)", "feature_porting/avg_idle_fair")
    ensure_contains(idle_c, "static void put_prev_task_idle(struct rq *rq, struct task_struct *prev)", "feature_porting/avg_idle_idle")
    ensure_contains(sched_h, "u64\t\t\tavg_idle;", "feature_porting/avg_idle_sched_h")

    if "void update_rq_avg_idle(struct rq *rq)" not in core_text:
        helper_anchor = "/*\n * Mark the task runnable and perform wakeup-preemption.\n */\n"
        helper_block = """/* ABK feature_porting: avg_idle preemption mode simplification. */\nvoid update_rq_avg_idle(struct rq *rq)\n{\n\tu64 delta = rq_clock(rq) - rq->idle_stamp;\n\tu64 max = 2 * rq->max_idle_balance_cost;\n\n\tupdate_avg(&rq->avg_idle, delta);\n\n\tif (rq->avg_idle > max)\n\t\trq->avg_idle = max;\n\trq->idle_stamp = 0;\n}\n\n/*\n * Mark the task runnable and perform wakeup-preemption.\n */\n"""
        core_text = replace_once(core_text, helper_anchor, helper_block, "feature_porting/avg_idle_helper")

    wakeup_old = """\tif (rq->idle_stamp) {\n\t\tu64 delta = rq_clock(rq) - rq->idle_stamp;\n\t\tu64 max = 2*rq->max_idle_balance_cost;\n\n\t\tupdate_avg(&rq->avg_idle, delta);\n\n\t\tif (rq->avg_idle > max)\n\t\t\trq->avg_idle = max;\n\n\t\trq->wake_stamp = jiffies;\n\t\trq->wake_avg_idle = rq->avg_idle / 2;\n\n\t\trq->idle_stamp = 0;\n\t}\n"""
    wakeup_new = ""
    if "rq->wake_avg_idle = rq->avg_idle / 2;" in core_text:
        core_text = replace_once(core_text, wakeup_old, wakeup_new, "feature_porting/avg_idle_ttwu")

    init_old = """\t\trq->idle_stamp = 0;\n\t\trq->avg_idle = 2*sysctl_sched_migration_cost;\n\t\trq->wake_stamp = jiffies;\n\t\trq->wake_avg_idle = rq->avg_idle;\n\t\trq->max_idle_balance_cost = sysctl_sched_migration_cost;\n"""
    init_new = """\t\trq->idle_stamp = 0;\n\t\trq->avg_idle = 2*sysctl_sched_migration_cost;\n\t\trq->max_idle_balance_cost = sysctl_sched_migration_cost;\n"""
    if "rq->wake_avg_idle = rq->avg_idle;" in core_text:
        core_text = replace_once(core_text, init_old, init_new, "feature_porting/avg_idle_init")

    if "sched_feat(SIS_PROP) && !has_idle_core" in fair_text:
        select_old = """/*\n * Scan the LLC domain for idle CPUs; this is dynamically regulated by\n * comparing the average scan cost (tracked in sd->avg_scan_cost) against the\n * average idle time for this rq (as found in rq->avg_idle).\n */\nstatic int select_idle_cpu(struct task_struct *p, struct sched_domain *sd, bool has_idle_core, int target)\n{\n\tstruct cpumask *cpus = this_cpu_cpumask_var_ptr(select_rq_mask);\n\tint i, cpu, idle_cpu = -1, nr = INT_MAX;\n\tstruct sched_domain_shared *sd_share;\n\tstruct rq *this_rq = this_rq();\n\tint this = smp_processor_id();\n\tstruct sched_domain *this_sd = NULL;\n\tu64 time = 0;\n\n\tcpumask_and(cpus, sched_domain_span(sd), p->cpus_ptr);\n\n\tif (sched_feat(SIS_PROP) && !has_idle_core) {\n\t\tu64 avg_cost, avg_idle, span_avg;\n\t\tunsigned long now = jiffies;\n\n\t\tthis_sd = rcu_dereference(*this_cpu_ptr(&sd_llc));\n\t\tif (!this_sd)\n\t\t\treturn -1;\n\n\t\t/*\n\t\t * If we're busy, the assumption that the last idle period\n\t\t * predicts the future is flawed; age away the remaining\n\t\t * predicted idle time.\n\t\t */\n\t\tif (unlikely(this_rq->wake_stamp < now)) {\n\t\t\twhile (this_rq->wake_stamp < now && this_rq->wake_avg_idle) {\n\t\t\t\tthis_rq->wake_stamp++;\n\t\t\t\tthis_rq->wake_avg_idle >>= 1;\n\t\t\t}\n\t\t}\n\n\t\tavg_idle = this_rq->wake_avg_idle;\n\t\tavg_cost = this_sd->avg_scan_cost + 1;\n\n\t\tspan_avg = sd->span_weight * avg_idle;\n\t\tif (span_avg > 4*avg_cost)\n\t\t\tnr = div_u64(span_avg, avg_cost);\n\t\telse\n\t\t\tnr = 4;\n\n\t\ttime = cpu_clock(this);\n\t}\n\n\tif (sched_feat(SIS_UTIL)) {\n\t\tsd_share = rcu_dereference(per_cpu(sd_llc_shared, target));\n\t\tif (sd_share) {\n\t\t\t/* because !--nr is the condition to stop scan */\n\t\t\tnr = READ_ONCE(sd_share->nr_idle_scan) + 1;\n\t\t\t/* overloaded LLC is unlikely to have idle cpu/core */\n\t\t\tif (nr == 1)\n\t\t\t\treturn -1;\n\t\t}\n\t}\n\n\tfor_each_cpu_wrap(cpu, cpus, target + 1) {\n\t\tif (has_idle_core) {\n\t\t\ti = select_idle_core(p, cpu, cpus, &idle_cpu);\n\t\t\tif ((unsigned int)i < nr_cpumask_bits)\n\t\t\t\treturn i;\n\n\t\t} else {\n\t\t\tif (!--nr)\n\t\t\t\treturn -1;\n\t\t\tidle_cpu = __select_idle_cpu(cpu, p);\n\t\t\tif ((unsigned int)idle_cpu < nr_cpumask_bits)\n\t\t\t\tbreak;\n\t\t}\n\t}\n\n\tif (has_idle_core)\n\t\tset_idle_cores(target, false);\n\n\tif (sched_feat(SIS_PROP) && this_sd && !has_idle_core) {\n\t\ttime = cpu_clock(this) - time;\n\n\t\t/*\n\t\t * Account for the scan cost of wakeups against the average\n\t\t * idle time.\n\t\t */\n\t\tthis_rq->wake_avg_idle -= min(this_rq->wake_avg_idle, time);\n\n\t\tupdate_avg(&this_sd->avg_scan_cost, time);\n\t}\n\n\treturn idle_cpu;\n}\n"""
        select_new = """/*\n * ABK feature_porting: avg_idle preemption mode simplification.\n * Scan the LLC domain for idle CPUs; this tree keeps the SIS_UTIL shared\n * LLC scan cap and drops the wake_avg_idle/SIS_PROP prediction path.\n */\nstatic int select_idle_cpu(struct task_struct *p, struct sched_domain *sd, bool has_idle_core, int target)\n{\n\tstruct cpumask *cpus = this_cpu_cpumask_var_ptr(select_rq_mask);\n\tint i, cpu, idle_cpu = -1, nr = INT_MAX;\n\tstruct sched_domain_shared *sd_share;\n\n\tcpumask_and(cpus, sched_domain_span(sd), p->cpus_ptr);\n\n\tif (sched_feat(SIS_UTIL)) {\n\t\tsd_share = rcu_dereference(per_cpu(sd_llc_shared, target));\n\t\tif (sd_share) {\n\t\t\t/* because !--nr is the condition to stop scan */\n\t\t\tnr = READ_ONCE(sd_share->nr_idle_scan) + 1;\n\t\t\t/* overloaded LLC is unlikely to have idle cpu/core */\n\t\t\tif (nr == 1)\n\t\t\t\treturn -1;\n\t\t}\n\t}\n\n\tfor_each_cpu_wrap(cpu, cpus, target + 1) {\n\t\tif (has_idle_core) {\n\t\t\ti = select_idle_core(p, cpu, cpus, &idle_cpu);\n\t\t\tif ((unsigned int)i < nr_cpumask_bits)\n\t\t\t\treturn i;\n\n\t\t} else {\n\t\t\tif (--nr <= 0)\n\t\t\t\treturn -1;\n\t\t\tidle_cpu = __select_idle_cpu(cpu, p);\n\t\t\tif ((unsigned int)idle_cpu < nr_cpumask_bits)\n\t\t\t\tbreak;\n\t\t}\n\t}\n\n\tif (has_idle_core)\n\t\tset_idle_cores(target, false);\n\n\treturn idle_cpu;\n}\n"""
        fair_text = replace_once(fair_text, select_old, select_new, "feature_porting/avg_idle_select_idle_cpu")

    idle_old = """static void put_prev_task_idle(struct rq *rq, struct task_struct *prev)\n{\n}\n"""
    idle_new = """static void put_prev_task_idle(struct rq *rq, struct task_struct *prev)\n{\n\tupdate_rq_avg_idle(rq);\n}\n"""
    if "update_rq_avg_idle(rq);" not in idle_text:
        idle_text = replace_once(idle_text, idle_old, idle_new, "feature_porting/avg_idle_idle_put_prev")

    if original_core != core_text:
        write_text(core_c, core_text)
    if original_fair != fair_text:
        write_text(fair_c, fair_text)
    if idle_text != original_idle:
        write_text(idle_c, idle_text)
    if "extern void update_rq_avg_idle(struct rq *rq);" not in sched_h_text:
        sched_anchor = "extern void cfs_bandwidth_usage_dec(void);\n\n#ifdef CONFIG_NO_HZ_COMMON\n"
        sched_insert = "extern void cfs_bandwidth_usage_dec(void);\nextern void update_rq_avg_idle(struct rq *rq);\n\n#ifdef CONFIG_NO_HZ_COMMON\n"
        sched_h_text = replace_once(sched_h_text, sched_anchor, sched_insert, "feature_porting/avg_idle_sched_h")
    if original_sched_h != sched_h_text:
        write_text(sched_h, sched_h_text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="file_local_helper",
        ),
        "group": "avg_idle_preemption_mode",
        "mode": "patched" if core_text != original_core or fair_text != original_fair or idle_text != original_idle or sched_h_text != original_sched_h else "already_patched",
        "status": "avg_idle_thresholds_simplified" if (core_text != original_core or fair_text != original_fair or idle_text != original_idle or sched_h_text != original_sched_h) else "already_simplified",
        "phase": "wake_side_prediction_removed",
        "target_shape": "idle_exit_avg_idle_only",
        "wake_avg_idle_retained": True,
        "sis_prop_simplified": True,
        "newidle_threshold_simplified": True,
        "paths": [str(core_c), str(fair_c), str(idle_c), str(sched_h)],
        "ported_semantics": [
            "avg_idle is updated from the idle exit helper path instead of wake-side prediction state",
            "select_idle_cpu() keeps only the SIS_UTIL shared LLC scan cap and no longer decays wake_avg_idle or budgets scans with SIS_PROP",
            "newidle and nohz thresholds continue to gate directly on avg_idle without the wake_avg_idle side channel",
        ],
        "tree_escalation_required": False,
        "next_action": (
            "Keep avg_idle preemption simplification inside feature_porting. "
            "Do not reintroduce wake-side prediction or idle-governor policy rewrites unless the direct avg_idle thresholds prove insufficient."
        ),
    }


def patch_swap_table_phase2_large_folios(common_root: Path) -> dict[str, object]:
    swap_state_c = common_root / "mm/swap_state.c"
    swap_h = common_root / "mm/swap.h"
    swap_state_text = read_text(swap_state_c)
    swap_h_text = read_text(swap_h)
    original_swap_state = swap_state_text
    original_swap_h = swap_h_text
    marker = "/* ABK feature_porting: swap table phase2 large folios helper graft. */"

    ensure_contains(swap_state_c, "struct folio *swap_cache_get_folio(swp_entry_t entry,", "feature_porting/swap_state_swap_cache_get")
    ensure_contains(swap_state_c, "struct page *__read_swap_cache_async(swp_entry_t entry, gfp_t gfp_mask,", "feature_porting/swap_state_read_async")
    ensure_contains(swap_state_c, "struct page *read_swap_cache_async(swp_entry_t entry, gfp_t gfp_mask,", "feature_porting/swap_state_read_public")
    ensure_contains(swap_state_c, "struct page *swap_cluster_readahead(swp_entry_t entry, gfp_t gfp_mask,", "feature_porting/swap_state_cluster_ra")
    ensure_contains(swap_state_c, "static struct page *swap_vma_readahead(swp_entry_t fentry, gfp_t gfp_mask,", "feature_porting/swap_state_vma_ra")
    ensure_contains(swap_h, "struct folio *swap_cache_get_folio(swp_entry_t entry,", "feature_porting/swap_h_swap_cache_get")

    if marker in swap_state_text:
        return {
            **graft_metadata(
                hard_port_possible=False,
                semantic_port_used=True,
                max_function_port_used=False,
                sidecar_state_used=False,
                sidecar_state_scope="none",
                new_interface_used=True,
                new_interface_scope="mm_swap_state_file_local_folio_helpers",
            ),
            "group": "swap_table_phase2_large_folios",
            "mode": "already_patched",
            "paths": [str(swap_state_c), str(swap_h)],
            "public_surface_retained": True,
            "ported_semantics": [
                "mm/swap_state.c uses folio-first swapcache allocation helpers under the legacy page-returning surface",
                "swap readahead queues IO through swap_read_folio()-style wrappers and reports SWAP_RA/SWAP_RA_HIT through folio state",
                "large folio race fallback stays explicit and does not widen into reclaim or shmem policy rewrites",
            ],
        }

    swap_h_insert_anchor = "struct page *find_get_incore_page(struct address_space *mapping, pgoff_t index);\n\n"
    swap_h_insert_block = """struct page *find_get_incore_page(struct address_space *mapping, pgoff_t index);\n\nstruct folio *swap_cache_alloc_folio(swp_entry_t entry, gfp_t gfp_mask,\n\t\t\t\t     struct vm_area_struct *vma,\n\t\t\t\t     unsigned long addr,\n\t\t\t\t     bool *new_page_allocated);\nstruct folio *swapin_folio(swp_entry_t entry, struct folio *folio,\n\t\t\t  struct swap_iocb **plug);\nstruct folio *read_swap_cache_async_folio(swp_entry_t entry, gfp_t gfp_mask,\n\t\t\t\t       struct vm_area_struct *vma,\n\t\t\t\t       unsigned long addr,\n\t\t\t\t       struct swap_iocb **plug);\n\n"""
    if "struct folio *swap_cache_alloc_folio(swp_entry_t entry, gfp_t gfp_mask," not in swap_h_text:
        swap_h_text = replace_once(swap_h_text, swap_h_insert_anchor, swap_h_insert_block, "feature_porting/swap_h_insert_folio_decls")

    swap_h_stub_anchor = "static inline struct page *swap_cluster_readahead(swp_entry_t entry,\n\t\t\t\tgfp_t gfp_mask, struct vm_fault *vmf)\n{\n\treturn NULL;\n}\n\n"
    swap_h_stub_block = """static inline struct folio *swap_cache_alloc_folio(swp_entry_t entry,\n\t\t\t\t\tgfp_t gfp_mask,\n\t\t\t\t\tstruct vm_area_struct *vma,\n\t\t\t\t\tunsigned long addr,\n\t\t\t\t\tbool *new_page_allocated)\n{\n\tif (new_page_allocated)\n\t\t*new_page_allocated = false;\n\treturn NULL;\n}\n\nstatic inline struct folio *swapin_folio(swp_entry_t entry, struct folio *folio,\n\t\t\t\t struct swap_iocb **plug)\n{\n\treturn NULL;\n}\n\nstatic inline struct folio *read_swap_cache_async_folio(swp_entry_t entry,\n\t\t\t\t\tgfp_t gfp_mask,\n\t\t\t\t\tstruct vm_area_struct *vma,\n\t\t\t\t\tunsigned long addr,\n\t\t\t\t\tstruct swap_iocb **plug)\n{\n\treturn NULL;\n}\n\nstatic inline struct page *swap_cluster_readahead(swp_entry_t entry,\n\t\t\t\tgfp_t gfp_mask, struct vm_fault *vmf)\n{\n\treturn NULL;\n}\n\n"""
    if "static inline struct folio *swap_cache_alloc_folio(swp_entry_t entry," not in swap_h_text:
        swap_h_text = replace_once(swap_h_text, swap_h_stub_anchor, swap_h_stub_block, "feature_porting/swap_h_insert_folio_stubs")

    forward_decl_anchor = "static inline bool swap_use_vma_readahead(void)\n{\n\treturn READ_ONCE(enable_vma_readahead) && !atomic_read(&nr_rotate_swap);\n}\n"
    forward_decl_block = """static inline bool swap_use_vma_readahead(void)\n{\n\treturn READ_ONCE(enable_vma_readahead) && !atomic_read(&nr_rotate_swap);\n}\n\nstatic void swap_update_readahead_info(struct folio *folio,\n\t\t\t\t       struct vm_area_struct *vma,\n\t\t\t\t       unsigned long addr);\n"""
    if "static void swap_update_readahead_info(struct folio *folio," not in swap_state_text:
        swap_state_text = replace_once(swap_state_text, forward_decl_anchor, forward_decl_block, "feature_porting/swap_state_forward_decl")

    helper_anchor = "struct page *__read_swap_cache_async(swp_entry_t entry, gfp_t gfp_mask,\n\t\t\tstruct vm_area_struct *vma, unsigned long addr,\n\t\t\tbool *new_page_allocated)\n{\n"
    helper_block = """/* ABK feature_porting: swap table phase2 large folios helper graft. */\nstatic void swap_update_readahead_info(struct folio *folio,\n\t\t\t\t       struct vm_area_struct *vma,\n\t\t\t\t       unsigned long addr)\n{\n\tbool readahead;\n\tbool vma_ra = swap_use_vma_readahead();\n\n\tif (unlikely(folio_test_large(folio)))\n\t\treturn;\n\n\treadahead = folio_test_clear_readahead(folio);\n\tif (vma && vma_ra) {\n\t\tunsigned long ra_val;\n\t\tint win, hits;\n\n\t\tra_val = GET_SWAP_RA_VAL(vma);\n\t\twin = SWAP_RA_WIN(ra_val);\n\t\thits = SWAP_RA_HITS(ra_val);\n\t\tif (readahead)\n\t\t\thits = min_t(int, hits + 1, SWAP_RA_HITS_MAX);\n\t\tatomic_long_set(&vma->swap_readahead_info,\n\t\t\t\tSWAP_RA_VAL(addr, win, hits));\n\t}\n\n\tif (readahead) {\n\t\tcount_vm_event(SWAP_RA_HIT);\n\t\tif (!vma || !vma_ra)\n\t\t\tatomic_inc(&swapin_readahead_hits);\n\t}\n}\n\nstatic void swap_read_folio_compat(struct folio *folio, struct swap_iocb **plug)\n{\n\tswap_readpage(&folio->page, false, plug);\n}\n\nstatic struct folio *__swap_cache_prepare_and_add(swp_entry_t entry,\n\t\t\t\t\t struct folio *folio,\n\t\t\t\t\t gfp_t gfp_mask,\n\t\t\t\t\t bool charged)\n{\n\tstruct folio *swapcache = NULL;\n\tvoid *shadow = NULL;\n\tbool cache_prepared = false;\n\n\t__folio_set_locked(folio);\n\t__folio_set_swapbacked(folio);\n\n\tif (!charged && mem_cgroup_swapin_charge_folio(folio, NULL, gfp_mask, entry))\n\t\tgoto fail_unlock;\n\n\tfor (;;) {\n\t\tint err;\n\n\t\terr = swapcache_prepare(entry);\n\t\tif (!err) {\n\t\t\tcache_prepared = true;\n\t\t\tbreak;\n\t\t}\n\t\tif (err != -EEXIST || folio_test_large(folio))\n\t\t\tgoto fail_unlock;\n\n\t\tswapcache = filemap_get_folio(swap_address_space(entry), swp_offset(entry));\n\t\tif (swapcache)\n\t\t\tgoto fail_unlock;\n\n\t\t/* public surface retained: keep the 6.1 cache-flag race backoff */\n\t\tschedule_timeout_uninterruptible(1);\n\t}\n\n\tif (add_to_swap_cache(folio, entry, gfp_mask & GFP_RECLAIM_MASK, &shadow))\n\t\tgoto fail_unlock;\n\n\tmem_cgroup_swapin_uncharge_swap(entry);\n\tif (shadow)\n\t\tworkingset_refault(folio, shadow);\n\tfolio_add_lru(folio);\n\treturn folio;\n\nfail_unlock:\n\tif (cache_prepared)\n\t\tput_swap_folio(folio, entry);\n\tfolio_unlock(folio);\n\treturn swapcache;\n}\n\nstruct folio *swap_cache_alloc_folio(swp_entry_t entry, gfp_t gfp_mask,\n\t\t\t\t     struct vm_area_struct *vma,\n\t\t\t\t     unsigned long addr,\n\t\t\t\t     bool *new_page_allocated)\n{\n\tstruct swap_info_struct *si;\n\tstruct folio *folio;\n\tstruct folio *result;\n\n\t*new_page_allocated = false;\n\tsi = get_swap_device(entry);\n\tif (!si)\n\t\treturn NULL;\n\tfolio = filemap_get_folio(swap_address_space(entry), swp_offset(entry));\n\tif (folio)\n\t\tgoto out_put;\n\tif (!__swp_swapcount(entry) && swap_slot_cache_enabled)\n\t\tgoto out_put_null;\n\n\tfolio = vma_alloc_folio(gfp_mask, 0, vma, addr, false);\n\tif (!folio)\n\t\tgoto out_put_null;\n\n\tresult = __swap_cache_prepare_and_add(entry, folio, gfp_mask, false);\n\tif (result != folio)\n\t\tfolio_put(folio);\n\telse\n\t\t*new_page_allocated = true;\n\tfolio = result;\n\nout_put:\n\tput_swap_device(si);\n\treturn folio;\n\nout_put_null:\n\tfolio = NULL;\n\tgoto out_put;\n}\n\nstruct folio *swapin_folio(swp_entry_t entry, struct folio *folio,\n\t\t\t  struct swap_iocb **plug)\n{\n\tstruct folio *swapcache;\n\n\tswapcache = __swap_cache_prepare_and_add(entry, folio, 0, true);\n\tif (swapcache == folio)\n\t\tswap_read_folio_compat(folio, plug);\n\treturn swapcache;\n}\n\nstruct folio *read_swap_cache_async_folio(swp_entry_t entry, gfp_t gfp_mask,\n\t\t\t\t       struct vm_area_struct *vma,\n\t\t\t\t       unsigned long addr,\n\t\t\t\t       struct swap_iocb **plug)\n{\n\tstruct folio *folio;\n\tbool page_allocated;\n\n\tfolio = swap_cache_alloc_folio(entry, gfp_mask, vma, addr,\n\t\t\t\t       &page_allocated);\n\tif (folio && page_allocated)\n\t\tswap_read_folio_compat(folio, plug);\n\treturn folio;\n}\n\nstruct page *__read_swap_cache_async(swp_entry_t entry, gfp_t gfp_mask,\n\t\t\tstruct vm_area_struct *vma, unsigned long addr,\n\t\t\tbool *new_page_allocated)\n{\n"""
    if marker not in swap_state_text:
        swap_state_text = replace_once(swap_state_text, helper_anchor, helper_block, "feature_porting/swap_state_insert_helpers")

    cache_get_old = """struct folio *swap_cache_get_folio(swp_entry_t entry,\n\t\tstruct vm_area_struct *vma, unsigned long addr)\n{\n\tstruct folio *folio;\n\tstruct swap_info_struct *si;\n\n\tsi = get_swap_device(entry);\n\tif (!si)\n\t\treturn NULL;\n\tfolio = filemap_get_folio(swap_address_space(entry), swp_offset(entry));\n\tput_swap_device(si);\n\n\tif (folio) {\n\t\tbool vma_ra = swap_use_vma_readahead();\n\t\tbool readahead;\n\n\t\t/*\n\t\t * At the moment, we don't support PG_readahead for anon THP\n\t\t * so let's bail out rather than confusing the readahead stat.\n\t\t */\n\t\tif (unlikely(folio_test_large(folio)))\n\t\t\treturn folio;\n\n\t\treadahead = folio_test_clear_readahead(folio);\n\t\tif (vma && vma_ra) {\n\t\t\tunsigned long ra_val;\n\t\t\tint win, hits;\n\n\t\t\tra_val = GET_SWAP_RA_VAL(vma);\n\t\t\twin = SWAP_RA_WIN(ra_val);\n\t\t\thits = SWAP_RA_HITS(ra_val);\n\t\t\tif (readahead)\n\t\t\t\thits = min_t(int, hits + 1, SWAP_RA_HITS_MAX);\n\t\t\tatomic_long_set(&vma->swap_readahead_info,\n\t\t\t\t\tSWAP_RA_VAL(addr, win, hits));\n\t\t}\n\n\t\tif (readahead) {\n\t\t\tcount_vm_event(SWAP_RA_HIT);\n\t\t\tif (!vma || !vma_ra)\n\t\t\t\tatomic_inc(&swapin_readahead_hits);\n\t\t}\n\t}\n\n\treturn folio;\n}\n"""
    cache_get_new = """struct folio *swap_cache_get_folio(swp_entry_t entry,\n\t\tstruct vm_area_struct *vma, unsigned long addr)\n{\n\tstruct folio *folio;\n\tstruct swap_info_struct *si;\n\n\tsi = get_swap_device(entry);\n\tif (!si)\n\t\treturn NULL;\n\tfolio = filemap_get_folio(swap_address_space(entry), swp_offset(entry));\n\tput_swap_device(si);\n\tif (folio)\n\t\tswap_update_readahead_info(folio, vma, addr);\n\treturn folio;\n}\n"""
    if "swap_update_readahead_info(folio, vma, addr);" not in swap_state_text:
        swap_state_text = replace_once(swap_state_text, cache_get_old, cache_get_new, "feature_porting/swap_state_cache_get_use_helper")

    read_public_old = """struct page *read_swap_cache_async(swp_entry_t entry, gfp_t gfp_mask,\n\t\t\t\t   struct vm_area_struct *vma,\n\t\t\t\t   unsigned long addr, struct swap_iocb **plug)\n{\n\tbool page_was_allocated;\n\tstruct page *retpage = __read_swap_cache_async(entry, gfp_mask,\n\t\t\tvma, addr, &page_was_allocated);\n\n\tif (page_was_allocated)\n\t\tswap_readpage(retpage, false, plug);\n\n\treturn retpage;\n}\n"""
    read_public_new = """struct page *read_swap_cache_async(swp_entry_t entry, gfp_t gfp_mask,\n\t\t\t\t   struct vm_area_struct *vma,\n\t\t\t\t   unsigned long addr, struct swap_iocb **plug)\n{\n\tstruct folio *folio;\n\n\tfolio = read_swap_cache_async_folio(entry, gfp_mask, vma, addr, plug);\n\tif (!folio)\n\t\treturn NULL;\n\treturn folio_file_page(folio, swp_offset(entry));\n}\n"""
    if "folio = read_swap_cache_async_folio(entry, gfp_mask, vma, addr, plug);" not in swap_state_text:
        swap_state_text = replace_once(swap_state_text, read_public_old, read_public_new, "feature_porting/swap_state_public_wrapper")

    cluster_old = """struct page *swap_cluster_readahead(swp_entry_t entry, gfp_t gfp_mask,\n\t\t\t\tstruct vm_fault *vmf)\n{\n\tstruct page *page;\n\tunsigned long entry_offset = swp_offset(entry);\n\tunsigned long offset = entry_offset;\n\tunsigned long start_offset, end_offset;\n\tunsigned long mask;\n\tstruct swap_info_struct *si = swp_swap_info(entry);\n\tstruct blk_plug plug;\n\tstruct swap_iocb *splug = NULL;\n\tbool page_allocated;\n\tstruct vm_area_struct *vma = vmf->vma;\n\tunsigned long addr = vmf->address;\n\n\tmask = swapin_nr_pages(offset) - 1;\n\tif (!mask)\n\t\tgoto skip;\n\n\t/* Read a page_cluster sized and aligned cluster around offset. */\n\tstart_offset = offset & ~mask;\n\tend_offset = offset | mask;\n\tif (!start_offset)\t/* First page is swap header. */\n\t\tstart_offset++;\n\tif (end_offset >= si->max)\n\t\tend_offset = si->max - 1;\n\n\tblk_start_plug(&plug);\n\tfor (offset = start_offset; offset <= end_offset ; offset++) {\n\t\t/* Ok, do the async read-ahead now */\n\t\tpage = __read_swap_cache_async(\n\t\t\tswp_entry(swp_type(entry), offset),\n\t\t\tgfp_mask, vma, addr, &page_allocated);\n\t\tif (!page)\n\t\t\tcontinue;\n\t\tif (page_allocated) {\n\t\t\tswap_readpage(page, false, &splug);\n\t\t\tif (offset != entry_offset) {\n\t\t\t\tSetPageReadahead(page);\n\t\t\t\tcount_vm_event(SWAP_RA);\n\t\t\t}\n\t\t}\n\t\tput_page(page);\n\t}\n\tblk_finish_plug(&plug);\n\tswap_read_unplug(splug);\n\n\tlru_add_drain();\t/* Push any new pages onto the LRU now */\nskip:\n\t/* The page was likely read above, so no need for plugging here */\n\treturn read_swap_cache_async(entry, gfp_mask, vma, addr, NULL);\n}\n"""
    cluster_new = """struct page *swap_cluster_readahead(swp_entry_t entry, gfp_t gfp_mask,\n\t\t\t\tstruct vm_fault *vmf)\n{\n\tstruct folio *folio;\n\tunsigned long entry_offset = swp_offset(entry);\n\tunsigned long offset = entry_offset;\n\tunsigned long start_offset, end_offset;\n\tunsigned long mask;\n\tstruct swap_info_struct *si = swp_swap_info(entry);\n\tstruct blk_plug plug;\n\tstruct swap_iocb *splug = NULL;\n\tbool page_allocated;\n\tstruct vm_area_struct *vma = vmf->vma;\n\tunsigned long addr = vmf->address;\n\n\tmask = swapin_nr_pages(offset) - 1;\n\tif (!mask)\n\t\tgoto skip;\n\n\t/* Read a page_cluster sized and aligned cluster around offset. */\n\tstart_offset = offset & ~mask;\n\tend_offset = offset | mask;\n\tif (!start_offset)\t/* First page is swap header. */\n\t\tstart_offset++;\n\tif (end_offset >= si->max)\n\t\tend_offset = si->max - 1;\n\n\tblk_start_plug(&plug);\n\tfor (offset = start_offset; offset <= end_offset ; offset++) {\n\t\tfolio = swap_cache_alloc_folio(swp_entry(swp_type(entry), offset),\n\t\t\t\t\t      gfp_mask, vma, addr,\n\t\t\t\t\t      &page_allocated);\n\t\tif (!folio)\n\t\t\tcontinue;\n\t\tif (page_allocated) {\n\t\t\tswap_read_folio_compat(folio, &splug);\n\t\t\tif (offset != entry_offset) {\n\t\t\t\tfolio_set_readahead(folio);\n\t\t\t\tcount_vm_event(SWAP_RA);\n\t\t\t}\n\t\t}\n\t\tfolio_put(folio);\n\t}\n\tblk_finish_plug(&plug);\n\tswap_read_unplug(splug);\n\n\tlru_add_drain();\t/* Push any new pages onto the LRU now */\nskip:\n\tfolio = read_swap_cache_async_folio(entry, gfp_mask, vma, addr, NULL);\n\tif (!folio)\n\t\treturn NULL;\n\treturn folio_file_page(folio, swp_offset(entry));\n}\n"""
    if "folio = swap_cache_alloc_folio(swp_entry(swp_type(entry), offset)," not in swap_state_text:
        swap_state_text = replace_once(swap_state_text, cluster_old, cluster_new, "feature_porting/swap_state_cluster_readahead")

    vma_old = """static struct page *swap_vma_readahead(swp_entry_t fentry, gfp_t gfp_mask,\n\t\t\t\t       struct vm_fault *vmf)\n{\n\tstruct blk_plug plug;\n\tstruct swap_iocb *splug = NULL;\n\tstruct vm_area_struct *vma = vmf->vma;\n\tstruct page *page;\n\tpte_t *pte, pentry;\n\tswp_entry_t entry;\n\tunsigned int i;\n\tbool page_allocated;\n\tstruct vma_swap_readahead ra_info = {\n\t\t.win = 1,\n\t};\n\n\tswap_ra_info(vmf, &ra_info);\n\tif (ra_info.win == 1)\n\t\tgoto skip;\n\n\tblk_start_plug(&plug);\n\tfor (i = 0, pte = ra_info.ptes; i < ra_info.nr_pte;\n\t     i++, pte++) {\n\t\tpentry = *pte;\n\t\tif (!is_swap_pte(pentry))\n\t\t\tcontinue;\n\t\tentry = pte_to_swp_entry(pentry);\n\t\tif (unlikely(non_swap_entry(entry)))\n\t\t\tcontinue;\n\t\tpage = __read_swap_cache_async(entry, gfp_mask, vma,\n\t\t\t\t\t       vmf->address, &page_allocated);\n\t\tif (!page)\n\t\t\tcontinue;\n\t\tif (page_allocated) {\n\t\t\tswap_readpage(page, false, &splug);\n\t\t\tif (i != ra_info.offset) {\n\t\t\t\tSetPageReadahead(page);\n\t\t\t\tcount_vm_event(SWAP_RA);\n\t\t\t}\n\t\t}\n\t\tput_page(page);\n\t}\n\tblk_finish_plug(&plug);\n\tswap_read_unplug(splug);\n\tlru_add_drain();\nskip:\n\t/* The page was likely read above, so no need for plugging here */\n\treturn read_swap_cache_async(fentry, gfp_mask, vma, vmf->address,\n\t\t\t\t     NULL);\n}\n"""
    vma_new = """static struct page *swap_vma_readahead(swp_entry_t fentry, gfp_t gfp_mask,\n\t\t\t\t       struct vm_fault *vmf)\n{\n\tstruct blk_plug plug;\n\tstruct swap_iocb *splug = NULL;\n\tstruct vm_area_struct *vma = vmf->vma;\n\tstruct folio *folio;\n\tpte_t *pte, pentry;\n\tswp_entry_t entry;\n\tunsigned int i;\n\tbool page_allocated;\n\tstruct vma_swap_readahead ra_info = {\n\t\t.win = 1,\n\t};\n\n\tswap_ra_info(vmf, &ra_info);\n\tif (ra_info.win == 1)\n\t\tgoto skip;\n\n\tblk_start_plug(&plug);\n\tfor (i = 0, pte = ra_info.ptes; i < ra_info.nr_pte;\n\t     i++, pte++) {\n\t\tpentry = *pte;\n\t\tif (!is_swap_pte(pentry))\n\t\t\tcontinue;\n\t\tentry = pte_to_swp_entry(pentry);\n\t\tif (unlikely(non_swap_entry(entry)))\n\t\t\tcontinue;\n\t\tfolio = swap_cache_alloc_folio(entry, gfp_mask, vma, vmf->address,\n\t\t\t\t\t      &page_allocated);\n\t\tif (!folio)\n\t\t\tcontinue;\n\t\tif (page_allocated) {\n\t\t\tswap_read_folio_compat(folio, &splug);\n\t\t\tif (i != ra_info.offset) {\n\t\t\t\tfolio_set_readahead(folio);\n\t\t\t\tcount_vm_event(SWAP_RA);\n\t\t\t}\n\t\t}\n\t\tfolio_put(folio);\n\t}\n\tblk_finish_plug(&plug);\n\tswap_read_unplug(splug);\n\tlru_add_drain();\nskip:\n\tfolio = read_swap_cache_async_folio(fentry, gfp_mask, vma, vmf->address,\n\t\t\t\t    NULL);\n\tif (!folio)\n\t\treturn NULL;\n\treturn folio_file_page(folio, swp_offset(fentry));\n}\n"""
    if "folio = swap_cache_alloc_folio(entry, gfp_mask, vma, vmf->address," not in swap_state_text:
        swap_state_text = replace_once(swap_state_text, vma_old, vma_new, "feature_porting/swap_state_vma_readahead")

    if swap_state_text != original_swap_state:
        write_text(swap_state_c, swap_state_text)
    if swap_h_text != original_swap_h:
        write_text(swap_h, swap_h_text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="mm_swap_state_file_local_folio_helpers",
        ),
        "group": "swap_table_phase2_large_folios",
        "mode": "patched" if swap_state_text != original_swap_state or swap_h_text != original_swap_h else "already_patched",
        "paths": [str(swap_state_c), str(swap_h)],
        "public_surface_retained": True,
        "ported_semantics": [
            "mm/swap_state.c now allocates swapcache through swap_cache_alloc_folio() and feeds read IO through folio helpers",
            "read_swap_cache_async(), swap_cluster_readahead(), and swapin_readahead() keep page-returning wrappers while the internal helper split is folio-first",
            "large folio race fallback remains explicit by returning NULL on incompatible cache races instead of widening reclaim or shmem policy",
        ],
    }


def patch_slab_alloc_free_hotpath(common_root: Path) -> dict[str, object]:
    slub_c = common_root / "mm/slub.c"
    text = read_text(slub_c)
    original = text
    marker = "/* ABK feature_porting: slab alloc/free hotpath helper graft. */"

    ensure_contains_any(
        slub_c,
        [
            # 6.1 threads a list_lru through for memcg accounting; 5.15 does not.
            "static __always_inline void *slab_alloc_node(struct kmem_cache *s, struct list_lru *lru,",
            "static __always_inline void *slab_alloc_node(struct kmem_cache *s,",
        ],
        "feature_porting/slub_alloc",
    )
    ensure_contains(slub_c, "int kmem_cache_alloc_bulk(struct kmem_cache *s, gfp_t flags, size_t size,", "feature_porting/slub_alloc_bulk")
    ensure_contains(slub_c, "void kmem_cache_free(struct kmem_cache *s, void *x)", "feature_porting/slub_free")
    ensure_contains(slub_c, "static __always_inline void maybe_wipe_obj_freeptr(struct kmem_cache *s,", "feature_porting/slub_wipe")

    helper_insert_anchor = """/*
 * Inlined fastpath so that allocation functions (kmalloc, kmem_cache_alloc)
"""
    helper_insert_block = """
/* ABK feature_porting: slab alloc/free hotpath helper graft. */
static __always_inline void *abk_slab_next_object(struct kmem_cache *s,
\t\t\t\t\t      void *object)
{
\tvoid *next_object = get_freepointer_safe(s, object);

\tprefetch_freepointer(s, next_object);
\treturn next_object;
}
"""
    if marker not in text:
        text = replace_once(text, helper_insert_anchor, helper_insert_block + helper_insert_anchor, "feature_porting/slub_helpers")

    alloc_fast_old = """\t} else {\n\t\tvoid *next_object = get_freepointer_safe(s, object);\n\n\t\t/*\n\t\t * The cmpxchg will only match if there was no additional\n\t\t * operation and if we are on the right processor.\n"""
    alloc_fast_new = """\t} else {\n\t\tvoid *next_object = abk_slab_next_object(s, object);\n\n\t\t/*\n\t\t * The cmpxchg will only match if there was no additional\n\t\t * operation and if we are on the right processor.\n"""
    if alloc_fast_new not in text:
        text = replace_once(text, alloc_fast_old, alloc_fast_new, "feature_porting/slub_alloc_fastpath_next")

    alloc_bulk_old = """\t\tc->freelist = get_freepointer(s, object);\n\t\tp[i] = object;\n\t\tmaybe_wipe_obj_freeptr(s, p[i]);\n"""
    alloc_bulk_bad = """\t\tvoid *next_object = abk_slab_next_object(s, object);\n\n\t\tc->freelist = next_object;\n\t\tp[i] = object;\n\t\tmaybe_wipe_obj_freeptr(s, p[i]);\n"""
    alloc_bulk_new = """\t\tnext_object = abk_slab_next_object(s, object);\n\t\tc->freelist = next_object;\n\t\tp[i] = object;\n\t\tmaybe_wipe_obj_freeptr(s, p[i]);\n"""
    bulk_start, bulk_end = find_c_block(
        text,
        "int kmem_cache_alloc_bulk(struct kmem_cache *s, gfp_t flags, size_t size,",
        "feature_porting/slub_alloc_bulk_prefetch",
    )
    bulk_scope = text[bulk_start:bulk_end]
    bulk_original_scope = bulk_scope
    if "\tvoid *next_object;\n" not in bulk_scope:
        brace_idx = bulk_scope.find("{")
        if brace_idx < 0:
            raise SystemExit("feature_porting/slub_alloc_bulk_prefetch: opening brace missing")
        tail = bulk_scope[brace_idx + 1 :]
        if tail.startswith("\n"):
            tail = tail[1:]
        bulk_scope = bulk_scope[: brace_idx + 1] + "\n\tvoid *next_object;\n" + tail
    if alloc_bulk_old in bulk_scope:
        bulk_scope = bulk_scope.replace(alloc_bulk_old, alloc_bulk_new, 1)
    elif alloc_bulk_bad in bulk_scope:
        bulk_scope = bulk_scope.replace(alloc_bulk_bad, alloc_bulk_new, 1)
    elif alloc_bulk_new not in bulk_scope:
        raise SystemExit("feature_porting/slub_alloc_bulk_prefetch: expected block missing")
    if bulk_scope != bulk_original_scope:
        text = text[:bulk_start] + bulk_scope + text[bulk_end:]

    # Hoist the slab/page handle above cache_from_obj() so it is derived before
    # `s` is reassigned. 6.1 works in struct slab (split out of struct page in
    # 5.17) and passes a tail pointer to slab_free(); 5.15 works in struct page
    # and has no tail parameter. Same reordering either way.
    kmem_cache_free_old = """void kmem_cache_free(struct kmem_cache *s, void *x)\n{\n\ts = cache_from_obj(s, x);\n\tif (!s)\n\t\treturn;\n\ttrace_kmem_cache_free(_RET_IP_, x, s);\n\tslab_free(s, virt_to_slab(x), x, NULL, &x, 1, _RET_IP_);\n}\n"""
    kmem_cache_free_new = """void kmem_cache_free(struct kmem_cache *s, void *x)\n{\n\tstruct slab *slab = virt_to_slab(x);\n\n\ts = cache_from_obj(s, x);\n\tif (!s)\n\t\treturn;\n\ttrace_kmem_cache_free(_RET_IP_, x, s);\n\tslab_free(s, slab, x, NULL, &x, 1, _RET_IP_);\n}\n"""
    kmem_cache_free_old_5_15 = """void kmem_cache_free(struct kmem_cache *s, void *x)\n{\n\ts = cache_from_obj(s, x);\n\tif (!s)\n\t\treturn;\n\tslab_free(s, virt_to_head_page(x), x, NULL, 1, _RET_IP_);\n\ttrace_kmem_cache_free(_RET_IP_, x, s->name);\n}\n"""
    kmem_cache_free_new_5_15 = """void kmem_cache_free(struct kmem_cache *s, void *x)\n{\n\tstruct page *page = virt_to_head_page(x);\n\n\ts = cache_from_obj(s, x);\n\tif (!s)\n\t\treturn;\n\tslab_free(s, page, x, NULL, 1, _RET_IP_);\n\ttrace_kmem_cache_free(_RET_IP_, x, s->name);\n}\n"""
    if kmem_cache_free_new in text or kmem_cache_free_new_5_15 in text:
        pass
    elif kmem_cache_free_old in text:
        text = replace_once(text, kmem_cache_free_old, kmem_cache_free_new, "feature_porting/slub_kmem_cache_free")
    else:
        text = replace_once(
            text,
            kmem_cache_free_old_5_15,
            kmem_cache_free_new_5_15,
            "feature_porting/slub_kmem_cache_free",
        )

    # 6.1 took the slab handle in two steps -- virt_to_folio() then
    # folio_slab() -- so this collapses it to one virt_to_slab(). 5.15 predates
    # both folios and struct slab and already reaches the handle in a single
    # virt_to_head_page(), so there is nothing to collapse there.
    build_detached_old = """\tstruct folio *folio;\n\tsize_t same;\n\n\tobject = p[--size];\n\tfolio = virt_to_folio(object);\n\tif (!s) {\n\t\t/* Handle kalloc'ed objects */\n\t\tif (unlikely(!folio_test_slab(folio))) {\n\t\t\tfree_large_kmalloc(folio, object);\n\t\t\tdf->slab = NULL;\n\t\t\treturn size;\n\t\t}\n\t\t/* Derive kmem_cache from object */\n\t\tdf->slab = folio_slab(folio);\n\t\tdf->s = df->slab->slab_cache;\n\t} else {\n\t\tdf->slab = folio_slab(folio);\n\t\tdf->s = cache_from_obj(s, object); /* Support for memcg */\n\t}\n"""
    build_detached_new = """\tstruct slab *slab;\n\tsize_t same;\n\n\tobject = p[--size];\n\tslab = virt_to_slab(object);\n\tif (!s) {\n\t\t/* Handle kalloc'ed objects */\n\t\tif (unlikely(!slab)) {\n\t\t\tfree_large_kmalloc(virt_to_folio(object), object);\n\t\t\tdf->slab = NULL;\n\t\t\treturn size;\n\t\t}\n\t\t/* Derive kmem_cache from object */\n\t\tdf->slab = slab;\n\t\tdf->s = slab->slab_cache;\n\t} else {\n\t\tdf->slab = slab;\n\t\tdf->s = cache_from_obj(s, object); /* Support for memcg */\n\t}\n"""
    if build_detached_new in text:
        pass
    elif build_detached_old in text:
        text = replace_once(text, build_detached_old, build_detached_new, "feature_porting/slub_build_detached_freelist")
    else:
        print(
            "::warning::feature_porting/slub_build_detached_freelist: this tree "
            "already derives the slab handle in one step, nothing to collapse"
        )

    write_text(slub_c, text)
    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="file_local_helper",
        ),
        "path": str(slub_c),
        "group": "slab_alloc_free_hotpath",
        "mode": "patched" if text != original else "already_patched",
        "public_surface_retained": True,
        "ported_semantics": [
            "slub single-object and bulk allocation now share a next-object helper that also issues freepointer prefetch",
            "kmem_cache_alloc_bulk() prefetches the next freelist entry before advancing the per-cpu freelist",
            "kmem_cache_free() and build_detached_freelist() each resolve struct slab once and reuse it through the hot path",
        ],
    }


def patch_hugepage_fault_alloc_fastpath(common_root: Path) -> dict[str, object]:
    huge_memory_c = common_root / "mm/huge_memory.c"
    memory_c = common_root / "mm/memory.c"
    huge_text = read_text(huge_memory_c)
    memory_text = read_text(memory_c)
    original_huge = huge_text
    original_memory = memory_text
    huge_marker = "/* ABK feature_porting: hugepage fault alloc fastpath helper graft. */"
    memory_marker = "/* ABK feature_porting: hugepage fault alloc fastpath routing helper. */"

    ensure_contains(
        huge_memory_c,
        "vm_fault_t do_huge_pmd_anonymous_page(struct vm_fault *vmf)\n{",
        "feature_porting/hugepage_fault_alloc_fastpath_huge_fault_entry",
    )
    ensure_contains(
        memory_c,
        "static inline vm_fault_t create_huge_pmd(struct vm_fault *vmf)\n{",
        "feature_porting/hugepage_fault_alloc_fastpath_memory",
    )
    if (
        "static vm_fault_t __do_huge_pmd_anonymous_page(struct vm_fault *vmf,\n\t\t\tstruct page *page, gfp_t gfp)\n{"
        not in huge_text
        and "static vm_fault_t __do_huge_pmd_anonymous_page(struct vm_fault *vmf,\n\t\t\tstruct folio *folio, gfp_t gfp)\n{"
        not in huge_text
    ):
        raise SystemExit(
            "feature_porting/hugepage_fault_alloc_fastpath_huge_memory: expected helper anchor missing"
        )

    if huge_marker not in huge_text:
        helper_anchor = "EXPORT_SYMBOL_GPL(thp_get_unmapped_area);\n"
        helper_block = """EXPORT_SYMBOL_GPL(thp_get_unmapped_area);\n\n/* ABK feature_porting: hugepage fault alloc fastpath helper graft. */\nstatic void set_huge_zero_page(pgtable_t pgtable, struct mm_struct *mm,\n\t\t\t\t struct vm_area_struct *vma, unsigned long haddr,\n\t\t\t\t pmd_t *pmd, struct page *zero_page);\n\nstatic vm_fault_t abk_thp_fault_fallback(bool charge)\n{\n\tcount_vm_event(THP_FAULT_FALLBACK);\n\tif (charge)\n\t\tcount_vm_event(THP_FAULT_FALLBACK_CHARGE);\n\treturn VM_FAULT_FALLBACK;\n}\n\nstatic vm_fault_t abk_thp_fault_prepare(struct vm_fault *vmf,\n\t\t\t\t       unsigned long haddr)\n{\n\tstruct vm_area_struct *vma = vmf->vma;\n\n\tif (!transhuge_vma_suitable(vma, haddr))\n\t\treturn VM_FAULT_FALLBACK;\n\tif (unlikely(anon_vma_prepare(vma)))\n\t\treturn VM_FAULT_OOM;\n\n\tkhugepaged_enter_vma(vma, vma->vm_flags);\n\treturn 0;\n}\n\nstatic struct folio *abk_thp_fault_alloc_folio(struct vm_area_struct *vma,\n\t\t\t\t\t      unsigned long haddr,\n\t\t\t\t\t      gfp_t *gfp)\n{\n\tstruct folio *folio;\n\n\t*gfp = vma_thp_gfp_mask(vma);\n\tfolio = vma_alloc_folio(*gfp, HPAGE_PMD_ORDER, vma, haddr, true);\n\tif (!folio)\n\t\treturn NULL;\n\n\tVM_BUG_ON_FOLIO(!folio_test_large(folio), folio);\n\treturn folio;\n}\n\nstatic vm_fault_t abk_thp_fault_charge_folio(struct folio *folio,\n\t\t\t\t\t     struct vm_area_struct *vma,\n\t\t\t\t\t     gfp_t gfp)\n{\n\tif (mem_cgroup_charge(folio, vma->vm_mm, gfp)) {\n\t\tfolio_put(folio);\n\t\treturn abk_thp_fault_fallback(true);\n\t}\n\n\tfolio_throttle_swaprate(folio, gfp);\n\treturn 0;\n}\n\nstatic void abk_prep_anon_thp_folio(struct folio *folio,\n\t\t\t\t    unsigned long address)\n{\n\tclear_huge_page(&folio->page, address, HPAGE_PMD_NR);\n\t/*\n\t * The memory barrier inside __folio_mark_uptodate makes sure that\n\t * clear_huge_page writes become visible before the set_pmd_at()\n\t * write.\n\t */\n\t__folio_mark_uptodate(folio);\n}\n\nstatic void abk_map_anon_folio_pmd(struct folio *folio, pgtable_t pgtable,\n\t\t\t\t\t  pmd_t *pmd,\n\t\t\t\t\t  struct vm_area_struct *vma,\n\t\t\t\t\t  unsigned long haddr,\n\t\t\t\t\t  unsigned long address)\n{\n\tpmd_t entry;\n\n\tentry = mk_huge_pmd(&folio->page, vma->vm_page_prot);\n\tentry = maybe_pmd_mkwrite(pmd_mkdirty(entry), vma);\n\tpage_add_new_anon_rmap(&folio->page, vma, haddr);\n\tfolio_add_lru_vma(folio, vma);\n\tpgtable_trans_huge_deposit(vma->vm_mm, pmd, pgtable);\n\tset_pmd_at(vma->vm_mm, haddr, pmd, entry);\n\tupdate_mmu_cache_pmd(vma, address, pmd);\n\tadd_mm_counter(vma->vm_mm, MM_ANONPAGES, HPAGE_PMD_NR);\n\tmm_inc_nr_ptes(vma->vm_mm);\n\tcount_vm_event(THP_FAULT_ALLOC);\n\tcount_memcg_event_mm(vma->vm_mm, THP_FAULT_ALLOC);\n}\n\nstatic vm_fault_t abk_do_huge_pmd_anonymous_zero_page(struct vm_fault *vmf,\n\t\t\t\t\t      unsigned long haddr)\n{\n\tstruct vm_area_struct *vma = vmf->vma;\n\tpgtable_t pgtable;\n\tstruct page *zero_page;\n\tvm_fault_t ret;\n\n\tpgtable = pte_alloc_one(vma->vm_mm);\n\tif (unlikely(!pgtable))\n\t\treturn VM_FAULT_OOM;\n\tzero_page = mm_get_huge_zero_page(vma->vm_mm);\n\tif (unlikely(!zero_page)) {\n\t\tpte_free(vma->vm_mm, pgtable);\n\t\treturn abk_thp_fault_fallback(false);\n\t}\n\tvmf->ptl = pmd_lock(vma->vm_mm, vmf->pmd);\n\tret = 0;\n\tif (pmd_none(*vmf->pmd)) {\n\t\tret = check_stable_address_space(vma->vm_mm);\n\t\tif (ret) {\n\t\t\tspin_unlock(vmf->ptl);\n\t\t\tpte_free(vma->vm_mm, pgtable);\n\t\t} else if (userfaultfd_missing(vma)) {\n\t\t\tspin_unlock(vmf->ptl);\n\t\t\tpte_free(vma->vm_mm, pgtable);\n\t\t\tret = handle_userfault(vmf, VM_UFFD_MISSING);\n\t\t\tVM_BUG_ON(ret & VM_FAULT_FALLBACK);\n\t\t} else {\n\t\t\tset_huge_zero_page(pgtable, vma->vm_mm, vma,\n\t\t\t\t\t   haddr, vmf->pmd, zero_page);\n\t\t\tupdate_mmu_cache_pmd(vma, vmf->address, vmf->pmd);\n\t\t\tspin_unlock(vmf->ptl);\n\t\t}\n\t} else {\n\t\tspin_unlock(vmf->ptl);\n\t\tpte_free(vma->vm_mm, pgtable);\n\t}\n\treturn ret;\n}\n"""
        huge_text = replace_once(
            huge_text,
            helper_anchor,
            helper_block,
            "feature_porting/hugepage_fault_alloc_fastpath_helpers",
        )

    do_huge_old = """static vm_fault_t __do_huge_pmd_anonymous_page(struct vm_fault *vmf,\n\t\t\tstruct page *page, gfp_t gfp)\n{\n\tstruct vm_area_struct *vma = vmf->vma;\n\tpgtable_t pgtable;\n\tunsigned long haddr = vmf->address & HPAGE_PMD_MASK;\n\tvm_fault_t ret = 0;\n\n\tVM_BUG_ON_PAGE(!PageCompound(page), page);\n\n\tif (mem_cgroup_charge(page_folio(page), vma->vm_mm, gfp)) {\n\t\tput_page(page);\n\t\tcount_vm_event(THP_FAULT_FALLBACK);\n\t\tcount_vm_event(THP_FAULT_FALLBACK_CHARGE);\n\t\treturn VM_FAULT_FALLBACK;\n\t}\n\tcgroup_throttle_swaprate(page, gfp);\n\n\tpgtable = pte_alloc_one(vma->vm_mm);\n\tif (unlikely(!pgtable)) {\n\t\tret = VM_FAULT_OOM;\n\t\tgoto release;\n\t}\n\n\tclear_huge_page(page, vmf->address, HPAGE_PMD_NR);\n\t/*\n\t * The memory barrier inside __SetPageUptodate makes sure that\n\t * clear_huge_page writes become visible before the set_pmd_at()\n\t * write.\n\t */\n\t__SetPageUptodate(page);\n\n\tvmf->ptl = pmd_lock(vma->vm_mm, vmf->pmd);\n\tif (unlikely(!pmd_none(*vmf->pmd))) {\n\t\tgoto unlock_release;\n\t} else {\n\t\tpmd_t entry;\n\n\t\tret = check_stable_address_space(vma->vm_mm);\n\t\tif (ret)\n\t\t\tgoto unlock_release;\n\n\t\t/* Deliver the page fault to userland */\n\t\tif (userfaultfd_missing(vma)) {\n\t\t\tspin_unlock(vmf->ptl);\n\t\t\tput_page(page);\n\t\t\tpte_free(vma->vm_mm, pgtable);\n\t\t\tret = handle_userfault(vmf, VM_UFFD_MISSING);\n\t\t\tVM_BUG_ON(ret & VM_FAULT_FALLBACK);\n\t\t\treturn ret;\n\t\t}\n\n\t\tentry = mk_huge_pmd(page, vma->vm_page_prot);\n\t\tentry = maybe_pmd_mkwrite(pmd_mkdirty(entry), vma);\n\t\tpage_add_new_anon_rmap(page, vma, haddr);\n\t\tlru_cache_add_inactive_or_unevictable(page, vma);\n\t\tpgtable_trans_huge_deposit(vma->vm_mm, vmf->pmd, pgtable);\n\t\tset_pmd_at(vma->vm_mm, haddr, vmf->pmd, entry);\n\t\tupdate_mmu_cache_pmd(vma, vmf->address, vmf->pmd);\n\t\tadd_mm_counter(vma->vm_mm, MM_ANONPAGES, HPAGE_PMD_NR);\n\t\tmm_inc_nr_ptes(vma->vm_mm);\n\t\tspin_unlock(vmf->ptl);\n\t\tcount_vm_event(THP_FAULT_ALLOC);\n\t\tcount_memcg_event_mm(vma->vm_mm, THP_FAULT_ALLOC);\n\t}\n\n\treturn 0;\nunlock_release:\n\tspin_unlock(vmf->ptl);\nrelease:\n\tif (pgtable)\n\t\tpte_free(vma->vm_mm, pgtable);\n\tput_page(page);\n\treturn ret;\n\n}\n"""
    do_huge_new = """static vm_fault_t __do_huge_pmd_anonymous_page(struct vm_fault *vmf,\n\t\t\tstruct folio *folio, gfp_t gfp)\n{\n\tstruct vm_area_struct *vma = vmf->vma;\n\tpgtable_t pgtable;\n\tunsigned long haddr = vmf->address & HPAGE_PMD_MASK;\n\tvm_fault_t ret;\n\n\tVM_BUG_ON_FOLIO(!folio_test_large(folio), folio);\n\n\tret = abk_thp_fault_charge_folio(folio, vma, gfp);\n\tif (ret)\n\t\treturn ret;\n\n\tpgtable = pte_alloc_one(vma->vm_mm);\n\tif (unlikely(!pgtable)) {\n\t\tret = VM_FAULT_OOM;\n\t\tgoto release;\n\t}\n\n\tabk_prep_anon_thp_folio(folio, vmf->address);\n\n\tvmf->ptl = pmd_lock(vma->vm_mm, vmf->pmd);\n\tif (unlikely(!pmd_none(*vmf->pmd)))\n\t\tgoto unlock_release;\n\n\tret = check_stable_address_space(vma->vm_mm);\n\tif (ret)\n\t\tgoto unlock_release;\n\n\t/* Deliver the page fault to userland */\n\tif (userfaultfd_missing(vma)) {\n\t\tspin_unlock(vmf->ptl);\n\t\tfolio_put(folio);\n\t\tpte_free(vma->vm_mm, pgtable);\n\t\tret = handle_userfault(vmf, VM_UFFD_MISSING);\n\t\tVM_BUG_ON(ret & VM_FAULT_FALLBACK);\n\t\treturn ret;\n\t}\n\n\tabk_map_anon_folio_pmd(folio, pgtable, vmf->pmd, vma,\n\t\t\t      haddr, vmf->address);\n\tspin_unlock(vmf->ptl);\n\treturn 0;\n\nunlock_release:\n\tspin_unlock(vmf->ptl);\nrelease:\n\tif (pgtable)\n\t\tpte_free(vma->vm_mm, pgtable);\n\tfolio_put(folio);\n\treturn ret;\n\n}\n"""
    if "static vm_fault_t __do_huge_pmd_anonymous_page(struct vm_fault *vmf,\n\t\t\tstruct folio *folio, gfp_t gfp)\n{" not in huge_text:
        huge_text = replace_within(
            huge_text,
            "static vm_fault_t __do_huge_pmd_anonymous_page(struct vm_fault *vmf,\n",
            "\n/*\n * always: directly stall for all thp allocations\n",
            do_huge_old,
            do_huge_new,
            "feature_porting/hugepage_fault_alloc_fastpath_do_huge",
        )

    fault_entry_old = """vm_fault_t do_huge_pmd_anonymous_page(struct vm_fault *vmf)\n{\n\tstruct vm_area_struct *vma = vmf->vma;\n\tgfp_t gfp;\n\tstruct folio *folio;\n\tunsigned long haddr = vmf->address & HPAGE_PMD_MASK;\n\n\tif (!transhuge_vma_suitable(vma, haddr))\n\t\treturn VM_FAULT_FALLBACK;\n\tif (unlikely(anon_vma_prepare(vma)))\n\t\treturn VM_FAULT_OOM;\n\tkhugepaged_enter_vma(vma, vma->vm_flags);\n\n\tif (!(vmf->flags & FAULT_FLAG_WRITE) &&\n\t\t\t!mm_forbids_zeropage(vma->vm_mm) &&\n\t\t\ttransparent_hugepage_use_zero_page()) {\n\t\tpgtable_t pgtable;\n\t\tstruct page *zero_page;\n\t\tvm_fault_t ret;\n\t\tpgtable = pte_alloc_one(vma->vm_mm);\n\t\tif (unlikely(!pgtable))\n\t\t\treturn VM_FAULT_OOM;\n\t\tzero_page = mm_get_huge_zero_page(vma->vm_mm);\n\t\tif (unlikely(!zero_page)) {\n\t\t\tpte_free(vma->vm_mm, pgtable);\n\t\t\tcount_vm_event(THP_FAULT_FALLBACK);\n\t\t\treturn VM_FAULT_FALLBACK;\n\t\t}\n\t\tvmf->ptl = pmd_lock(vma->vm_mm, vmf->pmd);\n\t\tret = 0;\n\t\tif (pmd_none(*vmf->pmd)) {\n\t\t\tret = check_stable_address_space(vma->vm_mm);\n\t\t\tif (ret) {\n\t\t\t\tspin_unlock(vmf->ptl);\n\t\t\t\tpte_free(vma->vm_mm, pgtable);\n\t\t\t} else if (userfaultfd_missing(vma)) {\n\t\t\t\tspin_unlock(vmf->ptl);\n\t\t\t\tpte_free(vma->vm_mm, pgtable);\n\t\t\t\tret = handle_userfault(vmf, VM_UFFD_MISSING);\n\t\t\t\tVM_BUG_ON(ret & VM_FAULT_FALLBACK);\n\t\t\t} else {\n\t\t\t\tset_huge_zero_page(pgtable, vma->vm_mm, vma,\n\t\t\t\t\t   haddr, vmf->pmd, zero_page);\n\t\t\t\tupdate_mmu_cache_pmd(vma, vmf->address, vmf->pmd);\n\t\t\t\tspin_unlock(vmf->ptl);\n\t\t\t}\n\t\t} else {\n\t\t\tspin_unlock(vmf->ptl);\n\t\t\tpte_free(vma->vm_mm, pgtable);\n\t\t}\n\t\treturn ret;\n\t}\n\tgfp = vma_thp_gfp_mask(vma);\n\tfolio = vma_alloc_folio(gfp, HPAGE_PMD_ORDER, vma, haddr, true);\n\tif (unlikely(!folio)) {\n\t\tcount_vm_event(THP_FAULT_FALLBACK);\n\t\treturn VM_FAULT_FALLBACK;\n\t}\n\treturn __do_huge_pmd_anonymous_page(vmf, &folio->page, gfp);\n}\n"""
    fault_entry_new = """vm_fault_t do_huge_pmd_anonymous_page(struct vm_fault *vmf)\n{\n\tstruct vm_area_struct *vma = vmf->vma;\n\tgfp_t gfp;\n\tstruct folio *folio;\n\tunsigned long haddr = vmf->address & HPAGE_PMD_MASK;\n\tvm_fault_t ret;\n\n\tret = abk_thp_fault_prepare(vmf, haddr);\n\tif (ret)\n\t\treturn ret;\n\n\tif (!(vmf->flags & FAULT_FLAG_WRITE) &&\n\t\t\t!mm_forbids_zeropage(vma->vm_mm) &&\n\t\t\ttransparent_hugepage_use_zero_page())\n\t\treturn abk_do_huge_pmd_anonymous_zero_page(vmf, haddr);\n\n\tfolio = abk_thp_fault_alloc_folio(vma, haddr, &gfp);\n\tif (unlikely(!folio))\n\t\treturn abk_thp_fault_fallback(false);\n\treturn __do_huge_pmd_anonymous_page(vmf, folio, gfp);\n}\n"""
    if "ret = abk_thp_fault_prepare(vmf, haddr);" not in huge_text:
        huge_text = replace_scope(
            huge_text,
            "vm_fault_t do_huge_pmd_anonymous_page(struct vm_fault *vmf)\n{",
            "\nstatic void insert_pfn_pmd(struct vm_area_struct *vma, unsigned long addr,\n",
            fault_entry_new,
            "feature_porting/hugepage_fault_alloc_fastpath_fault_entry",
        )

    if memory_marker not in memory_text:
        memory_old = """static inline vm_fault_t create_huge_pmd(struct vm_fault *vmf)\n{\n\tstruct vm_area_struct *vma = vmf->vma;\n\tif (vma_is_anonymous(vma))\n\t\treturn do_huge_pmd_anonymous_page(vmf);\n\tif (vma->vm_ops->huge_fault) {\n\t\tif (vmf->flags & FAULT_FLAG_VMA_LOCK) {\n\t\t\tvma_end_read(vma);\n\t\t\treturn VM_FAULT_RETRY;\n\t\t}\n\t\treturn vma->vm_ops->huge_fault(vmf, PE_SIZE_PMD);\n\t}\n\treturn VM_FAULT_FALLBACK;\n}\n"""
        memory_new = """/* ABK feature_porting: hugepage fault alloc fastpath routing helper. */\nstatic inline vm_fault_t abk_create_anonymous_huge_pmd(struct vm_fault *vmf)\n{\n\treturn do_huge_pmd_anonymous_page(vmf);\n}\n\nstatic inline vm_fault_t create_huge_pmd(struct vm_fault *vmf)\n{\n\tstruct vm_area_struct *vma = vmf->vma;\n\tif (vma_is_anonymous(vma))\n\t\treturn abk_create_anonymous_huge_pmd(vmf);\n\tif (vma->vm_ops->huge_fault) {\n\t\tif (vmf->flags & FAULT_FLAG_VMA_LOCK) {\n\t\t\tvma_end_read(vma);\n\t\t\treturn VM_FAULT_RETRY;\n\t\t}\n\t\treturn vma->vm_ops->huge_fault(vmf, PE_SIZE_PMD);\n\t}\n\treturn VM_FAULT_FALLBACK;\n}\n"""
        memory_text = replace_once(
            memory_text,
            memory_old,
            memory_new,
            "feature_porting/hugepage_fault_alloc_fastpath_memory_helper",
        )

    if huge_text != original_huge:
        write_text(huge_memory_c, huge_text)
    if memory_text != original_memory:
        write_text(memory_c, memory_text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="file_local_helper",
        ),
        "group": "hugepage_fault_alloc_fastpath",
        "mode": "patched" if huge_text != original_huge or memory_text != original_memory else "already_patched",
        "paths": [str(memory_c), str(huge_memory_c)],
        "ported_semantics": [
            "anonymous THP fault-time allocation is split into prepare, fallback, alloc, charge, and post-map helpers inside mm/huge_memory.c",
            "THP_FAULT_ALLOC and THP_FAULT_FALLBACK accounting stays on the direct fault-time anonymous PMD path",
            "mm/memory.c keeps the public routing surface but calls a file-local helper for the anonymous huge PMD branch",
        ],
    }


def collect_nohz_status(common_root: Path) -> dict[str, object]:
    nohz_h = common_root / "include/linux/sched/nohz.h"
    tick_h = common_root / "include/linux/tick.h"
    tick_sched_h = common_root / "kernel/time/tick-sched.h"
    tick_sched_c = common_root / "kernel/time/tick-sched.c"
    nohz_h_text = read_text(nohz_h)
    tick_h_text = read_text(tick_h)
    tick_sched_h_text = read_text(tick_sched_h)
    tick_sched_c_text = read_text(tick_sched_c)

    target_anchors = {
        "nohz_state_enum": "enum nohz_cpu_state {" in nohz_h_text,
        "nohz_state_inidle": "NOHZ_CPU_STATE_INIDLE = 1U << 0," in nohz_h_text,
        "nohz_state_idle_active": "NOHZ_CPU_STATE_IDLE_ACTIVE = 1U << 1," in nohz_h_text,
        "nohz_state_tick_stopped": "NOHZ_CPU_STATE_TICK_STOPPED = 1U << 2," in nohz_h_text,
        "nohz_cpu_state_flags_decl": "extern unsigned int nohz_cpu_state_flags(int cpu);" in nohz_h_text,
        "nohz_cpu_idle_calls_decl": "extern unsigned long nohz_cpu_idle_calls(int cpu);" in nohz_h_text,
        "nohz_cpu_inidle_inline": "static inline bool nohz_cpu_inidle(int cpu)" in nohz_h_text,
        "nohz_cpu_idle_active_inline": "static inline bool nohz_cpu_idle_active(int cpu)" in nohz_h_text,
        "nohz_cpu_tick_stopped_inline": "static inline bool nohz_cpu_tick_stopped(int cpu)" in nohz_h_text,
        "tick_nohz_get_idle_calls_decl": "extern unsigned long tick_nohz_get_idle_calls(void);" in tick_h_text,
        "tick_nohz_idle_stop_tick_protected": "static inline void tick_nohz_idle_stop_tick_protected(void)" in tick_h_text,
        "tick_sched_inidle_field": "unsigned int\t\t\tinidle" in tick_sched_h_text,
        "tick_sched_tick_stopped_field": "unsigned int\t\t\ttick_stopped" in tick_sched_h_text,
        "tick_sched_idle_active_field": "unsigned int\t\t\tidle_active" in tick_sched_h_text,
        "tick_sched_helper_marker": "nohz state field consistency helpers" in tick_sched_c_text,
        "tick_sched_state_flags": "static unsigned int abk_tick_nohz_state_flags(const struct tick_sched *ts)" in tick_sched_c_text,
        "tick_cpu_state_export": "unsigned int nohz_cpu_state_flags(int cpu)" in tick_sched_c_text,
        "tick_cpu_idle_calls_export": "unsigned long nohz_cpu_idle_calls(int cpu)" in tick_sched_c_text,
        "tick_stopped_helper_use": "return !!(abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_TICK_STOPPED);" in tick_sched_c_text,
        "irq_exit_helper_use": "if (abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_INIDLE)" in tick_sched_c_text,
        "sleep_length_helper_use": "WARN_ON_ONCE(!(abk_tick_nohz_state_flags(ts) & NOHZ_CPU_STATE_INIDLE));" in tick_sched_c_text,
        "idle_exit_state_snapshot": "idle_active = !!(nohz_state & NOHZ_CPU_STATE_IDLE_ACTIVE);" in tick_sched_c_text
        and "tick_stopped = !!(nohz_state & NOHZ_CPU_STATE_TICK_STOPPED);" in tick_sched_c_text,
        "idle_calls_cpu_helper_use": "return nohz_cpu_idle_calls(cpu);" in tick_sched_c_text,
        "idle_calls_local_helper_use": "return nohz_cpu_idle_calls(smp_processor_id());" in tick_sched_c_text,
    }

    tick_sched_shape = "unknown"
    if (
        target_anchors["tick_sched_inidle_field"]
        and target_anchors["tick_sched_tick_stopped_field"]
        and target_anchors["tick_sched_idle_active_field"]
    ):
        tick_sched_shape = "legacy_bitfield_triplet"

    idle_entry_exit_consistent = (
        target_anchors["irq_exit_helper_use"]
        and target_anchors["sleep_length_helper_use"]
        and target_anchors["idle_exit_state_snapshot"]
    )
    tick_stop_consistent = (
        target_anchors["tick_stopped_helper_use"]
        and target_anchors["idle_exit_state_snapshot"]
    )
    idle_calls_consistent = (
        target_anchors["tick_nohz_get_idle_calls_decl"]
        and target_anchors["idle_calls_cpu_helper_use"]
        and target_anchors["idle_calls_local_helper_use"]
    )
    all_present = all(target_anchors.values())

    return {
        "status": "nohz_state_fields_grafted" if all_present else "partial",
        "phase": "legacy_tick_sched_state_consistent" if all_present else "legacy_tick_sched_state_scan",
        "tick_sched_shape": tick_sched_shape,
        "idle_entry_exit_consistent": idle_entry_exit_consistent,
        "tick_stop_consistent": tick_stop_consistent,
        "idle_calls_consistent": idle_calls_consistent,
        "policy_scope": "kernel_time_and_sched_nohz_only",
        "path": [str(nohz_h), str(tick_h), str(tick_sched_h), str(tick_sched_c)],
        "target_anchors": {key: bool_status(value) for key, value in target_anchors.items()},
        "tree_escalation_required": False,
        "next_action": (
            "Keep nohz field refinement inside feature_porting and stop at state/helper parity. "
            "Do not widen this batch into avg_idle, idle-governor, or scheduler policy rewrites unless the legacy tick_sched shape stops carrying the required state clearly."
        ),
    }


def collect_avg_idle_status(common_root: Path) -> dict[str, object]:
    core_c = common_root / "kernel/sched/core.c"
    fair_c = common_root / "kernel/sched/fair.c"
    idle_c = common_root / "kernel/sched/idle.c"
    sched_h = common_root / "kernel/sched/sched.h"
    core_text = read_text(core_c)
    fair_text = read_text(fair_c)
    idle_text = read_text(idle_c)
    sched_h_text = read_text(sched_h)

    target_anchors = {
        "avg_idle_helper": "void update_rq_avg_idle(struct rq *rq)" in core_text,
        "avg_idle_helper_body": (
            "u64 max = 2 * rq->max_idle_balance_cost;" in core_text
            or "u64 max = 2*rq->max_idle_balance_cost;" in core_text
        ),
        "avg_idle_idle_call": "update_rq_avg_idle(rq);" in idle_text,
        "avg_idle_field": "u64\t\t\tavg_idle;" in sched_h_text,
        "wake_avg_idle_field": "u64\t\t\twake_avg_idle;" in sched_h_text,
        "wake_stamp_field": "unsigned long\t\twake_stamp;" in sched_h_text,
        "sis_prop_removed": "sched_feat(SIS_PROP)" not in fair_text,
        "sis_util_kept": "sched_feat(SIS_UTIL)" in fair_text,
        "wake_prediction_removed": "this_rq->wake_avg_idle" not in fair_text,
        "wake_stamp_removed": "this_rq->wake_stamp" not in fair_text,
        "newidle_threshold_direct": (
            "this_rq->avg_idle < sysctl_sched_migration_cost" in fair_text
            and "this_rq->avg_idle < sd->max_newidle_lb_cost" in fair_text
            and "this_rq->avg_idle < curr_cost + sd->max_newidle_lb_cost" in fair_text
        ),
    }

    sis_prop_simplified = (
        target_anchors["sis_prop_removed"]
        and target_anchors["sis_util_kept"]
        and target_anchors["wake_prediction_removed"]
    )
    newidle_threshold_simplified = target_anchors["newidle_threshold_direct"]
    all_present = (
        target_anchors["avg_idle_helper"]
        and target_anchors["avg_idle_helper_body"]
        and target_anchors["avg_idle_idle_call"]
        and target_anchors["avg_idle_field"]
        and sis_prop_simplified
        and newidle_threshold_simplified
    )

    return {
        "status": "avg_idle_thresholds_simplified" if all_present else "partial",
        "phase": "wake_side_prediction_removed" if all_present else "wake_side_prediction_scan",
        "target_shape": "idle_exit_avg_idle_only" if all_present else "legacy_wake_avg_idle_path",
        "wake_avg_idle_retained": target_anchors["wake_avg_idle_field"],
        "sis_prop_simplified": sis_prop_simplified,
        "newidle_threshold_simplified": newidle_threshold_simplified,
        "path": [str(core_c), str(fair_c), str(idle_c), str(sched_h)],
        "target_anchors": {key: bool_status(value) for key, value in target_anchors.items()},
        "tree_escalation_required": False,
        "next_action": (
            "Keep avg_idle preemption simplification inside feature_porting. "
            "Do not reintroduce wake-side prediction or idle-governor policy rewrites unless the direct avg_idle thresholds prove insufficient."
        ),
    }


def collect_sched_anchor_status(common_root: Path) -> dict[str, object]:
    fair_c = common_root / "kernel/sched/fair.c"
    sched_h = common_root / "include/linux/sched.h"
    fair = read_text(fair_c)
    sched_h_text = read_text(sched_h)

    target_anchors = {
        "avg_vruntime": "avg_vruntime(" in fair,
        "pick_eevdf": "pick_eevdf(" in fair or "abk_pick_eevdf(" in fair,
        "pick_next_entity_cfs_shape": "pick_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *curr)" in fair,
        "util_est_dequeue": "static inline void util_est_dequeue(struct cfs_rq *cfs_rq," in fair,
        "android_vendor_pick_hook": "trace_android_rvh_pick_next_entity" in fair,
        "deadline_field": "deadline" in sched_h_text and "ANDROID_KABI_USE(1, u64 deadline);" in sched_h_text,
        "vlag_field": "s64 vlag;" in sched_h_text,
        "scan_eevdf_marker": "scan-based EEVDF runtime-state graft" in fair,
        "relative_deadline_marker": "ABK_EEVDF_REL_DEADLINE_BIT" in fair,
        "preserved_lag_marker": "abk_eevdf_preserved_lag(" in fair,
        "reweight_runtime_state": "abk_eevdf_store_rel_deadline(se);" in fair,
        "phase3_reweight_marker": "phase-3 preserve lag/deadline across both current and queued reweight paths" in fair,
        "place_entity_refresh": "abk_eevdf_place_entity(cfs_rq, se, initial);" in fair,
        "set_next_refresh": "update_stats_wait_end_fair(cfs_rq, se);\n\t\tabk_eevdf_refresh_deadline(cfs_rq, se);" in fair,
        "put_prev_refresh": "update_stats_wait_start_fair(cfs_rq, prev);\n\t\tabk_eevdf_refresh_deadline(cfs_rq, prev);" in fair,
        "tick_refresh": "if (abk_eevdf_refresh_deadline(cfs_rq, curr)) {" in fair,
        "tick_lag_refresh": "\tabk_eevdf_update_lag(cfs_rq, curr);" in fair,
        "delayed_dequeue_hooks": "DEQUEUE_DELAYED" in fair or "DELAY_DEQUEUE" in fair,
    }

    runtime_state_extended = (
        target_anchors["scan_eevdf_marker"]
        and target_anchors["relative_deadline_marker"]
        and target_anchors["preserved_lag_marker"]
        and target_anchors["reweight_runtime_state"]
    )
    slice_lifecycle_consistent = (
        target_anchors["place_entity_refresh"]
        and target_anchors["set_next_refresh"]
        and target_anchors["put_prev_refresh"]
        and target_anchors["tick_refresh"]
        and target_anchors["tick_lag_refresh"]
    )
    runtime_state_phase3_stable = (
        runtime_state_extended
        and target_anchors["phase3_reweight_marker"]
        and slice_lifecycle_consistent
    )
    delayed_path_status = "delayed_path_supported" if target_anchors["delayed_dequeue_hooks"] else "delayed_path_deferred"
    milestones: list[str] = []
    if runtime_state_extended:
        milestones.append("runtime_state_extended")
    if runtime_state_phase3_stable:
        milestones.append("runtime_state_phase3_stable")
    if delayed_path_status == "delayed_path_deferred":
        milestones.append("delayed_path_deferred")

    status = "partial"
    if runtime_state_phase3_stable:
        status = "runtime_state_phase3_stable"
    elif runtime_state_extended:
        status = "runtime_state_extended"
    elif target_anchors["scan_eevdf_marker"]:
        status = "ported_scan_pick_logic"
    elif target_anchors["avg_vruntime"] and target_anchors["pick_eevdf"]:
        status = "already_eevdf_like"
    elif not target_anchors["pick_eevdf"] and target_anchors["pick_next_entity_cfs_shape"]:
        status = "legacy_cfs_pick_logic"

    return {
        "status": status,
        "phase": "scan_based_runtime_phase3" if runtime_state_phase3_stable else "scan_based_runtime_parity" if runtime_state_extended else "scan_based_pick_only",
        "milestones": milestones,
        "ported_scan_pick_logic": bool(target_anchors["scan_eevdf_marker"]),
        "runtime_state_extended": runtime_state_extended,
        "runtime_state_phase3_stable": runtime_state_phase3_stable,
        "slice_lifecycle_consistent": slice_lifecycle_consistent,
        "delayed_path_status": delayed_path_status,
        "cfs_rq_augmentation_used": False,
        "tree_escalation_required": False,
        "target_anchors": {key: bool_status(value) for key, value in target_anchors.items()},
        "next_action": (
            "Hold the existing fair.c tree order and keep the scan-based selector. "
            "Keep delayed-dequeue explicitly deferred unless parity can be expressed without cfs_rq augmentation, "
            "and only escalate to tree augmentation if preserved-lag, reweight, or slice-lifecycle parity stop fitting the scan-based model."
        ),
    }


def collect_pidfd_status(common_root: Path) -> dict[str, object]:
    fork_c = common_root / "kernel/fork.c"
    pid_c = common_root / "kernel/pid.c"
    fork = read_text(fork_c)
    pid = read_text(pid_c)

    flags = {
        "clone_pidfd_flow": "CLONE_PIDFD" in fork,
        "pidfd_open_syscall": "SYSCALL_DEFINE2(pidfd_open" in pid,
        "pidfd_getfd_syscall": "SYSCALL_DEFINE3(pidfd_getfd" in pid,
        "pidfd_create_helper": "int pidfd_create(struct pid *pid, unsigned int flags)" in pid,
        "pidfd_fops": "const struct file_operations pidfd_fops = {" in fork,
        "pidfd_prepare_helper": "pidfd_prepare(" in fork,
        "compat_helper": "abk_pidfd_has_forbidden_flags(" in pid,
        "compat_marker_fork": "keep CLONE_PIDFD on legacy pidfd plumbing; pidfs remains deferred" in fork,
        "pidfs_prepare_pid": "pidfs_prepare_pid(" in pid,
    }
    surface_complete = (
        flags["pidfd_open_syscall"]
        and flags["pidfd_getfd_syscall"]
        and flags["clone_pidfd_flow"]
        and flags["pidfd_create_helper"]
        and flags["pidfd_fops"]
    )
    surface_status = "pidfd_surface_tracked" if surface_complete else "baseline_pidfd_only"
    status = "baseline_pidfd_only"
    if flags["compat_helper"]:
        status = "pidfd_helper_grafted"
    elif surface_complete and flags["compat_marker_fork"]:
        status = "pidfd_surface_tracked"

    return {
        "status": status,
        "surface_status": surface_status,
        "pidfs_status": "pidfs_deferred",
        "surface_complete": surface_complete,
        "helper_grafted": flags["compat_helper"],
        "anchors": {key: bool_status(value) for key, value in flags.items()},
        "next_action": (
            "Keep pidfd_preparation_compat at helper/report level. "
            "Do not backport pidfs_prepare_pid() or change pidfd syscall-visible ABI in this batch."
        ),
    }


def collect_swap_table_phase2_large_folios_status(common_root: Path) -> dict[str, object]:
    swap_state_c = common_root / "mm/swap_state.c"
    swap_h = common_root / "mm/swap.h"
    shmem_c = common_root / "mm/shmem.c"

    if not swap_h.is_file():
        return {
            "status": "blocked_by_layout",
            "skipped_reason": f"{swap_h} does not exist on this tree",
            "path": str(swap_state_c),
        }

    swap_state_text = read_text(swap_state_c)
    swap_h_text = read_text(swap_h)
    shmem_text = read_text(shmem_c) if shmem_c.is_file() else ""

    target_anchors = {
        "swap_phase2_marker": "swap table phase2 large folios helper graft" in swap_state_text,
        "swap_update_readahead_info": "static void swap_update_readahead_info(struct folio *folio," in swap_state_text,
        "swap_cache_prepare_helper": "static struct folio *__swap_cache_prepare_and_add(swp_entry_t entry," in swap_state_text,
        "swap_cache_alloc_folio": "struct folio *swap_cache_alloc_folio(swp_entry_t entry, gfp_t gfp_mask," in swap_state_text,
        "swapin_folio": "struct folio *swapin_folio(swp_entry_t entry, struct folio *folio," in swap_state_text,
        "read_swap_cache_async_folio": "struct folio *read_swap_cache_async_folio(swp_entry_t entry, gfp_t gfp_mask," in swap_state_text,
        "public_surface_retained": "struct page *read_swap_cache_async(swp_entry_t entry, gfp_t gfp_mask," in swap_state_text,
        "cluster_readahead_folio_helper": "folio = swap_cache_alloc_folio(swp_entry(swp_type(entry), offset)," in swap_state_text,
        "vma_readahead_folio_helper": "folio = swap_cache_alloc_folio(entry, gfp_mask, vma, vmf->address," in swap_state_text,
        "readahead_folio_marker": "folio_set_readahead(folio);" in swap_state_text,
        "swap_h_folio_decl": "struct folio *swap_cache_alloc_folio(swp_entry_t entry, gfp_t gfp_mask," in swap_h_text,
        "swap_h_wrapper_decl": "struct folio *read_swap_cache_async_folio(swp_entry_t entry, gfp_t gfp_mask," in swap_h_text,
        "shmem_surface_unchanged": "page = swap_cluster_readahead(swap, gfp, &vmf);" in shmem_text,
    }

    all_present = all(target_anchors.values())
    return {
        "status": "swap_folio_path_grafted" if all_present else "partial",
        "phase": "swapin_swapcache_phase2",
        "target_shape": "folio_swapcache_helper_split",
        "folio_surface_used": (
            target_anchors["swap_cache_prepare_helper"]
            and target_anchors["swap_cache_alloc_folio"]
            and target_anchors["read_swap_cache_async_folio"]
        ),
        "public_surface_retained": target_anchors["public_surface_retained"],
        "swapcache_helper_grafted": (
            target_anchors["swap_cache_prepare_helper"]
            and target_anchors["swap_cache_alloc_folio"]
            and target_anchors["swapin_folio"]
        ),
        "swap_readahead_simplified": (
            target_anchors["cluster_readahead_folio_helper"]
            and target_anchors["vma_readahead_folio_helper"]
            and target_anchors["readahead_folio_marker"]
        ),
        "shmem_escalation_required": False,
        "tree_escalation_required": False,
        "path": [str(swap_state_c), str(swap_h)],
        "target_anchors": {key: bool_status(value) for key, value in target_anchors.items()},
        "next_action": (
            "Keep swap_table_phase2_large_folios focused on mm/swap_state.c helper split. "
            "Retain page-returning public wrappers until a separate batch can safely widen memory.c, madvise, and zswap call surfaces."
        ),
    }


def collect_slab_alloc_free_hotpath_status(common_root: Path) -> dict[str, object]:
    slub_c = common_root / "mm/slub.c"
    text = read_text(slub_c)

    target_anchors = {
        "slab_hotpath_marker": "slab alloc/free hotpath helper graft" in text,
        "abk_next_object_helper": "static __always_inline void *abk_slab_next_object(struct kmem_cache *s," in text,
        "alloc_fastpath_helper_use": "void *next_object = abk_slab_next_object(s, object);" in text,
        "alloc_bulk_helper_use": "c->freelist = next_object;" in text,
        "kmem_cache_free_slab_lookup": "struct slab *slab;" in text and "slab = virt_to_slab(x);" in text,
        "build_detached_slab_lookup": "struct slab *slab;" in text and "df->slab = slab;" in text,
        "public_surface_retained": "void kmem_cache_free(struct kmem_cache *s, void *x)" in text and "int kmem_cache_alloc_bulk(struct kmem_cache *s, gfp_t flags, size_t size," in text,
    }

    all_present = all(target_anchors.values())
    return {
        "status": "slub_hotpath_grafted" if all_present else "partial",
        "phase": "alloc_free_hotpath_phase1",
        "target_shape": "slub_alloc_free_helper_split",
        "public_surface_retained": target_anchors["public_surface_retained"],
        "alloc_path_tightened": (
            target_anchors["abk_next_object_helper"]
            and target_anchors["alloc_fastpath_helper_use"]
            and target_anchors["alloc_bulk_helper_use"]
        ),
        "free_path_tightened": (
            target_anchors["kmem_cache_free_slab_lookup"]
            and target_anchors["build_detached_slab_lookup"]
        ),
        "bulk_path_touched": target_anchors["alloc_bulk_helper_use"],
        "tree_escalation_required": False,
        "path": [str(slub_c)],
        "target_anchors": {key: bool_status(value) for key, value in target_anchors.items()},
        "next_action": (
            "Keep slab_alloc_free_hotpath inside mm/slub.c and stop at helper grafts. "
            "Do not widen this batch into sheaf/barn structural ports unless a later phase justifies broader allocator layout changes."
        ),
    }


def collect_hugepage_fault_alloc_fastpath_status(common_root: Path) -> dict[str, object]:
    memory_c = common_root / "mm/memory.c"
    huge_memory_c = common_root / "mm/huge_memory.c"
    vmstat_c = common_root / "mm/vmstat.c"
    memory_text = read_text(memory_c)
    huge_text = read_text(huge_memory_c)
    vmstat_text = read_text(vmstat_c)

    target_anchors = {
        "hugepage_marker": "hugepage fault alloc fastpath helper graft" in huge_text,
        "memory_marker": "hugepage fault alloc fastpath routing helper" in memory_text,
        "fault_prepare_helper": "static vm_fault_t abk_thp_fault_prepare(struct vm_fault *vmf," in huge_text,
        "fault_fallback_helper": "static vm_fault_t abk_thp_fault_fallback(bool charge)" in huge_text,
        "fault_alloc_helper": "static struct folio *abk_thp_fault_alloc_folio(struct vm_area_struct *vma," in huge_text,
        "fault_charge_helper": "static vm_fault_t abk_thp_fault_charge_folio(struct folio *folio," in huge_text,
        "fault_prep_helper": "static void abk_prep_anon_thp_folio(struct folio *folio," in huge_text,
        "fault_map_helper": "static void abk_map_anon_folio_pmd(struct folio *folio, pgtable_t pgtable," in huge_text,
        "zero_page_helper": "static vm_fault_t abk_do_huge_pmd_anonymous_zero_page(struct vm_fault *vmf," in huge_text,
        "fault_prepare_use": "ret = abk_thp_fault_prepare(vmf, haddr);" in huge_text,
        "fault_alloc_use": "folio = abk_thp_fault_alloc_folio(vma, haddr, &gfp);" in huge_text,
        "fault_alloc_call": "return __do_huge_pmd_anonymous_page(vmf, folio, gfp);" in huge_text,
        "fault_charge_use": "ret = abk_thp_fault_charge_folio(folio, vma, gfp);" in huge_text,
        "fault_map_use": "abk_map_anon_folio_pmd(folio, pgtable, vmf->pmd, vma," in huge_text,
        "fallback_charge_use": "return abk_thp_fault_fallback(true);" in huge_text,
        "fallback_alloc_use": "return abk_thp_fault_fallback(false);" in huge_text,
        "memory_routing_helper": "static inline vm_fault_t abk_create_anonymous_huge_pmd(struct vm_fault *vmf)" in memory_text,
        "memory_routing_use": "return abk_create_anonymous_huge_pmd(vmf);" in memory_text,
        "do_huge_pmd_entry_retained": "vm_fault_t do_huge_pmd_anonymous_page(struct vm_fault *vmf)" in huge_text,
        "vmstat_thp_fault_alloc": '"thp_fault_alloc"' in vmstat_text,
        "vmstat_thp_fault_fallback": '"thp_fault_fallback"' in vmstat_text,
    }

    fault_alloc_helper_grafted = (
        target_anchors["fault_prepare_helper"]
        and target_anchors["fault_alloc_helper"]
        and target_anchors["fault_charge_helper"]
        and target_anchors["fault_prep_helper"]
        and target_anchors["fault_map_helper"]
        and target_anchors["memory_routing_helper"]
    )
    fault_fallback_tracked = (
        target_anchors["fault_fallback_helper"]
        and target_anchors["fallback_charge_use"]
        and target_anchors["fallback_alloc_use"]
        and target_anchors["vmstat_thp_fault_alloc"]
        and target_anchors["vmstat_thp_fault_fallback"]
    )
    all_present = all(target_anchors.values())

    return {
        "status": "thp_fault_alloc_grafted" if all_present else "partial",
        "phase": "anon_thp_fault_fastpath",
        "target_shape": "fault_alloc_helper_split",
        "fault_alloc_helper_grafted": fault_alloc_helper_grafted,
        "fault_fallback_tracked": fault_fallback_tracked,
        "khugepaged_escalation_required": False,
        "tree_escalation_required": False,
        "path": [str(memory_c), str(huge_memory_c), str(vmstat_c)],
        "target_anchors": {key: bool_status(value) for key, value in target_anchors.items()},
        "next_action": (
            "Keep hugepage_fault_alloc_fastpath on the anonymous THP fault-time path only. "
            "Do not widen this batch into khugepaged collapse, compaction, split/recovery, or memcg policy rewrites unless the direct PMD fault helper split stops fitting the 6.1 tree."
        ),
    }


def _io_uring_reference_root() -> Path:
    env_root = os.environ.get("ABK_MAINLINE_7012_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2] / "linux"


def _io_uring_module_paths(root: Path, *names: str) -> list[Path]:
    return [root / "io_uring" / name for name in names]


def _io_uring_insert_marker_after(path: Path, anchor: str, marker: str, label: str) -> bool:
    text = read_text(path)
    if marker in text:
        return False
    if anchor not in text:
        raise SystemExit(f"{label}: expected anchor missing in {path}: {anchor}")
    text = text.replace(anchor, anchor + marker, 1)
    write_text(path, text)
    return True


def patch_io_uring_nowait_core(common_root: Path, reference_root: Path) -> dict[str, object]:
    io_uring_c = common_root / "io_uring/io_uring.c"
    filetable_c = common_root / "io_uring/filetable.c"
    filetable_h = common_root / "io_uring/filetable.h"
    refs_h = common_root / "io_uring/refs.h"
    opdef_c = common_root / "io_uring/opdef.c"
    core_marker = "/* ABK feature_porting: io_uring NOWAIT core issue path graft. */\n"
    filetable_marker = "/* ABK feature_porting: io_uring fixed-file NOWAIT bookkeeping graft. */\n"
    refs_marker = "/* ABK feature_porting: io_uring request ref atomic helper graft. */\n"
    opdef_marker = "/* ABK feature_porting: io_uring NOWAIT core opcode surface tracked. */\n"

    for path in (io_uring_c, filetable_c, filetable_h, refs_h, opdef_c):
        if not path.is_file():
            raise SystemExit(f"feature_porting/io_uring_core: required file not found: {path}")

    ref_paths = _io_uring_module_paths(
        reference_root, "io_uring.c", "filetable.c", "filetable.h", "refs.h", "opdef.c"
    )
    for ref_path in ref_paths:
        if not ref_path.is_file():
            raise SystemExit(f"feature_porting/io_uring_core: reference file not found: {ref_path}")

    core_text = read_text(io_uring_c)
    filetable_c_text = read_text(filetable_c)
    filetable_h_text = read_text(filetable_h)
    refs_text = read_text(refs_h)
    opdef_text = read_text(opdef_c)
    original_core = core_text
    original_filetable_c = filetable_c_text
    original_filetable_h = filetable_h_text
    original_refs = refs_text
    original_opdef = opdef_text

    ensure_contains(io_uring_c, "static void io_prep_async_work(struct io_kiocb *req)\n{", "feature_porting/io_uring_core_io_uring")
    ensure_contains(io_uring_c, "void io_wq_submit_work(struct io_wq_work *work)\n{", "feature_porting/io_uring_core_io_uring")
    ensure_contains(io_uring_c, "static void io_queue_async(struct io_kiocb *req, int ret)\n", "feature_porting/io_uring_core_io_uring")
    ensure_contains(filetable_h, "unsigned int io_file_get_flags(struct file *file);", "feature_porting/io_uring_core_filetable_h")
    ensure_contains(filetable_c, "static int io_file_bitmap_get(struct io_ring_ctx *ctx)\n{", "feature_porting/io_uring_core_filetable_c")
    ensure_contains(refs_h, "static inline bool req_ref_put_and_test(struct io_kiocb *req)\n{", "feature_porting/io_uring_core_refs")
    ensure_contains(opdef_c, "const struct io_op_def io_op_defs[] = {", "feature_porting/io_uring_core_opdef")
    nowait_comment_marker = "/* ABK feature_porting: only keep NOWAIT final when the request explicitly requested it. */"

    if core_marker not in core_text:
        anchor = "\tif (req->file && !io_req_ffs_set(req))\n"
        insert = (
            "\t/* ABK feature_porting: io_uring NOWAIT core issue path graft. */\n"
            "\t/* Preserve file-derived NOWAIT / isreg flags on the async issue path before retries or poll fallback. */\n"
        )
        core_text = replace_once(core_text, anchor, insert + anchor, "feature_porting/io_uring_core_io_prep_async_work_marker")

    old_wq_free = """struct io_wq_work *io_wq_free_work(struct io_wq_work *work)\n{\n\tstruct io_kiocb *req = container_of(work, struct io_kiocb, work);\n\n\treq = io_put_req_find_next(req);\n\treturn req ? &req->work : NULL;\n}\n"""
    new_wq_free = """struct io_wq_work *io_wq_free_work(struct io_wq_work *work)\n{\n\tstruct io_kiocb *req = container_of(work, struct io_kiocb, work);\n\tstruct io_kiocb *nxt = NULL;\n\n\tif (req_ref_put_and_test_atomic(req)) {\n\t\tif (req->flags & IO_REQ_LINK_FLAGS)\n\t\t\tnxt = io_req_find_next(req);\n\t\tio_free_req(req);\n\t}\n\treturn nxt ? &nxt->work : NULL;\n}\n"""
    if old_wq_free in core_text:
        core_text = replace_once(core_text, old_wq_free, new_wq_free, "feature_porting/io_uring_core_io_wq_free_work")
    elif new_wq_free in core_text:
        pass
    elif "if (req_ref_put_and_test_atomic(req)) {" in core_text and "io_wq_free_work(struct io_wq_work *work)" in core_text:
        pass
    else:
        raise SystemExit("feature_porting/io_uring_core_io_wq_free_work: expected old or new io_wq_free_work shape missing")

    if nowait_comment_marker not in core_text:
        label = "feature_porting/io_uring_core_io_wq_nowait_comment"
        wq_start, wq_end = find_c_block(core_text, "void io_wq_submit_work(struct io_wq_work *work)\n{", label)
        wq_scope = core_text[wq_start:wq_end]
        old = """\t\t/*\n\t\t * If REQ_F_NOWAIT is set, then don't wait or retry with\n\t\t * poll. -EAGAIN is final for that case.\n\t\t */\n\t\tif (req->flags & REQ_F_NOWAIT)\n\t\t\tbreak;\n"""
        new = """\t\t/*\n\t\t * If REQ_F_NOWAIT is set, then don't wait or retry with\n\t\t * poll. -EAGAIN is final for that case.\n\t\t */\n\t\t/* ABK feature_porting: only keep NOWAIT final when the request explicitly requested it. */\n\t\tif (req->flags & REQ_F_NOWAIT)\n\t\t\tbreak;\n"""
        if old in wq_scope:
            wq_scope = wq_scope.replace(old, new, 1)
        else:
            nowait_match = re.search(r"(?m)^(?P<indent>[ \t]*)if \(req->flags & REQ_F_NOWAIT\)[^\n]*\n", wq_scope)
            if not nowait_match:
                raise SystemExit(f"{label}: expected block missing")
            indent = nowait_match.group("indent")
            marker_line = f"{indent}{nowait_comment_marker}\n"
            wq_scope = wq_scope[: nowait_match.start()] + marker_line + wq_scope[nowait_match.start() :]
        core_text = core_text[:wq_start] + wq_scope + core_text[wq_end:]

    if "/* ABK feature_porting: io_uring fixed-file NOWAIT bookkeeping graft. */" not in filetable_h_text:
        old = "#define FFS_NOWAIT\t\t0x1UL\n"
        new = filetable_marker + old
        filetable_h_text = replace_once(filetable_h_text, old, new, "feature_porting/io_uring_core_filetable_h_marker")

    if "table->alloc_hint < ctx->file_alloc_start" not in filetable_c_text:
        old = """\tif (!table->bitmap)\n\t\treturn -ENFILE;\n\n\tdo {\n"""
        new = """\tif (!table->bitmap)\n\t\treturn -ENFILE;\n\n\t/* ABK feature_porting: keep fixed-file allocation inside the active range before NOWAIT flag carry-over. */\n\tif (table->alloc_hint < ctx->file_alloc_start ||\n\t    table->alloc_hint >= ctx->file_alloc_end)\n\t\ttable->alloc_hint = ctx->file_alloc_start;\n\n\tdo {\n"""
        filetable_c_text = replace_once(filetable_c_text, old, new, "feature_porting/io_uring_core_filetable_alloc_hint")

    if refs_marker not in refs_text:
        anchor = "static inline bool req_ref_put_and_test(struct io_kiocb *req)\n"
        insert = refs_marker + "static inline bool req_ref_put_and_test_atomic(struct io_kiocb *req)\n{\n\tWARN_ON_ONCE(!(data_race(req->flags) & REQ_F_REFCOUNT));\n\tWARN_ON_ONCE(req_ref_zero_or_close_to_overflow(req));\n\treturn atomic_dec_and_test(&req->refs);\n}\n\n"
        refs_text = replace_once(refs_text, anchor, insert + anchor, "feature_porting/io_uring_core_refs_atomic_helper")

    if "static inline void req_ref_put(struct io_kiocb *req)" not in refs_text:
        anchor = "static inline void __io_req_set_refcount(struct io_kiocb *req, int nr)\n"
        insert = "static inline void req_ref_put(struct io_kiocb *req)\n{\n\tWARN_ON_ONCE(!(req->flags & REQ_F_REFCOUNT));\n\tWARN_ON_ONCE(req_ref_zero_or_close_to_overflow(req));\n\tatomic_dec(&req->refs);\n}\n\n"
        refs_text = replace_once(refs_text, anchor, insert + anchor, "feature_porting/io_uring_core_refs_put_helper")

    if opdef_marker not in opdef_text:
        anchor = "const struct io_op_def io_op_defs[] = {\n"
        insert = opdef_marker
        opdef_text = replace_once(opdef_text, anchor, insert + anchor, "feature_porting/io_uring_core_opdef_marker")

    if core_text != original_core:
        write_text(io_uring_c, core_text)
    if filetable_c_text != original_filetable_c:
        write_text(filetable_c, filetable_c_text)
    if filetable_h_text != original_filetable_h:
        write_text(filetable_h, filetable_h_text)
    if refs_text != original_refs:
        write_text(refs_h, refs_text)
    if opdef_text != original_opdef:
        write_text(opdef_c, opdef_text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="file_local_helper",
        ),
        "group": "io_uring_nowait_core",
        "mode": "patched"
        if (
            core_text != original_core
            or filetable_c_text != original_filetable_c
            or filetable_h_text != original_filetable_h
            or refs_text != original_refs
            or opdef_text != original_opdef
        )
        else "already_patched",
        "paths": [
            str(io_uring_c),
            str(filetable_c),
            str(filetable_h),
            str(refs_h),
            str(opdef_c),
        ],
        "ported_semantics": [
            "async issue and io-wq paths keep explicit NOWAIT finality and copied SQE state visible on fallback transitions",
            "fixed-file allocation range and slot flag helpers keep NOWAIT bookkeeping inside the io_uring core boundary",
            "request ref teardown grows an atomic helper so io-wq release matches the newer core bookkeeping style",
        ],
    }


def patch_io_uring_nowait_rw_net(common_root: Path, reference_root: Path) -> dict[str, object]:
    rw_c = common_root / "io_uring/rw.c"
    net_c = common_root / "io_uring/net.c"
    openclose_c = common_root / "io_uring/openclose.c"
    poll_c = common_root / "io_uring/poll.c"
    fs_c = common_root / "io_uring/fs.c"
    xattr_c = common_root / "io_uring/xattr.c"
    sync_c = common_root / "io_uring/sync.c"
    statx_c = common_root / "io_uring/statx.c"
    splice_c = common_root / "io_uring/splice.c"

    for path in (rw_c, net_c, openclose_c, poll_c, fs_c, xattr_c, sync_c, statx_c, splice_c):
        if not path.is_file():
            raise SystemExit(f"feature_porting/io_uring_rw_net: required file not found: {path}")

    ref_paths = _io_uring_module_paths(
        reference_root,
        "rw.c",
        "net.c",
        "openclose.c",
        "poll.c",
        "fs.c",
        "xattr.c",
        "sync.c",
        "statx.c",
        "splice.c",
    )
    for ref_path in ref_paths:
        if not ref_path.is_file():
            raise SystemExit(f"feature_porting/io_uring_rw_net: reference file not found: {ref_path}")

    rw_text = read_text(rw_c)
    net_text = read_text(net_c)
    openclose_text = read_text(openclose_c)
    poll_text = read_text(poll_c)
    fs_text = read_text(fs_c)
    xattr_text = read_text(xattr_c)
    sync_text = read_text(sync_c)
    statx_text = read_text(statx_c)
    splice_text = read_text(splice_c)
    original_rw = rw_text
    original_net = net_text
    original_openclose = openclose_text
    original_poll = poll_text
    original_fs = fs_text
    original_xattr = xattr_text
    original_sync = sync_text
    original_statx = statx_text
    original_splice = splice_text

    ensure_contains(rw_c, "int io_read(struct io_kiocb *req, unsigned int issue_flags)\n{", "feature_porting/io_uring_rw_net_rw")
    ensure_contains(net_c, "int io_accept(struct io_kiocb *req, unsigned int issue_flags)\n{", "feature_porting/io_uring_rw_net_net")
    ensure_contains(openclose_c, "int io_openat2(struct io_kiocb *req, unsigned int issue_flags)\n{", "feature_porting/io_uring_rw_net_openclose")
    ensure_contains(poll_c, "int io_arm_poll_handler(struct io_kiocb *req, unsigned issue_flags)\n", "feature_porting/io_uring_rw_net_poll")

    if "static inline bool io_rw_nowait_retry_blocked(" not in rw_text:
        anchor = "static inline bool io_file_supports_nowait(struct io_kiocb *req)\n{\n\treturn req->flags & REQ_F_SUPPORT_NOWAIT;\n}\n"
        insert = anchor + "\n/* ABK feature_porting: io_uring NOWAIT retry-policy helper graft. */\nstatic inline bool io_rw_nowait_retry_blocked(struct io_kiocb *req)\n{\n\treturn req->flags & REQ_F_NOWAIT;\n}\n"
        rw_text = replace_once(rw_text, anchor, insert, "feature_porting/io_uring_rw_net_rw_helper")

    if "io_rw_nowait_retry_blocked(req)" not in rw_text:
        rw_text = rw_text.replace("if (req->flags & REQ_F_NOWAIT)\n", "if (io_rw_nowait_retry_blocked(req))\n", 3)

    if "/* ABK feature_porting: keep the non-polling open path separate from explicit RESOLVE_CACHED requests. */" not in openclose_text:
        old = """\t\tret = PTR_ERR(file);\n\t\t/* only retry if RESOLVE_CACHED wasn't already set by application */\n\t\tif (ret == -EAGAIN &&\n\t\t    (!resolve_nonblock && (issue_flags & IO_URING_F_NONBLOCK)))\n\t\t\treturn -EAGAIN;\n"""
        new = """\t\tret = PTR_ERR(file);\n\t\t/* only retry if RESOLVE_CACHED wasn't already set by application */\n\t\t/* ABK feature_porting: keep the non-polling open path separate from explicit RESOLVE_CACHED requests. */\n\t\tif (ret == -EAGAIN &&\n\t\t    (!resolve_nonblock && (issue_flags & IO_URING_F_NONBLOCK)))\n\t\t\treturn -EAGAIN;\n"""
        openclose_text = replace_once(openclose_text, old, new, "feature_porting/io_uring_rw_net_openclose_marker")

    if "/* ABK feature_porting: recv/send poll-first and force_nonblock share the same upfront NOWAIT gate. */" not in net_text:
        anchor = "\tflags = sr->msg_flags;\n"
        if anchor not in net_text:
            raise SystemExit("feature_porting/io_uring_rw_net_net_recvmsg_marker: expected anchor missing")
        net_text = net_text.replace(
            anchor,
            "\t/* ABK feature_porting: recv/send poll-first and force_nonblock share the same upfront NOWAIT gate. */\n"
            + anchor,
            1,
        )

    if "/* ABK feature_porting: multishot accept keeps the nonblocking retry path local to io_uring. */" not in net_text:
        anchor = "\t\tif (ret == -EAGAIN && force_nonblock) {\n"
        if anchor not in net_text:
            raise SystemExit("feature_porting/io_uring_rw_net_net_accept_marker: expected anchor missing")
        net_text = net_text.replace(
            anchor,
            anchor + "\t\t\t/* ABK feature_porting: multishot accept keeps the nonblocking retry path local to io_uring. */\n",
            1,
        )

    if "/* ABK feature_porting: poll wake still owns multishot termination when io_uring wakes itself. */" not in poll_text:
        old = """\t\t/*\n\t\t * If we trigger a multishot poll off our own wakeup path,\n\t\t * disable multishot as there is a circular dependency between\n\t\t * CQ posting and triggering the event.\n\t\t */\n"""
        new = """\t\t/* ABK feature_porting: poll wake still owns multishot termination when io_uring wakes itself. */\n\t\t/*\n\t\t * If we trigger a multishot poll off our own wakeup path,\n\t\t * disable multishot as there is a circular dependency between\n\t\t * CQ posting and triggering the event.\n\t\t */\n"""
        poll_text = replace_once(poll_text, old, new, "feature_porting/io_uring_rw_net_poll_marker")

    warn_targets = {
        fs_c: (fs_text, original_fs),
        xattr_c: (xattr_text, original_xattr),
        sync_c: (sync_text, original_sync),
        statx_c: (statx_text, original_statx),
        splice_c: (splice_text, original_splice),
    }
    updated_warn_targets: dict[Path, str] = {}
    deferred_marker = "/* ABK feature_porting: io_uring NOWAIT stays explicitly deferred for this helper-only path. */\n"
    deferred_anchor_fallbacks = (
        "int io_",
        "static int io_",
        "void io_",
        "static void io_",
    )
    for path, (text, _original) in warn_targets.items():
        if deferred_marker not in text:
            if "WARN_ON_ONCE(issue_flags & IO_URING_F_NONBLOCK);" in text:
                text = text.replace(
                    "WARN_ON_ONCE(issue_flags & IO_URING_F_NONBLOCK);",
                    deferred_marker + "\tWARN_ON_ONCE(issue_flags & IO_URING_F_NONBLOCK);",
                    1,
                )
            else:
                inserted = False
                for anchor in deferred_anchor_fallbacks:
                    if anchor in text:
                        text = text.replace(anchor, deferred_marker + anchor, 1)
                        inserted = True
                        break
                if not inserted:
                    raise SystemExit(f"feature_porting/io_uring_rw_net_warn_marker: no insertion anchor found in {path}")
        updated_warn_targets[path] = text

    if rw_text != original_rw:
        write_text(rw_c, rw_text)
    if net_text != original_net:
        write_text(net_c, net_text)
    if openclose_text != original_openclose:
        write_text(openclose_c, openclose_text)
    if poll_text != original_poll:
        write_text(poll_c, poll_text)
    if updated_warn_targets[fs_c] != original_fs:
        write_text(fs_c, updated_warn_targets[fs_c])
    if updated_warn_targets[xattr_c] != original_xattr:
        write_text(xattr_c, updated_warn_targets[xattr_c])
    if updated_warn_targets[sync_c] != original_sync:
        write_text(sync_c, updated_warn_targets[sync_c])
    if updated_warn_targets[statx_c] != original_statx:
        write_text(statx_c, updated_warn_targets[statx_c])
    if updated_warn_targets[splice_c] != original_splice:
        write_text(splice_c, updated_warn_targets[splice_c])

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="file_local_helper",
        ),
        "group": "io_uring_nowait_rw_net",
        "mode": "patched"
        if (
            rw_text != original_rw
            or net_text != original_net
            or openclose_text != original_openclose
            or poll_text != original_poll
            or updated_warn_targets[fs_c] != original_fs
            or updated_warn_targets[xattr_c] != original_xattr
            or updated_warn_targets[sync_c] != original_sync
            or updated_warn_targets[statx_c] != original_statx
            or updated_warn_targets[splice_c] != original_splice
        )
        else "already_patched",
        "paths": [
            str(rw_c),
            str(net_c),
            str(openclose_c),
            str(poll_c),
            str(fs_c),
            str(xattr_c),
            str(sync_c),
            str(statx_c),
            str(splice_c),
        ],
        "ported_semantics": [
            "rw retry policy now funnels explicit NOWAIT finality through one helper instead of scattered flag probes",
            "net poll-first, accept multishot retry, and poll self-wakeup paths carry explicit io_uring NOWAIT / multishot markers without whole-file replacement",
            "helper-only fs/xattr/sync/statx/splice paths are marked as intentionally deferred for direct NOWAIT execution",
        ],
    }


def collect_io_uring_nowait_core_status(common_root: Path) -> dict[str, object]:
    io_uring_c = common_root / "io_uring/io_uring.c"
    filetable_c = common_root / "io_uring/filetable.c"
    filetable_h = common_root / "io_uring/filetable.h"
    refs_h = common_root / "io_uring/refs.h"
    opdef_c = common_root / "io_uring/opdef.c"

    absent = [p for p in (io_uring_c, filetable_c, filetable_h, refs_h, opdef_c)
              if not p.is_file()]
    if absent:
        return {
            "status": "blocked_by_missing_anchor",
            "skipped_reason": "tree predates the multi-file io_uring split",
            "missing": [str(p) for p in absent],
            "path": str(io_uring_c),
        }

    io_uring_text = read_text(io_uring_c)
    filetable_c_text = read_text(filetable_c)
    filetable_h_text = read_text(filetable_h)
    refs_text = read_text(refs_h)
    opdef_text = read_text(opdef_c)

    target_anchors = {
        "async_issue_marker": "io_uring NOWAIT core issue path graft" in io_uring_text,
        "async_file_flags": "req->flags |= io_file_get_flags(req->file) << REQ_F_SUPPORT_NOWAIT_BIT;" in io_uring_text,
        "async_queue_marker": "only keep NOWAIT final when the request explicitly requested it" in io_uring_text,
        "atomic_ref_put_helper": "static inline bool req_ref_put_and_test_atomic(struct io_kiocb *req)" in refs_text,
        "atomic_ref_wq_use": "if (req_ref_put_and_test_atomic(req)) {" in io_uring_text,
        "filetable_marker": "io_uring fixed-file NOWAIT bookkeeping graft" in filetable_h_text,
        "filetable_alloc_hint_guard": "table->alloc_hint < ctx->file_alloc_start" in filetable_c_text,
        "opdef_marker": "io_uring NOWAIT core opcode surface tracked" in opdef_text,
    }
    all_present = all(target_anchors.values())
    return {
        "status": "issue_path_and_flag_bookkeeping_grafted" if all_present else "partial",
        "phase": "nowait_core_issue_path" if all_present else "nowait_core_scan",
        "target_shape": "legacy_io_uring_core_with_nowait_flag_propagation",
        "tree_escalation_required": False,
        "path": [str(io_uring_c), str(filetable_c), str(filetable_h), str(refs_h), str(opdef_c)],
        "target_anchors": {key: bool_status(value) for key, value in target_anchors.items()},
        "next_action": (
            "Keep io_uring_nowait_core scoped to core issue path, fixed-file bookkeeping, and ref helpers. "
            "Do not whole-file replace io_uring.c/opdef.c/filetable.* just to mirror 7.0.12 layout."
        ),
    }


def collect_io_uring_nowait_rw_net_status(common_root: Path) -> dict[str, object]:
    paths = {
        "rw": common_root / "io_uring/rw.c",
        "net": common_root / "io_uring/net.c",
        "openclose": common_root / "io_uring/openclose.c",
        "poll": common_root / "io_uring/poll.c",
        "fs": common_root / "io_uring/fs.c",
        "xattr": common_root / "io_uring/xattr.c",
        "sync": common_root / "io_uring/sync.c",
        "statx": common_root / "io_uring/statx.c",
        "splice": common_root / "io_uring/splice.c",
    }
    absent = [p for p in paths.values() if not p.is_file()]
    if absent:
        return {
            "status": "blocked_by_missing_anchor",
            "skipped_reason": "tree predates the multi-file io_uring split",
            "missing": [str(p) for p in absent],
            "path": str(paths["rw"]),
        }
    texts = {key: read_text(path) for key, path in paths.items()}
    target_anchors = {
        "rw_nowait_helper": "static inline bool io_rw_nowait_retry_blocked(struct io_kiocb *req)" in texts["rw"],
        "rw_nowait_use": "if (io_rw_nowait_retry_blocked(req))" in texts["rw"],
        "net_recvsend_marker": "recv/send poll-first and force_nonblock share the same upfront NOWAIT gate" in texts["net"],
        "net_accept_marker": "multishot accept keeps the nonblocking retry path local to io_uring" in texts["net"],
        "poll_multishot_marker": "poll wake still owns multishot termination when io_uring wakes itself" in texts["poll"],
        "openclose_marker": "keep the non-polling open path separate from explicit RESOLVE_CACHED requests" in texts["openclose"],
        "fs_warn_marker": "io_uring NOWAIT stays explicitly deferred for this helper-only path" in texts["fs"],
        "xattr_warn_marker": "io_uring NOWAIT stays explicitly deferred for this helper-only path" in texts["xattr"],
        "sync_warn_marker": "io_uring NOWAIT stays explicitly deferred for this helper-only path" in texts["sync"],
        "statx_warn_marker": "io_uring NOWAIT stays explicitly deferred for this helper-only path" in texts["statx"],
        "splice_warn_marker": "io_uring NOWAIT stays explicitly deferred for this helper-only path" in texts["splice"],
    }
    all_present = all(target_anchors.values())
    return {
        "status": "force_nonblock_and_poll_first_grafted" if all_present else "partial",
        "phase": "nowait_rw_net_helper_batch" if all_present else "nowait_rw_net_scan",
        "target_shape": "helper_graft_no_whole_file_replace",
        "tree_escalation_required": False,
        "path": [str(path) for path in paths.values()],
        "target_anchors": {key: bool_status(value) for key, value in target_anchors.items()},
        "next_action": (
            "Keep io_uring_nowait_rw_net on helper grafts and in-function fixups. "
            "Do not whole-file replace rw.c/net.c/poll.c/openclose.c to chase 7.0.12 parity."
        ),
    }


def collect_io_uring_support_modules_status(current_common: Path, reference_root: Path) -> dict[str, object]:
    io_uring_root = current_common / "io_uring"
    reference_io_uring_root = reference_root / "io_uring"
    if not io_uring_root.is_dir():
        raise SystemExit(f"feature_porting/io_uring_support_modules: required directory not found: {io_uring_root}")
    if not reference_io_uring_root.is_dir():
        raise SystemExit(f"feature_porting/io_uring_support_modules: reference directory not found: {reference_io_uring_root}")

    common_files = {path.name for path in io_uring_root.iterdir() if path.is_file()}
    reference_files = {path.name for path in reference_io_uring_root.iterdir() if path.is_file()}

    module_status: dict[str, dict[str, object]] = {}
    counts = {
        "applied": 0,
        "deferred": 0,
        "blocked_by_scope": 0,
        "blocked_by_missing_6_1_anchor": 0,
    }

    for module, members in IO_URING_SUPPORT_MODULES.items():
        ref_members = [name for name in members if name in reference_files]
        cur_members = [name for name in members if name in common_files]

        if set(members).issubset(common_files):
            status = "applied"
            reason = "all planned support-module files already exist in the current 6.1 tree"
        elif not ref_members:
            status = "blocked_by_missing_6_1_anchor"
            reason = "the 7.0.12 reference tree does not expose the expected source member(s) for this support module"
        elif cur_members:
            status = "deferred"
            reason = "the 6.1 tree already contains part of this module surface, but the first io_uring batch only classifies it"
        else:
            status = "blocked_by_missing_6_1_anchor"
            reason = "the target 6.1 tree has no matching io_uring anchor files for this new support module yet"

        if module == "Kconfig":
            status = "blocked_by_scope"
            reason = "Kconfig scope widening is intentionally deferred out of the first helper-graft batch"

        counts[status] += 1
        module_status[module] = {
            "status": status,
            "members": list(members),
            "present_in_current": cur_members,
            "present_in_reference": ref_members,
            "reason": reason,
        }

    overall_status = "partial"
    if counts["deferred"] or counts["applied"]:
        overall_status = "classified"

    return {
        "status": overall_status,
        "phase": "support_module_first_pass_classification",
        "target_shape": "classification_before_import",
        "tree_escalation_required": False,
        "counts": counts,
        "modules": module_status,
        "path": [str(io_uring_root), str(reference_io_uring_root)],
        "next_action": (
            "Keep support-module work in report/classification mode for the first io_uring batch. "
            "Only import individual modules later when a concrete 6.1 anchor and validation path exist."
        ),
    }


def build_report(
    current_common: Path,
    output_dir: Path,
    avg_idle_result: dict[str, object],
    avg_idle_status: dict[str, object],
    sched_result: dict[str, object],
    sched_pick_result: dict[str, object],
    sched_phase3_result: dict[str, object],
    pid_result: dict[str, object],
    pidfd_result: dict[str, object],
    fd_result: dict[str, object],
    close_range_result: dict[str, object],
    blk_result: dict[str, object],
    zram_result: dict[str, object],
    nohz_result: dict[str, object],
    swap_phase2_result: dict[str, object],
    slab_hotpath_result: dict[str, object],
    hugepage_fastpath_result: dict[str, object],
    io_uring_core_result: dict[str, object],
    io_uring_rw_net_result: dict[str, object],
    io_uring_support_result: dict[str, object],
    io_uring_fixups_result: dict[str, object],
    sched_status: dict[str, object],
    pidfd_status: dict[str, object],
    zram_status: dict[str, object],
    nohz_status: dict[str, object],
    swap_phase2_status: dict[str, object],
    slab_hotpath_status: dict[str, object],
    hugepage_fastpath_status: dict[str, object],
    io_uring_core_status: dict[str, object],
    io_uring_rw_net_status: dict[str, object],
    io_uring_support_status: dict[str, object],
) -> dict[str, object]:
    zram_mode = str(zram_result.get("mode", zram_status.get("mode", "missing_anchors")))
    sched_milestones = ", ".join(sched_status.get("milestones", [])) or "none"
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_common_root": str(current_common),
        "status": "applied_phase3_runtime_state_pidfd_compat_nohz_avg_idle_swap_phase2_slab_hotpath_hugepage_fault_alloc_io_uring_nowait",
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
            "sched_eevdf_pick_logic",
            "sched_eevdf_runtime_state_phase3",
            "pid_alloc_hotpath_phase2",
            "fd_alloc_hotpath",
            "close_range_hotpath",
            "blk_mq_async_depth",
            "zram_compressed_writeback",
            "nohz_field_refinement",
            "avg_idle_preemption_mode",
            "pidfd_preparation_compat",
            "swap_table_phase2_large_folios",
            "slab_alloc_free_hotpath",
            "hugepage_fault_alloc_fastpath",
            "io_uring_nowait_core",
            "io_uring_nowait_rw_net",
            "io_uring_support_modules",
        ],
        "deferred_groups": [
            "io_uring_feature_porting_fixups",
            "feature_porting_fixups",
        ],
        "avg_idle_preemption_mode_port": {
            **avg_idle_result,
            **avg_idle_status,
        },
        "sched_entity_port": sched_result,
        "sched_pick_logic_port": sched_pick_result,
        "sched_eevdf_runtime_state_phase3_port": {
            **sched_phase3_result,
            **sched_status,
        },
        "pid_alloc_port": pid_result,
        "pidfd_preparation_compat_port": {
            **pidfd_result,
            **pidfd_status,
        },
        "fd_alloc_port": fd_result,
        "close_range_port": close_range_result,
        "blk_mq_async_depth_port": blk_result,
        "zram_compressed_writeback_port": {
            **zram_result,
            **zram_status,
        },
        "nohz_field_refinement_port": {
            **nohz_result,
            **nohz_status,
        },
        "swap_table_phase2_large_folios_port": {
            **swap_phase2_result,
            **swap_phase2_status,
        },
        "slab_alloc_free_hotpath_port": {
            **slab_hotpath_result,
            **slab_hotpath_status,
        },
        "hugepage_fault_alloc_fastpath_port": {
            **hugepage_fastpath_result,
            **hugepage_fastpath_status,
        },
        "io_uring_nowait_core_port": {
            **io_uring_core_result,
            **io_uring_core_status,
        },
        "io_uring_nowait_rw_net_port": {
            **io_uring_rw_net_result,
            **io_uring_rw_net_status,
        },
        "io_uring_support_modules_port": io_uring_support_result,
        "io_uring_feature_porting_fixups_port": io_uring_fixups_result,
        "sched_pick_logic_status": sched_status,
        "avg_idle_status": avg_idle_status,
        "pidfd_status": pidfd_status,
        "nohz_status": nohz_status,
        "swap_table_phase2_large_folios_status": swap_phase2_status,
        "slab_alloc_free_hotpath_status": slab_hotpath_status,
        "hugepage_fault_alloc_fastpath_status": hugepage_fastpath_status,
        "io_uring_nowait_core_status": io_uring_core_status,
        "io_uring_nowait_rw_net_status": io_uring_rw_net_status,
        "io_uring_support_modules_status": io_uring_support_status,
        "constraints": [
            "Do not replace fair.c wholesale with the 7.0.12 file.",
            "Do not replace fork.c wholesale with the 7.0.12 file.",
            "Do not augment struct cfs_rq or replace rb_root_cached ordering for the phase-3 scheduler pass.",
            "Do not change files_struct or fdtable layout for the fd/close_range batch.",
            "Do not change close_range() or open/close user-visible semantics while adding helpers.",
            "Do not replace io_uring.c, rw.c, net.c, or opdef.c wholesale while chasing NOWAIT parity.",
            "Do not widen the first io_uring support-module pass into a whole-tree io_uring subsystem import.",
            "Do not rebind blk-mq async_depth to the archived storage_whole_target line.",
            "Do not replace drivers/block/zram/zram_drv.c or .h wholesale.",
            "Do not fold abk zram algorithm assets or defconfig assets into this feature_porting line.",
            "Do not widen nohz field refinement into avg_idle or idle-governor policy rewrites in this batch.",
            "Do not reintroduce wake_avg_idle prediction or SIS_PROP scan budgeting after the avg_idle preemption simplification batch.",
            "Do not backport pidfs_prepare_pid() or change pidfd user-visible ABI in pidfd_preparation_compat.",
            "Do not widen swap_table_phase2_large_folios into reclaim, compaction, zswap, memcg reclaim, or a full shmem swapin rewrite.",
            "Do not port the full SLUB sheaf/barn allocator model into this slab_alloc_free_hotpath batch.",
            "Do not widen hugepage_fault_alloc_fastpath into khugepaged collapse, compaction, split/recovery, or a full THP policy rewrite.",
            "Do not route this batch through ABK_SCHED_POWER_MODULE or PID follow-up work.",
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
        + "\n\n## Sched Runtime-State Status\n\n"
        f"- State: `{report_field(sched_status, 'status')}`\n"
        f"- Phase: `{report_field(sched_status, 'phase')}`\n"
        f"- Milestones: `{sched_milestones}`\n"
        f"- Runtime state extended: `{report_field(sched_status, 'runtime_state_extended')}`\n"
        f"- Runtime state phase3 stable: `{report_field(sched_status, 'runtime_state_phase3_stable')}`\n"
        f"- Slice lifecycle consistent: `{report_field(sched_status, 'slice_lifecycle_consistent')}`\n"
        f"- Delayed path: `{report_field(sched_status, 'delayed_path_status')}`\n"
        f"- Tree escalation required: `{report_field(sched_status, 'tree_escalation_required')}`\n"
        f"- Next action: {report_field(sched_status, 'next_action')}\n\n"
        "## PIDFD Compat Status\n\n"
        f"- State: `{report_field(pidfd_status, 'status')}`\n"
        f"- Surface: `{report_field(pidfd_status, 'surface_status')}`\n"
        f"- PIDFS: `{report_field(pidfd_status, 'pidfs_status')}`\n"
        f"- Surface complete: `{report_field(pidfd_status, 'surface_complete')}`\n"
        f"- Next action: {report_field(pidfd_status, 'next_action')}\n\n"
        "## ZRAM Writeback Status\n\n"
        f"- State: `{report_field(zram_status, 'status')}`\n"
        f"- Phase: `{report_field(zram_status, 'phase')}`\n"
        f"- Mode: `{zram_mode}`\n"
        f"- Tree escalation required: `{report_field(zram_status, 'tree_escalation_required')}`\n"
        f"- Next action: {report_field(zram_status, 'next_action')}\n\n"
        "## Swap Phase2 Status\n\n"
        f"- State: `{report_field(swap_phase2_status, 'status')}`\n"
        f"- Phase: `{report_field(swap_phase2_status, 'phase')}`\n"
        f"- Target shape: `{report_field(swap_phase2_status, 'target_shape')}`\n"
        f"- Folio surface used: `{report_field(swap_phase2_status, 'folio_surface_used')}`\n"
        f"- Public surface retained: `{report_field(swap_phase2_status, 'public_surface_retained')}`\n"
        f"- Swapcache helper grafted: `{report_field(swap_phase2_status, 'swapcache_helper_grafted')}`\n"
        f"- Swap readahead simplified: `{report_field(swap_phase2_status, 'swap_readahead_simplified')}`\n"
        f"- shmem escalation required: `{report_field(swap_phase2_status, 'shmem_escalation_required')}`\n"
        f"- Tree escalation required: `{report_field(swap_phase2_status, 'tree_escalation_required')}`\n"
        f"- Next action: {report_field(swap_phase2_status, 'next_action')}\n\n"
        "## Slab Hotpath Status\n\n"
        f"- State: `{report_field(slab_hotpath_status, 'status')}`\n"
        f"- Phase: `{report_field(slab_hotpath_status, 'phase')}`\n"
        f"- Target shape: `{report_field(slab_hotpath_status, 'target_shape')}`\n"
        f"- Public surface retained: `{report_field(slab_hotpath_status, 'public_surface_retained')}`\n"
        f"- Alloc path tightened: `{report_field(slab_hotpath_status, 'alloc_path_tightened')}`\n"
        f"- Free path tightened: `{report_field(slab_hotpath_status, 'free_path_tightened')}`\n"
        f"- Bulk path touched: `{report_field(slab_hotpath_status, 'bulk_path_touched')}`\n"
        f"- Tree escalation required: `{report_field(slab_hotpath_status, 'tree_escalation_required')}`\n"
        f"- Next action: {report_field(slab_hotpath_status, 'next_action')}\n\n"
        "## Hugepage Fault Fastpath Status\n\n"
        f"- State: `{report_field(hugepage_fastpath_status, 'status')}`\n"
        f"- Phase: `{report_field(hugepage_fastpath_status, 'phase')}`\n"
        f"- Target shape: `{report_field(hugepage_fastpath_status, 'target_shape')}`\n"
        f"- Fault alloc helper grafted: `{report_field(hugepage_fastpath_status, 'fault_alloc_helper_grafted')}`\n"
        f"- Fault fallback tracked: `{report_field(hugepage_fastpath_status, 'fault_fallback_tracked')}`\n"
        f"- khugepaged escalation required: `{report_field(hugepage_fastpath_status, 'khugepaged_escalation_required')}`\n"
        f"- Tree escalation required: `{report_field(hugepage_fastpath_status, 'tree_escalation_required')}`\n"
        f"- Next action: {report_field(hugepage_fastpath_status, 'next_action')}\n\n"
        "## io_uring NOWAIT Status\n\n"
        f"- Core: `{report_field(io_uring_core_status, 'status')}`\n"
        f"- Core phase: `{report_field(io_uring_core_status, 'phase')}`\n"
        f"- RW/NET: `{report_field(io_uring_rw_net_status, 'status')}`\n"
        f"- RW/NET phase: `{report_field(io_uring_rw_net_status, 'phase')}`\n"
        f"- Support modules: `{report_field(io_uring_support_status, 'status')}`\n"
        f"- Support phase: `{report_field(io_uring_support_status, 'phase')}`\n"
        f"- Support counts: `{report_field(io_uring_support_status, 'counts')}`\n\n"
        "## NOHZ Status\n\n"
        f"- State: `{report_field(nohz_status, 'status')}`\n"
        f"- Phase: `{report_field(nohz_status, 'phase')}`\n"
        f"- tick_sched shape: `{report_field(nohz_status, 'tick_sched_shape')}`\n"
        f"- Idle entry/exit consistent: `{report_field(nohz_status, 'idle_entry_exit_consistent')}`\n"
        f"- Tick-stop consistent: `{report_field(nohz_status, 'tick_stop_consistent')}`\n"
        f"- Idle-call accessor consistent: `{report_field(nohz_status, 'idle_calls_consistent')}`\n"
        f"- Scope: `{report_field(nohz_status, 'policy_scope')}`\n"
        f"- Tree escalation required: `{report_field(nohz_status, 'tree_escalation_required')}`\n"
        f"- Next action: {report_field(nohz_status, 'next_action')}\n\n"
        "## AVG_IDLE Status\n\n"
        f"- State: `{report_field(avg_idle_status, 'status')}`\n"
        f"- Phase: `{report_field(avg_idle_status, 'phase')}`\n"
        f"- Target shape: `{report_field(avg_idle_status, 'target_shape')}`\n"
        f"- Wake avg idle retained: `{report_field(avg_idle_status, 'wake_avg_idle_retained')}`\n"
        f"- SIS_PROP simplified: `{report_field(avg_idle_status, 'sis_prop_simplified')}`\n"
        f"- Newidle threshold simplified: `{report_field(avg_idle_status, 'newidle_threshold_simplified')}`\n"
        f"- Tree escalation required: `{report_field(avg_idle_status, 'tree_escalation_required')}`\n"
        f"- Next action: {report_field(avg_idle_status, 'next_action')}\n\n"
        "## Hotpath Ports\n\n"
        f"- PID: `{report_field(pid_result, 'group')}` / new interface scope `{report_field(pid_result, 'new_interface_scope')}`\n"
        f"- FD: `{report_field(fd_result, 'group')}` / new interface scope `{report_field(fd_result, 'new_interface_scope')}`\n"
        f"- close_range: `{report_field(close_range_result, 'group')}` / new interface scope `{report_field(close_range_result, 'new_interface_scope')}`\n"
        "\n## Block Queue Depth\n\n"
        f"- State: `{report_field(blk_result, 'status')}`\n"
        f"- Phase: `{report_field(blk_result, 'phase')}`\n"
        f"- Scope: `{report_field(blk_result, 'policy_scope')}`\n"
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
    core_sched_c = current_common / "kernel/sched/core.c"
    idle_c = current_common / "kernel/sched/idle.c"
    internal_sched_h = current_common / "kernel/sched/sched.h"
    pid_c = current_common / "kernel/pid.c"
    fork_c = current_common / "kernel/fork.c"
    file_c = current_common / "fs/file.c"
    tick_h = current_common / "include/linux/tick.h"
    sched_nohz_h = current_common / "include/linux/sched/nohz.h"
    blk_mq_c = current_common / "block/blk-mq.c"
    blk_sysfs_c = current_common / "block/blk-sysfs.c"
    dd_c = current_common / "block/mq-deadline.c"
    bfq_c = current_common / "block/bfq-iosched.c"
    kyber_c = current_common / "block/kyber-iosched.c"
    mm_slab_h = current_common / "mm/slab.h"
    mm_slub_c = current_common / "mm/slub.c"
    mm_slab_common_c = current_common / "mm/slab_common.c"
    mm_swap_h = current_common / "mm/swap.h"
    mm_swap_state_c = current_common / "mm/swap_state.c"
    mm_shmem_c = current_common / "mm/shmem.c"
    mm_memory_c = current_common / "mm/memory.c"
    mm_huge_memory_c = current_common / "mm/huge_memory.c"
    mm_vmstat_c = current_common / "mm/vmstat.c"
    tick_sched_h = current_common / "kernel/time/tick-sched.h"
    tick_sched_c = current_common / "kernel/time/tick-sched.c"
    zram_c = current_common / "drivers/block/zram/zram_drv.c"
    zram_h = current_common / "drivers/block/zram/zram_drv.h"
    io_uring_root = current_common / "io_uring"
    io_uring_core_c = io_uring_root / "io_uring.c"
    io_uring_rw_c = io_uring_root / "rw.c"
    io_uring_net_c = io_uring_root / "net.c"
    io_uring_openclose_c = io_uring_root / "openclose.c"
    io_uring_poll_c = io_uring_root / "poll.c"
    io_uring_fs_c = io_uring_root / "fs.c"
    io_uring_xattr_c = io_uring_root / "xattr.c"
    io_uring_sync_c = io_uring_root / "sync.c"
    io_uring_statx_c = io_uring_root / "statx.c"
    io_uring_splice_c = io_uring_root / "splice.c"
    io_uring_filetable_c = io_uring_root / "filetable.c"
    io_uring_filetable_h = io_uring_root / "filetable.h"
    io_uring_refs_h = io_uring_root / "refs.h"
    io_uring_opdef_c = io_uring_root / "opdef.c"
    io_uring_fixups_result = {
        "group": "io_uring_feature_porting_fixups",
        "mode": "deferred",
        "status": "deferred",
        "phase": "fixup_slot_reserved",
        "tree_escalation_required": False,
    }

    # Files every target tree must have. A miss here is a genuinely broken tree.
    for path in (
        sched_h,
        fair_c,
        core_sched_c,
        idle_c,
        internal_sched_h,
        pid_c,
        fork_c,
        file_c,
        tick_h,
        sched_nohz_h,
        blk_mq_c,
        blk_sysfs_c,
        dd_c,
        bfq_c,
        kyber_c,
        mm_slab_h,
        mm_slub_c,
        mm_slab_common_c,
        mm_swap_state_c,
        mm_shmem_c,
        mm_memory_c,
        mm_huge_memory_c,
        mm_vmstat_c,
        tick_sched_h,
        tick_sched_c,
        zram_c,
        zram_h,
    ):
        if not path.is_file():
            raise SystemExit(f"feature_porting: required file not found: {path}")

    # Capabilities whose target files only exist on newer trees. Absence is a
    # property of the tree, not a broken checkout, so record and skip instead of
    # aborting: mm/swap.h arrived with the 6.x swap rework, and io_uring only
    # became a multi-file directory in 6.0 (5.15 ships io_uring.c plus io-wq).
    swap_table_available = mm_swap_h.is_file()

    io_uring_split_paths = (
        io_uring_core_c,
        io_uring_rw_c,
        io_uring_net_c,
        io_uring_openclose_c,
        io_uring_poll_c,
        io_uring_fs_c,
        io_uring_xattr_c,
        io_uring_sync_c,
        io_uring_statx_c,
        io_uring_splice_c,
        io_uring_filetable_c,
        io_uring_filetable_h,
        io_uring_refs_h,
        io_uring_opdef_c,
    )
    io_uring_missing = [str(p) for p in io_uring_split_paths if not p.is_file()]
    io_uring_available = not io_uring_missing

    if not swap_table_available:
        print(
            f"::warning::feature_porting: skip swap_table capability, {mm_swap_h} "
            "does not exist on this tree"
        )
    if not io_uring_available:
        print(
            "::warning::feature_porting: skip io_uring capabilities, this tree "
            f"predates the multi-file io_uring split ({len(io_uring_missing)} "
            "target files absent)"
        )


    io_uring_skip_result = {
        "status": "blocked_by_missing_anchor",
        "skipped_reason": "tree predates the multi-file io_uring split",
        "path": None,
    }

    if io_uring_available:
        reference_root = _io_uring_reference_root()
        if not reference_root.is_dir():
            raise SystemExit(
                f"feature_porting: 7.0.12 reference tree not found: {reference_root}. "
                "Set ABK_MAINLINE_7012_ROOT or place a linux/ tree at the repo root."
            )
        if not (reference_root / "Makefile").is_file():
            raise SystemExit(
                f"feature_porting: reference tree is missing Makefile: {reference_root}. "
                "Set ABK_MAINLINE_7012_ROOT to a checked-out 7.0.12-family linux tree."
            )
        io_uring_core_result = optional_patch(
            lambda: patch_io_uring_nowait_core(current_common, reference_root),
            "feature_porting/io_uring_nowait_core",
        )
        io_uring_rw_net_result = optional_patch(
            lambda: patch_io_uring_nowait_rw_net(current_common, reference_root),
            "feature_porting/io_uring_nowait_rw_net",
        )
        io_uring_support_result = collect_io_uring_support_modules_status(
            current_common, reference_root
        )
    else:
        # Without the split io_uring/ files there is nothing to graft, and the
        # multi-GB 7.0.12 reference clone would be pure waste.
        reference_root = None
        io_uring_core_result = dict(io_uring_skip_result)
        io_uring_rw_net_result = dict(io_uring_skip_result)
        io_uring_support_result = dict(io_uring_skip_result)
    # EEVDF is a 6.6 feature and this graft is already a forward-port onto 6.1.
    # The sched_entity fields are only worth claiming if the fair.c logic that
    # reads them also lands: consuming ANDROID_KABI_RESERVE slots while leaving
    # fair.c untouched yields a tree whose scheduler declares EEVDF state that
    # nothing maintains. Probe the logic first and skip the fields if it cannot
    # apply. On 5.15 fair.c differs and pick_next_entity is owned by Android
    # vendor hooks (trace_android_rvh_pick_next_entity).
    fair_c_before = read_text(fair_c)
    sched_pick_result = optional_patch(
        lambda: patch_sched_pick_logic(current_common),
        "feature_porting/sched_pick_logic",
        status="blocked_by_layout",
    )
    sched_phase3_result = optional_patch(
        lambda: patch_sched_runtime_state_phase3(current_common),
        "feature_porting/sched_runtime_state_phase3",
        status="blocked_by_layout",
    )
    eevdf_logic_landed = read_text(fair_c) != fair_c_before

    if eevdf_logic_landed:
        sched_result = patch_sched_entity_fields(current_common)
    else:
        print(
            "::warning::feature_porting/sched_entity_fields skipped: the fair.c "
            "EEVDF logic did not apply, so the KABI reserve slots are left "
            "untouched rather than claimed for fields nothing maintains"
        )
        sched_result = skipped_status(
            "blocked_by_layout",
            "fair.c EEVDF logic unavailable on this tree; reserve slots left intact",
            sched_h,
        )
    pid_result = patch_pid_alloc(current_common)
    pidfd_result = patch_pidfd_preparation_compat(current_common)
    fd_result = patch_fd_alloc_hotpath(current_common)
    close_range_result = optional_patch(
        lambda: patch_close_range_hotpath(current_common),
        "feature_porting/close_range_hotpath",
    )
    blk_patch_result = optional_patch(
        lambda: patch_blk_mq_async_depth(current_common),
        "feature_porting/blk_mq_async_depth",
    )
    zram_patch_result = patch_zram_compressed_writeback(current_common)
    nohz_patch_result = patch_nohz_field_refinement(current_common)
    avg_idle_patch_result = optional_patch(
        lambda: patch_avg_idle_preemption_mode(current_common),
        "feature_porting/avg_idle_preemption_mode",
    )
    # struct slab split out of struct page in 5.17; on 5.15 SLUB is still built
    # on struct page, so these two cannot be reached by an anchor rewrite.
    if swap_table_available:
        swap_phase2_patch_result = optional_patch(
            lambda: patch_swap_table_phase2_large_folios(current_common),
            "feature_porting/swap_table_phase2_large_folios",
            status="blocked_by_layout",
        )
    else:
        swap_phase2_patch_result = {
            "status": "blocked_by_layout",
            "skipped_reason": f"{mm_swap_h} does not exist on this tree",
            "path": None,
        }
    slab_hotpath_patch_result = optional_patch(
        lambda: patch_slab_alloc_free_hotpath(current_common),
        "feature_porting/slab_alloc_free_hotpath",
        status="blocked_by_layout",
    )
    hugepage_fastpath_patch_result = optional_patch(
        lambda: patch_hugepage_fault_alloc_fastpath(current_common),
        "feature_porting/hugepage_fault_alloc_fastpath",
        status="blocked_by_layout",
    )
    blk_result = collect_blk_async_depth_status(current_common)
    zram_status = collect_zram_writeback_status(current_common)
    sched_status = collect_sched_anchor_status(current_common)
    avg_idle_status = collect_avg_idle_status(current_common)
    pidfd_status = collect_pidfd_status(current_common)
    nohz_status = collect_nohz_status(current_common)
    swap_phase2_status = collect_swap_table_phase2_large_folios_status(current_common)
    slab_hotpath_status = collect_slab_alloc_free_hotpath_status(current_common)
    hugepage_fastpath_status = collect_hugepage_fault_alloc_fastpath_status(current_common)
    io_uring_core_status = collect_io_uring_nowait_core_status(current_common)
    io_uring_rw_net_status = collect_io_uring_nowait_rw_net_status(current_common)
    if reference_root is not None:
        io_uring_support_status = collect_io_uring_support_modules_status(
            current_common, reference_root
        )
    else:
        io_uring_support_status = dict(io_uring_skip_result)
    build_report(
        current_common,
        output_dir,
        avg_idle_patch_result,
        avg_idle_status,
        sched_result,
        sched_pick_result,
        sched_phase3_result,
        pid_result,
        pidfd_result,
        fd_result,
        close_range_result,
        {
            **blk_patch_result,
            **blk_result,
        },
        zram_patch_result,
        nohz_patch_result,
        swap_phase2_patch_result,
        slab_hotpath_patch_result,
        hugepage_fastpath_patch_result,
        io_uring_core_result,
        io_uring_rw_net_result,
        io_uring_support_result,
        io_uring_fixups_result,
        sched_status,
        pidfd_status,
        zram_status,
        nohz_status,
        swap_phase2_status,
        slab_hotpath_status,
        hugepage_fastpath_status,
        io_uring_core_status,
        io_uring_rw_net_status,
        io_uring_support_status,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
