# ABK Dual ABI/KMI Bridge Samples

## Purpose

Track the first bridge-facing sample set so bridge policy and future
`abi_fixups` stay tied to real modules instead of ad hoc guesses.

## Baseline

- Current kernel line: `6.1.118`
- Mainline reference: `7.0.12-arch1`
- Default bridge policy: `allowlist`
- Broad bridge policy: `experimental`

## First Sample Set

| Module Prefix | Family | Source | Status | Notes |
| --- | --- | --- | --- | --- |
| `kernelsu` | KernelSU | external 7.0.12 third-party LKM | queued | default allowlist family |
| `sukisu` | SukiSU | external 7.0.12 third-party LKM | queued | default allowlist family |
| `resukisu` | ReSukiSU | external 7.0.12 third-party LKM | queued | default allowlist family |
| `ksu` | Generic KSU-named modules | external 7.0.12 third-party LKM | queued | generic compatibility family |

## Required Per-Sample Notes

- original vermagic
- whether `__versions` is present
- first failure point without bridge
- first failure point with `allowlist`
- first failure point with `experimental`
- whether follow-up `abi_fixups` are needed

## Do Not Repeat

- Do not extend the default allowlist before adding the module family here
- Do not treat `experimental` success as proof that allowlist mode is safe
