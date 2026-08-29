# ABK ABI Patch Suite

`ABK_ABI_PATCH_SUITE` is a single `module_set` for Android GKI kernels.

Target families:

- `android14-6.1` — the family the suite was written against
- `android13-5.15` — supported as of the 5.15 support line; capabilities whose
  target types or files arrived after 5.15 degrade to report-only rather than
  failing the build. Since the Aug-2025 Al Viro fdtable refactor backport
  (around SUBLEVEL 190 on `android13-5.15-lts`), `alloc_fdtable()` uses the
  upstream slot-count/`ERR_PTR()` shape; `fd_alloc_hotpath` treats that shape as
  already upstream and only lands the `expand_files()`/`alloc_fd()` helper
  prechecks.

The suite reads `ABK_BUILD_ANDROID_VERSION` / `ABK_BUILD_KERNEL_VERSION` /
`ABK_BUILD_SUB_LEVEL`, which ABK exports at both module stages, and falls back
to the tree's own `Makefile` outside ABK CI.

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

Stamps boot-image metadata (`os_version`/`os_patch_level` in build_utils.sh and
the GKI SPL date) to 16.0.0 / 2026-06. It deliberately does NOT rewrite the
kernel's runtime release interfaces (`uname()`, `/proc/sys/kernel/osrelease`,
`/proc/version`): on android13-5.15 that made Android's vold parse the spoofed
release as 7.0 and take the fscrypt hardware-wrapped-key path, which the 5.15
fscrypt rejects, so `cryptfs enablefilecrypto` failed and init rebooted into
recovery (`enablefilecrypto_failed`). f2fs-tools also reads `/proc/version`, so
the text layer is left real too. The real UTS release suffix, vermagic and
every other ABI-sensitive build input stay intact.

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
set:https://github.com/fanziyun/ABK_ABI_PATCH_SUITE.git#display_release_spoof;after_patch
set:https://github.com/fanziyun/ABK_ABI_PATCH_SUITE.git#abi_bridge;after_patch
set:https://github.com/fanziyun/ABK_ABI_PATCH_SUITE.git#security_backport;after_patch
set:https://github.com/fanziyun/ABK_ABI_PATCH_SUITE.git#feature_porting_core;after_patch
set:https://github.com/fanziyun/ABK_ABI_PATCH_SUITE.git#feature_porting_backlog;after_patch
```

If no child id is provided, the module set still defaults to `display_release_spoof`.

Paused child ids are intentionally not injectable from the public catalog.

## Local Verification

Static checks:

```bash
python3 -m py_compile ABK_ABI_PATCH_SUITE/scripts/*.py
bash -n ABK_ABI_PATCH_SUITE/setup.sh ABK_ABI_PATCH_SUITE/scripts/*.sh ABK_ABI_PATCH_SUITE/tests/smoke.sh
```

Unit tests:

```bash
python3 ABK_ABI_PATCH_SUITE/tests/feature_porting_regression_test.py
python3 ABK_ABI_PATCH_SUITE/tests/android13_5_15_test.py
```

The first covers the android14-6.1 fixtures; the second covers the
android13-5.15 branches, including that the shape-rewriting helpers stay
disarmed on a 6.1 tree.

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
set:https://github.com/fanziyun/ABK_ABI_PATCH_SUITE.git#<child>;after_patch
```

Inside `abk` CI, `setup.sh` now adapts to that environment directly:

- reads `GITHUB_WORKSPACE`, `KERNEL_ROOT`, `DEFCONFIG`, and `CUSTOM_EXTERNAL_MODULE_STAGE`
- auto-prepares the 7.0.12 reference tree under `$GITHUB_WORKSPACE/reference/linux` when needed
- exports `ABK_MAINLINE_7012_ROOT` for the Python child scripts

Default auto-clone source:

- repo: `https://github.com/archlinux/linux`
- ref: `v7.0.12-arch1`

## Docs

- [PROGRESS.md](./PROGRESS.md)
- [test.md](./test.md)
- [public.md](./public.md)
- [plan.md](./plan.md)
- [bridge_samples.md](./docs/bridge_samples.md)
- [security_backport_sources.md](./docs/security_backport_sources.md)
- [feature_porting_eevdf_pid.md](./docs/feature_porting_eevdf_pid.md)
