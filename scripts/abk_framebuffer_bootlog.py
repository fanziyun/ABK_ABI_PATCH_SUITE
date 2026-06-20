#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_CONFIGS = (
    ("CONFIG_VT", "y"),
    ("CONFIG_VT_CONSOLE", "y"),
    ("CONFIG_DUMMY_CONSOLE", "y"),
    ("CONFIG_FB", "y"),
    ("CONFIG_FRAMEBUFFER_CONSOLE", "y"),
    ("CONFIG_DRM_KMS_HELPER", "y"),
    ("CONFIG_DRM_FBDEV_EMULATION", "y"),
)


def read_text(path: Path) -> str:
    return path.read_text()


def write_text(path: Path, text: str) -> None:
    path.write_text(text)


def ensure_before(path: Path, anchor: str, snippet: str, label: str, legacy_snippet: str | None = None) -> None:
    text = read_text(path)
    if snippet in text:
        return
    if legacy_snippet and legacy_snippet in text:
        write_text(path, text.replace(legacy_snippet, snippet, 1))
        return
    if anchor not in text:
        raise SystemExit(f"{label}: anchor not found in {path}")
    write_text(path, text.replace(anchor, snippet + anchor, 1))


def set_config(path: Path, symbol: str, value: str) -> None:
    text = read_text(path)
    clean_symbol = symbol.removeprefix("CONFIG_")
    lines = text.splitlines()
    kept: list[str] = []
    prefix = f"CONFIG_{clean_symbol}="
    disabled = f"# CONFIG_{clean_symbol} is not set"
    for line in lines:
        if line.startswith(prefix) or line == disabled:
            continue
        kept.append(line)
    kept.append(f"CONFIG_{clean_symbol}={value}")
    write_text(path, "\n".join(kept) + "\n")


def patch_defconfig(defconfig: Path) -> dict[str, object]:
    for symbol, value in REQUIRED_CONFIGS:
        set_config(defconfig, symbol, value)
    cmdline_value = read_config_value(defconfig, "CONFIG_CMDLINE")
    cmdline_status = "not_present"
    removed_ttynull = False
    if cmdline_value is not None:
        adjusted_cmdline = strip_console_ttynull(cmdline_value)
        removed_ttynull = adjusted_cmdline != cmdline_value
        if removed_ttynull:
            set_string_config(defconfig, "CONFIG_CMDLINE", adjusted_cmdline)
            cmdline_status = "console_ttynull_removed"
        else:
            cmdline_status = "already_without_console_ttynull"
    return {
        "status": "framebuffer_console_config_enabled",
        "required": [{symbol: value} for symbol, value in REQUIRED_CONFIGS],
        "cmdline_status": cmdline_status,
        "cmdline_ttynull_removed": removed_ttynull,
    }


def read_config_value(path: Path, symbol: str) -> str | None:
    prefix = f"{symbol}="
    for line in read_text(path).splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def set_string_config(path: Path, symbol: str, value: str) -> None:
    text = read_text(path)
    prefix = f"{symbol}="
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            continue
        kept.append(line)
    kept.append(f'{symbol}="{value}"')
    write_text(path, "\n".join(kept) + "\n")


def strip_console_ttynull(value: str) -> str:
    raw = value.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        raw = raw[1:-1]
    tokens = [token for token in raw.split() if token != "console=ttynull"]
    return " ".join(tokens)


def patch_build_utils(build_utils: Path) -> dict[str, object]:
    legacy_build_boot_images_snippet = """  # ABK framebuffer bootlog slot: prefer fbcon handoff without pulling in a UEFI display stack.\n  ABK_FB_BOOTLOG_ARGS=${ABK_FB_BOOTLOG_ARGS:-"console=tty0 fbcon=nodefer vt.global_cursor_default=0 logo.nologo printk.time=1"}\n  ABK_FB_BOOTLOG_EXTRA_ARGS=${ABK_FB_BOOTLOG_EXTRA_ARGS:-}\n  ABK_FB_BOOTLOG_CMDLINE="${ABK_FB_BOOTLOG_ARGS}"\n  if [ -n "${ABK_FB_BOOTLOG_EXTRA_ARGS}" ]; then\n    ABK_FB_BOOTLOG_CMDLINE+=" ${ABK_FB_BOOTLOG_EXTRA_ARGS}"\n  fi\n  if [ -n "${ABK_FB_BOOTLOG_CMDLINE}" ]; then\n    if [ -n "${KERNEL_VENDOR_CMDLINE:-}" ]; then\n      KERNEL_VENDOR_CMDLINE+=" ${ABK_FB_BOOTLOG_CMDLINE}"\n    else\n      KERNEL_VENDOR_CMDLINE="${ABK_FB_BOOTLOG_CMDLINE}"\n    fi\n  fi\n  if [ -n "${ABK_FB_BOOTLOG_BOOTCONFIG_PARAMS:-}" ]; then\n    if [ -n "${VENDOR_BOOTCONFIG:-}" ]; then\n      VENDOR_BOOTCONFIG+=" ${ABK_FB_BOOTLOG_BOOTCONFIG_PARAMS}"\n    else\n      VENDOR_BOOTCONFIG="${ABK_FB_BOOTLOG_BOOTCONFIG_PARAMS}"\n    fi\n  fi\n"""
    build_boot_images_snippet = """  # ABK framebuffer bootlog slot: prefer fbcon handoff without pulling in a UEFI display stack.\n  ABK_FB_BOOTLOG_ARGS=${ABK_FB_BOOTLOG_ARGS:-"console=tty0 fbcon=nodefer vt.global_cursor_default=0 logo.nologo printk.time=1"}\n  ABK_FB_BOOTLOG_EXTRA_ARGS=${ABK_FB_BOOTLOG_EXTRA_ARGS:-}\n  ABK_FB_BOOTLOG_APPLY_TO_BOOT_CMDLINE=${ABK_FB_BOOTLOG_APPLY_TO_BOOT_CMDLINE:-1}\n  ABK_FB_BOOTLOG_STRIP_TTYNULL=${ABK_FB_BOOTLOG_STRIP_TTYNULL:-1}\n  ABK_FB_BOOTLOG_CMDLINE="${ABK_FB_BOOTLOG_ARGS}"\n  if [ -n "${ABK_FB_BOOTLOG_EXTRA_ARGS}" ]; then\n    ABK_FB_BOOTLOG_CMDLINE+=" ${ABK_FB_BOOTLOG_EXTRA_ARGS}"\n  fi\n  if [ -n "${ABK_FB_BOOTLOG_CMDLINE}" ]; then\n    if [ "${BOOT_IMAGE_HEADER_VERSION}" -ge "3" ]; then\n      if [ -n "${KERNEL_VENDOR_CMDLINE:-}" ]; then\n        KERNEL_VENDOR_CMDLINE+=" ${ABK_FB_BOOTLOG_CMDLINE}"\n      else\n        KERNEL_VENDOR_CMDLINE="${ABK_FB_BOOTLOG_CMDLINE}"\n      fi\n      if [ "${ABK_FB_BOOTLOG_STRIP_TTYNULL}" != "0" ]; then\n        KERNEL_VENDOR_CMDLINE="$(printf '%s\n' "${KERNEL_VENDOR_CMDLINE}" | sed -E 's/(^| )console=ttynull( |$)/ /g; s/[[:space:]]+/ /g; s/^ //; s/ $//')"\n      fi\n    fi\n    if [ "${ABK_FB_BOOTLOG_APPLY_TO_BOOT_CMDLINE}" != "0" ] || [ "${BOOT_IMAGE_HEADER_VERSION}" -lt "3" ]; then\n      if [ -n "${KERNEL_CMDLINE:-}" ]; then\n        KERNEL_CMDLINE+=" ${ABK_FB_BOOTLOG_CMDLINE}"\n      else\n        KERNEL_CMDLINE="${ABK_FB_BOOTLOG_CMDLINE}"\n      fi\n      if [ "${ABK_FB_BOOTLOG_STRIP_TTYNULL}" != "0" ]; then\n        KERNEL_CMDLINE="$(printf '%s\n' "${KERNEL_CMDLINE}" | sed -E 's/(^| )console=ttynull( |$)/ /g; s/[[:space:]]+/ /g; s/^ //; s/ $//')"\n      fi\n    fi\n  fi\n  if [ -n "${ABK_FB_BOOTLOG_BOOTCONFIG_PARAMS:-}" ]; then\n    if [ -n "${VENDOR_BOOTCONFIG:-}" ]; then\n      VENDOR_BOOTCONFIG+=" ${ABK_FB_BOOTLOG_BOOTCONFIG_PARAMS}"\n    else\n      VENDOR_BOOTCONFIG="${ABK_FB_BOOTLOG_BOOTCONFIG_PARAMS}"\n    fi\n  fi\n"""
    ensure_before(
        build_utils,
        "  MKBOOTIMG_ARGS=(\"--header_version\" \"${BOOT_IMAGE_HEADER_VERSION}\")\n",
        build_boot_images_snippet,
        "framebuffer_bootlog/build_boot_images",
        legacy_snippet=legacy_build_boot_images_snippet,
    )

    gki_snippet = """  # ABK framebuffer bootlog slot: mirror fbcon-friendly arguments for standalone GKI boot images.\n  ABK_GKI_FB_BOOTLOG_ARGS=${ABK_GKI_FB_BOOTLOG_ARGS:-${ABK_FB_BOOTLOG_ARGS:-"console=tty0 fbcon=nodefer vt.global_cursor_default=0 logo.nologo printk.time=1"}}\n  ABK_GKI_FB_BOOTLOG_EXTRA_ARGS=${ABK_GKI_FB_BOOTLOG_EXTRA_ARGS:-${ABK_FB_BOOTLOG_EXTRA_ARGS:-}}\n  ABK_GKI_FB_BOOTLOG_STRIP_TTYNULL=${ABK_GKI_FB_BOOTLOG_STRIP_TTYNULL:-${ABK_FB_BOOTLOG_STRIP_TTYNULL:-1}}\n  ABK_GKI_FB_BOOTLOG_CMDLINE="${ABK_GKI_FB_BOOTLOG_ARGS}"\n  if [ -n "${ABK_GKI_FB_BOOTLOG_EXTRA_ARGS}" ]; then\n    ABK_GKI_FB_BOOTLOG_CMDLINE+=" ${ABK_GKI_FB_BOOTLOG_EXTRA_ARGS}"\n  fi\n  if [ -n "${ABK_GKI_FB_BOOTLOG_CMDLINE}" ]; then\n    if [ -n "${GKI_KERNEL_CMDLINE:-}" ]; then\n      GKI_KERNEL_CMDLINE+=" ${ABK_GKI_FB_BOOTLOG_CMDLINE}"\n    else\n      GKI_KERNEL_CMDLINE="${ABK_GKI_FB_BOOTLOG_CMDLINE}"\n    fi\n    if [ "${ABK_GKI_FB_BOOTLOG_STRIP_TTYNULL}" != "0" ]; then\n      GKI_KERNEL_CMDLINE="$(printf '%s\n' "${GKI_KERNEL_CMDLINE}" | sed -E 's/(^| )console=ttynull( |$)/ /g; s/[[:space:]]+/ /g; s/^ //; s/ $//')"\n    fi\n  fi\n\n"""
    ensure_before(
        build_utils,
        "  DEFAULT_MKBOOTIMG_ARGS=(\"--header_version\" \"4\")\n",
        gki_snippet,
        "framebuffer_bootlog/build_gki_boot_images",
    )

    return {
        "status": "cmdline_slots_injected",
        "default_args": "console=tty0 fbcon=nodefer vt.global_cursor_default=0 logo.nologo printk.time=1",
        "env": [
            "ABK_FB_BOOTLOG_ARGS",
            "ABK_FB_BOOTLOG_EXTRA_ARGS",
            "ABK_FB_BOOTLOG_APPLY_TO_BOOT_CMDLINE",
            "ABK_FB_BOOTLOG_STRIP_TTYNULL",
            "ABK_FB_BOOTLOG_BOOTCONFIG_PARAMS",
            "ABK_GKI_FB_BOOTLOG_ARGS",
            "ABK_GKI_FB_BOOTLOG_EXTRA_ARGS",
            "ABK_GKI_FB_BOOTLOG_STRIP_TTYNULL",
        ],
    }


def build_report(
    common_root: Path,
    defconfig: Path,
    output_dir: Path,
    config_status: dict[str, object],
    build_utils_status: dict[str, object],
) -> None:
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_common_root": str(common_root),
        "defconfig": str(defconfig),
        "status": "lightweight_framebuffer_bootlog_baseline",
        "strategy": "defconfig_and_cmdline_only",
        "scope": {
            "allowed": [
                "DEFCONFIG",
                "build/kernel/build_utils.sh",
            ],
            "not_allowed": [
                "drivers/gpu/",
                "drivers/video/",
                "drivers/tty/",
                "vendor display driver rewrites",
            ],
        },
        "config_status": config_status,
        "build_utils_status": build_utils_status,
        "expected_cmdline_shape": [
            "console=tty0",
            "fbcon=nodefer",
            "vt.global_cursor_default=0",
            "logo.nologo",
            "printk.time=1",
        ],
        "known_limitations": [
            "If runtime cmdline is overridden again after packaging, tty0 takeover may still remain hidden or secondary.",
            "This child does not add earlycon or device-specific UART values.",
            "This child does not import a firmware framebuffer logger or UEFI graphics console stack.",
            "Do not use video=vfb as a default screen-log strategy; vfb is a virtual test framebuffer and not the real device panel path.",
            "Actual on-screen output still depends on the vendor DRM/fbdev handoff path reaching fbcon.",
        ],
    }
    write_text(output_dir / "framebuffer_bootlog_report.json", json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
    write_text(
        output_dir / "framebuffer_bootlog_report.md",
        "# ABK Framebuffer Bootlog Report\n\n"
        f"- Generated: `{report['generated_at_utc']}`\n"
        f"- Current tree: `{report['current_common_root']}`\n"
        f"- Defconfig: `{report['defconfig']}`\n"
        f"- Status: `{report['status']}`\n"
        f"- Strategy: `{report['strategy']}`\n\n"
        "## Config\n\n"
        f"- State: `{config_status['status']}`\n"
        f"- Required: `{config_status['required']}`\n\n"
        "## Build Utils\n\n"
        f"- State: `{build_utils_status['status']}`\n"
        f"- Default args: `{build_utils_status['default_args']}`\n"
        f"- Env slots: `{build_utils_status['env']}`\n\n"
        "## Known Limitations\n\n"
        + "\n".join(f"- {item}" for item in report["known_limitations"])
        + "\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        raise SystemExit(f"usage: {argv[0]} <current-common-root> <defconfig> <build-utils-path> <output-dir>")

    common_root = Path(argv[1])
    defconfig = Path(argv[2])
    build_utils = Path(argv[3])
    output_dir = Path(argv[4])
    output_dir.mkdir(parents=True, exist_ok=True)

    if not common_root.is_dir():
        raise SystemExit(f"framebuffer_bootlog: common root not found: {common_root}")
    if not defconfig.is_file():
        raise SystemExit(f"framebuffer_bootlog: defconfig not found: {defconfig}")
    if not build_utils.is_file():
        raise SystemExit(f"framebuffer_bootlog: build_utils.sh not found: {build_utils}")

    config_status = patch_defconfig(defconfig)
    build_utils_status = patch_build_utils(build_utils)
    build_report(common_root, defconfig, output_dir, config_status, build_utils_status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
