# ABK Dual ABI/KMI Bridge Samples

## Purpose

Track representative bridge-facing sample modules so validation and future
`abi_fixups` stay tied to real modules instead of ad hoc guesses.

## Baseline

- Current kernel line: `6.1.118`
- Mainline reference: `7.0.12-arch1`
- Default bridge policy: `global_7012`
- Broad bridge policy: `experimental`

## First Sample Set

| Module Prefix | Family | Source | Status | Notes |
| --- | --- | --- | --- | --- |
| `kernelsu` | KernelSU | external 7.0.12 third-party LKM | queued | validation sample, not default policy gate |
| `sukisu` | SukiSU | external 7.0.12 third-party LKM | queued | validation sample, not default policy gate |
| `resukisu` | ReSukiSU | external 7.0.12 third-party LKM | queued | validation sample, not default policy gate |
| `ksu` | Generic KSU-named modules | external 7.0.12 third-party LKM | queued | validation sample, not default policy gate |

## Required Per-Sample Notes

- original vermagic
- whether `__versions` is present
- first failure point without bridge
- first failure point with `allowlist`
- first failure point with `experimental`
- whether follow-up `abi_fixups` are needed

## Do Not Repeat

- Do not treat this sample table as the default bridge coverage boundary
- Do not treat `experimental` success as proof that default global `7.0.12` bridge is runtime-safe
