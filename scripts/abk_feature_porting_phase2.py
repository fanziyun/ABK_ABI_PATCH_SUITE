#!/usr/bin/env python3
from __future__ import annotations

import json
import os
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
        "feature_porting_backlog_batch2",
        "Single large batch for the six remaining non-paused phase2 items, with fixed landing strength per item.",
    ),
    PatchGroup(
        "tcp_socket_layout_reduction",
        "Keep TCP socket struct slimming report-only and blocked by layout.",
    ),
    PatchGroup(
        "ipv6_tcp_output_path",
        "Keep IPv6 TCP output-path follow-ups bounded and report-first without resuming network_porting.",
    ),
    PatchGroup(
        "io_uring_cbpf_filters",
        "Promote io_uring cBPF filters to a bounded ring-level executable item via support-module wiring already present in the target tree.",
    ),
    PatchGroup(
        "io_uring_non_circular_sq",
        "Tighten non-circular SQ tracking through bounded SQ helper split and deferred semantic boundary markers.",
    ),
    PatchGroup(
        "io_uring_large_rx_buffer_zcrx",
        "Keep zcrx within preparatory support-boundary wiring only, without widening into page-pool or netdev migration.",
    ),
    PatchGroup(
        "bpf_timer_bpf_wq_lockless",
        "Keep bpf_timer/bpf_wq lockless follow-ups inside helper-side async path tightening only.",
    ),
    PatchGroup(
        "feature_porting_backlog_fixups",
        "Reserve later scope-expanding follow-up batches for items intentionally left partial or report-only here.",
    ),
)


STATUS_REPORT_ONLY = "report_only"
STATUS_PARTIAL = "partial"
STATUS_DEFERRED = "deferred"
STATUS_BLOCKED_BY_LAYOUT = "blocked_by_layout"
STATUS_BLOCKED_BY_MISSING_ANCHOR = "blocked_by_missing_anchor"
STATUS_BLOCKED_BY_SCOPE = "blocked_by_scope"


def read_text(path: Path) -> str:
    return path.read_text()


def write_text(path: Path, text: str) -> None:
    path.write_text(text)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected block missing")
    return text.replace(old, new, 1)


def reference_root() -> Path:
    env_root = os.environ.get("ABK_MAINLINE_7012_ROOT")
    if env_root:
        root = Path(env_root)
    else:
        root = Path(__file__).resolve().parents[2] / "linux"
    return root


def file_present(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def text_present(root: Path, rel: str, needle: str) -> bool:
    path = root / rel
    if not path.exists():
        return False
    return needle in read_text(path)


def collect_presence(root: Path, rels: list[str]) -> dict[str, bool]:
    return {rel: file_present(root, rel) for rel in rels}


def supports_io_uring_cbpf(common_root: Path) -> bool:
    return all(
        file_present(common_root, rel)
        for rel in (
            "io_uring/register.c",
            "io_uring/bpf_filter.c",
            "io_uring/bpf_filter.h",
        )
    ) and text_present(common_root, "include/linux/io_uring_types.h", "bpf_filters")


def supports_non_circular_sq(common_root: Path) -> bool:
    return text_present(common_root, "io_uring/io_uring.c", "IORING_SETUP_NO_SQARRAY")


def supports_zcrx(common_root: Path) -> bool:
    return all(
        file_present(common_root, rel)
        for rel in (
            "io_uring/zcrx.c",
            "io_uring/zcrx.h",
        )
    ) and text_present(common_root, "io_uring/net.c", "io_recvzc_prep")


def supports_bpf_wq(common_root: Path) -> bool:
    return text_present(common_root, "kernel/bpf/helpers.c", "bpf_wq_start")


def supports_defer_timer_wq(common_root: Path) -> bool:
    return text_present(common_root, "kernel/bpf/helpers.c", "defer_timer_wq_op")


def report_item(
    *,
    key: str,
    title: str,
    group: str,
    status: str,
    phase: str,
    risk: str,
    summary: str,
    dependency_type: str,
    helper_graft_candidate: bool,
    executable: bool,
    scope_expansion_required: bool,
    blocked_by_layout: bool,
    blocked_by_missing_anchor: bool,
    blocked_by_scope: bool,
    target_presence: dict[str, bool],
    reference_presence: dict[str, bool],
    stable_anchors: list[str],
    missing_anchors: list[str],
    constraints: list[str],
    notes: list[str],
    follow_up_batch: str | None = None,
) -> dict[str, object]:
    return {
        "key": key,
        "title": title,
        "group": group,
        "status": status,
        "phase": phase,
        "risk": risk,
        "summary": summary,
        "dependency_type": dependency_type,
        "helper_graft_candidate": helper_graft_candidate,
        "executable": executable,
        "scope_expansion_required": scope_expansion_required,
        "blocked_by_layout": blocked_by_layout,
        "blocked_by_missing_anchor": blocked_by_missing_anchor,
        "blocked_by_scope": blocked_by_scope,
        "target_presence": target_presence,
        "reference_presence": reference_presence,
        "stable_anchors": stable_anchors,
        "missing_anchors": missing_anchors,
        "constraints": constraints,
        "notes": notes,
        "follow_up_batch": follow_up_batch,
    }


def ensure_marker(path: Path, anchor: str, marker: str, label: str) -> bool:
    text = read_text(path)
    if marker in text:
        return False
    text = replace_once(text, anchor, marker + "\n" + anchor, label)
    write_text(path, text)
    return True


def patch_io_uring_cbpf(common_root: Path) -> dict[str, object]:
    io_uring_c = common_root / "io_uring/io_uring.c"
    io_uring_h = common_root / "io_uring/io_uring.h"
    register_c = common_root / "io_uring/register.c"
    if not supports_io_uring_cbpf(common_root):
        return {
            "group": "io_uring_cbpf_filters",
            "status": STATUS_BLOCKED_BY_MISSING_ANCHOR,
            "phase": "legacy_io_uring_layout_without_support_module",
            "risk": "medium",
            "executable": False,
            "helper_graft_candidate": True,
            "scope_expansion_required": True,
            "marker": "ABK feature_porting_phase2: io_uring cBPF filters require support-module layout not present in this tree",
        }

    header_text = read_text(io_uring_h)
    changed = False
    if "io_activate_bpf_filters(" not in header_text:
        helper_block = """static inline void io_activate_bpf_filters(struct io_ring_ctx *ctx,
\t\t\t\t\tstruct io_restriction *restrictions)
{
\t/* ABK feature_porting_phase2: bounded io_uring cBPF filter activation keeps
\t * the ring-level executable path inside existing support-module wiring.
\t */
\tif (!restrictions->bpf_filters)
\t\treturn;
\tWRITE_ONCE(ctx->bpf_filters, restrictions->bpf_filters->filters);
}

"""
        anchor = "struct io_ctx_config {\n\tstruct io_uring_params p;\n\tstruct io_rings_layout layout;\n\tstruct io_uring_params __user *uptr;\n};\n"
        header_text = replace_once(
            header_text,
            anchor,
            helper_block + anchor,
            "feature_porting_phase2/io_activate_bpf_filters_helper",
        )
        changed = True
    if changed:
        write_text(io_uring_h, header_text)

    text = read_text(io_uring_c)
    c_changed = False
    if "io_activate_bpf_filters(ctx, dst);" not in text and "dst->bpf_filters" in text:
        text = text.replace(
            """\tif (dst->bpf_filters)\n\t\tWRITE_ONCE(ctx->bpf_filters, dst->bpf_filters->filters);\n""",
            """\tio_activate_bpf_filters(ctx, dst);\n""",
            1,
        )
        c_changed = True
    if c_changed:
        write_text(io_uring_c, text)

    reg_text = read_text(register_c)
    reg_changed = False
    reg_old = """\t\tret = io_register_bpf_filter(&ctx->restrictions, arg);\n\t\tif (!ret)\n\t\t\tWRITE_ONCE(ctx->bpf_filters,\n\t\t\t\t   ctx->restrictions.bpf_filters->filters);\n"""
    reg_new = """\t\tret = io_register_bpf_filter(&ctx->restrictions, arg);\n\t\tif (!ret)\n\t\t\tio_activate_bpf_filters(ctx, &ctx->restrictions);\n"""
    if reg_old in reg_text:
        reg_text = reg_text.replace(reg_old, reg_new, 1)
        reg_changed = True
    if reg_changed:
        write_text(register_c, reg_text)

    marker = "ABK feature_porting_phase2: bounded io_uring cBPF filter activation keeps"
    return {
        "group": "io_uring_cbpf_filters",
        "status": STATUS_PARTIAL,
        "phase": "ring_level_filter_wiring_grafted",
        "risk": "medium",
        "executable": True,
        "helper_graft_candidate": True,
        "scope_expansion_required": False,
        "marker": marker,
    }


def patch_non_circular_sq(common_root: Path) -> dict[str, object]:
    io_uring_c = common_root / "io_uring/io_uring.c"

    if not supports_non_circular_sq(common_root):
        return {
            "group": "io_uring_non_circular_sq",
            "status": STATUS_DEFERRED,
            "phase": "legacy_io_uring_layout_without_sqarray_gate",
            "risk": "medium",
            "executable": False,
            "helper_graft_candidate": False,
            "scope_expansion_required": True,
            "marker": "ABK feature_porting_phase2: non-circular SQ requires IORING_SETUP_NO_SQARRAY anchors not present in this tree",
        }

    text = read_text(io_uring_c)
    helper = """static inline bool io_sqring_uses_sq_array(struct io_ring_ctx *ctx)
{
\t/* ABK feature_porting_phase2: non-circular SQ stays bounded to existing
\t * SQ-array gating and helper splits; ring head/tail semantics remain deferred.
\t */
\treturn static_branch_unlikely(&io_key_has_sqarray.key) &&
\t\t!(ctx->flags & IORING_SETUP_NO_SQARRAY);
}

"""
    changed = False
    anchor = "static __cold void io_ring_ctx_ref_free(struct percpu_ref *ref)\n"
    if "static inline bool io_sqring_uses_sq_array(struct io_ring_ctx *ctx)" not in text:
        text = replace_once(
            text,
            anchor,
            helper + anchor,
            "feature_porting_phase2/io_sqring_uses_sq_array",
        )
        changed = True

    old = """\thead = READ_ONCE(ctx->sq_array[sq_idx]);\n"""
    new = """\tif (io_sqring_uses_sq_array(ctx))\n\t\thead = READ_ONCE(ctx->sq_array[sq_idx]);\n\telse\n\t\thead = sq_idx;\n"""
    if old in text and "if (io_sqring_uses_sq_array(ctx))" not in text:
        text = text.replace(old, new, 1)
        changed = True
    if changed:
        write_text(io_uring_c, text)

    return {
        "group": "io_uring_non_circular_sq",
        "status": STATUS_PARTIAL,
        "phase": "sq_array_gate_helper_split_only",
        "risk": "medium",
        "executable": False,
        "helper_graft_candidate": True,
        "scope_expansion_required": True,
        "marker": "ABK feature_porting_phase2: non-circular SQ stays bounded to existing",
    }


def patch_zcrx_boundary(common_root: Path) -> dict[str, object]:
    net_c = common_root / "io_uring/net.c"
    if not supports_zcrx(common_root):
        return {
            "group": "io_uring_large_rx_buffer_zcrx",
            "status": STATUS_BLOCKED_BY_MISSING_ANCHOR,
            "phase": "legacy_io_uring_layout_without_zcrx_surface",
            "risk": "high",
            "executable": False,
            "helper_graft_candidate": False,
            "scope_expansion_required": True,
            "marker": "ABK feature_porting_phase2: zcrx surface is absent in this tree",
        }
    marker = (
        "/* ABK feature_porting_phase2: zcrx stays in preparatory io_uring receive wiring only; "
        "do not widen this batch into page-pool, netdev, or driver-side migration. */"
    )
    ensure_marker(
        net_c,
        "int io_recvzc_prep(struct io_kiocb *req, const struct io_uring_sqe *sqe)\n",
        marker,
        "feature_porting_phase2/zcrx_boundary_marker",
    )
    return {
        "group": "io_uring_large_rx_buffer_zcrx",
        "status": STATUS_PARTIAL,
        "phase": "preparatory_rx_anchor_bounded",
        "risk": "high",
        "executable": False,
        "helper_graft_candidate": False,
        "scope_expansion_required": True,
        "marker": marker,
    }


def patch_bpf_timer_wq(common_root: Path) -> dict[str, object]:
    helpers_c = common_root / "kernel/bpf/helpers.c"
    if not supports_bpf_wq(common_root):
        return {
            "group": "bpf_timer_bpf_wq_lockless",
            "status": STATUS_BLOCKED_BY_MISSING_ANCHOR,
            "phase": "legacy_bpf_timer_only",
            "risk": "medium",
            "executable": False,
            "helper_graft_candidate": False,
            "scope_expansion_required": True,
            "marker": "ABK feature_porting_phase2: bpf_wq lockless follow-up is absent in this tree",
        }
    text = read_text(helpers_c)
    changed = False
    helper = """static inline bool bpf_async_use_direct_start(void)
{
\t/* ABK feature_porting_phase2: helper-side bpf_timer/bpf_wq lockless follow-up
\t * stays inside async start/cancel routing and does not reopen verifier/core scope.
\t */
\treturn !defer_timer_wq_op();
}

"""
    anchor = "BPF_CALL_3(bpf_timer_start, struct bpf_async_kern *, async, u64, nsecs, u64, flags)\n"
    if "static inline bool bpf_async_use_direct_start(void)" not in text:
        text = replace_once(
            text,
            anchor,
            helper + anchor,
            "feature_porting_phase2/bpf_async_use_direct_start",
        )
        changed = True

    if "bpf_async_use_direct_start()" not in text:
        helper = """static inline bool bpf_async_use_direct_start(void)
{
\t/* ABK feature_porting_phase2: helper-side bpf_timer/bpf_wq lockless follow-up
\t * stays inside async start/cancel routing and does not reopen verifier/core scope.
\t */
\treturn !defer_timer_wq_op();
}

"""
        anchor = "static bool defer_timer_wq_op(void)\n"
        text = replace_once(
            text,
            anchor,
            helper + anchor,
            "feature_porting_phase2/bpf_async_use_direct_start",
        )
        changed = True

    old_timer_start = "if (!defer_timer_wq_op()) {\n"
    if old_timer_start in text:
        text = text.replace(old_timer_start, "if (bpf_async_use_direct_start()) {\n", 1)
        changed = True

    old_wq_start = "if (!defer_timer_wq_op()) {\n\t\tschedule_work(&w->work);\n"
    if old_wq_start in text:
        text = text.replace(old_wq_start, "if (bpf_async_use_direct_start()) {\n\t\tschedule_work(&w->work);\n", 1)
        changed = True

    old_cancel = "if (!defer_timer_wq_op()) {\n\t\tstruct bpf_hrtimer *t = container_of(cb, struct bpf_hrtimer, cb);\n"
    if old_cancel in text:
        text = text.replace(old_cancel, "if (bpf_async_use_direct_start()) {\n\t\tstruct bpf_hrtimer *t = container_of(cb, struct bpf_hrtimer, cb);\n", 1)
        changed = True

    if changed:
        write_text(helpers_c, text)

    return {
        "group": "bpf_timer_bpf_wq_lockless",
        "status": STATUS_PARTIAL,
        "phase": "helper_side_async_routing_tightened",
        "risk": "medium",
        "executable": False,
        "helper_graft_candidate": True,
        "scope_expansion_required": True,
        "marker": "ABK feature_porting_phase2: helper-side bpf_timer/bpf_wq lockless follow-up",
    }


def classify_tcp_socket_layout(common_root: Path, ref_root: Path) -> dict[str, object]:
    target = [
        "include/net/sock.h",
        "include/net/tcp.h",
    ]
    ref = target
    stable = []
    if text_present(common_root, "include/net/sock.h", "struct sock {"):
        stable.append("include/net/sock.h:struct sock")
    if text_present(common_root, "include/net/tcp.h", "struct tcp_sock"):
        stable.append("include/net/tcp.h:struct tcp_sock")
    return report_item(
        key="tcp_socket_layout_reduction",
        title="TCP socket struct slimming",
        group="tcp_socket_layout_reduction",
        status=STATUS_BLOCKED_BY_LAYOUT,
        phase="layout_sensitive_core_structs",
        risk="high",
        summary="Keep TCP socket slimming blocked by layout and outside this batch's executable scope.",
        dependency_type="layout_and_protocol_core",
        helper_graft_candidate=False,
        executable=False,
        scope_expansion_required=True,
        blocked_by_layout=True,
        blocked_by_missing_anchor=False,
        blocked_by_scope=False,
        target_presence=collect_presence(common_root, target),
        reference_presence=collect_presence(ref_root, ref),
        stable_anchors=stable,
        missing_anchors=[],
        constraints=[
            "Do not change struct sock layout in this batch.",
            "Do not change struct tcp_sock layout in this batch.",
            "Do not reopen network_porting through TCP layout work.",
        ],
        notes=[
            "This item stays report-only at the layout boundary.",
            "A later batch would need explicit layout scope and validation.",
        ],
        follow_up_batch="separate_network_or_layout_batch",
    )


def classify_ipv6_tcp_output(common_root: Path, ref_root: Path) -> dict[str, object]:
    target = [
        "net/ipv4/tcp_output.c",
        "net/ipv6/ip6_output.c",
        "net/ipv6/inet6_connection_sock.c",
    ]
    ref = target
    stable = []
    if text_present(common_root, "net/ipv4/tcp_output.c", "INDIRECT_CALLABLE_DECLARE(int inet6_csk_xmit"):
        stable.append("net/ipv4/tcp_output.c:inet6_csk_xmit_indirect_call")
    if text_present(common_root, "net/ipv6/ip6_output.c", "ip6_autoflowlabel"):
        stable.append("net/ipv6/ip6_output.c:ip6_autoflowlabel")
    if text_present(common_root, "net/ipv6/inet6_connection_sock.c", "__inet6_csk_dst_check"):
        stable.append("net/ipv6/inet6_connection_sock.c:dst_cookie_check")

    return report_item(
        key="ipv6_tcp_output_path",
        title="IPv6 TCP output path",
        group="ipv6_tcp_output_path",
        status=STATUS_REPORT_ONLY,
        phase="bounded_anchor_tracking_only",
        risk="medium",
        summary="Keep IPv6 TCP output-path follow-ups report-first and bounded; do not resume network mainline migration here.",
        dependency_type="network_main_path",
        helper_graft_candidate=False,
        executable=False,
        scope_expansion_required=True,
        blocked_by_layout=False,
        blocked_by_missing_anchor=False,
        blocked_by_scope=True,
        target_presence=collect_presence(common_root, target),
        reference_presence=collect_presence(ref_root, ref),
        stable_anchors=stable,
        missing_anchors=[],
        constraints=[
            "Do not modify paused network_porting.",
            "Do not widen phase2 into tcp_output.c/ip6_output.c mainline migration.",
            "Do not claim IPv6 TCP output parity from local anchors alone.",
        ],
        notes=[
            "Current anchors are enough for bounded reporting only.",
            "This batch explicitly keeps network main-path work paused.",
        ],
        follow_up_batch="network_porting_resume_only",
    )


def classify_io_uring_cbpf(
    common_root: Path,
    ref_root: Path,
    graft_result: dict[str, object],
) -> dict[str, object]:
    target = [
        "io_uring/io_uring.c",
        "io_uring/register.c",
        "io_uring/bpf_filter.c",
        "io_uring/bpf_filter.h",
        "include/linux/filter.h",
        "include/uapi/linux/filter.h",
    ]
    ref = target
    stable = []
    missing = []
    if text_present(common_root, "io_uring/register.c", "io_register_bpf_filter(&ctx->restrictions, arg)"):
        stable.append("io_uring/register.c:bpf_filter_register_op")
    if text_present(common_root, "io_uring/io_uring.c", "io_uring_run_bpf_filters(ctx->bpf_filters, req)"):
        stable.append("io_uring/io_uring.c:ring_exec_filter_hook")
    if text_present(common_root, "io_uring/bpf_filter.c", "bpf_prog_create_from_user"):
        stable.append("io_uring/bpf_filter.c:classic_bpf_import")
    if text_present(common_root, "include/uapi/linux/filter.h", "struct sock_fprog"):
        stable.append("include/uapi/linux/filter.h:struct_sock_fprog")
    if text_present(common_root, "io_uring/io_uring.c", graft_result["marker"]):
        stable.append("io_uring/io_uring.c:phase2_cbpf_activation_marker")
    if graft_result["status"] == STATUS_BLOCKED_BY_MISSING_ANCHOR:
        for rel in ("io_uring/register.c", "io_uring/bpf_filter.c", "io_uring/bpf_filter.h"):
            if not file_present(common_root, rel):
                missing.append(f"{rel}:target_missing")
        if not text_present(common_root, "include/linux/io_uring_types.h", "bpf_filters"):
            missing.append("include/linux/io_uring_types.h:bpf_filters_state_missing")

    return report_item(
        key="io_uring_cbpf_filters",
        title="cBPF filters for io_uring",
        group="io_uring_cbpf_filters",
        status=graft_result["status"],
        phase=graft_result["phase"],
        risk=graft_result["risk"],
        summary=(
            "Phase2 batch two treats io_uring cBPF filters as the main executable item when support-module anchors exist; "
            "older single-file io_uring trees stay blocked by missing anchors."
        ),
        dependency_type="io_uring_support_module",
        helper_graft_candidate=graft_result["helper_graft_candidate"],
        executable=graft_result["executable"],
        scope_expansion_required=graft_result["scope_expansion_required"],
        blocked_by_layout=False,
        blocked_by_missing_anchor=graft_result["status"] == STATUS_BLOCKED_BY_MISSING_ANCHOR,
        blocked_by_scope=False,
        target_presence=collect_presence(common_root, target),
        reference_presence=collect_presence(ref_root, ref),
        stable_anchors=stable,
        missing_anchors=missing,
        constraints=[
            "Do not replace io_uring whole files.",
            "Keep the landing inside existing bpf_filter support-module wiring.",
            "Do not widen into a new io_uring support-tree import.",
        ],
        notes=[
            "The target tree only becomes executable here when it already carries bpf_filter.c/.h, register entrypoints, and request execution hook-up.",
            f"Marker: {graft_result['marker']}",
        ],
        follow_up_batch="feature_porting_phase2_fixups",
    )


def classify_non_circular_sq(
    common_root: Path,
    ref_root: Path,
    graft_result: dict[str, object],
) -> dict[str, object]:
    target = [
        "io_uring/io_uring.c",
        "io_uring/io_uring.h",
        "io_uring/sqpoll.c",
        "io_uring/register.c",
    ]
    ref = target
    stable = []
    missing = []
    if text_present(common_root, "io_uring/io_uring.c", "ctx->cached_sq_head"):
        stable.append("io_uring/io_uring.c:cached_sq_head")
    if text_present(common_root, "io_uring/register.c", "IORING_SETUP_NO_SQARRAY"):
        stable.append("io_uring/register.c:no_sqarray_resize_anchor")
    if text_present(common_root, "io_uring/io_uring.c", graft_result["marker"]):
        stable.append("io_uring/io_uring.c:phase2_non_circular_sq_marker")
    if graft_result["status"] == STATUS_DEFERRED:
        missing.append("io_uring/io_uring.c:IORING_SETUP_NO_SQARRAY_missing")

    return report_item(
        key="io_uring_non_circular_sq",
        title="Non-circular SQ",
        group="io_uring_non_circular_sq",
        status=graft_result["status"],
        phase=graft_result["phase"],
        risk=graft_result["risk"],
        summary="This batch only tightens SQ-array gating and helper boundaries; ring head/tail semantics remain deferred.",
        dependency_type="io_uring_ring_semantics",
        helper_graft_candidate=graft_result["helper_graft_candidate"],
        executable=graft_result["executable"],
        scope_expansion_required=graft_result["scope_expansion_required"],
        blocked_by_layout=False,
        blocked_by_missing_anchor=False,
        blocked_by_scope=True,
        target_presence=collect_presence(common_root, target),
        reference_presence=collect_presence(ref_root, ref),
        stable_anchors=stable,
        missing_anchors=missing,
        constraints=[
            "Do not rewrite SQ ring head/tail semantics in this batch.",
            "Do not widen into SQPOLL model changes.",
            "Keep the work limited to helper split and boundary tightening.",
        ],
        notes=[
            "This batch only becomes partial when no-sqarray anchors already exist in the target tree.",
            f"Marker: {graft_result['marker']}",
        ],
        follow_up_batch="dedicated_io_uring_ring_batch",
    )


def classify_zcrx(
    common_root: Path,
    ref_root: Path,
    graft_result: dict[str, object],
) -> dict[str, object]:
    target = [
        "io_uring/kbuf.c",
        "io_uring/net.c",
        "io_uring/io_uring.c",
        "io_uring/zcrx.c",
        "io_uring/zcrx.h",
    ]
    ref = target
    stable = []
    missing = []
    if text_present(common_root, "io_uring/kbuf.c", "ring-mapped provided buffer mode"):
        stable.append("io_uring/kbuf.c:ring_mapped_provided_buffers")
    if text_present(common_root, "io_uring/net.c", "io_recvzc_prep"):
        stable.append("io_uring/net.c:recvzc_prep_anchor")
    if text_present(common_root, "io_uring/net.c", graft_result["marker"]):
        stable.append("io_uring/net.c:phase2_zcrx_boundary_marker")
    if graft_result["status"] == STATUS_BLOCKED_BY_MISSING_ANCHOR:
        for rel in ("io_uring/zcrx.c", "io_uring/zcrx.h"):
            if not file_present(common_root, rel):
                missing.append(f"{rel}:target_missing")
        if not text_present(common_root, "io_uring/net.c", "io_recvzc_prep"):
            missing.append("io_uring/net.c:io_recvzc_prep_missing")

    return report_item(
        key="io_uring_large_rx_buffer_zcrx",
        title="Large RX buffer support (zcrx)",
        group="io_uring_large_rx_buffer_zcrx",
        status=graft_result["status"],
        phase=graft_result["phase"],
        risk=graft_result["risk"],
        summary="This batch only records preparatory zcrx receive-side anchor alignment; it does not widen into page-pool, netdev, or driver-side rollout.",
        dependency_type="io_uring_support_module_plus_network",
        helper_graft_candidate=graft_result["helper_graft_candidate"],
        executable=graft_result["executable"],
        scope_expansion_required=graft_result["scope_expansion_required"],
        blocked_by_layout=False,
        blocked_by_missing_anchor=graft_result["status"] == STATUS_BLOCKED_BY_MISSING_ANCHOR,
        blocked_by_scope=True,
        target_presence=collect_presence(common_root, target),
        reference_presence=collect_presence(ref_root, ref),
        stable_anchors=stable,
        missing_anchors=missing,
        constraints=[
            "Do not widen phase2 into page-pool or netdev support expansion.",
            "Do not treat zcrx presence as permission for whole-module migration.",
            "Keep this batch at preparatory wiring and boundary marking only.",
        ],
        notes=[
            "The target tree only becomes partial here when zcrx files and recvzc surface already exist.",
            f"Marker: {graft_result['marker']}",
        ],
        follow_up_batch="later_zcrx_support_module_batch",
    )


def classify_bpf_timer_wq(
    common_root: Path,
    ref_root: Path,
    graft_result: dict[str, object],
) -> dict[str, object]:
    target = [
        "kernel/bpf/helpers.c",
        "kernel/bpf/verifier.c",
        "kernel/bpf/syscall.c",
        "include/uapi/linux/bpf.h",
    ]
    ref = target
    stable = []
    missing = []
    if text_present(common_root, "kernel/bpf/helpers.c", "bpf_timer_cancel_async"):
        stable.append("kernel/bpf/helpers.c:bpf_timer_cancel_async")
    if text_present(common_root, "kernel/bpf/helpers.c", "bpf_wq_start"):
        stable.append("kernel/bpf/helpers.c:bpf_wq_start")
    if text_present(common_root, "include/uapi/linux/bpf.h", "struct bpf_wq"):
        stable.append("include/uapi/linux/bpf.h:struct_bpf_wq")
    if text_present(common_root, "kernel/bpf/helpers.c", graft_result["marker"]):
        stable.append("kernel/bpf/helpers.c:phase2_bpf_async_helper_marker")
    if graft_result["status"] == STATUS_BLOCKED_BY_MISSING_ANCHOR:
        if not text_present(common_root, "kernel/bpf/helpers.c", "bpf_wq_start"):
            missing.append("kernel/bpf/helpers.c:bpf_wq_start_missing")
        if not text_present(common_root, "include/uapi/linux/bpf.h", "struct bpf_wq"):
            missing.append("include/uapi/linux/bpf.h:struct_bpf_wq_missing")
        if not text_present(common_root, "kernel/bpf/helpers.c", "bpf_timer_cancel_async"):
            missing.append("kernel/bpf/helpers.c:bpf_timer_cancel_async_missing")

    return report_item(
        key="bpf_timer_bpf_wq_lockless",
        title="bpf_timer/bpf_wq lockless",
        group="bpf_timer_bpf_wq_lockless",
        status=graft_result["status"],
        phase=graft_result["phase"],
        risk=graft_result["risk"],
        summary="This batch only tightens helper-side async start/cancel routing; verifier, BTF, syscall, and broader core rewrites remain out of scope.",
        dependency_type="bpf_helper_verifier_core",
        helper_graft_candidate=graft_result["helper_graft_candidate"],
        executable=graft_result["executable"],
        scope_expansion_required=graft_result["scope_expansion_required"],
        blocked_by_layout=False,
        blocked_by_missing_anchor=graft_result["status"] == STATUS_BLOCKED_BY_MISSING_ANCHOR,
        blocked_by_scope=True,
        target_presence=collect_presence(common_root, target),
        reference_presence=collect_presence(ref_root, ref),
        stable_anchors=stable,
        missing_anchors=missing,
        constraints=[
            "Do not widen phase2 into verifier/core infra rewrite.",
            "Keep all follow-up inside kernel/bpf/helpers.c helper-side routing.",
            "Do not claim full lockless parity from helper-side tightening alone.",
        ],
        notes=[
            "This batch only becomes partial when both bpf_wq and async-cancel surfaces already exist.",
            f"Marker: {graft_result['marker']}",
        ],
        follow_up_batch="dedicated_bpf_async_batch",
    )


def build_report(
    current_common: Path,
    output_dir: Path,
    items: list[dict[str, object]],
) -> dict[str, object]:
    counts: dict[str, int] = {}
    executable_keys: list[str] = []
    scope_expansion_keys: list[str] = []
    for item in items:
        status = str(item["status"])
        counts[status] = counts.get(status, 0) + 1
        if item["executable"]:
            executable_keys.append(str(item["key"]))
        if item["scope_expansion_required"]:
            scope_expansion_keys.append(str(item["key"]))

    actual_partial_keys = [
        str(item["key"])
        for item in items
        if item["status"] == STATUS_PARTIAL and not item["executable"]
    ]
    actual_report_first_keys = [
        str(item["key"])
        for item in items
        if item["status"] in (STATUS_REPORT_ONLY, STATUS_BLOCKED_BY_LAYOUT)
    ]
    compat_fallback_keys = [
        str(item["key"])
        for item in items
        if item["status"] in (STATUS_DEFERRED, STATUS_BLOCKED_BY_MISSING_ANCHOR)
    ]

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_common_root": str(current_common),
        "reference_root": str(reference_root()),
        "status": "single_large_batch_structured_convergence",
        "strategy": "single_large_batch_with_layered_landings",
        "phase": "feature_porting_backlog_batch2",
        "allowed_statuses": [
            STATUS_REPORT_ONLY,
            STATUS_PARTIAL,
            STATUS_DEFERRED,
            STATUS_BLOCKED_BY_LAYOUT,
            STATUS_BLOCKED_BY_MISSING_ANCHOR,
            STATUS_BLOCKED_BY_SCOPE,
        ],
        "batch_items": [
            "tcp_socket_layout_reduction",
            "ipv6_tcp_output_path",
            "io_uring_cbpf_filters",
            "io_uring_non_circular_sq",
            "io_uring_large_rx_buffer_zcrx",
            "bpf_timer_bpf_wq_lockless",
        ],
        "active_follow_up_items": [
            "io_uring_cbpf_filters",
            "io_uring_non_circular_sq",
        ],
        "planned_batch_layers": {
            "executable": [
                "io_uring_cbpf_filters",
            ],
            "bounded_partial": [
                "io_uring_non_circular_sq",
                "io_uring_large_rx_buffer_zcrx",
                "bpf_timer_bpf_wq_lockless",
            ],
            "report_first": [
                "ipv6_tcp_output_path",
                "tcp_socket_layout_reduction",
            ],
        },
        "batch_layers": {
            "executable": executable_keys,
            "bounded_partial": actual_partial_keys,
            "report_first": actual_report_first_keys,
            "compat_fallback": compat_fallback_keys,
        },
        "patch_groups": [
            {
                "key": group.key,
                "summary": group.summary,
            }
            for group in PATCH_GROUPS
        ],
        "applied_groups": [
            "feature_porting_backlog_batch2",
        ] + executable_keys,
        "deferred_groups": [
            "feature_porting_backlog_fixups",
        ],
        "items": items,
        "status_counts": counts,
        "executable_items": executable_keys,
        "scope_expansion_items": scope_expansion_keys,
        "paused_children": [
            "network_porting",
            "framebuffer_bootlog",
        ],
        "excluded_backlog": [
            "AccECN",
            "false-sharing 消除",
        ],
        "constraints": [
            "Do not modify paused network_porting or framebuffer_bootlog while advancing this phase2 batch.",
            "Do not turn TCP socket slimming into struct sock / struct tcp_sock relayout work here.",
            "Do not resume IPv6 TCP output mainline migration from this batch.",
            "Do not replace io_uring whole files or import new support-module trees wholesale.",
            "Do not widen zcrx into page-pool, netdev, or driver-side rollout here.",
            "Do not widen bpf_timer/bpf_wq follow-ups into verifier/syscall/BTF/core rewrites.",
            "Do not widen into drivers/, boot image, display, or device logsystem work from this child.",
        ],
    }

    write_text(
        output_dir / "feature_porting_backlog_report.json",
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
    )
    write_text(
        output_dir / "feature_porting_backlog_report.md",
        "# ABK Feature Porting Backlog Report\n\n"
        f"- Generated: `{report['generated_at_utc']}`\n"
        f"- Current tree: `{report['current_common_root']}`\n"
        f"- Reference tree: `{report['reference_root']}`\n"
        f"- Status: `{report['status']}`\n"
        f"- Strategy: `{report['strategy']}`\n"
        f"- Phase: `{report['phase']}`\n\n"
        "## Batch Items\n\n"
        + "\n".join(f"- `{item}`" for item in report["batch_items"])
        + "\n\n## Active Follow-up\n\n"
        + "\n".join(f"- `{item}`" for item in report["active_follow_up_items"])
        + "\n\n## Applied Groups\n\n"
        + "\n".join(f"- `{item}`" for item in report["applied_groups"])
        + "\n\n## Deferred Groups\n\n"
        + "\n".join(f"- `{item}`" for item in report["deferred_groups"])
        + "\n\n## Items\n\n"
        + "\n".join(
            f"- `{item['key']}`: `{item['status']}` / `{item['phase']}` / executable=`{item['executable']}` / scope_expansion=`{item['scope_expansion_required']}`"
            for item in items
        )
        + "\n\n## Constraints\n\n"
        + "\n".join(f"- {item}" for item in report["constraints"])
        + "\n"
    )
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit(f"usage: {argv[0]} <current-common-root> <output-dir>")

    current_common = Path(argv[1])
    output_dir = Path(argv[2])
    ref_root = reference_root()
    output_dir.mkdir(parents=True, exist_ok=True)

    for path in (
        current_common / "io_uring/io_uring.c",
        current_common / "io_uring/io_uring.h",
        current_common / "io_uring/kbuf.c",
        current_common / "io_uring/net.c",
        current_common / "io_uring/sqpoll.c",
        current_common / "kernel/bpf/helpers.c",
        current_common / "kernel/bpf/syscall.c",
        current_common / "kernel/bpf/verifier.c",
        current_common / "include/linux/filter.h",
        current_common / "include/uapi/linux/bpf.h",
        current_common / "include/uapi/linux/filter.h",
        current_common / "include/net/sock.h",
        current_common / "include/net/tcp.h",
        current_common / "net/ipv4/tcp_output.c",
        current_common / "net/ipv6/ip6_output.c",
        current_common / "net/ipv6/inet6_connection_sock.c",
    ):
        if not path.exists():
            raise SystemExit(f"feature_porting_backlog: required file not found: {path}")

    if not ref_root.is_dir():
        raise SystemExit(
            f"feature_porting_backlog: 7.0.12 reference tree not found: {ref_root}. "
            "Set ABK_MAINLINE_7012_ROOT or place a linux/ tree at the repo root."
        )
    if not (ref_root / "Makefile").is_file():
        raise SystemExit(
            f"feature_porting_backlog: reference tree is missing Makefile: {ref_root}. "
            "Set ABK_MAINLINE_7012_ROOT to a checked-out 7.0.12-family linux tree."
        )

    cbpf_result = patch_io_uring_cbpf(current_common)
    non_circular_result = patch_non_circular_sq(current_common)
    zcrx_result = patch_zcrx_boundary(current_common)
    bpf_async_result = patch_bpf_timer_wq(current_common)

    items = [
        classify_tcp_socket_layout(current_common, ref_root),
        classify_ipv6_tcp_output(current_common, ref_root),
        classify_io_uring_cbpf(current_common, ref_root, cbpf_result),
        classify_non_circular_sq(current_common, ref_root, non_circular_result),
        classify_zcrx(current_common, ref_root, zcrx_result),
        classify_bpf_timer_wq(current_common, ref_root, bpf_async_result),
    ]
    build_report(current_common, output_dir, items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
