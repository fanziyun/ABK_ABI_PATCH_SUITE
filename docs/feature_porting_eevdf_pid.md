# Feature Porting: EEVDF And PID Allocation

## Strategy

This child uses a minimal-intrusion graft strategy instead of replaying full
`7.0.12-arch1` scheduler or PID files onto the Android `6.1.118` base.

The current goal is to:

- preserve the local `6.1.118` baseline and existing vendor deltas
- deepen only the scan-based EEVDF runtime state machine
- keep `ABK_SCHED_POWER_MODULE` and later PID follow-up work out of this batch
- leave whole-file `fair.c` and `fork.c` rewrites out of scope

## Current Scope

Applied in the executable `feature_porting` child:

- `sched_eevdf_core_fields`
  - map first-stage EEVDF fields onto Android KABI reserve slots in `struct sched_entity`
  - fields covered:
    - `deadline`
    - `min_vruntime`
    - `vlag`
    - `slice`
- `sched_eevdf_pick_logic`
  - keep the existing scan-based EEVDF selector on top of the legacy `6.1` rb-tree layout
  - route `pick_next_entity()` into `abk_pick_eevdf()` without rewriting tree order
  - keep the scan-based selector separate from the phase-3 runtime-state closure
- `sched_eevdf_runtime_state_phase3`
  - keep the runtime-state line scan-based and explicitly reject `cfs_rq` augmentation in this batch
  - cover:
    - preserved-lag placement
    - relative-deadline save and restore
    - `reweight_entity()` lag and deadline scaling for both current and non-current paths
    - `dequeue_entity()` sleep vs non-sleep lag/deadline handling
    - `entity_tick()` deadline refresh through a unified slice-lifecycle path
    - `put_prev_entity()` and `set_next_entity()` deadline/lag refresh boundaries
  - if delayed-dequeue parity cannot be expressed without augmentation:
    - report `delayed_path_deferred`
    - do not force a fake delayed lifecycle into the tree
- `pid_alloc_hotpath_phase2`
  - translate `idr_alloc_cyclic()` `-ENOSPC` to `-EAGAIN`
  - retry `idr_preload(GFP_KERNEL)` once after `GFP_ATOMIC` `-ENOMEM`
  - keep the port within the existing `6.1` `struct pid_namespace` shape
  - explicitly do not force per-namespace `pid_max` onto a tree that lacks that field
- `fd_alloc_hotpath`
  - graft lock-before-allocate helper logic into `fs/file.c`
  - keep `files_struct` / `fdtable` layout unchanged
  - avoid unconditional expand calls once the free fd is already known
- `close_range_hotpath`
  - switch range close traversal to bitmap-driven batching
  - keep syscall-visible `close_range()` semantics unchanged
  - preserve `close_fd_get_file()` / `__close_fd_get_file()` callers
- `blk_mq_async_depth`
  - port `q->async_depth` queue-depth policy into the 6.1 block tree as a real graft
  - keep the validation model to build/injection plus source-anchor checks
  - confirm `blk_mq_limit_depth()`, `queue_async_depth_store()`, and the scheduler hooks stay aligned

## Phase Boundary

`phase 3 = scan-based runtime-state closure, not tree rewrite`

The current implementation is intentionally still a scan-based EEVDF phase:

- `pick_next_entity()` routes into `abk_pick_eevdf()`
- the legacy `rb_root_cached` ordering is preserved
- no augmented-tree state is added to `struct cfs_rq`
- `reweight_entity()`, `place_entity()`, `set_next_entity()`, `put_prev_entity()`, and `entity_tick()` share one scan-based deadline/lag lifecycle

This batch does not attempt:

- whole-file `fair.c` replacement
- whole-file `fork.c` replacement
- full upstream `pick_eevdf()` heap-pruning traversal
- full delayed-dequeue feature backport when it would require augmentation
- full pidfs backport
- storage-wide queue policy rewrites
- `ABK_SCHED_POWER_MODULE` integration
- mixing the PID follow-up line into the immediate EEVDF next step

## Tree Escalation Gate

Do not introduce tree augmentation by default.

Escalate only if one of these becomes true:

- scan-based selection can no longer preserve lag or relative deadlines correctly
- `reweight_entity()` and dequeue paths cannot be expressed without aggregated `cfs_rq` state
- repeated full-rq scans in `avg_vruntime()` or pick logic become the actual blocker
- `pick_next_entity()` behavior diverges in ways the preserved scan model cannot contain
- delayed-dequeue parity becomes mandatory but cannot be expressed without augmentation

If escalation becomes necessary, the next batch should explicitly add:

- `cfs_rq->sum_weight`
- `cfs_rq->sum_w_vruntime`
- `cfs_rq->zero_vruntime`
- optional `nr_queued` / `min_slice` / `max_slice` if the scan model can no longer carry slice state

## PID Boundary

PID allocation optimization belongs to `feature_porting`, not
`abi_bridge`.

`pidfd_preparation_compat` also belongs to `feature_porting`, but only as a
helper/report-level compat line.

Current pidfd compat boundary:

- track and report the in-tree pidfd surface:
  - `pidfd_open`
  - `pidfd_getfd`
  - `CLONE_PIDFD`
  - `pidfd_create`
  - `pidfd_fops`
- allow file-local helper grafts or report markers when they do not change syscall-visible behavior
- keep `pidfs_prepare_pid()` and the pidfs object model deferred
- do not claim pidfs has been backported

If later PID migration introduces ABI glue needs:

- keep the main port here
- move only narrow compatibility glue into `abi_bridge`

## Patch Series Shape

Current series order:

1. `feature_porting_scaffold`
2. `sched_eevdf_core_fields`
3. `sched_eevdf_pick_logic`
4. `sched_eevdf_runtime_state_phase3`
5. `pid_alloc_hotpath_phase2`
6. `fd_alloc_hotpath`
7. `close_range_hotpath`
8. `pidfd_preparation_compat`
9. `feature_porting_fixups`

Internal phase-3 execution order for the scheduler line:

1. runtime state
2. slice lifecycle
3. delayed-path escalation check
4. tree-escalation check

## Constraints

- Do not treat this as a `fair.c` file swap.
- Do not treat this as a `fork.c` file swap.
- Do not hide PID feature work inside bridge or fixup children.
- Do not claim pidfs is backported when only alloc_pid semantics were ported.
- Do not describe phase 3 as a tree rewrite; it is a scan-based runtime-state closure pass.
- Do not add `cfs_rq` augmentation just to force delayed-dequeue parity into this batch.
