# Feature Porting: EEVDF And PID Allocation

## Strategy

This child uses a minimal-intrusion graft strategy instead of replaying full
`7.0.12-arch1` scheduler or PID files onto the Android `6.1.118` base.

The goal is to:

- preserve the local `6.1.118` baseline and existing vendor deltas
- keep `ABK_SCHED_POWER_MODULE` as a first-class compatibility target
- port low-risk EEVDF and PID allocation semantics in small batches
- leave large `fair.c` and `fork.c` rewrites out of phase one

## Phase One Scope

Applied in the executable `feature_porting` child:

- `sched_eevdf_core_fields`
  - map first-stage EEVDF fields onto Android KABI reserve slots in `struct sched_entity`
  - fields covered:
    - `deadline`
    - `min_vruntime`
    - `min_slice`
    - `max_slice`
    - `vlag`
    - `slice`
- `pid_alloc_core_port`
  - update `alloc_pid()` to use per-namespace `pid_max`
  - translate `idr_alloc_cyclic()` `-ENOSPC` to `-EAGAIN`
  - retry `idr_preload(GFP_KERNEL)` once after `GFP_ATOMIC` `-ENOMEM`

Not applied in phase one:

- full `avg_vruntime` and `pick_eevdf()` migration
- whole-file `fair.c` replacement
- whole-file `fork.c` replacement
- full pidfs backport
- full `pidfd_prepare()` / stale-pidfd flow
- sched-ext, tracing-only, or documentation-only bulk backports

## ABK_SCHED_POWER_MODULE Boundary

`ABK_SCHED_POWER_MODULE` already modifies:

- `kernel/sched/fair.c`
- `kernel/sched/cpufreq_schedutil.c`
- thermal and devfreq paths

Because of that:

- `feature_porting` does not overwrite `fair.c`
- scheduler follow-up work must target existing hooks and anchors
- compatibility work should attach to:
  - `util_est_*`
  - `trace_android_rvh_pick_next_entity`
  - sugov util scaling
  - thermal override hooks

## PID Boundary

PID allocation optimization belongs to `feature_porting`, not
`dual_abi_kmi_bridge`.

If later PID migration introduces ABI glue needs:

- keep the main port here
- move only narrow compatibility glue into `abi_fixups`

## Patch Series Shape

Planned series order:

1. `feature_porting_scaffold`
2. `sched_eevdf_core_fields`
3. `sched_eevdf_pick_logic`
4. `sched_eevdf_abk_sched_compat`
5. `pid_alloc_core_port`
6. `pidfd_preparation_compat`
7. `feature_porting_fixups`

## Constraints

- Do not treat this as a fair.c file swap.
- Do not treat this as a fork.c file swap.
- Do not hide PID feature work inside bridge or fixup children.
- Do not claim pidfs is backported when only alloc_pid semantics were ported.
