#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class PatchGroup:
    key: str
    summary: str


PATCH_GROUPS = (
    PatchGroup(
        "network_porting_scaffold",
        "Real executable network_porting child with dedicated reports, smoke anchors, and bounded net/include-net scope.",
    ),
    PatchGroup(
        "net_timestamp_socket_semantics",
        "Port socket/TCP timestamp semantics helpers and receive/send timestamp gating without expanding into drivers or hwtstamp providers.",
    ),
    PatchGroup(
        "net_flow_info_cache_ipv6",
        "Port IPv6 flowlabel, flow cache, and socket dst-cache hotpath helpers without whole-file replacement.",
    ),
    PatchGroup(
        "net_accecn_core",
        "Track the bounded AccECN mode/helper/report surface that fits the 6.1 anchors without tcp struct growth.",
    ),
    PatchGroup(
        "net_accecn_mainline_protocol",
        "Keep AccECN send/recv/timer/TCP_INFO mainline expansion deferred until the 6.1 boot-safe anchors are proven.",
    ),
    PatchGroup(
        "net_accecn_path_fixups",
        "Keep only minimal AccECN child/openreq and syncookie glue where 6.1 anchors stay layout-safe.",
    ),
    PatchGroup(
        "net_driver_dependent_features",
        "Classify timestamp and AccECN offload/provider dependencies as applied, deferred, or blocked by driver scope.",
    ),
    PatchGroup(
        "network_porting_fixups",
        "Reserve follow-up compatibility glue discovered after the first bounded network graft batch.",
    ),
)


DRIVER_DEPENDENT_FEATURES = (
    {
        "key": "timestamp_hardware_provider_path",
        "summary": "SOF_TIMESTAMPING hardware provider and PHC/device capability expansion beyond socket semantics.",
        "status": "blocked_by_driver_scope",
    },
    {
        "key": "timestamp_ethtool_hwtstamp_provider_sync",
        "summary": "ethtool/hwtstamp provider capability synchronization in drivers/net and PHY/MAC implementations.",
        "status": "blocked_by_driver_scope",
    },
    {
        "key": "accecn_gso_segmentation_offload",
        "summary": "AccECN-specific GSO/segmentation/offload feature-bit plumbing.",
        "status": "deferred",
    },
    {
        "key": "accecn_driver_feature_bits",
        "summary": "Driver feature bits and ndo/offload behavior for AccECN-aware transmit/receive handling.",
        "status": "blocked_by_driver_scope",
    },
)


def read_text(path: Path) -> str:
    return path.read_text()


def write_text(path: Path, text: str) -> None:
    path.write_text(text)


def ensure_contains(path: Path, needle: str, label: str) -> None:
    if needle not in read_text(path):
        raise SystemExit(f"{label}: expected anchor missing in {path}: {needle}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected block missing")
    return text.replace(old, new, 1)


def replace_any_once(text: str, candidates: tuple[str, ...], new: str, label: str) -> str:
    for old in candidates:
        if old in text:
            return text.replace(old, new, 1)
    raise SystemExit(f"{label}: expected block missing")


def replace_within(text: str, start: str, end: str, old: str, new: str, label: str) -> str:
    start_idx = text.find(start)
    if start_idx < 0:
        raise SystemExit(f"{label}: start anchor missing")
    end_idx = text.find(end, start_idx)
    if end_idx < 0:
        raise SystemExit(f"{label}: end anchor missing")

    scoped = text[start_idx:end_idx]
    if old not in scoped:
        raise SystemExit(f"{label}: expected scoped block missing")
    scoped = scoped.replace(old, new, 1)
    return text[:start_idx] + scoped + text[end_idx:]


def graft_metadata(
    *,
    hard_port_possible: bool,
    semantic_port_used: bool,
    max_function_port_used: bool,
    sidecar_state_used: bool,
    sidecar_state_scope: str,
    new_interface_used: bool,
    new_interface_scope: str,
) -> dict[str, object]:
    return {
        "hard_port_possible": hard_port_possible,
        "semantic_port_used": semantic_port_used,
        "max_function_port_used": max_function_port_used,
        "sidecar_state_used": sidecar_state_used,
        "sidecar_state_scope": sidecar_state_scope,
        "new_interface_used": new_interface_used,
        "new_interface_scope": new_interface_scope,
    }


def patch_timestamp_socket_semantics(common_root: Path) -> dict[str, object]:
    sock_h = common_root / "include/net/sock.h"
    sock_c = common_root / "net/core/sock.c"
    skbuff_c = common_root / "net/core/skbuff.c"
    socket_c = common_root / "net/socket.c"
    tcp_c = common_root / "net/ipv4/tcp.c"

    sock_h_text = read_text(sock_h)
    sock_h_changed = False
    compat_cookie_and_flags = """static inline void _sock_tx_timestamp_cookie(struct sock *sk,
\t\t\t\t      const struct sockcm_cookie *sockc,
\t\t\t\t      __u8 *tx_flags, __u32 *tskey)
{
\t__u32 tsflags = sockc->tsflags;

\tif (unlikely(tsflags)) {
\t\t__sock_tx_timestamp(tsflags, tx_flags);
\t\tif (tsflags & SOF_TIMESTAMPING_OPT_ID && tskey &&
\t\t    tsflags & SOF_TIMESTAMPING_TX_RECORD_MASK) {
\t\t\tif (tsflags & SOCKCM_FLAG_TS_OPT_ID)
\t\t\t\t*tskey = sockc->ts_opt_id;
\t\t\telse
\t\t\t\t*tskey = atomic_inc_return(&sk->sk_tskey) - 1;
\t\t}
\t}
\tif (unlikely(sock_flag(sk, SOCK_WIFI_STATUS)))
\t\t*tx_flags |= SKBTX_WIFI_STATUS;
}

static inline void _sock_tx_timestamp(struct sock *sk, __u32 tsflags,
\t\t\t\t      __u8 *tx_flags, __u32 *tskey)
{
\tstruct sockcm_cookie sockc = {
\t\t.tsflags = tsflags,
\t};

\t_sock_tx_timestamp_cookie(sk, &sockc, tx_flags, tskey);
}

static inline void sock_tx_timestamp(struct sock *sk, __u32 tsflags,
\t\t\t\t     __u8 *tx_flags)
{
\t_sock_tx_timestamp(sk, tsflags, tx_flags, NULL);
}

static inline void sock_tx_timestamp_cookie(struct sock *sk,
\t\t\t\t    const struct sockcm_cookie *sockc,
\t\t\t\t    __u8 *tx_flags)
{
\t_sock_tx_timestamp_cookie(sk, sockc, tx_flags, NULL);
}

static inline void skb_setup_tx_timestamp(struct sk_buff *skb, __u32 tsflags)
{
\t_sock_tx_timestamp(skb->sk, tsflags, &skb_shinfo(skb)->tx_flags,
\t\t\t   &skb_shinfo(skb)->tskey);
}

static inline void skb_setup_tx_timestamp_cookie(struct sk_buff *skb,
\t\t\t\t\t const struct sockcm_cookie *sockc)
{
\t_sock_tx_timestamp_cookie(skb->sk, sockc, &skb_shinfo(skb)->tx_flags,
\t\t\t\t &skb_shinfo(skb)->tskey);
}
"""
    sock_tx_helper_start = "static inline void _sock_tx_timestamp("
    sock_tx_helper_end = "static inline bool sk_is_inet"
    helper_start_idx = sock_h_text.find(sock_tx_helper_start)
    helper_end_idx = sock_h_text.find(sock_tx_helper_end, helper_start_idx if helper_start_idx >= 0 else 0)
    if helper_start_idx >= 0 and helper_end_idx > helper_start_idx:
        helper_block = sock_h_text[helper_start_idx:helper_end_idx]
        if "sock_tx_timestamp_cookie" not in helper_block:
            sock_h_text = (
                sock_h_text[:helper_start_idx]
                + compat_cookie_and_flags
                + sock_h_text[helper_end_idx:]
            )
            sock_h_changed = True
    if "ABK_NET_TS_OPT_ID_TCP" not in sock_h_text:
        sock_h_text = replace_once(
            sock_h_text,
            "void __sock_recv_cmsgs(struct msghdr *msg, struct sock *sk,\n\t\t       struct sk_buff *skb);\n\n#define SK_DEFAULT_STAMP (-1L * NSEC_PER_SEC)\n",
            "void __sock_recv_cmsgs(struct msghdr *msg, struct sock *sk,\n\t\t       struct sk_buff *skb);\n\n#define SK_DEFAULT_STAMP (-1L * NSEC_PER_SEC)\n#define ABK_NET_TS_OPT_ID_TCP\t\tBIT(16)\n#define ABK_NET_TS_OPT_RX_FILTER\tBIT(17)\n#define ABK_NET_TS_TX_COMPLETION\tBIT(18)\n",
            "network_porting/sock_h_internal_ts_flags",
        )
        sock_h_changed = True
    if "#define SOCKCM_FLAG_TS_OPT_ID" not in sock_h_text:
        if "void __sock_recv_cmsgs(struct msghdr *msg, struct sock *sk,\n\t\t       struct sk_buff *skb);\n\n#define SK_DEFAULT_STAMP (-1L * NSEC_PER_SEC)\n" in sock_h_text:
            sock_h_text = replace_once(
                sock_h_text,
                "void __sock_recv_cmsgs(struct msghdr *msg, struct sock *sk,\n\t\t       struct sk_buff *skb);\n\n#define SK_DEFAULT_STAMP (-1L * NSEC_PER_SEC)\n",
                "void __sock_recv_cmsgs(struct msghdr *msg, struct sock *sk,\n\t\t       struct sk_buff *skb);\n\n#define SK_DEFAULT_STAMP (-1L * NSEC_PER_SEC)\n#define SOCKCM_FLAG_TS_OPT_ID\tBIT(31)\n",
                "network_porting/sock_h_sockcm_flag",
            )
        elif "struct sockcm_cookie {\n" in sock_h_text:
            sock_h_text = sock_h_text.replace(
                "struct sockcm_cookie {\n",
                "#define SOCKCM_FLAG_TS_OPT_ID\tBIT(31)\n\nstruct sockcm_cookie {\n",
                1,
            )
        else:
            raise SystemExit("network_porting/sock_h_sockcm_flag: expected anchor missing")
        sock_h_changed = True
    if "SOCK_TIMESTAMPING_ANY" not in sock_h_text:
        sock_h_text = replace_once(
            sock_h_text,
            "\tSOCK_TSTAMP_NEW, /* Indicates 64 bit timestamps always */\n\tSOCK_RCVMARK, /* Receive SO_MARK  ancillary data with packet */\n};\n",
            "\tSOCK_TSTAMP_NEW, /* Indicates 64 bit timestamps always */\n\tSOCK_RCVMARK, /* Receive SO_MARK  ancillary data with packet */\n\tSOCK_RCVPRIORITY, /* Receive SO_PRIORITY ancillary data with packet */\n\tSOCK_TIMESTAMPING_ANY, /* Copy of sk_tsflags & TSFLAGS_ANY */\n};\n",
            "network_porting/sock_h_sock_flags",
        )
        sock_h_changed = True
    if "u32 tsflags;" not in sock_h_text:
        sock_h_text = replace_once(
            sock_h_text,
            "struct sockcm_cookie {\n\tu64 transmit_time;\n\tu32 mark;\n\tu16 tsflags;\n};\n",
            "struct sockcm_cookie {\n\tu64 transmit_time;\n\tu32 mark;\n\tu32 tsflags;\n\tu32 ts_opt_id;\n};\n",
            "network_porting/sock_h_sockcm_cookie",
        )
        sock_h_text = replace_once(
            sock_h_text,
            "\t*sockc = (struct sockcm_cookie) {\n\t\t.tsflags = READ_ONCE(sk->sk_tsflags)\n\t};\n",
            "\t*sockc = (struct sockcm_cookie) {\n\t\t.mark = READ_ONCE(sk->sk_mark),\n\t\t.tsflags = READ_ONCE(sk->sk_tsflags),\n\t};\n",
            "network_porting/sock_h_sockcm_init",
        )
        sock_h_text = replace_once(
            sock_h_text,
            "void __sock_tx_timestamp(__u16 tsflags, __u8 *tx_flags);\n",
            "void __sock_tx_timestamp(__u32 tsflags, __u8 *tx_flags);\n",
            "network_porting/sock_h_sock_tx_decl",
        )
        sock_h_text = replace_once(
            sock_h_text,
            "#define FLAGS_RECV_CMSGS ((1UL << SOCK_RXQ_OVFL)\t\t\t| \\\n\t\t\t   (1UL << SOCK_RCVTSTAMP)\t\t\t| \\\n\t\t\t   (1UL << SOCK_RCVMARK))\n#define TSFLAGS_ANY\t  (SOF_TIMESTAMPING_SOFTWARE\t\t\t| \\\n\t\t\t   SOF_TIMESTAMPING_RAW_HARDWARE)\n\n\tif (sk->sk_flags & FLAGS_RECV_CMSGS ||\n\t    READ_ONCE(sk->sk_tsflags) & TSFLAGS_ANY)\n",
            "#define FLAGS_RECV_CMSGS ((1UL << SOCK_RXQ_OVFL)\t\t\t| \\\n\t\t\t   (1UL << SOCK_RCVTSTAMP)\t\t\t| \\\n\t\t\t   (1UL << SOCK_RCVMARK)\t\t\t| \\\n\t\t\t   (1UL << SOCK_RCVPRIORITY)\t\t\t| \\\n\t\t\t   (1UL << SOCK_TIMESTAMPING_ANY))\n#define TSFLAGS_ANY\t  (SOF_TIMESTAMPING_SOFTWARE\t\t\t| \\\n\t\t\t   SOF_TIMESTAMPING_RAW_HARDWARE)\n\n\tif (READ_ONCE(sk->sk_flags) & FLAGS_RECV_CMSGS)\n",
            "network_porting/sock_h_recv_cmsgs_flags",
        )
        if "sock_tx_timestamp_cookie" not in sock_h_text:
            sock_h_text = replace_once(
                sock_h_text,
                "static inline void _sock_tx_timestamp(struct sock *sk, __u16 tsflags,\n\t\t\t\t      __u8 *tx_flags, __u32 *tskey)\n{\n\tif (unlikely(tsflags)) {\n\t\t__sock_tx_timestamp(tsflags, tx_flags);\n\t\tif (tsflags & SOF_TIMESTAMPING_OPT_ID && tskey &&\n\t\t    tsflags & SOF_TIMESTAMPING_TX_RECORD_MASK)\n\t\t\t*tskey = atomic_inc_return(&sk->sk_tskey) - 1;\n\t}\n\tif (unlikely(sock_flag(sk, SOCK_WIFI_STATUS)))\n\t\t*tx_flags |= SKBTX_WIFI_STATUS;\n}\n\nstatic inline void sock_tx_timestamp(struct sock *sk, __u16 tsflags,\n\t\t\t\t     __u8 *tx_flags)\n{\n\t_sock_tx_timestamp(sk, tsflags, tx_flags, NULL);\n}\n\nstatic inline void skb_setup_tx_timestamp(struct sk_buff *skb, __u16 tsflags)\n{\n\t_sock_tx_timestamp(skb->sk, tsflags, &skb_shinfo(skb)->tx_flags,\n\t\t\t   &skb_shinfo(skb)->tskey);\n}\n",
                compat_cookie_and_flags,
                "network_porting/sock_h_sock_tx_helpers",
            )
        sock_h_changed = True
    if sock_h_changed:
        write_text(sock_h, sock_h_text)

    sock_c_text = read_text(sock_c)
    if "ABK_NET_TS_OPT_ID_TCP" not in sock_c_text:
        sock_c_text = replace_once(
            sock_c_text,
            "\tif (val & SOF_TIMESTAMPING_OPT_ID &&\n\t    !(sk->sk_tsflags & SOF_TIMESTAMPING_OPT_ID)) {\n\t\tif (sk_is_tcp(sk)) {\n\t\t\tif ((1 << sk->sk_state) &\n\t\t\t    (TCPF_CLOSE | TCPF_LISTEN))\n\t\t\t\treturn -EINVAL;\n\t\t\tatomic_set(&sk->sk_tskey, tcp_sk(sk)->snd_una);\n\t\t} else {\n\t\t\tatomic_set(&sk->sk_tskey, 0);\n\t\t}\n\t}\n",
            "\tif (val & ABK_NET_TS_OPT_ID_TCP &&\n\t    !(val & SOF_TIMESTAMPING_OPT_ID))\n\t\treturn -EINVAL;\n\n\tif (val & SOF_TIMESTAMPING_OPT_ID &&\n\t    !(sk->sk_tsflags & SOF_TIMESTAMPING_OPT_ID)) {\n\t\tif (sk_is_tcp(sk)) {\n\t\t\tif ((1 << sk->sk_state) &\n\t\t\t    (TCPF_CLOSE | TCPF_LISTEN))\n\t\t\t\treturn -EINVAL;\n\t\t\tif (val & ABK_NET_TS_OPT_ID_TCP)\n\t\t\t\tatomic_set(&sk->sk_tskey, tcp_sk(sk)->write_seq);\n\t\t\telse\n\t\t\t\tatomic_set(&sk->sk_tskey, tcp_sk(sk)->snd_una);\n\t\t} else {\n\t\t\tatomic_set(&sk->sk_tskey, 0);\n\t\t}\n\t}\n",
            "network_porting/sock_c_opt_id_tcp",
        )
        sock_c_text = replace_once(
            sock_c_text,
            "\tWRITE_ONCE(sk->sk_tsflags, val);\n\tsock_valbool_flag(sk, SOCK_TSTAMP_NEW, optname == SO_TIMESTAMPING_NEW);\n",
            "\tWRITE_ONCE(sk->sk_tsflags, val);\n\tsock_valbool_flag(sk, SOCK_TSTAMP_NEW, optname == SO_TIMESTAMPING_NEW);\n\tsock_valbool_flag(sk, SOCK_TIMESTAMPING_ANY, !!(val & TSFLAGS_ANY));\n",
            "network_porting/sock_c_any_flag",
        )
        write_text(sock_c, sock_c_text)

    socket_c_text = read_text(socket_c)
    if "void __sock_tx_timestamp(__u16 tsflags, __u8 *tx_flags)\n" in socket_c_text:
        socket_c_text = replace_once(
            socket_c_text,
            "void __sock_tx_timestamp(__u16 tsflags, __u8 *tx_flags)\n",
            "void __sock_tx_timestamp(__u32 tsflags, __u8 *tx_flags)\n",
            "network_porting/socket_c_sock_tx_decl",
        )
    old_completion = "\tif (tsflags & ABK_NET_TS_TX_COMPLETION)\n\t\tflags |= SKBTX_COMPLETION_TSTAMP;\n"
    guarded_completion = "#ifdef SKBTX_COMPLETION_TSTAMP\n\tif (tsflags & ABK_NET_TS_TX_COMPLETION)\n\t\tflags |= SKBTX_COMPLETION_TSTAMP;\n#endif\n"
    if old_completion in socket_c_text and guarded_completion not in socket_c_text:
        socket_c_text = socket_c_text.replace(old_completion, guarded_completion, 1)
    elif "ABK_NET_TS_TX_COMPLETION" not in socket_c_text:
        socket_c_text = replace_once(
            socket_c_text,
            "\tif (tsflags & SOF_TIMESTAMPING_TX_SCHED)\n\t\tflags |= SKBTX_SCHED_TSTAMP;\n\n\t*tx_flags = flags;\n",
            "\tif (tsflags & SOF_TIMESTAMPING_TX_SCHED)\n\t\tflags |= SKBTX_SCHED_TSTAMP;\n\n#ifdef SKBTX_COMPLETION_TSTAMP\n\tif (tsflags & ABK_NET_TS_TX_COMPLETION)\n\t\tflags |= SKBTX_COMPLETION_TSTAMP;\n#endif\n\n\t*tx_flags = flags;\n",
            "network_porting/socket_c_tx_completion",
        )
        socket_c_text = replace_once(
            socket_c_text,
            "\tif ((tsflags & SOF_TIMESTAMPING_SOFTWARE) &&\n\t    ktime_to_timespec64_cond(skb->tstamp, tss.ts + 0))\n\t\tempty = 0;\n",
            "\tif ((tsflags & SOF_TIMESTAMPING_SOFTWARE &&\n\t     (tsflags & SOF_TIMESTAMPING_RX_SOFTWARE ||\n\t      skb_is_err_queue(skb) ||\n\t      !(tsflags & ABK_NET_TS_OPT_RX_FILTER))) &&\n\t    ktime_to_timespec64_cond(skb->tstamp, tss.ts + 0))\n\t\tempty = 0;\n",
            "network_porting/socket_c_rx_sw_filter",
        )
        socket_c_text = replace_once(
            socket_c_text,
            "\tif (shhwtstamps &&\n\t    (tsflags & SOF_TIMESTAMPING_RAW_HARDWARE) &&\n\t    !skb_is_swtx_tstamp(skb, false_tstamp)) {\n",
            "\tif (shhwtstamps &&\n\t    (tsflags & SOF_TIMESTAMPING_RAW_HARDWARE &&\n\t     (tsflags & SOF_TIMESTAMPING_RX_HARDWARE ||\n\t      skb_is_err_queue(skb) ||\n\t      !(tsflags & ABK_NET_TS_OPT_RX_FILTER))) &&\n\t    !skb_is_swtx_tstamp(skb, false_tstamp)) {\n",
            "network_porting/socket_c_rx_hw_filter",
        )
    write_text(socket_c, socket_c_text)

    skbuff_text = read_text(skbuff_c)
    if "ABK network_porting: timestamp send/completion reporting is kept inside net/core and net/ipv4 without widening into provider drivers." not in skbuff_text:
        skbuff_text = replace_once(
            skbuff_text,
            "void skb_complete_tx_timestamp(struct sk_buff *skb,\n\t\t\t       struct skb_shared_hwtstamps *hwtstamps)\n{\n\tstruct sock *sk = skb->sk;\n\n\tif (!skb_may_tx_timestamp(sk, false))\n\t\tgoto err;\n",
            "void skb_complete_tx_timestamp(struct sk_buff *skb,\n\t\t\t       struct skb_shared_hwtstamps *hwtstamps)\n{\n\tstruct sock *sk = skb->sk;\n\n\t/* ABK network_porting: timestamp send/completion reporting is kept inside net/core and net/ipv4 without widening into provider drivers. */\n\tif (!skb_may_tx_timestamp(sk, false))\n\t\tgoto err;\n",
            "network_porting/skbuff_c_completion_marker",
        )
        write_text(skbuff_c, skbuff_text)

    tcp_c_text = read_text(tcp_c)
    if "tsflags & ABK_NET_TS_OPT_RX_FILTER" in tcp_c_text:
        # Remove an older broken graft that referenced an out-of-scope local tsflags.
        broken_block = "\n\t\tif (tsflags & SOF_TIMESTAMPING_SOFTWARE &&\n\t\t    (tsflags & SOF_TIMESTAMPING_RX_SOFTWARE ||\n\t\t     !(tsflags & ABK_NET_TS_OPT_RX_FILTER)))\n\t\t\thas_timestamping = true;\n\t\telse\n\t\t\ttss->ts[0] = (struct timespec64) {0};\n\t}\n\n\tif (tss->ts[2].tv_sec || tss->ts[2].tv_nsec) {\n\t\tif (tsflags & SOF_TIMESTAMPING_RAW_HARDWARE &&\n\t\t    (tsflags & SOF_TIMESTAMPING_RX_HARDWARE ||\n\t\t     !(tsflags & ABK_NET_TS_OPT_RX_FILTER)))\n\t\t\thas_timestamping = true;\n\t\telse\n\t\t\ttss->ts[2] = (struct timespec64) {0};\n\t}\n"
        tcp_c_text = tcp_c_text.replace(broken_block, "\n", 1)
        write_text(tcp_c, tcp_c_text)
        tcp_c_text = read_text(tcp_c)
    broken_gap = "\t\t}\n\n\n\tif (has_timestamping) {\n"
    if broken_gap in tcp_c_text:
        tcp_c_text = tcp_c_text.replace(broken_gap, "\t\t}\n\t}\n\n\tif (has_timestamping) {\n", 1)
        write_text(tcp_c, tcp_c_text)
        tcp_c_text = read_text(tcp_c)
    marker = "/* ABK network_porting: socket/TCP timestamp receive filtering and completion-tstamp semantics aligned without widening into drivers/net. */\n"
    if marker not in tcp_c_text:
        tcp_c_text = tcp_c_text.replace(
            "/* Similar to __sock_recv_timestamp, but does not require an skb */\n",
            marker + "/* Similar to __sock_recv_timestamp, but does not require an skb */\n",
            1,
        )
        write_text(tcp_c, tcp_c_text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="internal_static_api",
        ),
        "group": "net_timestamp_socket_semantics",
        "status": "main_path_grafted",
        "phase": "socket_tcp_semantics_main_path_grafted",
        "scope": "net_and_include_net_only",
        "uapi_expanded_in_scope": False,
        "driver_scope_escaped": False,
        "remaining_blockers": [
            "blocked_by_driver_scope: hardware/provider timestamp enablement remains out of scope",
            "blocked_by_driver_scope: ethtool hwtstamp provider sync remains out of scope",
        ],
        "marker": "ABK network_porting: socket/TCP timestamp receive filtering and completion-tstamp semantics aligned without widening into drivers/net.",
    }


def patch_flow_info_cache_ipv6(common_root: Path) -> dict[str, object]:
    ipv6_h = common_root / "include/net/ipv6.h"
    inet6_csk_c = common_root / "net/ipv6/inet6_connection_sock.c"
    ip6_output_c = common_root / "net/ipv6/ip6_output.c"
    ipv6_sockglue_c = common_root / "net/ipv6/ipv6_sockglue.c"

    ipv6_text = read_text(ipv6_h)
    if "bool ip6_autoflowlabel(struct net *net, const struct sock *sk);" not in ipv6_text:
        ipv6_text = replace_once(
            ipv6_text,
            "bool ip6_autoflowlabel(struct net *net, const struct ipv6_pinfo *np);\n",
            "bool ip6_autoflowlabel(struct net *net, const struct sock *sk);\n",
            "network_porting/ipv6_h_autoflowlabel_decl",
        )
        ipv6_text = replace_once(
            ipv6_text,
            "static inline __be32 ip6_make_flowlabel(struct net *net, struct sk_buff *skb,\n",
            "static inline __be32 ip6_make_flowlabel(const struct net *net, struct sk_buff *skb,\n",
            "network_porting/ipv6_h_flowlabel_helper_1",
        )
        ipv6_text = replace_once(
            ipv6_text,
            "static inline __be32 ip6_make_flowlabel(struct net *net, struct sk_buff *skb,\n",
            "static inline __be32 ip6_make_flowlabel(const struct net *net, struct sk_buff *skb,\n",
            "network_porting/ipv6_h_flowlabel_helper_2",
        )
        write_text(ipv6_h, ipv6_text)

    inet6_text = read_text(inet6_csk_c)
    broken_signature = "struct dst_entry *inet6_csk_route_req(const struct sock *sk,\n\t\t\t\t      struct dst_entry *dst,\n\t\t\t\t      struct flowi6 *fl6,\n\t\t\t\t      const struct request_sock *req,\n\t\t\t\t      u8 proto)\n"
    if broken_signature in inet6_text:
        inet6_text = replace_once(
            inet6_text,
            broken_signature,
            "struct dst_entry *inet6_csk_route_req(const struct sock *sk,\n\t\t\t\t      struct flowi6 *fl6,\n\t\t\t\t      const struct request_sock *req,\n\t\t\t\t      u8 proto)\n",
            "network_porting/inet6_csk_restore_signature",
        )
        inet6_text = replace_once(
            inet6_text,
            "\tfl6->fl6_sport = htons(ireq->ir_num);\n\tfl6->flowi6_uid = sk_uid(sk);\n\tsecurity_req_classify_flow(req, flowi6_to_flowi_common(fl6));\n\n\tif (!dst) {\n\t\tdst = ip6_dst_lookup_flow(sock_net(sk), sk, fl6, final_p);\n\t\tif (IS_ERR(dst))\n\t\t\treturn NULL;\n\t}\n\treturn dst;\n}\n",
            "\tfl6->fl6_sport = htons(ireq->ir_num);\n\tfl6->flowi6_uid = sk->sk_uid;\n\tsecurity_req_classify_flow(req, flowi6_to_flowi_common(fl6));\n\n\tdst = ip6_dst_lookup_flow(sock_net(sk), sk, fl6, final_p);\n\tif (IS_ERR(dst))\n\t\treturn NULL;\n\n\treturn dst;\n}\n",
            "network_porting/inet6_csk_restore_req_body",
        )
        inet6_text = replace_once(
            inet6_text,
            "\tfl6->fl6_sport = inet->inet_sport;\n\tfl6->fl6_dport = inet->inet_dport;\n\tfl6->flowi6_uid = sk_uid(sk);\n\tsecurity_sk_classify_flow(sk, flowi6_to_flowi_common(fl6));\n\n\trcu_read_lock();\n\tfinal_p = fl6_update_dst(fl6, rcu_dereference(np->opt), &np->final);\n\trcu_read_unlock();\n\n\tdst = __inet6_csk_dst_check(sk, np->dst_cookie);\n\tif (!dst) {\n\t\tdst = ip6_dst_lookup_flow(sock_net(sk), sk, fl6, final_p);\n\n\t\tif (!IS_ERR(dst))\n\t\t\tip6_dst_store(sk, dst, NULL, NULL);\n\t}\n\treturn dst;\n}\n",
            "\tfl6->fl6_sport = inet->inet_sport;\n\tfl6->fl6_dport = inet->inet_dport;\n\tfl6->flowi6_uid = sk->sk_uid;\n\tsecurity_sk_classify_flow(sk, flowi6_to_flowi_common(fl6));\n\n\trcu_read_lock();\n\tfinal_p = fl6_update_dst(fl6, rcu_dereference(np->opt), &final);\n\trcu_read_unlock();\n\n\tdst = __inet6_csk_dst_check(sk, np->dst_cookie);\n\tif (!dst) {\n\t\tdst = ip6_dst_lookup_flow(sock_net(sk), sk, fl6, final_p);\n\n\t\tif (!IS_ERR(dst))\n\t\t\tip6_dst_store(sk, dst, NULL, NULL);\n\t}\n\treturn dst;\n}\n",
            "network_porting/inet6_csk_restore_route_socket",
        )
        inet6_text = replace_once(
            inet6_text,
            "int inet6_csk_xmit(struct sock *sk, struct sk_buff *skb, struct flowi *fl_unused)\n{\n\tstruct flowi6 *fl6 = &inet_sk(sk)->cork.fl.u.ip6;\n\tstruct ipv6_pinfo *np = inet6_sk(sk);\n\tstruct dst_entry *dst;\n\tint res;\n\n\tdst = __sk_dst_check(sk, np->dst_cookie);\n\tif (unlikely(!dst)) {\n\t\tdst = inet6_csk_route_socket(sk, fl6);\n\t\tif (IS_ERR(dst)) {\n\t\t\tWRITE_ONCE(sk->sk_err_soft, -PTR_ERR(dst));\n\t\t\tsk->sk_route_caps = 0;\n\t\t\tkfree_skb(skb);\n\t\t\treturn PTR_ERR(dst);\n\t\t}\n\t\t/* Restore final destination back after routing done */\n\t\tfl6->daddr = sk->sk_v6_daddr;\n\t}\n\n\trcu_read_lock();\n\tskb_dst_set_noref(skb, dst);\n\n\tres = ip6_xmit(sk, skb, fl6, sk->sk_mark, rcu_dereference(np->opt),\n\t\t       np->tclass, READ_ONCE(sk->sk_priority));\n",
            "int inet6_csk_xmit(struct sock *sk, struct sk_buff *skb, struct flowi *fl_unused)\n{\n\tstruct ipv6_pinfo *np = inet6_sk(sk);\n\tstruct flowi6 fl6;\n\tstruct dst_entry *dst;\n\tint res;\n\n\tdst = inet6_csk_route_socket(sk, &fl6);\n\tif (IS_ERR(dst)) {\n\t\tsk->sk_err_soft = -PTR_ERR(dst);\n\t\tsk->sk_route_caps = 0;\n\t\tkfree_skb(skb);\n\t\treturn PTR_ERR(dst);\n\t}\n\n\trcu_read_lock();\n\tskb_dst_set_noref(skb, dst);\n\n\t/* Restore final destination back after routing done */\n\tfl6.daddr = sk->sk_v6_daddr;\n\n\tres = ip6_xmit(sk, skb, &fl6, sk->sk_mark, rcu_dereference(np->opt),\n\t\t       np->tclass,  sk->sk_priority);\n",
            "network_porting/inet6_csk_restore_xmit",
        )
        inet6_text = replace_once(
            inet6_text,
            "struct dst_entry *inet6_csk_update_pmtu(struct sock *sk, u32 mtu)\n{\n\tstruct flowi6 *fl6 = &inet_sk(sk)->cork.fl.u.ip6;\n\tstruct dst_entry *dst;\n\n\tdst = inet6_csk_route_socket(sk, fl6);\n\n\tif (IS_ERR(dst))\n\t\treturn NULL;\n\tdst->ops->update_pmtu(dst, sk, NULL, mtu, true);\n\n\tdst = inet6_csk_route_socket(sk, fl6);\n\treturn IS_ERR(dst) ? NULL : dst;\n}\n",
            "struct dst_entry *inet6_csk_update_pmtu(struct sock *sk, u32 mtu)\n{\n\tstruct flowi6 fl6;\n\tstruct dst_entry *dst = inet6_csk_route_socket(sk, &fl6);\n\n\tif (IS_ERR(dst))\n\t\treturn NULL;\n\tdst->ops->update_pmtu(dst, sk, NULL, mtu, true);\n\n\tdst = inet6_csk_route_socket(sk, &fl6);\n\treturn IS_ERR(dst) ? NULL : dst;\n}\n",
            "network_porting/inet6_csk_restore_pmtu",
        )
        write_text(inet6_csk_c, inet6_text)
    if "ABK network_porting: IPv6 flow/cache hotpath graft" not in inet6_text:
        inet6_text = inet6_text.replace(
            "static struct dst_entry *inet6_csk_route_socket(struct sock *sk,\n\t\t\t\t\t\tstruct flowi6 *fl6)\n",
            "/* ABK network_porting: IPv6 flow/cache hotpath graft keeps cork-backed flow state and socket dst-cookie reuse in net/ + include/net/ only. */\nstatic struct dst_entry *inet6_csk_route_socket(struct sock *sk,\n\t\t\t\t\t\tstruct flowi6 *fl6)\n",
            1,
        )
        write_text(inet6_csk_c, inet6_text)

    ip6_output_text = read_text(ip6_output_c)
    ip6_output_changed = False
    compat_np_autoflowlabel = """bool ip6_autoflowlabel(struct net *net, const struct sock *sk)
{
\tconst struct ipv6_pinfo *np = inet6_sk(sk);

\tif (!np->autoflowlabel_set)
\t\treturn ip6_default_np_autolabel(net);
\treturn np->autoflowlabel;
}
"""
    autoflowlabel_start = "bool ip6_autoflowlabel(struct net *net, const struct sock *sk)\n"
    autoflowlabel_end = "/*\n * xmit an sk_buff"
    auto_start_idx = ip6_output_text.find(autoflowlabel_start)
    auto_end_idx = ip6_output_text.find(autoflowlabel_end, auto_start_idx if auto_start_idx >= 0 else 0)
    if auto_start_idx >= 0 and auto_end_idx > auto_start_idx:
        auto_block = ip6_output_text[auto_start_idx:auto_end_idx]
        if "inet6_test_bit" in auto_block or "const struct ipv6_pinfo *np = inet6_sk(sk);" not in auto_block:
            ip6_output_text = (
                ip6_output_text[:auto_start_idx]
                + compat_np_autoflowlabel
                + "\n"
                + ip6_output_text[auto_end_idx:]
            )
            ip6_output_changed = True
    if "if (np && np->rtalert_isolate &&" in ip6_output_text and "const struct ipv6_pinfo *np = inet6_sk(sk);" not in ip6_output_text[ip6_output_text.find("static int ip6_call_ra_chain"):ip6_output_text.find("read_lock(&ip6_ra_lock);")]:
        ip6_output_text = ip6_output_text.replace(
            "static int ip6_call_ra_chain(struct sk_buff *skb, int sel)\n{\n\tstruct ip6_ra_chain *ra;\n\tstruct sock *last = NULL;\n\n\tread_lock(&ip6_ra_lock);\n",
            "static int ip6_call_ra_chain(struct sk_buff *skb, int sel)\n{\n\tstruct ip6_ra_chain *ra;\n\tconst struct ipv6_pinfo *np = skb->sk ? inet6_sk(skb->sk) : NULL;\n\tstruct sock *last = NULL;\n\n\tread_lock(&ip6_ra_lock);\n",
            1,
        )
        ip6_output_changed = True
    if "struct ipv6_pinfo *np = inet6_sk(sk);\n\tstruct net *net = sock_net(sk);\n" in ip6_output_text:
        ip6_output_text = ip6_output_text.replace(
            "struct ipv6_pinfo *np = inet6_sk(sk);\n\tstruct net *net = sock_net(sk);\n",
            "struct net *net = sock_net(sk);\n",
            1,
        )
        ip6_output_changed = True
    if "bool ip6_autoflowlabel(struct net *net, const struct sock *sk)" not in ip6_output_text:
        ip6_output_text = replace_once(
            ip6_output_text,
            "bool ip6_autoflowlabel(struct net *net, const struct ipv6_pinfo *np)\n{\n\tif (!np->autoflowlabel_set)\n\t\treturn ip6_default_np_autolabel(net);\n\telse\n\t\treturn np->autoflowlabel;\n}\n",
            compat_np_autoflowlabel,
            "network_porting/ip6_output_autoflowlabel",
        )
        ip6_output_text = replace_once(
            ip6_output_text,
            "ip6_flow_hdr(hdr, tclass, ip6_make_flowlabel(net, skb, fl6->flowlabel,\n\t\t\t\tip6_autoflowlabel(net, np), fl6));\n",
            "ip6_flow_hdr(hdr, tclass, ip6_make_flowlabel(net, skb, fl6->flowlabel,\n\t\t\t\tip6_autoflowlabel(net, sk), fl6));\n",
            "network_porting/ip6_output_flow_hdr",
        )
        ip6_output_text = replace_once(
            ip6_output_text,
            "\tip6_flow_hdr(hdr, v6_cork->tclass,\n\t\t     ip6_make_flowlabel(net, skb, fl6->flowlabel,\n\t\t\t\t\tip6_autoflowlabel(net, np), fl6));\n",
            "\tip6_flow_hdr(hdr, v6_cork->tclass,\n\t\t     ip6_make_flowlabel(net, skb, fl6->flowlabel,\n\t\t\t\t\tip6_autoflowlabel(net, sk), fl6));\n",
            "network_porting/ip6_output_flow_hdr_late",
        )
        ip6_output_text = replace_once(
            ip6_output_text,
            "\tstruct ipv6_pinfo *np = inet6_sk(sk);\n",
            "",
            "network_porting/ip6_output_drop_unused_np",
        )
        ip6_output_changed = True
    if ip6_output_changed:
        write_text(ip6_output_c, ip6_output_text)

    ipv6_sockglue_text = read_text(ipv6_sockglue_c)
    if "ip6_autoflowlabel(sock_net(sk), sk)" not in ipv6_sockglue_text:
        ipv6_sockglue_text = replace_once(
            ipv6_sockglue_text,
            "\t\tval = ip6_autoflowlabel(sock_net(sk), np);\n",
            "\t\tval = ip6_autoflowlabel(sock_net(sk), sk);\n",
            "network_porting/ipv6_sockglue_autoflowlabel_get",
        )
        write_text(ipv6_sockglue_c, ipv6_sockglue_text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="file_local_helper",
        ),
        "group": "net_flow_info_cache_ipv6",
        "status": "main_path_grafted",
        "phase": "flowlabel_dst_cookie_cork_hotpath_main_path",
        "target_shape": "socket_dst_cookie_and_autoflowlabel_refresh",
        "tree_escalation_required": False,
        "marker": "ABK network_porting: IPv6 flow/cache hotpath graft keeps cork-backed flow state and socket dst-cookie reuse in net/ + include/net/ only.",
    }


def patch_accecn_core(common_root: Path) -> dict[str, object]:
    tcp_h = common_root / "include/net/tcp.h"
    tcp_ecn_h = common_root / "include/net/tcp_ecn.h"
    tcp_ipv4_c = common_root / "net/ipv4/tcp_ipv4.c"
    sysctl_ipv4_c = common_root / "net/ipv4/sysctl_net_ipv4.c"
    netns_ipv4_h = common_root / "include/net/netns/ipv4.h"

    tcp_h_text = read_text(tcp_h)
    if "TCP_ECN_MODE_RFC3168" not in tcp_h_text:
        tcp_h_text = replace_once(
            tcp_h_text,
            "#define\tTCP_ECN_OK\t\t1\n#define\tTCP_ECN_QUEUE_CWR\t2\n#define\tTCP_ECN_DEMAND_CWR\t4\n#define\tTCP_ECN_SEEN\t\t8\n",
            "#define\tTCP_ECN_MODE_RFC3168\tBIT(0)\n#define\tTCP_ECN_QUEUE_CWR\tBIT(1)\n#define\tTCP_ECN_DEMAND_CWR\tBIT(2)\n#define\tTCP_ECN_SEEN\t\tBIT(3)\n#define\tTCP_ECN_MODE_ACCECN\tBIT(4)\n\n#define\tTCP_ECN_DISABLED\t0\n#define\tTCP_ECN_MODE_PENDING\t(TCP_ECN_MODE_RFC3168 | TCP_ECN_MODE_ACCECN)\n#define\tTCP_ECN_MODE_ANY\t(TCP_ECN_MODE_RFC3168 | TCP_ECN_MODE_ACCECN)\n\nstatic inline bool tcp_ecn_mode_any(const struct tcp_sock *tp)\n{\n\treturn tp->ecn_flags & TCP_ECN_MODE_ANY;\n}\n\nstatic inline bool tcp_ecn_mode_rfc3168(const struct tcp_sock *tp)\n{\n\treturn (tp->ecn_flags & TCP_ECN_MODE_ANY) == TCP_ECN_MODE_RFC3168;\n}\n\nstatic inline bool tcp_ecn_mode_accecn(const struct tcp_sock *tp)\n{\n\treturn (tp->ecn_flags & TCP_ECN_MODE_ANY) == TCP_ECN_MODE_ACCECN;\n}\n\nstatic inline bool tcp_ecn_disabled(const struct tcp_sock *tp)\n{\n\treturn !tcp_ecn_mode_any(tp);\n}\n\nstatic inline bool tcp_ecn_mode_pending(const struct tcp_sock *tp)\n{\n\treturn (tp->ecn_flags & TCP_ECN_MODE_PENDING) == TCP_ECN_MODE_PENDING;\n}\n\nstatic inline void tcp_ecn_mode_set(struct tcp_sock *tp, u8 mode)\n{\n\ttp->ecn_flags &= ~TCP_ECN_MODE_ANY;\n\ttp->ecn_flags |= mode;\n}\n",
            "network_porting/tcp_h_ecn_mode_core",
        )
        tcp_h_text = replace_once(
            tcp_h_text,
            "/* Algorithm can be set on socket without CAP_NET_ADMIN privileges */\n#define TCP_CONG_NON_RESTRICTED 0x1\n/* Requires ECN/ECT set on all packets */\n#define TCP_CONG_NEEDS_ECN\t0x2\n#define TCP_CONG_MASK\t(TCP_CONG_NON_RESTRICTED | TCP_CONG_NEEDS_ECN)\n",
            "/* Algorithm can be set on socket without CAP_NET_ADMIN privileges */\n#define TCP_CONG_NON_RESTRICTED\t\tBIT(0)\n/* Requires ECN/ECT set on all packets */\n#define TCP_CONG_NEEDS_ECN\t\tBIT(1)\n/* Require successfully negotiated AccECN capability */\n#define TCP_CONG_NEEDS_ACCECN\t\tBIT(2)\n/* Use ECT(1) instead of ECT(0) while the CA is uninitialized */\n#define TCP_CONG_ECT_1_NEGOTIATION\tBIT(3)\n/* Cannot fallback to RFC3168 during AccECN negotiation */\n#define TCP_CONG_NO_FALLBACK_RFC3168\tBIT(4)\n#define TCP_CONG_MASK  (TCP_CONG_NON_RESTRICTED | TCP_CONG_NEEDS_ECN | \\\n\t\t\tTCP_CONG_NEEDS_ACCECN | TCP_CONG_ECT_1_NEGOTIATION | \\\n\t\t\tTCP_CONG_NO_FALLBACK_RFC3168)\n",
            "network_porting/tcp_h_cong_flags",
        )
        tcp_h_text = replace_once(
            tcp_h_text,
            "static inline bool tcp_ca_needs_ecn(const struct sock *sk)\n{\n\tconst struct inet_connection_sock *icsk = inet_csk(sk);\n\n\treturn icsk->icsk_ca_ops->flags & TCP_CONG_NEEDS_ECN;\n}\n",
            "static inline bool tcp_ca_needs_ecn(const struct sock *sk)\n{\n\tconst struct inet_connection_sock *icsk = inet_csk(sk);\n\n\treturn icsk->icsk_ca_ops->flags & TCP_CONG_NEEDS_ECN;\n}\n\nstatic inline bool tcp_ca_needs_accecn(const struct sock *sk)\n{\n\tconst struct inet_connection_sock *icsk = inet_csk(sk);\n\n\treturn icsk->icsk_ca_ops->flags & TCP_CONG_NEEDS_ACCECN;\n}\n\nstatic inline bool tcp_ca_ect_1_negotiation(const struct sock *sk)\n{\n\tconst struct inet_connection_sock *icsk = inet_csk(sk);\n\n\treturn icsk->icsk_ca_ops->flags & TCP_CONG_ECT_1_NEGOTIATION;\n}\n\nstatic inline bool tcp_ca_no_fallback_rfc3168(const struct sock *sk)\n{\n\tconst struct inet_connection_sock *icsk = inet_csk(sk);\n\n\treturn icsk->icsk_ca_ops->flags & TCP_CONG_NO_FALLBACK_RFC3168;\n}\n",
            "network_porting/tcp_h_cong_helpers",
        )
    marker = "/* ABK network_porting: bounded AccECN mode/core helper graft fits 6.1 include/net + net/ipv4 anchors without tcp struct growth. */\n"
    if "#define\tTCP_ECN_OK\t\tTCP_ECN_MODE_RFC3168\n" not in tcp_h_text and "TCP_ECN_MODE_RFC3168" in tcp_h_text:
        tcp_h_text = tcp_h_text.replace(
            "#define\tTCP_ECN_MODE_ANY\t(TCP_ECN_MODE_RFC3168 | TCP_ECN_MODE_ACCECN)\n",
            "#define\tTCP_ECN_MODE_ANY\t(TCP_ECN_MODE_RFC3168 | TCP_ECN_MODE_ACCECN)\n#define\tTCP_ECN_OK\t\tTCP_ECN_MODE_RFC3168\n",
            1,
        )
    if marker not in tcp_h_text:
        tcp_h_text = tcp_h_text.replace(
            "enum tcp_tw_status {\n",
            marker + "enum tcp_tw_status {\n",
            1,
        )
    write_text(tcp_h, tcp_h_text)

    netns_text = read_text(netns_ipv4_h)
    if "sysctl_tcp_ecn_option" not in netns_text:
        netns_text = replace_once(
            netns_text,
            "\tu8 sysctl_tcp_ecn;\n\tu8 sysctl_tcp_ecn_fallback;\n",
            "\tu8 sysctl_tcp_ecn;\n\tu8 sysctl_tcp_ecn_option;\n\tu8 sysctl_tcp_ecn_option_beacon;\n\tu8 sysctl_tcp_ecn_fallback;\n",
            "network_porting/netns_ipv4_accecn_sysctls",
        )
        write_text(netns_ipv4_h, netns_text)

    if not tcp_ecn_h.exists():
        write_text(
            tcp_ecn_h,
            """/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef _TCP_ECN_H
#define _TCP_ECN_H

#include <net/inet_ecn.h>
#include <net/tcp.h>

/* ABK network_porting: bounded AccECN helper graft fits 6.1 without include/linux/tcp.h layout growth. */
enum tcp_accecn_option {
\tTCP_ACCECN_OPTION_DISABLED = 0,
\tTCP_ACCECN_OPTION_MINIMUM = 1,
\tTCP_ACCECN_OPTION_FULL = 2,
\tTCP_ACCECN_OPTION_BEACON = 3,
};

static inline bool tcp_accecn_any_enabled(const struct sock *sk)
{
\treturn READ_ONCE(sock_net(sk)->ipv4.sysctl_tcp_ecn_option) != TCP_ACCECN_OPTION_DISABLED;
}

static inline bool tcp_accecn_option_beacon_check(const struct sock *sk)
{
\treturn READ_ONCE(sock_net(sk)->ipv4.sysctl_tcp_ecn_option_beacon) != TCP_ACCECN_OPTION_DISABLED;
}

static inline bool tcp_accecn_option_requested(const struct sock *sk)
{
\treturn tcp_ca_needs_accecn(sk) || tcp_accecn_any_enabled(sk);
}

static inline bool tcp_accecn_fallback_blocked(const struct sock *sk)
{
\treturn tcp_ca_no_fallback_rfc3168(sk);
}

static inline bool tcp_accecn_path_capable(const struct sock *sk)
{
\treturn tcp_accecn_option_requested(sk) && !tcp_accecn_fallback_blocked(sk);
}

#endif
""",
        )

    tcp_ipv4_text = read_text(tcp_ipv4_c)
    if "#include <net/tcp_ecn.h>" not in tcp_ipv4_text:
        tcp_ipv4_text = replace_once(
            tcp_ipv4_text,
            "#include <net/tcp.h>\n",
            "#include <net/tcp.h>\n#include <net/tcp_ecn.h>\n",
            "network_porting/tcp_ipv4_include_tcp_ecn",
        )
    if "sysctl_tcp_ecn_option" not in tcp_ipv4_text and "sysctl_tcp_ecn_fallback = 1;" in tcp_ipv4_text:
        tcp_ipv4_text = replace_once(
            tcp_ipv4_text,
            "\tnet->ipv4.sysctl_tcp_ecn = 2;\n\tnet->ipv4.sysctl_tcp_ecn_fallback = 1;\n",
            "\tnet->ipv4.sysctl_tcp_ecn = 2;\n\tnet->ipv4.sysctl_tcp_ecn_option = TCP_ACCECN_OPTION_DISABLED;\n\tnet->ipv4.sysctl_tcp_ecn_option_beacon = TCP_ACCECN_OPTION_DISABLED;\n\tnet->ipv4.sysctl_tcp_ecn_fallback = 1;\n",
            "network_porting/tcp_ipv4_default_sysctls",
        )
    write_text(tcp_ipv4_c, tcp_ipv4_text)

    sysctl_text = read_text(sysctl_ipv4_c)
    if "tcp_ecn_option_beacon" not in sysctl_text:
        sysctl_text = replace_once(
            sysctl_text,
            "\t{\n\t\t.procname\t= \"tcp_ecn_fallback\",\n\t\t.data\t\t= &init_net.ipv4.sysctl_tcp_ecn_fallback,\n\t\t.maxlen\t\t= sizeof(u8),\n\t\t.mode\t\t= 0644,\n\t\t.proc_handler\t= proc_dou8vec_minmax,\n\t\t.extra1\t\t= SYSCTL_ZERO,\n\t\t.extra2\t\t= SYSCTL_ONE,\n\t},\n",
            "\t{\n\t\t.procname\t= \"tcp_ecn_fallback\",\n\t\t.data\t\t= &init_net.ipv4.sysctl_tcp_ecn_fallback,\n\t\t.maxlen\t\t= sizeof(u8),\n\t\t.mode\t\t= 0644,\n\t\t.proc_handler\t= proc_dou8vec_minmax,\n\t\t.extra1\t\t= SYSCTL_ZERO,\n\t\t.extra2\t\t= SYSCTL_ONE,\n\t},\n\t{\n\t\t.procname\t= \"tcp_ecn_option\",\n\t\t.data\t\t= &init_net.ipv4.sysctl_tcp_ecn_option,\n\t\t.maxlen\t\t= sizeof(u8),\n\t\t.mode\t\t= 0644,\n\t\t.proc_handler\t= proc_dou8vec_minmax,\n\t\t.extra1\t\t= SYSCTL_ZERO,\n\t\t.extra2\t\t= SYSCTL_THREE,\n\t},\n\t{\n\t\t.procname\t= \"tcp_ecn_option_beacon\",\n\t\t.data\t\t= &init_net.ipv4.sysctl_tcp_ecn_option_beacon,\n\t\t.maxlen\t\t= sizeof(u8),\n\t\t.mode\t\t= 0644,\n\t\t.proc_handler\t= proc_dou8vec_minmax,\n\t\t.extra1\t\t= SYSCTL_ZERO,\n\t\t.extra2\t\t= SYSCTL_THREE,\n\t},\n",
            "network_porting/sysctl_ipv4_accecn_entries",
        )
        write_text(sysctl_ipv4_c, sysctl_text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=True,
            new_interface_scope="internal_static_api",
        ),
        "group": "net_accecn_core",
        "status": "partial",
        "phase": "helper_header_and_sysctl_shell_only",
        "target_shape": "include_net_mode_helpers_and_ipv4_report_state_only",
        "tree_escalation_required": False,
        "boot_safe_priority": True,
        "blocked": [
            "blocked_by_missing_6_1_anchor: include/linux/tcp.h request_sock and tcp_sock AccECN state expansion stays outside this bounded batch",
            "blocked_by_missing_6_1_anchor: full ACE/counter accounting requires tcp_sock fields absent from the 6.1 target",
            "deferred_for_boot_safety: tcp_output/tcp_input/tcp_timer/tcp.c mainline AccECN semantics stay on the conservative 6.1 path in this batch",
        ],
        "marker": "ABK network_porting: bounded AccECN mode/core helper graft fits 6.1 include/net + net/ipv4 anchors without tcp struct growth.",
    }


def patch_accecn_protocol_mainline(common_root: Path) -> dict[str, object]:
    tcp_input_c = common_root / "net/ipv4/tcp_input.c"
    tcp_output_c = common_root / "net/ipv4/tcp_output.c"
    tcp_timer_c = common_root / "net/ipv4/tcp_timer.c"
    tcp_c = common_root / "net/ipv4/tcp.c"

    tcp_output_text = read_text(tcp_output_c)
    tcp_output_text = tcp_output_text.replace("#include <net/tcp_ecn.h>\n", "", 1)
    tcp_output_text = tcp_output_text.replace(
        "/* Set up ECN state for a packet on a ESTABLISHED socket that is about to\n * be sent.\n */\nstatic void tcp_ecn_send(struct sock *sk, struct sk_buff *skb,\n\t\t\t struct tcphdr *th, int tcp_header_len)\n{\n\tstruct tcp_sock *tp = tcp_sk(sk);\n\n\tif (!tcp_ecn_mode_any(tp))\n\t\treturn;\n\n\tif (tcp_ecn_mode_accecn(tp)) {\n\t\t/* ABK network_porting: AccECN core is grafted only at the mode and path gate layer on 6.1 anchors. */\n\t\tINET_ECN_xmit(sk);\n\t\tskb_shinfo(skb)->gso_type |= SKB_GSO_TCP_ECN;\n\t} else {\n\t\t/* Not-retransmitted data segment: set ECT and inject CWR. */\n\t\tif (skb->len != tcp_header_len &&\n\t\t    !before(TCP_SKB_CB(skb)->seq, tp->snd_nxt)) {\n\t\t\tINET_ECN_xmit(sk);\n\t\t\tif (tp->ecn_flags & TCP_ECN_QUEUE_CWR) {\n\t\t\t\ttp->ecn_flags &= ~TCP_ECN_QUEUE_CWR;\n\t\t\t\tth->cwr = 1;\n\t\t\t\tskb_shinfo(skb)->gso_type |= SKB_GSO_TCP_ECN;\n\t\t\t}\n\t\t} else if (!tcp_ca_needs_ecn(sk)) {\n\t\t\t/* ACK or retransmitted segment: clear ECT|CE */\n\t\t\tINET_ECN_dontxmit(sk);\n\t\t}\n\t\tif (tp->ecn_flags & TCP_ECN_DEMAND_CWR)\n\t\t\tth->ece = 1;\n\t}\n}\n",
        "/* Set up ECN state for a packet on a ESTABLISHED socket that is about to\n * be sent.\n */\nstatic void tcp_ecn_send(struct sock *sk, struct sk_buff *skb,\n\t\t\t struct tcphdr *th, int tcp_header_len)\n{\n\tstruct tcp_sock *tp = tcp_sk(sk);\n\n\tif (tp->ecn_flags & TCP_ECN_OK) {\n\t\t/* Not-retransmitted data segment: set ECT and inject CWR. */\n\t\tif (skb->len != tcp_header_len &&\n\t\t    !before(TCP_SKB_CB(skb)->seq, tp->snd_nxt)) {\n\t\t\tINET_ECN_xmit(sk);\n\t\t\tif (tp->ecn_flags & TCP_ECN_QUEUE_CWR) {\n\t\t\t\ttp->ecn_flags &= ~TCP_ECN_QUEUE_CWR;\n\t\t\t\tth->cwr = 1;\n\t\t\t\tskb_shinfo(skb)->gso_type |= SKB_GSO_TCP_ECN;\n\t\t\t}\n\t\t} else if (!tcp_ca_needs_ecn(sk)) {\n\t\t\t/* ACK or retransmitted segment: clear ECT|CE */\n\t\t\tINET_ECN_dontxmit(sk);\n\t\t}\n\t\tif (tp->ecn_flags & TCP_ECN_DEMAND_CWR)\n\t\t\tth->ece = 1;\n\t}\n}\n",
        1,
    )
    tcp_output_text = tcp_output_text.replace(
        "static void tcp_ecn_send_synack(struct sock *sk, struct sk_buff *skb)\n{\n\tconst struct tcp_sock *tp = tcp_sk(sk);\n\n\t/* ABK network_porting: bounded AccECN SYN/SYN-ACK send path keeps negotiation inside 6.1 mode bits and sysctls. */\n\tTCP_SKB_CB(skb)->tcp_flags &= ~TCPHDR_CWR;\n\tif (tcp_ecn_mode_accecn(tp) && tcp_accecn_path_capable(sk)) {\n\t\tTCP_SKB_CB(skb)->tcp_flags |= TCPHDR_ECE;\n\t} else if (!(tp->ecn_flags & TCP_ECN_OK)) {\n\t\tTCP_SKB_CB(skb)->tcp_flags &= ~TCPHDR_ECE;\n\t} else if (tcp_ca_needs_ecn(sk) ||\n\t\t   tcp_bpf_ca_needs_ecn(sk)) {\n\t\tINET_ECN_xmit(sk);\n\t}\n}\n",
        "static void tcp_ecn_send_synack(struct sock *sk, struct sk_buff *skb)\n{\n\tconst struct tcp_sock *tp = tcp_sk(sk);\n\n\tTCP_SKB_CB(skb)->tcp_flags &= ~TCPHDR_CWR;\n\tif (!(tp->ecn_flags & TCP_ECN_OK))\n\t\tTCP_SKB_CB(skb)->tcp_flags &= ~TCPHDR_ECE;\n\telse if (tcp_ca_needs_ecn(sk) ||\n\t\t tcp_bpf_ca_needs_ecn(sk))\n\t\tINET_ECN_xmit(sk);\n}\n",
        1,
    )
    tcp_output_text = tcp_output_text.replace(
        "static void tcp_ecn_send_syn(struct sock *sk, struct sk_buff *skb)\n{\n\tstruct tcp_sock *tp = tcp_sk(sk);\n\tbool bpf_needs_ecn = tcp_bpf_ca_needs_ecn(sk);\n\tbool use_accecn = tcp_accecn_path_capable(sk);\n\tbool use_ecn = READ_ONCE(sock_net(sk)->ipv4.sysctl_tcp_ecn) == 1 ||\n\t\ttcp_ca_needs_ecn(sk) || bpf_needs_ecn || use_accecn;\n\n\tif (!use_ecn) {\n\t\tconst struct dst_entry *dst = __sk_dst_get(sk);\n\n\t\tif (dst && dst_feature(dst, RTAX_FEATURE_ECN))\n\t\t\tuse_ecn = true;\n\t}\n\n\ttp->ecn_flags = 0;\n\n\tif (use_ecn) {\n\t\tTCP_SKB_CB(skb)->tcp_flags |= TCPHDR_ECE | TCPHDR_CWR;\n\t\tif (use_accecn)\n\t\t\ttcp_ecn_mode_set(tp, TCP_ECN_MODE_PENDING);\n\t\telse\n\t\t\ttp->ecn_flags = TCP_ECN_OK;\n\t\tif (tcp_ca_needs_ecn(sk) || bpf_needs_ecn)\n\t\t\tINET_ECN_xmit(sk);\n\t}\n}\n",
        "static void tcp_ecn_send_syn(struct sock *sk, struct sk_buff *skb)\n{\n\tstruct tcp_sock *tp = tcp_sk(sk);\n\tbool bpf_needs_ecn = tcp_bpf_ca_needs_ecn(sk);\n\tbool use_ecn = READ_ONCE(sock_net(sk)->ipv4.sysctl_tcp_ecn) == 1 ||\n\t\ttcp_ca_needs_ecn(sk) || bpf_needs_ecn;\n\n\tif (!use_ecn) {\n\t\tconst struct dst_entry *dst = __sk_dst_get(sk);\n\n\t\tif (dst && dst_feature(dst, RTAX_FEATURE_ECN))\n\t\t\tuse_ecn = true;\n\t}\n\n\ttp->ecn_flags = 0;\n\n\tif (use_ecn) {\n\t\tTCP_SKB_CB(skb)->tcp_flags |= TCPHDR_ECE | TCPHDR_CWR;\n\t\ttp->ecn_flags = TCP_ECN_OK;\n\t\tif (tcp_ca_needs_ecn(sk) || bpf_needs_ecn)\n\t\t\tINET_ECN_xmit(sk);\n\t}\n}\n",
        1,
    )
    write_text(tcp_output_c, tcp_output_text)

    tcp_input_text = read_text(tcp_input_c)
    tcp_input_text = tcp_input_text.replace("#include <net/tcp_ecn.h>\n", "", 1)
    tcp_input_text = tcp_input_text.replace(
        "static void tcp_ecn_check_ce(struct sock *sk, const struct sk_buff *skb)\n{\n\tstruct tcp_sock *tp = tcp_sk(sk);\n\n\t/* ABK network_porting: bounded AccECN receive gate keeps 6.1 on helper-backed mode checks only. */\n\tif (tcp_ecn_mode_accecn(tp) && !tcp_accecn_path_capable(sk))\n\t\ttcp_ecn_mode_set(tp, TCP_ECN_MODE_RFC3168);\n\tif (tp->ecn_flags & TCP_ECN_OK)\n\t\t__tcp_ecn_check_ce(sk, skb);\n}\n",
        "static void tcp_ecn_check_ce(struct sock *sk, const struct sk_buff *skb)\n{\n\tif (tcp_sk(sk)->ecn_flags & TCP_ECN_OK)\n\t\t__tcp_ecn_check_ce(sk, skb);\n}\n",
        1,
    )
    tcp_input_text = tcp_input_text.replace(
        "static void tcp_ecn_rcv_synack(struct tcp_sock *tp, const struct tcphdr *th)\n{\n\t/* ABK network_porting: bounded AccECN receive negotiation keeps SYN and SYN/ACK fallback inside 6.1-capable gates. */\n\tif (tcp_ecn_mode_pending(tp)) {\n\t\tif (!th->ece || th->cwr)\n\t\t\ttcp_ecn_mode_set(tp, TCP_ECN_MODE_RFC3168);\n\t\telse\n\t\t\ttcp_ecn_mode_set(tp, TCP_ECN_MODE_ACCECN);\n\t\treturn;\n\t}\n\tif ((tp->ecn_flags & TCP_ECN_OK) && (!th->ece || th->cwr))\n\t\ttp->ecn_flags &= ~TCP_ECN_OK;\n}\n",
        "static void tcp_ecn_rcv_synack(struct tcp_sock *tp, const struct tcphdr *th)\n{\n\tif ((tp->ecn_flags & TCP_ECN_OK) && (!th->ece || th->cwr))\n\t\ttp->ecn_flags &= ~TCP_ECN_OK;\n}\n",
        1,
    )
    tcp_input_text = tcp_input_text.replace(
        "static void tcp_ecn_rcv_syn(struct tcp_sock *tp, const struct tcphdr *th)\n{\n\tif (tcp_ecn_mode_pending(tp)) {\n\t\tif (!th->ece || !th->cwr)\n\t\t\ttcp_ecn_mode_set(tp, TCP_ECN_MODE_RFC3168);\n\t\telse\n\t\t\ttcp_ecn_mode_set(tp, TCP_ECN_MODE_ACCECN);\n\t\treturn;\n\t}\n\tif ((tp->ecn_flags & TCP_ECN_OK) && (!th->ece || !th->cwr))\n\t\ttp->ecn_flags &= ~TCP_ECN_OK;\n}\n",
        "static void tcp_ecn_rcv_syn(struct tcp_sock *tp, const struct tcphdr *th)\n{\n\tif ((tp->ecn_flags & TCP_ECN_OK) && (!th->ece || !th->cwr))\n\t\ttp->ecn_flags &= ~TCP_ECN_OK;\n}\n",
        1,
    )
    tcp_input_text = tcp_input_text.replace(
        "static void tcp_ecn_create_request(struct request_sock *req,\n\t\t\t\t   const struct sk_buff *skb,\n\t\t\t\t   const struct sock *listen_sk,\n\t\t\t\t   const struct dst_entry *dst)\n{\n\tconst struct tcphdr *th = tcp_hdr(skb);\n\tconst struct net *net = sock_net(listen_sk);\n\tbool th_ecn = th->ece && th->cwr;\n\tbool ect, ecn_ok;\n\tu32 ecn_ok_dst;\n\n\t/* ABK network_porting: bounded AccECN listener request gate accepts future-ecn negotiation only when 6.1 path helpers can carry it. */\n\tif (th->res1 && th_ecn && tcp_accecn_option_requested(listen_sk)) {\n\t\tinet_rsk(req)->ecn_ok = 1;\n\t\treturn;\n\t}\n\tif (!th_ecn)\n\t\treturn;\n\n\tect = !INET_ECN_is_not_ect(TCP_SKB_CB(skb)->ip_dsfield);\n\tecn_ok_dst = dst_feature(dst, DST_FEATURE_ECN_MASK);\n\tecn_ok = READ_ONCE(net->ipv4.sysctl_tcp_ecn) || ecn_ok_dst;\n\n\tif (((!ect || th->res1) && ecn_ok) || tcp_ca_needs_ecn(listen_sk) ||\n\t    (ecn_ok_dst & DST_FEATURE_ECN_CA) ||\n\t    tcp_bpf_ca_needs_ecn((struct sock *)req))\n\t\tinet_rsk(req)->ecn_ok = 1;\n}\n",
        "static void tcp_ecn_create_request(struct request_sock *req,\n\t\t\t\t   const struct sk_buff *skb,\n\t\t\t\t   const struct sock *listen_sk,\n\t\t\t\t   const struct dst_entry *dst)\n{\n\tconst struct tcphdr *th = tcp_hdr(skb);\n\tconst struct net *net = sock_net(listen_sk);\n\tbool th_ecn = th->ece && th->cwr;\n\tbool ect, ecn_ok;\n\tu32 ecn_ok_dst;\n\n\tif (!th_ecn)\n\t\treturn;\n\n\tect = !INET_ECN_is_not_ect(TCP_SKB_CB(skb)->ip_dsfield);\n\tecn_ok_dst = dst_feature(dst, DST_FEATURE_ECN_MASK);\n\tecn_ok = READ_ONCE(net->ipv4.sysctl_tcp_ecn) || ecn_ok_dst;\n\n\tif (((!ect || th->res1) && ecn_ok) || tcp_ca_needs_ecn(listen_sk) ||\n\t    (ecn_ok_dst & DST_FEATURE_ECN_CA) ||\n\t    tcp_bpf_ca_needs_ecn((struct sock *)req))\n\t\tinet_rsk(req)->ecn_ok = 1;\n}\n",
        1,
    )
    write_text(tcp_input_c, tcp_input_text)

    tcp_timer_text = read_text(tcp_timer_c)
    tcp_timer_text = tcp_timer_text.replace(
        "static int tcp_write_timeout(struct sock *sk)\n{\n\tstruct inet_connection_sock *icsk = inet_csk(sk);\n\tstruct tcp_sock *tp = tcp_sk(sk);\n\tstruct net *net = sock_net(sk);\n\tbool expired = false, do_reset;\n\tint retry_until;\n\n\t/* ABK network_porting: bounded AccECN retrans/timeouts fall back to RFC3168 before socket timeout escalation. */\n\tif (tcp_ecn_mode_pending(tp) && icsk->icsk_retransmits)\n\t\ttcp_ecn_mode_set(tp, TCP_ECN_MODE_RFC3168);\n",
        "static int tcp_write_timeout(struct sock *sk)\n{\n\tstruct inet_connection_sock *icsk = inet_csk(sk);\n\tstruct tcp_sock *tp = tcp_sk(sk);\n\tstruct net *net = sock_net(sk);\n\tbool expired = false, do_reset;\n\tint retry_until;\n",
        1,
    )
    tcp_timer_text = tcp_timer_text.replace(
        "\treq = rcu_dereference_protected(tp->fastopen_rsk,\n\t\t\t\t\tlockdep_sock_is_held(sk));\n\tif (req) {\n\t\tif (tcp_ecn_mode_pending(tp) && inet_rsk(req)->ecn_ok)\n\t\t\ttcp_ecn_mode_set(tp, TCP_ECN_MODE_RFC3168);\n",
        "\treq = rcu_dereference_protected(tp->fastopen_rsk,\n\t\t\t\t\tlockdep_sock_is_held(sk));\n\tif (req) {\n",
        1,
    )
    write_text(tcp_timer_c, tcp_timer_text)

    tcp_text = read_text(tcp_c)
    tcp_text = tcp_text.replace(
        "\t/* ABK network_porting: TCP_INFO reports bounded AccECN mode bits without exposing unsupported 6.1 accounting fields. */\n\tif (tcp_ecn_mode_any(tp) || (tp->ecn_flags & TCP_ECN_OK))\n\t\tinfo->tcpi_options |= TCPI_OPT_ECN;\n\tif (tp->ecn_flags & TCP_ECN_SEEN)\n\t\tinfo->tcpi_options |= TCPI_OPT_ECN_SEEN;\n",
        "\tif (tp->ecn_flags & TCP_ECN_OK)\n\t\tinfo->tcpi_options |= TCPI_OPT_ECN;\n\tif (tp->ecn_flags & TCP_ECN_SEEN)\n\t\tinfo->tcpi_options |= TCPI_OPT_ECN_SEEN;\n",
        1,
    )
    write_text(tcp_c, tcp_text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=False,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=False,
            new_interface_scope="none",
        ),
        "group": "net_accecn_mainline_protocol",
        "status": "deferred",
        "phase": "boot_safe_mainline_semantics_deferred",
        "tree_escalation_required": False,
        "boot_safe_priority": True,
        "deferred": [
            "deferred_for_boot_safety: tcp_output.c AccECN SYN/SYN-ACK and established-path semantics are intentionally left on the conservative 6.1 baseline",
            "deferred_for_boot_safety: tcp_input.c receive negotiation and request creation stay on the conservative 6.1 baseline",
            "deferred_for_boot_safety: tcp_timer.c retrans/timeout fallback and tcp.c TCP_INFO reporting stay on the conservative 6.1 baseline",
            "blocked_by_driver_scope: AccECN GSO/offload and feature-bit plumbing remain out of scope",
        ],
        "marker": "ABK network_porting: AccECN mainline protocol semantics stay deferred while boot compatibility takes priority over send/recv/timer expansion.",
    }


def patch_accecn_path_fixups(common_root: Path) -> dict[str, object]:
    tcp_minisocks_c = common_root / "net/ipv4/tcp_minisocks.c"
    syncookies_c = common_root / "net/ipv4/syncookies.c"
    text = read_text(tcp_minisocks_c)
    applied = False
    if "#include <net/tcp_ecn.h>" not in text:
        text = replace_once(
            text,
            "#include <net/tcp.h>\n",
            "#include <net/tcp.h>\n#include <net/tcp_ecn.h>\n",
            "network_porting/tcp_minisocks_include_tcp_ecn",
        )
        applied = True
    conservative_openreq_child = "static void tcp_ecn_openreq_child(struct sock *sk,\n\t\t\t\t  const struct request_sock *req)\n{\n\tstruct tcp_sock *tp = tcp_sk(sk);\n\n\tif (!inet_rsk(req)->ecn_ok) {\n\t\ttcp_ecn_mode_set(tp, TCP_ECN_DISABLED);\n\t\treturn;\n\t}\n\n\t/* ABK network_porting: keep child sockets on RFC3168-compatible mode until the full AccECN mainline path is proven boot-safe on 6.1. */\n\ttcp_ecn_mode_set(tp, TCP_ECN_MODE_RFC3168);\n}\n"
    if conservative_openreq_child not in text:
        text = replace_any_once(
            text,
            (
                "static void tcp_ecn_openreq_child(struct tcp_sock *tp,\n\t\t\t\t  const struct request_sock *req)\n{\n\ttp->ecn_flags = inet_rsk(req)->ecn_ok ? TCP_ECN_OK : 0;\n}\n",
                "static void tcp_ecn_openreq_child(struct sock *sk,\n\t\t\t\t  const struct request_sock *req,\n\t\t\t\t  const struct sk_buff *skb)\n{\n\tstruct tcp_sock *tp = tcp_sk(sk);\n\n\tif (!inet_rsk(req)->ecn_ok) {\n\t\ttcp_ecn_mode_set(tp, TCP_ECN_DISABLED);\n\t\treturn;\n\t}\n\n\tif (tcp_accecn_path_capable(sk) && skb)\n\t\ttcp_ecn_mode_set(tp, TCP_ECN_MODE_ACCECN);\n\telse\n\t\ttcp_ecn_mode_set(tp, TCP_ECN_MODE_RFC3168);\n}\n",
            ),
            conservative_openreq_child,
            "network_porting/tcp_minisocks_openreq_child",
        )
        text = replace_any_once(
            text,
            (
                "\ttcp_ecn_openreq_child(newtp, req);\n",
                "\ttcp_ecn_openreq_child(newsk, req, skb);\n",
            ),
            "\ttcp_ecn_openreq_child(newsk, req);\n",
            "network_porting/tcp_minisocks_openreq_callsite",
        )
        applied = True
    if applied:
        marker = "/* ABK network_porting: AccECN path fixups cover child/openreq and syncookie negotiation glue only; request-sock state expansion remains deferred. */\n"
        if marker not in text:
            text = text.replace(
                "static void tcp_ecn_openreq_child(struct sock *sk,\n",
                marker + "static void tcp_ecn_openreq_child(struct sock *sk,\n",
                1,
            )
        write_text(tcp_minisocks_c, text)

    syncookies_text = read_text(syncookies_c)
    sync_applied = False
    if "#include <net/tcp_ecn.h>" not in syncookies_text:
        syncookies_text = replace_once(
            syncookies_text,
            "#include <net/tcp.h>\n",
            "#include <net/tcp.h>\n#include <net/tcp_ecn.h>\n",
            "network_porting/syncookies_include_tcp_ecn",
        )
        sync_applied = True
    if "ABK network_porting: syncookie AccECN glue keeps only ECN-option eligibility inside net/ + include/net/." not in syncookies_text:
        syncookies_text = replace_once(
            syncookies_text,
            "bool cookie_ecn_ok(const struct tcp_options_received *tcp_opt,\n\t\t   const struct net *net, const struct dst_entry *dst)\n{\n\tbool ecn_ok = tcp_opt->rcv_tsecr & TS_OPT_ECN;\n\n\tif (!ecn_ok)\n\t\treturn false;\n\n\tif (READ_ONCE(net->ipv4.sysctl_tcp_ecn))\n\t\treturn true;\n\n\treturn dst_feature(dst, RTAX_FEATURE_ECN);\n}\n",
            "bool cookie_ecn_ok(const struct tcp_options_received *tcp_opt,\n\t\t   const struct net *net, const struct dst_entry *dst)\n{\n\tbool ecn_ok = tcp_opt->rcv_tsecr & TS_OPT_ECN;\n\n\t/* ABK network_porting: syncookie AccECN glue keeps only ECN-option eligibility inside net/ + include/net/. */\n\tif (!ecn_ok)\n\t\treturn false;\n\n\tif (READ_ONCE(net->ipv4.sysctl_tcp_ecn) ||\n\t    READ_ONCE(net->ipv4.sysctl_tcp_ecn_option))\n\t\treturn true;\n\n\treturn dst_feature(dst, RTAX_FEATURE_ECN);\n}\n",
            "network_porting/syncookies_cookie_ecn_ok",
        )
        sync_applied = True
    if sync_applied:
        write_text(syncookies_c, syncookies_text)

    return {
        **graft_metadata(
            hard_port_possible=False,
            semantic_port_used=True,
            max_function_port_used=False,
            sidecar_state_used=False,
            sidecar_state_scope="none",
            new_interface_used=False,
            new_interface_scope="none",
        ),
        "group": "net_accecn_path_fixups",
        "status": "partial",
        "phase": "handshake_and_child_glue_only",
        "tree_escalation_required": False,
        "deferred": [
            "blocked_by_missing_6_1_anchor: failure-mode counters and ACE accounting remain outside current anchors",
            "blocked_by_driver_scope: GSO and offload glue remains outside the current route",
        ],
        "marker": "ABK network_porting: AccECN path fixups cover child/openreq and syncookie negotiation glue only; request-sock state expansion remains deferred.",
    }


def collect_driver_dependent_features_status() -> dict[str, object]:
    counts: dict[str, int] = {}
    for item in DRIVER_DEPENDENT_FEATURES:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "status": "classified",
        "counts": counts,
        "items": list(DRIVER_DEPENDENT_FEATURES),
    }


def build_report(
    current_common: Path,
    output_dir: Path,
    timestamp_result: dict[str, object],
    flow_result: dict[str, object],
    accecn_core_result: dict[str, object],
    accecn_mainline_result: dict[str, object],
    accecn_fixups_result: dict[str, object],
    driver_features_status: dict[str, object],
) -> dict[str, object]:
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_common_root": str(current_common),
        "status": "boot_safe_timestamp_ipv6_main_path_accecn_conservative",
        "priority": "boot_compatibility_first",
        "strategy": "minimal_intrusion_graft",
        "patch_groups": [
            {
                "key": group.key,
                "summary": group.summary,
            }
            for group in PATCH_GROUPS
        ],
        "applied_groups": [
            "network_porting_scaffold",
            "net_timestamp_socket_semantics",
            "net_flow_info_cache_ipv6",
            "net_accecn_core",
            "net_accecn_path_fixups",
            "net_driver_dependent_features",
        ],
        "deferred_groups": [
            "net_accecn_mainline_protocol",
            "network_porting_fixups",
        ],
        "net_timestamp_socket_semantics_port": timestamp_result,
        "net_flow_info_cache_ipv6_port": flow_result,
        "net_accecn_core_port": accecn_core_result,
        "net_accecn_mainline_protocol_port": accecn_mainline_result,
        "net_accecn_path_fixups_port": accecn_fixups_result,
        "net_driver_dependent_features_status": driver_features_status,
        "boot_logging_companion": {
            "status": "suite_build_utils_hook_available",
            "path": "build/kernel/build_utils.sh",
            "env": [
                "ABK_BOOT_IMAGE_LOGGING_ARGS",
                "ABK_BOOTLOG_CONSOLE",
                "ABK_BOOTLOG_EARLYCON",
                "ABK_VENDOR_BOOTCONFIG_PARAMS",
                "ABK_GKI_BOOT_IMAGE_LOGGING_ARGS",
                "ABK_GKI_BOOTLOG_CONSOLE",
                "ABK_GKI_BOOTLOG_EARLYCON",
            ],
        },
        "constraints": [
            "Do not modify drivers/net/ in this network_porting child.",
            "Do not widen socket timestamp work into PHY/MAC hwtstamp providers in this batch.",
            "Do not replace whole net/ files while grafting IPv6 flow/cache helpers.",
            "Prefer boot compatibility over AccECN send/recv/timer/TCP_INFO expansion on the 6.1 target.",
            "Do not claim full AccECN parity when the 6.1 request_sock and tcp_sock anchors cannot carry full state.",
            "Do not hide GSO or driver-offload gaps behind an applied status.",
            "Use the build_utils cmdline/bootconfig slots for early panic visibility instead of hardcoding platform UART parameters here.",
        ],
    }

    (output_dir / "network_porting_report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "network_porting_report.md").write_text(
        "# ABK Network Porting Report\n\n"
        f"- Generated: `{report['generated_at_utc']}`\n"
        f"- Current tree: `{report['current_common_root']}`\n"
        f"- Status: `{report['status']}`\n"
        f"- Priority: `{report['priority']}`\n"
        f"- Strategy: `{report['strategy']}`\n\n"
        "## Applied Groups\n\n"
        + "\n".join(f"- `{item}`" for item in report["applied_groups"])
        + "\n\n## Deferred Groups\n\n"
        + "\n".join(f"- `{item}`" for item in report["deferred_groups"])
        + "\n\n## Timestamp Socket Semantics\n\n"
        f"- State: `{timestamp_result['status']}`\n"
        f"- Phase: `{timestamp_result['phase']}`\n"
        f"- Scope: `{timestamp_result['scope']}`\n\n"
        "## IPv6 Flow/Cache\n\n"
        f"- State: `{flow_result['status']}`\n"
        f"- Phase: `{flow_result['phase']}`\n"
        f"- Target shape: `{flow_result['target_shape']}`\n\n"
        "## AccECN\n\n"
        f"- Core: `{accecn_core_result['status']}` / `{accecn_core_result['phase']}`\n"
        f"- Mainline protocol: `{accecn_mainline_result['status']}` / `{accecn_mainline_result['phase']}`\n"
        f"- Path fixups: `{accecn_fixups_result['status']}` / `{accecn_fixups_result['phase']}`\n"
        f"- Blocked anchors: `{accecn_core_result.get('blocked', [])}`\n\n"
        "## Boot Logging Companion\n\n"
        f"- State: `{report['boot_logging_companion']['status']}`\n"
        f"- Path: `{report['boot_logging_companion']['path']}`\n"
        f"- Env slots: `{report['boot_logging_companion']['env']}`\n\n"
        "## Driver-Dependent Features\n\n"
        + "\n".join(
            f"- `{item['key']}`: `{item['status']}`"
            for item in driver_features_status["items"]
        )
        + "\n\n## Constraints\n\n"
        + "\n".join(f"- {item}" for item in report["constraints"])
        + "\n"
    )
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit(f"usage: {argv[0]} <current-common-root> <output-dir>")

    current_common = Path(argv[1])
    output_dir = Path(argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    for path in (
        current_common / "include/net/tcp.h",
        current_common / "include/net/sock.h",
        current_common / "include/net/ipv6.h",
        current_common / "include/net/ip6_route.h",
        current_common / "include/net/netns/ipv4.h",
        current_common / "include/uapi/linux/net_tstamp.h",
        current_common / "net/core/sock.c",
        current_common / "net/core/skbuff.c",
        current_common / "net/socket.c",
        current_common / "net/ipv4/tcp.c",
        current_common / "net/ipv4/tcp_input.c",
        current_common / "net/ipv4/tcp_output.c",
        current_common / "net/ipv4/tcp_minisocks.c",
        current_common / "net/ipv4/syncookies.c",
        current_common / "net/ipv4/tcp_timer.c",
        current_common / "net/ipv4/tcp_ipv4.c",
        current_common / "net/ipv4/sysctl_net_ipv4.c",
        current_common / "net/ipv6/ip6_output.c",
        current_common / "net/ipv6/inet6_connection_sock.c",
        current_common / "net/ipv6/ipv6_sockglue.c",
    ):
        if not path.is_file():
            raise SystemExit(f"network_porting: required file not found: {path}")

    timestamp_result = patch_timestamp_socket_semantics(current_common)
    flow_result = patch_flow_info_cache_ipv6(current_common)
    accecn_core_result = patch_accecn_core(current_common)
    accecn_mainline_result = patch_accecn_protocol_mainline(current_common)
    accecn_fixups_result = patch_accecn_path_fixups(current_common)
    driver_features_status = collect_driver_dependent_features_status()
    build_report(
        current_common,
        output_dir,
        timestamp_result,
        flow_result,
        accecn_core_result,
        accecn_mainline_result,
        accecn_fixups_result,
        driver_features_status,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
