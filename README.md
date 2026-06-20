# ABK ABI Patch Suite

ABK external module set for Android 14 / Linux 6.1.118 kernels that groups:

- display-only `7.0.12` release spoofing
- dual-stack `6.1.118` / `7.0.12` ABI and KMI bridge work
- ABI fixups
- security update backports
- feature porting
- phase-2 feature backlog classification
- network porting

This repository is a `module_set`. The previous single-purpose display spoof
module has been absorbed as the `display_release_spoof` child.

## Current Status

Implemented:

- `display_release_spoof`
- `dual_abi_kmi_bridge` preflight/report generation
- `dual_abi_kmi_bridge` first-pass loader bridge
- `abi_fixups` minimum executable child
- `security_update_backport` executable low-risk security backport child
- `feature_porting`
- `feature_porting_phase2`
- `network_porting`
- `framebuffer_bootlog`

## Child Behavior

### `display_release_spoof`

Changes common kernel version display endpoints to `7.0.12` while preserving:

- the real compiled `UTS_RELEASE` suffix
- `vermagic`
- generated `utsrelease.h`
- other ABI-sensitive build inputs
- boot image runtime-facing ABI checks that still key off the real kernel build release

It also injects boot-image packaging metadata for the display line:

- sets `mkbootimg --os_version` to a stable Android release value
- sets `mkbootimg --os_patch_level` so unpack tools report the selected patch month
- adds a minimal early-boot logging slot in `build/kernel/build_utils.sh`
  with default `ignore_loglevel panic=30 oops=panic`
- leaves `console=` / `earlycon=` values configurable through
  `ABK_BOOTLOG_CONSOLE` and `ABK_BOOTLOG_EARLYCON` instead of hardcoding a
  device UART
- preserves the current strategy of spoofing visible release strings without rewriting
  the actual kernel build release used by module ABI checks

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

- global `7.0.12`-family `vermagic` acceptance
- global `7.0.12`-family `module_layout` bypass when the bridge is enabled
- global `7.0.12`-family symbol CRC mismatch bypass with explicit warnings

Default policy is `global_7012`.
Default bridge coverage is all `7.0.12`-family modules, not a name-prefix allowlist.
Representative validation samples currently include:

- `kernelsu`
- `sukisu`
- `resukisu`
- `ksu`

Experimental broad mode is available via:

- `ABK_ABI_BRIDGE_POLICY=experimental`

Experimental mode is a broader override/fallback for all modules and appends
`[experimental]` to bridge warnings. It is not the default path.

Default report output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/dual_abi_kmi_bridge/bridge_report.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/dual_abi_kmi_bridge/bridge_report.json`

Optional environment overrides:

- `ABK_MAINLINE_7012_ROOT`
- `ABK_ABI_BRIDGE_REPORT_DIR`
- `ABK_ABI_BRIDGE_POLICY`

### `abi_fixups`

Provides the first executable compat-glue layer for bridge-related fixes. The
current version now applies a minimal real compat batch after confirming bridge
hooks are present:

- marks global `7.0.12`-family loader compat as active
- keeps the compat glue loader-adjacent
- explicitly defers wider runtime ABI follow-ups

### `security_update_backport`

Applies the first executable low-risk security backport batch while keeping
`7.0.12-arch1` as the fixed source baseline and the documented source ledger as
the batch registry.

Current behavior:

- plans from the fixed `7.0.12-first` source base
- applies `sec_lowrisk_batch_001` directly when anchors match
- pre-registers `sec_lowrisk_batch_002` candidates with explicit
  `blocked_by_bridge`, `blocked_by_fixups`, or `missing_anchor` outcomes
- keeps this line limited to low-risk security fixes and does not absorb
  `feature_porting`, bridge, or ABI-fixup payloads
- exports a real batch report to the existing queue file names so external
  callers do not need to change paths

Default output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/security_update_backport/security_backport_queue.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/security_update_backport/security_backport_queue.json`

Optional environment overrides:

- `ABK_SECURITY_BACKPORT_REPORT_DIR`

### `feature_porting`

Provides the first executable feature migration entry for the `6.1.118` target
tree while keeping `7.0.12` as a reference source.

Current behavior:

- ports first-stage EEVDF `sched_entity` fields through Android KABI slots
- tightens scan-based EEVDF runtime-state into a phase-3 stable boundary without `cfs_rq` augmentation
- ports `alloc_pid()` preload/retry semantics as `pid_alloc_hotpath_phase2`
- ports `fs/file.c` fd allocation helpers as `fd_alloc_hotpath`
- ports bitmap-driven `close_range()` batching as `close_range_hotpath`
- ports `blk-mq async_depth` queue-depth policy as `blk_mq_async_depth`
- tracks `zram compressed writeback` on the existing `kernel/common` zram writeback path
- refines legacy `nohz` / `tick_sched` state fields into helper-backed reportable anchors without widening into `avg_idle`
- simplifies `avg_idle` preemption gating by removing `wake_avg_idle` prediction while keeping the direct `avg_idle` newidle thresholds
- ports `Swap Table Phase II Large folios` as a folio-first swapcache helper split in `mm/swap_state.c` while retaining the legacy page-returning wrappers
- ports `Slab 优化` as a SLUB alloc/free hotpath helper graft in `mm/slub.c` while keeping the public allocator API intact
- ports `io_uring NOWAIT 扩展与新子模块回移` as a core issue-path / fixed-file bookkeeping graft plus rw/net helper fixups and support-module status classification
- runs `pidfd_preparation_compat` as helper/report-level compat only, while keeping pidfs deferred
- exports a feature-porting report with sched/pid anchor status
- exports graft metadata for helper/sidecar/new-interface usage
- current `avg_idle` batch stays separate from `nohz_field_refinement` and only narrows wake-side prediction plus scan gating

Completed backlog items also now include `open/close` hotpath, `close_range()`, `pid` allocation, `blk-mq async_depth`, `zram compressed writeback`, `nohz 字段改进`, and `io_uring NOWAIT 扩展与新子模块回移`.
`false-sharing 消除` is currently treated as plan-out-of-scope until it has a
concrete subsystem target and validation shape.

`zram compressed writeback` stays inside the `feature_porting` boundary:

- `ABK_ABI_PATCH_SUITE` only tracks the `kernel/common` zram writeback control path
- `abk/zram` remains the home for algorithm assets such as LZ4/LZ4HC/NEON and related config work
- the two lines must coexist without whole-file replacement or mutual overwrite

`blk_mq_async_depth` stays inside `feature_porting` as a block queue-depth
policy line:

- it is validated by build/injection and source-anchor checks
- it is not treated as a storage whole-target migration
- device-side sysfs or tracefs observation remains a separate manual step

`nohz_field_refinement` stays inside `feature_porting` as a `kernel/time` +
`include/linux/sched/nohz.h` consistency line:

- it is validated by source-anchor checks and the exported feature report
- it does not widen into `avg_idle`, idle-governor, or scheduler policy rewrites
- device-side idle-entry/exit observation remains a separate manual step

`avg_idle_preemption_mode` stays inside `feature_porting` as a scheduler
threshold simplification line:

- it is validated by source-anchor checks and the exported feature report
- it removes `wake_avg_idle` prediction from the `select_idle_cpu()` scan path
- device-side newidle/idle-path observation remains a separate manual step

`Swap Table Phase II Large folios` stays inside `feature_porting` as a swapcache
helper split:

- it centers on `mm/swap_state.c` and keeps the public page-returning wrappers for now
- it does not expand into reclaim, compaction, zswap, memcg reclaim, or a full shmem rewrite
- device-side swapin and `/proc/vmstat` observation remains a separate manual step

`Slab 优化` stays inside `feature_porting` as a SLUB hotpath helper graft:

- it centers on `mm/slub.c` and keeps the allocator public surface unchanged
- it does not widen into a full sheaf/barn structural port in this batch
- device-side alloc/free observation remains a separate manual step

`io_uring NOWAIT 扩展与新子模块回移` stays inside `feature_porting` as an
`io_uring/` helper-graft + classification line:

- it keeps `io_uring.c` / `rw.c` / `net.c` / `poll.c` / `openclose.c` on local grafts instead of whole-file replacement
- it upgrades report output with `io_uring_nowait_core`, `io_uring_nowait_rw_net`, and `io_uring_support_modules` status
- it classifies new support modules before any broad import and leaves large follow-up module moves to later batches

Default output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/feature_porting/feature_porting_report.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/feature_porting/feature_porting_report.json`

Optional environment overrides:

- `ABK_MAINLINE_7012_ROOT`
- `ABK_FEATURE_PORTING_REPORT_DIR`

### `feature_porting_phase2`

Carries the remaining non-paused backlog that does not belong to the paused
`network_porting` or `framebuffer_bootlog` lines.

Current behavior:

- exports a standalone `feature_porting_phase2_report.md/json` pair
- carries a fixed 6-item single large batch:
  `TCP socket 结构体瘦身`, `IPv6 TCP 输出路径`,
  `cBPF filters for io_uring`, `Non-circular SQ`,
  `Large RX buffer support（zcrx）`, and `bpf_timer/bpf_wq 无锁化`
- currently treats `cBPF filters for io_uring` plus `Non-circular SQ` as the
  active follow-up pair inside that larger batch
- uses layered landing strength inside that batch instead of forcing all items
  to the same execution level
- treats `cBPF filters for io_uring` as the bounded executable item in the
  batch when existing io_uring support-module wiring is present
- leaves `TCP socket 结构体瘦身` blocked by layout rather than widening into a
  `struct sock` / `struct tcp_sock` relayout project
- leaves `IPv6 TCP 输出路径` report-only so this child does not become a second
  `network_porting`
- leaves `Non-circular SQ`, `zcrx`, and `bpf_timer/bpf_wq 无锁化` on bounded
  partial landings only, with broader semantic or subsystem work deferred
- on older 6.1 trees, missing support-module or `NO_SQARRAY` anchors downgrade
  these items to `blocked_by_missing_anchor` / `deferred` instead of failing

This child keeps the following scope boundary:

- allowed: report generation, source-anchor classification, and bounded
  single-file/helper grafts when the target anchors are already stable
- not allowed: reviving paused `network_porting` or `framebuffer_bootlog`
- not allowed: `struct sock` / `struct tcp_sock` relayout work
- not allowed: whole-file `io_uring` replacement or broad support-module import
- not allowed: broad BPF verifier/core rewrites
- not allowed: `drivers/`, display, boot image, or device logsystem expansion

Default output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/feature_porting_phase2/feature_porting_phase2_report.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/feature_porting_phase2/feature_porting_phase2_report.json`

Optional environment overrides:

- `ABK_MAINLINE_7012_ROOT`
- `ABK_FEATURE_PORTING_PHASE2_REPORT_DIR`

### `network_porting`

Provides the first executable network migration entry for the `6.1.118` target
tree while keeping `7.0.12` as a reference source and keeping this batch
strictly inside `net/` + `include/net/`.

Current behavior:

- ports the socket/TCP timestamp semantic main path, including receive-side
  filter gating and completion-tstamp bookkeeping, without widening into
  `drivers/net/` or PHY/MAC hwtstamp providers
- ports the IPv6 flow/cache hotpath main path around `flowi6`,
  autoflowlabel, cork flow state, and socket dst-cookie reuse
- keeps AccECN at a conservative helper/report/fixup baseline: bounded mode
  helpers, sysctl/report state, and child/openreq/syncookie glue remain, while
  `tcp_output.c` / `tcp_input.c` / `tcp_timer.c` / `tcp.c` mainline AccECN
  semantics stay deferred to improve boot compatibility
- exposes a minimal boot-image logging slot through
  `build/kernel/build_utils.sh`: default `ignore_loglevel panic=30
  oops=panic`, optional `ABK_BOOTLOG_CONSOLE`, optional
  `ABK_BOOTLOG_EARLYCON`, and optional `ABK_VENDOR_BOOTCONFIG_PARAMS`
- classifies driver/GSO/offload dependent network follow-ups in the report
  instead of hiding them behind an `applied` status

This child keeps the first-pass runtime scope boundary:

- allowed: `net/`, `include/net/`
- not allowed: `drivers/net/`
- build-time exception: `build/kernel/build_utils.sh` for the logging slot only
- not included: PHY/MAC hwtstamp providers, ethtool provider adaptation,
  and driver feature-bit/offload work

Default output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/network_porting/network_porting_report.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/network_porting/network_porting_report.json`

Optional environment overrides:

- `ABK_MAINLINE_7012_ROOT`
- `ABK_NETWORK_PORTING_REPORT_DIR`
- `ABK_BOOT_IMAGE_LOGGING_ARGS`
- `ABK_BOOTLOG_CONSOLE`
- `ABK_BOOTLOG_EARLYCON`
- `ABK_VENDOR_BOOTCONFIG_PARAMS`
- `ABK_GKI_BOOT_IMAGE_LOGGING_ARGS`
- `ABK_GKI_BOOTLOG_CONSOLE`
- `ABK_GKI_BOOTLOG_EARLYCON`

If you do not have the device-specific serial parameters yet, leave
`ABK_BOOTLOG_CONSOLE` and `ABK_BOOTLOG_EARLYCON` unset and use only the
generic cmdline defaults first.

### `framebuffer_bootlog`

Provides a lightweight framebuffer-console boot logging child for the current
Android/Linux boot chain without importing a UEFI display stack.

Current behavior:

- enables a conservative set of `DEFCONFIG` symbols that make `tty0` +
  `fbcon` handoff possible on trees that already have a working display path:
  `VT`, `VT_CONSOLE`, `DUMMY_CONSOLE`, `FB`, `FRAMEBUFFER_CONSOLE`,
  `DRM_KMS_HELPER`, and `DRM_FBDEV_EMULATION`
- strips `console=ttynull` from an existing `CONFIG_CMDLINE` baseline when
  the selected defconfig already bakes it in, so the child does not rely only
  on later cmdline append points
- injects a framebuffer-oriented cmdline slot in
  `build/kernel/build_utils.sh` with the default arguments
  `console=tty0 fbcon=nodefer vt.global_cursor_default=0 logo.nologo printk.time=1`
- mirrors the framebuffer bootlog args into `boot --cmdline` by default and
  still appends them to `vendor_cmdline` for header-v3/v4 packing paths, so
  the child is not limited to `vendor_boot`-only delivery
- keeps the existing generic panic/loglevel enhancement path compatible with
  this child instead of replacing it
- exports a report describing the expected cmdline shape and the known
  limitations

This child keeps a stricter scope boundary than `network_porting`:

- allowed: `DEFCONFIG`, `build/kernel/build_utils.sh`
- not allowed: `drivers/gpu/`, `drivers/video/`, `drivers/tty/`
- not included: UEFI `BootShim`, firmware framebuffer loggers, or vendor DRM
  driver rewrites

Known limitations:

- if the runtime cmdline is overridden again after packing, `tty0` output may
  still remain hidden or secondary
- this child does not add `earlycon` or device-private UART values
- this child does not guarantee the earliest possible pre-DRM output; it only
  makes framebuffer console takeover more likely once the in-kernel display
  path reaches `fbcon`
- do not use `video=vfb` as the default screen-log path here; `vfb` is a
  virtual test framebuffer and not the device panel's real display path

Default output:

- `$KERNEL_ROOT/abk_abi_patch_suite_reports/framebuffer_bootlog/framebuffer_bootlog_report.md`
- `$KERNEL_ROOT/abk_abi_patch_suite_reports/framebuffer_bootlog/framebuffer_bootlog_report.json`

Optional environment overrides:

- `ABK_FRAMEBUFFER_BOOTLOG_REPORT_DIR`
- `ABK_FB_BOOTLOG_ARGS`
- `ABK_FB_BOOTLOG_EXTRA_ARGS`
- `ABK_FB_BOOTLOG_APPLY_TO_BOOT_CMDLINE`
- `ABK_FB_BOOTLOG_STRIP_TTYNULL`
- `ABK_FB_BOOTLOG_BOOTCONFIG_PARAMS`
- `ABK_GKI_FB_BOOTLOG_ARGS`
- `ABK_GKI_FB_BOOTLOG_EXTRA_ARGS`
- `ABK_GKI_FB_BOOTLOG_STRIP_TTYNULL`

### Archived storage experiment

`storage_whole_target` was prototyped as an experimental storage/F2FS line and
is now treated as plan-out-of-scope.

- The child is not part of the current supported module set.
- The implementation file remains in-tree as an archive artifact.
- Do not treat it as a current validation path.

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

Security backport:

```text
set:/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE#security_update_backport;after_patch
```

Feature porting:

```text
set:/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE#feature_porting;after_patch
```

Feature porting phase 2:

```text
set:/run/media/xingguangcuican/Project/testa/ABK_ABI_PATCH_SUITE#feature_porting_phase2;after_patch
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
|   |-- abk_feature_porting_phase2.py
|   `-- libabk.sh
|-- files/
|   `-- README.md
|-- patches/
|   `-- README.md
`-- tests/
    `-- smoke.sh
```

## Verification

Current built-in verification is `build/injection verification`, not
`device runtime verification`.

It proves:

- the child can enter the module chain
- expected source markers or report files are emitted
- shell/python wiring is valid
- selected target objects can pass source-level or compile-level checks

It does not prove:

- the logic is active on a booted device
- the feature is observable through runtime behavior
- performance, latency, power, or scheduling effects are acceptable on hardware

Run:

```bash
bash tests/smoke.sh /run/media/xingguangcuican/Project/kernelexp/new_test/.local-build/workspace/kernel/common
```

That validates shell syntax, checks the implemented display child remains
idempotent, verifies bridge report generation, confirms the minimum
`abi_fixups`, `security_update_backport`, `feature_porting`, and
`feature_porting_phase2` children
execute successfully.

If you need runtime proof, add a separate device-side validation path:

- `adb shell` probes
- `dmesg` / `tracefs` / `sysfs` observations
- on-device benchmarks
- behavior checks tied to the specific child
