# ABK ABI Patch Suite

`ABK_ABI_PATCH_SUITE` is a single `module_set` for Android 14 / Linux 6.1.118 kernels.

Public child ids:

- `display_release_spoof`
- `abi_bridge`
- `security_backport`
- `feature_porting_core`
- `feature_porting_backlog`

Paused implementations:

- `network_porting`
- `framebuffer_bootlog`

Those paused lines remain in-tree, but they are no longer exposed through `module.conf` and should not be injected from the default catalog.

## Child Map

### `display_release_spoof`

Spoofs visible kernel release strings to `7.0.12` while preserving ABI-sensitive build inputs and localversion suffixes. It also keeps the build-utils boot-image logging slot.

Default output:

- modifies the target source tree in place

### `abi_bridge`

Combines the old bridge and fixup lines into one capability-domain child.

It does three things in one run:

- generates the 7.0.12-family bridge report
- applies the first loader bridge policy layer
- applies the loader-adjacent ABI fixup baseline

Default output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/abi_bridge/bridge_report.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/abi_bridge/bridge_report.json`

Relevant env:

- `ABK_MAINLINE_7012_ROOT`
- `ABK_ABI_BRIDGE_REPORT_DIR`
- `ABK_ABI_BRIDGE_POLICY`

Legacy child ids now rejected:

- `dual_abi_kmi_bridge` -> `abi_bridge`
- `abi_fixups` -> `abi_bridge`

### `security_backport`

Applies the current low-risk security batch and exports the backlog report.

Default output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/security_backport/security_backport_queue.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/security_backport/security_backport_queue.json`

Relevant env:

- `ABK_SECURITY_BACKPORT_REPORT_DIR`

Legacy child id now rejected:

- `security_update_backport` -> `security_backport`

### `feature_porting_core`

Carries the active bounded feature migration line.

Default output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/feature_porting_core/feature_porting_report.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/feature_porting_core/feature_porting_report.json`

Relevant env:

- `ABK_MAINLINE_7012_ROOT`
- `ABK_FEATURE_PORTING_REPORT_DIR`

Legacy child id now rejected:

- `feature_porting` -> `feature_porting_core`

### `feature_porting_backlog`

Carries the remaining non-paused backlog as a report-first line with bounded helper grafts.

Default output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/feature_porting_backlog/feature_porting_backlog_report.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/feature_porting_backlog/feature_porting_backlog_report.json`

Relevant env:

- `ABK_MAINLINE_7012_ROOT`
- `ABK_FEATURE_PORTING_PHASE2_REPORT_DIR`

Legacy child id now rejected:

- `feature_porting_phase2` -> `feature_porting_backlog`

## Reference Tree Rules

7.0.12 reference source lookup is intentionally narrow:

1. `ABK_MAINLINE_7012_ROOT`
2. repo-local `./linux`
3. when running inside `abk` GitHub Actions, auto-cloned `$GITHUB_WORKSPACE/reference/linux`

No script should fall back to a developer-machine absolute path.

When running inside `abk` CI and no reference tree is present yet, the module will shallow-clone it automatically.

Optional clone-control env:

- `ABK_MAINLINE_7012_REPO`
- `ABK_MAINLINE_7012_REF`

## Usage

Remote injection examples:

```text
set:https://github.com/xingguangcuican6666/ABK_ABI_PATCH_SUITE.git#display_release_spoof;after_patch
set:https://github.com/xingguangcuican6666/ABK_ABI_PATCH_SUITE.git#abi_bridge;after_patch
set:https://github.com/xingguangcuican6666/ABK_ABI_PATCH_SUITE.git#security_backport;after_patch
set:https://github.com/xingguangcuican6666/ABK_ABI_PATCH_SUITE.git#feature_porting_core;after_patch
set:https://github.com/xingguangcuican6666/ABK_ABI_PATCH_SUITE.git#feature_porting_backlog;after_patch
```

If no child id is provided, the module set still defaults to `display_release_spoof`.

Paused child ids are intentionally not injectable from the public catalog.

## Local Verification

Static checks:

```bash
python3 -m py_compile ABK_ABI_PATCH_SUITE/scripts/*.py
bash -n ABK_ABI_PATCH_SUITE/setup.sh ABK_ABI_PATCH_SUITE/scripts/*.sh ABK_ABI_PATCH_SUITE/tests/smoke.sh
```

Smoke:

```bash
bash ABK_ABI_PATCH_SUITE/tests/smoke.sh /path/to/kernel/common
```

Bridge test module:

```bash
bash ABK_ABI_PATCH_SUITE/tests/build_bridge_test_ko.sh "$ABK_MAINLINE_7012_ROOT"
```

## ABK CI

This module set is intended to be injected by `abk` kernel build workflows through:

```text
set:https://github.com/xingguangcuican6666/ABK_ABI_PATCH_SUITE.git#<child>;after_patch
```

Inside `abk` CI, `setup.sh` now adapts to that environment directly:

- reads `GITHUB_WORKSPACE`, `KERNEL_ROOT`, `DEFCONFIG`, and `CUSTOM_EXTERNAL_MODULE_STAGE`
- auto-prepares the 7.0.12 reference tree under `$GITHUB_WORKSPACE/reference/linux` when needed
- exports `ABK_MAINLINE_7012_ROOT` for the Python child scripts

Default auto-clone source:

- repo: `https://github.com/archlinux/linux`
- ref: `build-v7.0.12`

## Docs

- [PROGRESS.md](./PROGRESS.md)
- [test.md](./test.md)
- [public.md](./public.md)
- [plan.md](./plan.md)
- [bridge_samples.md](./docs/bridge_samples.md)
- [security_backport_sources.md](./docs/security_backport_sources.md)
- [feature_porting_eevdf_pid.md](./docs/feature_porting_eevdf_pid.md)
