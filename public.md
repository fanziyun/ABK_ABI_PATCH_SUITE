# Public Surface

Public module-set child ids:

- `display_release_spoof`
- `abi_bridge`
- `security_backport`
- `feature_porting_core`
- `feature_porting_backlog`

Legacy ids are rejected with migration guidance.

Paused implementations are intentionally not exposed:

- `network_porting`
- `framebuffer_bootlog`

Reference-tree injection is environment-driven:

- `ABK_MAINLINE_7012_ROOT`
- or repo-local `./linux`
