- [x] nohz 字段改进
- [x] avg_idle Preemption 模式简化
- [x] Swap Table Phase II Large folios 批量回收
- [x] Slab 优化
- [x] Hugepage 分配加速
- [x] io_uring NOWAIT 扩展与新子模块回移
- [x] feature_porting_backlog 子模块（承接剩余非暂停 backlog，当前按 6 项单大批次推进，并在批次内分层落地）
- [x] timestamp 更新（network_porting: socket/TCP 语义主路径已 graft，driver/provider 仍分类）
- [x] network_porting 起机优先收口（boot cmdline 日志增强槽位已补，AccECN 主路径改回保守 deferred；当前先停，实机表现为卡一）
- [x] framebuffer_bootlog 子模块（轻量 framebuffer/fbcon 起机日志基线，独立于 UEFI 路线；当前先停，实机表现为瞬间重启）
- [x] framebuffer_bootlog 收口（处理 header v3/v4 `vendor_cmdline` 分流与 `CONFIG_CMDLINE` 内建 `console=ttynull`；当前先停，不再继续扩）
- [ ] network_porting 后续：driver/GSO 相关网络外围收口（仅分类，继续 deferred/blocked_by_driver_scope；当前暂停，不再继续推进）
- [x] display_release_spoof uid 分流（uid < 1000 看真值避免 netbpfload 选错 BPF 变体 + vold/f2fs 路径错误，uid >= 1000 看 7.0.12 让 Settings 显示正确；exe-name 白名单三代全失败因为 app 进程都是 zygote fork 出来的 exe_file 一律 app_process64 无法区分）
- [x] open/close 热点路径
- [ ] false-sharing 消除（计划外）
- [x] close_range() 优化
- [x] pid 分配优化
- [ ] TCP socket 结构体瘦身（feature_porting_backlog: blocked_by_layout / report-first）
- [ ] IPv6 TCP 输出路径（feature_porting_backlog: report_only；不恢复 network 主路径迁移）
- [x] flow info 缓存（network_porting: IPv6 flow/cache hotpath 主路径已 graft）
- [ ] AccECN（network_porting: 仅保留 helper/report/fixup 保守基线，mainline protocol deferred；随 network_porting 一并暂停）
- [x] cBPF filters for io_uring（feature_porting_backlog: 源码树 partial / executable 路径已落地并编译通过；构建工作树 fallback 为 blocked_by_missing_anchor）
- [x] Non-circular SQ（feature_porting_backlog: 源码树 partial 路径已落地并编译通过；构建工作树 fallback 为 deferred）
- [x] Large RX buffer support（zcrx）（feature_porting_backlog: 源码树 partial 路径已落地并编译通过；构建工作树 fallback 为 blocked_by_missing_anchor）
- [x] blk-mq async_depth
- [x] zram compressed writeback
- [x] 7.0.12 ko 全局加载兼容
- [x] BTF binary search 优化（已独立落地；不计入当前 phase2 这 6 项批次）
- [x] bpf_timer/bpf_wq 无锁化（feature_porting_backlog: 源码树 partial 路径已落地并编译通过；构建工作树 fallback 为 blocked_by_missing_anchor）

## `feature_porting_backlog` 收口规则

- `feature_porting_backlog` 是 `feature_porting` 的剩余 backlog 承接线，不是第二个 `network_porting`
- 当前轮次固定为“6 项单大批次”，不是散条目推进
- 当前批次只纳入以下 6 项：
  `TCP socket 结构体瘦身`、`IPv6 TCP 输出路径`、`cBPF filters for io_uring`、
  `Non-circular SQ`、`Large RX buffer support（zcrx）`、`bpf_timer/bpf_wq 无锁化`
- 当前批次明确排除：
  `AccECN`、所有已完成项、所有 paused lines，以及已独立落地的 `BTF binary search 优化`
- 当前 active follow-up pair 固定为：
  `cBPF filters for io_uring` + `Non-circular SQ`
- 当前 active follow-up pair 实现状态：
  已实现、报告已同步、编译已通过；这是 phase2 内部子批次状态，不等于这两个 backlog 项整体完成；运行期验证仍单列处理
- 当前批次固定分三层：
  `cBPF filters for io_uring` = executable
  `Non-circular SQ` / `Large RX buffer support（zcrx）` / `bpf_timer/bpf_wq 无锁化` = bounded partial
  `IPv6 TCP 输出路径` / `TCP socket 结构体瘦身` = report-first
- 当前批次固定状态词：
  `report_only`、`partial`、`deferred`、`blocked_by_layout`、`blocked_by_missing_anchor`、`blocked_by_scope`
- 当前批次固定收口：
  `TCP socket 结构体瘦身` = `blocked_by_layout`
- 当前批次固定收口：
  `IPv6 TCP 输出路径` = `report_only`
- 当前批次固定收口：
  `cBPF filters for io_uring` = 有 support-module 锚点时 `partial` + executable；旧 6.1 单文件 io_uring 树为 `blocked_by_missing_anchor`
- 当前批次固定收口：
  `Non-circular SQ` = 有 `NO_SQARRAY` 锚点时 `partial`（语义主线继续 deferred）；旧 6.1 无该锚点时为 `deferred`
- 当前批次固定收口：
  `Large RX buffer support（zcrx）` = 有 zcrx surface 时 `partial`（仅 preparatory/support boundary）；旧 6.1 无该 surface 时为 `blocked_by_missing_anchor`
- 当前批次固定收口：
  `bpf_timer/bpf_wq 无锁化` = 有 `bpf_wq`/async anchors 时 `partial`（仅 helper-side async routing）；旧 6.1 仅有 bpf_timer 时为 `blocked_by_missing_anchor`

## `feature_porting_backlog` 旧 6.1 兼容现实

- 当前部分目标树仍是旧 6.1 布局：
  `io_uring/register.c`、`io_uring/bpf_filter.c/.h`、`io_uring/zcrx.c/.h`、`bpf_wq` / `bpf_timer_cancel_async` 等锚点不存在
- 对这类树，`feature_porting_backlog` 必须继续出报告，但不得因为缺少较新锚点而直接失败
- 当前兼容收口基线：
  `TCP socket 结构体瘦身` = `blocked_by_layout`
  `IPv6 TCP 输出路径` = `report_only`
  `cBPF filters for io_uring` = `blocked_by_missing_anchor`
  `Non-circular SQ` = `deferred`
  `Large RX buffer support（zcrx）` = `blocked_by_missing_anchor`
  `bpf_timer/bpf_wq 无锁化` = `blocked_by_missing_anchor`

## `feature_porting_backlog` 禁区

- 不继续推进已暂停的 `network_porting`
- 不继续推进已暂停的 `framebuffer_bootlog`
- 不把 `AccECN` 拉回本批次
- 不把 `false-sharing 消除` 纳入 `feature_porting_backlog`
- 不把 `TCP socket 结构体瘦身` 扩成 `struct sock` / `struct tcp_sock` 重布局工程
- 不把 `IPv6 TCP 输出路径` 扩成 network 主路径迁移工程
- 不对 `io_uring` 做 whole-file replacement
- 不直接导入 7.0.12 新 support-module 整树
- 不把 `zcrx` 扩到 page-pool / netdev / driver side
- 不把 `bpf_timer/bpf_wq` 扩大成 verifier / syscall / BTF / core infra 全量重写
- 不扩大到 `drivers/`、boot image、显示链路、设备日志系统
