#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def ensure_before(path: Path, anchor: str, snippet: str, label: str, legacy_snippet: str | None = None) -> None:
    text = path.read_text()
    if snippet in text:
        return
    if legacy_snippet and legacy_snippet in text:
        path.write_text(text.replace(legacy_snippet, snippet, 1))
        return
    if anchor not in text:
        raise SystemExit(f"{label}: anchor not found in {path}")
    path.write_text(text.replace(anchor, snippet + anchor, 1))


def patch_build_utils(path: Path) -> None:
    legacy_build_boot_images_snippet = """  # ABK boot logging slot: generic early panic visibility without hardcoded device UART values.\n  ABK_BOOT_IMAGE_LOGGING_ARGS=${ABK_BOOT_IMAGE_LOGGING_ARGS:-\"ignore_loglevel panic=30 oops=panic\"}\n  ABK_BOOTLOG_CONSOLE=${ABK_BOOTLOG_CONSOLE:-}\n  ABK_BOOTLOG_EARLYCON=${ABK_BOOTLOG_EARLYCON:-}\n  ABK_BOOT_IMAGE_LOGGING_CMDLINE=\"${ABK_BOOT_IMAGE_LOGGING_ARGS}\"\n  if [ -n \"${ABK_BOOTLOG_CONSOLE}\" ]; then\n    ABK_BOOT_IMAGE_LOGGING_CMDLINE+=\" console=${ABK_BOOTLOG_CONSOLE}\"\n  fi\n  if [ -n \"${ABK_BOOTLOG_EARLYCON}\" ]; then\n    ABK_BOOT_IMAGE_LOGGING_CMDLINE+=\" earlycon=${ABK_BOOTLOG_EARLYCON}\"\n  fi\n  if [ -n \"${ABK_BOOT_IMAGE_LOGGING_CMDLINE}\" ]; then\n    if [ -n \"${KERNEL_VENDOR_CMDLINE:-}\" ]; then\n      KERNEL_VENDOR_CMDLINE+=\" ${ABK_BOOT_IMAGE_LOGGING_CMDLINE}\"\n    else\n      KERNEL_VENDOR_CMDLINE=\"${ABK_BOOT_IMAGE_LOGGING_CMDLINE}\"\n    fi\n  fi\n  if [ -n \"${ABK_VENDOR_BOOTCONFIG_PARAMS:-}\" ]; then\n    if [ -n \"${VENDOR_BOOTCONFIG:-}\" ]; then\n      VENDOR_BOOTCONFIG+=\" ${ABK_VENDOR_BOOTCONFIG_PARAMS}\"\n    else\n      VENDOR_BOOTCONFIG=\"${ABK_VENDOR_BOOTCONFIG_PARAMS}\"\n    fi\n  fi\n"""
    build_boot_images_snippet = """  # ABK boot logging slot: generic early panic visibility without hardcoded device UART values.\n  ABK_BOOT_IMAGE_LOGGING_ARGS=${ABK_BOOT_IMAGE_LOGGING_ARGS:-\"ignore_loglevel panic=30 oops=panic\"}\n  ABK_BOOTLOG_CONSOLE=${ABK_BOOTLOG_CONSOLE:-}\n  ABK_BOOTLOG_EARLYCON=${ABK_BOOTLOG_EARLYCON:-}\n  ABK_BOOT_IMAGE_LOGGING_APPLY_TO_BOOT_CMDLINE=${ABK_BOOT_IMAGE_LOGGING_APPLY_TO_BOOT_CMDLINE:-1}\n  ABK_BOOT_IMAGE_LOGGING_CMDLINE=\"${ABK_BOOT_IMAGE_LOGGING_ARGS}\"\n  if [ -n \"${ABK_BOOTLOG_CONSOLE}\" ]; then\n    ABK_BOOT_IMAGE_LOGGING_CMDLINE+=\" console=${ABK_BOOTLOG_CONSOLE}\"\n  fi\n  if [ -n \"${ABK_BOOTLOG_EARLYCON}\" ]; then\n    ABK_BOOT_IMAGE_LOGGING_CMDLINE+=\" earlycon=${ABK_BOOTLOG_EARLYCON}\"\n  fi\n  if [ -n \"${ABK_BOOT_IMAGE_LOGGING_CMDLINE}\" ]; then\n    if [ \"${BOOT_IMAGE_HEADER_VERSION}\" -ge \"3\" ]; then\n      if [ -n \"${KERNEL_VENDOR_CMDLINE:-}\" ]; then\n        KERNEL_VENDOR_CMDLINE+=\" ${ABK_BOOT_IMAGE_LOGGING_CMDLINE}\"\n      else\n        KERNEL_VENDOR_CMDLINE=\"${ABK_BOOT_IMAGE_LOGGING_CMDLINE}\"\n      fi\n    fi\n    if [ \"${ABK_BOOT_IMAGE_LOGGING_APPLY_TO_BOOT_CMDLINE}\" != \"0\" ] || [ \"${BOOT_IMAGE_HEADER_VERSION}\" -lt \"3\" ]; then\n      if [ -n \"${KERNEL_CMDLINE:-}\" ]; then\n        KERNEL_CMDLINE+=\" ${ABK_BOOT_IMAGE_LOGGING_CMDLINE}\"\n      else\n        KERNEL_CMDLINE=\"${ABK_BOOT_IMAGE_LOGGING_CMDLINE}\"\n      fi\n    fi\n  fi\n  if [ -n \"${ABK_VENDOR_BOOTCONFIG_PARAMS:-}\" ]; then\n    if [ -n \"${VENDOR_BOOTCONFIG:-}\" ]; then\n      VENDOR_BOOTCONFIG+=\" ${ABK_VENDOR_BOOTCONFIG_PARAMS}\"\n    else\n      VENDOR_BOOTCONFIG=\"${ABK_VENDOR_BOOTCONFIG_PARAMS}\"\n    fi\n  fi\n"""
    ensure_before(
        path,
        "  MKBOOTIMG_ARGS=(\"--header_version\" \"${BOOT_IMAGE_HEADER_VERSION}\")\n",
        build_boot_images_snippet,
        "boot_image_logging/build_boot_images",
        legacy_snippet=legacy_build_boot_images_snippet,
    )

    gki_logging_snippet = """  # ABK boot logging slot: mirror the same conservative panic logging knobs for standalone GKI boot images.\n  ABK_GKI_BOOT_IMAGE_LOGGING_ARGS=${ABK_GKI_BOOT_IMAGE_LOGGING_ARGS:-${ABK_BOOT_IMAGE_LOGGING_ARGS:-\"ignore_loglevel panic=30 oops=panic\"}}\n  ABK_GKI_BOOTLOG_CONSOLE=${ABK_GKI_BOOTLOG_CONSOLE:-${ABK_BOOTLOG_CONSOLE:-}}\n  ABK_GKI_BOOTLOG_EARLYCON=${ABK_GKI_BOOTLOG_EARLYCON:-${ABK_BOOTLOG_EARLYCON:-}}\n  ABK_GKI_BOOT_IMAGE_LOGGING_CMDLINE=\"${ABK_GKI_BOOT_IMAGE_LOGGING_ARGS}\"\n  if [ -n \"${ABK_GKI_BOOTLOG_CONSOLE}\" ]; then\n    ABK_GKI_BOOT_IMAGE_LOGGING_CMDLINE+=\" console=${ABK_GKI_BOOTLOG_CONSOLE}\"\n  fi\n  if [ -n \"${ABK_GKI_BOOTLOG_EARLYCON}\" ]; then\n    ABK_GKI_BOOT_IMAGE_LOGGING_CMDLINE+=\" earlycon=${ABK_GKI_BOOTLOG_EARLYCON}\"\n  fi\n  if [ -n \"${ABK_GKI_BOOT_IMAGE_LOGGING_CMDLINE}\" ]; then\n    if [ -n \"${GKI_KERNEL_CMDLINE:-}\" ]; then\n      GKI_KERNEL_CMDLINE+=\" ${ABK_GKI_BOOT_IMAGE_LOGGING_CMDLINE}\"\n    else\n      GKI_KERNEL_CMDLINE=\"${ABK_GKI_BOOT_IMAGE_LOGGING_CMDLINE}\"\n    fi\n  fi\n\n"""
    ensure_before(
        path,
        "  DEFAULT_MKBOOTIMG_ARGS=(\"--header_version\" \"4\")\n",
        gki_logging_snippet,
        "boot_image_logging/build_gki_boot_images",
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit(f"usage: {argv[0]} <build-utils-path>")

    path = Path(argv[1])
    if not path.is_file():
        raise SystemExit(f"build_utils.sh not found: {path}")
    patch_build_utils(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
