# ABK ABI Patch Suite

ABK external module set for Android 14 / Linux 6.1.118 kernels that groups:

- display-only `7.0.12` release spoofing
- dual-stack `6.1.118` / `7.0.12` ABI and KMI bridge work
- ABI fixups
- security update backports
- feature porting

This repository is a `module_set`. The previous single-purpose display spoof
module has been absorbed as the `display_release_spoof` child.

## Current Status

Implemented:

- `display_release_spoof`
- `dual_abi_kmi_bridge` preflight/report generation
- `dual_abi_kmi_bridge` first-pass loader bridge
- `abi_fixups` minimum executable child
- `security_update_backport` queue/export child
- `feature_porting`

## Child Behavior

### `display_release_spoof`

Changes common kernel version display endpoints to `7.0.12` while preserving:

- the real compiled `UTS_RELEASE` suffix
- `vermagic`
- generated `utsrelease.h`
- other ABI-sensitive build inputs

After rebuild:

- `uname -r` returns `7.0.12` plus the original localversion suffix
- `/proc/sys/kernel/osrelease` returns `7.0.12` plus the original localversion suffix
- `/proc/version` shows `Linux version 7.0.12...` plus the original localversion suffix

### `dual_abi_kmi_bridge`

Generates a bridge input report for the current `6.1.118` tree and a
`7.0.12`-family reference tree. The report samples:

- `same_magic()` behavior
- `module_layout` checks
- `CONFIG_MODVERSIONS` state
- `VERMAGIC_STRING` macro shape
- `Module.symvers` / `vmlinux.symvers` availability
- source-level block equality for bridge-sensitive loader code

It then applies a first-pass loader bridge on top of the current tree:

- allowlist-based `vermagic` acceptance for `7.0.12`-family modules
- allowlist-based `module_layout` bypass when the bridge is enabled
- allowlist-based symbol CRC mismatch bypass with explicit warnings

Default policy is `allowlist`.
Current built-in allowlist is name-prefix based and targets:

- `kernelsu`
- `sukisu`
- `resukisu`
- `ksu`

Experimental broad mode is available via:

- `ABK_ABI_BRIDGE_POLICY=experimental`

Experimental mode enables the same bridge behavior for all modules and appends
`[experimental]` to bridge warnings.

Default report output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/dual_abi_kmi_bridge/bridge_report.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/dual_abi_kmi_bridge/bridge_report.json`

Optional environment overrides:

- `ABK_MAINLINE_7012_ROOT`
- `ABK_ABI_BRIDGE_REPORT_DIR`
- `ABK_ABI_BRIDGE_POLICY`

### `abi_fixups`

Provides the first executable compat-glue layer for bridge-related fixes. The
current version only applies a baseline marker after confirming bridge hooks
are present, so later fixup batches can detect that the bridge glue phase
already ran.

### `security_update_backport`

Exports the first formal security queue and binds this child to the documented
security source ledger.

Default output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/security_update_backport/security_backport_queue.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/security_update_backport/security_backport_queue.json`

Optional environment overrides:

- `ABK_SECURITY_BACKPORT_REPORT_DIR`

### `feature_porting`

Provides the first executable feature migration entry for the `6.1.118` target
tree while keeping `7.0.12` as a reference source.

Phase one behavior:

- ports first-stage EEVDF `sched_entity` fields through Android KABI slots
- ports `alloc_pid()` preload/retry and per-namespace `pid_max` semantics
- exports a feature-porting report with sched/pid anchor status
- defers large `fair.c` pick logic and full pidfd/pidfs work

Default output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/feature_porting/feature_porting_report.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/feature_porting/feature_porting_report.json`

Optional environment overrides:

- `ABK_MAINLINE_7012_ROOT`
- `ABK_FEATURE_PORTING_REPORT_DIR`

## Docs

- [PROGRESS.md](/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE/PROGRESS.md:1)
- [bridge_samples.md](/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE/docs/bridge_samples.md:1)
- [security_backport_sources.md](/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE/docs/security_backport_sources.md:1)
- [feature_porting_eevdf_pid.md](/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE/docs/feature_porting_eevdf_pid.md:1)

## Test KO

Minimal test module source:

- [abk_bridge_test.c](/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE/tests/ko/abk_bridge_test.c:1)
- [Makefile](/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE/tests/ko/Makefile:1)

Build helper:

```bash
bash ABK_ABI_PATCH_SUITE/tests/build_bridge_test_ko.sh /run/media/xingguangcuican/Project/testa/linux
```

## Usage

Display spoof:

```text
set:/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE#display_release_spoof;after_patch
```

Bridge:

```text
set:/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE#dual_abi_kmi_bridge;after_patch
```

Fixups:

```text
set:/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE#abi_fixups;after_patch
```

Security queue:

```text
set:/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE#security_update_backport;after_patch
```

Feature porting:

```text
set:/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE#feature_porting;after_patch
```

If the suite is added without a child id, it currently defaults to applying
only `display_release_spoof`.

## Layout

```text
.
|-- module.conf
|-- setup.sh
|-- docs/
|   |-- bridge_samples.md
|   `-- security_backport_sources.md
|-- scripts/
|   |-- abi_patch_suite.sh
|   |-- abk_display_spoof.py
|   |-- abk_dual_abi_bridge_apply.py
|   |-- abk_dual_abi_bridge_report.py
|   |-- abk_abi_fixups.py
|   |-- abk_security_update_backport.py
|   |-- abk_feature_porting.py
|   `-- libabk.sh
|-- files/
|   `-- README.md
|-- patches/
|   `-- README.md
`-- tests/
    `-- smoke.sh
```

## Verification

Run:

```bash
bash tests/smoke.sh /run/media/xingguangcuican/Project/kernelexp/new_test/.local-build/workspace/kernel/common
```

That validates shell syntax, checks the implemented display child remains
idempotent, verifies bridge report generation, confirms the minimum
`abi_fixups`, `security_update_backport`, and `feature_porting` children
execute successfully.
