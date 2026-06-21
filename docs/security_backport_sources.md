# ABK Security Update Backport Sources

## Purpose

Track the fixed `7.0.12-first` security source baseline and the executable
low-risk batch registry for `security_backport`.

## Source Policy

### Primary Reference

- `7.0.12-arch1`
- treated as `7.0.12-first` in reports
- used only for low-risk security fixes that do not widen exported symbol
  surface, KMI-sensitive struct layout, or bridge policy scope

### Acceptance Rules

- do not mix feature ports into security batches
- do not land bridge glue in this child
- do not land runtime ABI fixups in this child
- allow only:
  - `guard tightening`
  - `in-function fixup`
  - `scoped helper graft`
- do not use whole-file replacement
- mark any candidate that touches loader policy, shared module ABI, or broader
  bridge/fixup coordination as blocked instead of force-applying it

## Batch Registry

| Batch | Source Base | Status Shape | Notes |
| --- | --- | --- | --- |
| `sec_lowrisk_batch_001` | `7.0.12-first` | `applied` or `partial` | first executable low-risk batch; only the sysctl marker is expected to land by default |
| `sec_lowrisk_batch_002` | `7.0.12-first` | `applied`, `blocked_by_bridge`, `blocked_by_fixups`, or `missing_anchor` | wider follow-up function-level candidates kept inside the same low-risk boundary |

## Current Fixed Candidates

| Candidate | Batch | Apply Mode | Default Outcome | Notes |
| --- | --- | --- | --- | --- |
| `sysctl_modules_disabled_minmax_guard` | `sec_lowrisk_batch_001` | `guard tightening` | `applied` | keeps `/proc/sys/kernel/modules_disabled` write-once at the sysctl boundary |
| `blk_sync_queue_timer_delete_sync` | `sec_lowrisk_batch_001` | `guard tightening` | `blocked_by_fixups` | blocked until a real `blk-core`-safe helper exists for this tree |
| `pid_deferred_free_batching` | `sec_lowrisk_batch_002` | `in-function fixup` | `blocked_by_fixups` | blocked because the widened pid signature breaks current callers in the reset build tree |
| `elevator_sysfs_dying_guard` | `sec_lowrisk_batch_002` | `guard tightening` | `blocked_by_fixups` | depends on broader elevator teardown shape and should not be forced in the security child |
| `module_extended_version_checks` | `sec_lowrisk_batch_002` | `scoped helper graft` | `blocked_by_bridge` | touches loader-version validation and stays outside this batch until bridge coordination is explicit |
