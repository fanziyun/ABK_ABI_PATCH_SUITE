# ABK Security Update Backport Sources

## Purpose

Track the first security backport queues before larger patch batches land.

## Source Groups

### AOSP 6.1 Monthly Security Updates

Primary source for low-risk backports on top of Android 14 / Linux `6.1.118`.

### 7.0.12-arch1 / Mainline

Secondary source for security-relevant fixes with bounded ABI/KMI fallout.

## First Queue

| Batch | Source Group | Status | Notes |
| --- | --- | --- | --- |
| `sec_meta_batch_001` | mixed | queued | queue/export only in the current implementation |

## Rules

- Do not mix feature ports into security batches
- Mark any candidate that touches loader, exported symbols, or shared
  structures as `blocked by bridge` or `blocked by fixups`
- Do not land large batches here before bridge/fixup review
