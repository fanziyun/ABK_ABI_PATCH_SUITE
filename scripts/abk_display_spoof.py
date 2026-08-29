#!/usr/bin/env python3
"""ABK Display Release Spoof -- boot-image metadata only.

Rewriting the runtime release interfaces (uname(), /proc/sys/kernel/osrelease,
/proc/version) is unsafe on android13-5.15: vold parses the kernel release to
pick the fscrypt key path, and spoofing it to 7.0.12 made vold take the
HW_WRAPPED path the 5.15 kernel rejects, so cryptfs enablefilecrypto failed
and init rebooted into recovery (enablefilecrypto_failed). f2fs-tools also
reads /proc/version. Only mkbootimg os_version/os_patch_level and the GKI SPL
date are stamped; runtime release strings stay real.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

DISPLAY_SECURITY_PATCH = "2026-06"


def _abk_common():
    """Load abk_common from this script's directory.

    ABK runs each child as `python3 .../scripts/abk_child.py`, so a plain import
    works there; loading by path keeps it working when a caller imports this
    module under another name.
    """
    spec = importlib.util.spec_from_file_location(
        "abk_common", Path(__file__).resolve().parent / "abk_common.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_common = _abk_common()
write_text = _common.write_text


def patch_build_utils(path: Path) -> None:
    """Stamp boot-image metadata, where the build actually uses build_utils.sh.

    Both blocks below only affect mkbootimg arguments -- os_version, patch level
    and the GKI SPL date -- so neither has any bearing on the release strings the
    kernel itself reports. build_utils.sh also differs across target families,
    and some builders (ABK among them) never source it at all: it is referenced
    nowhere in ABK's build.yml, which assembles boot images itself.

    So a missing block here is not a failure. Warn and leave that stamp alone
    rather than aborting a run whose kernel-side patches already applied.
    """
    text = path.read_text()
    os_version_block = """  BOOT_IMAGE_HEADER_VERSION=${BOOT_IMAGE_HEADER_VERSION:-3}\n  MKBOOTIMG_ARGS=(\"--header_version\" \"${BOOT_IMAGE_HEADER_VERSION}\")\n"""
    os_version_new = f"""  BOOT_IMAGE_HEADER_VERSION=${{BOOT_IMAGE_HEADER_VERSION:-3}}\n  BOOT_IMAGE_OS_VERSION=${{ABK_BOOT_IMAGE_OS_VERSION:-16.0.0}}\n  BOOT_IMAGE_OS_PATCH_LEVEL=${{ABK_BOOT_IMAGE_OS_PATCH_LEVEL:-{DISPLAY_SECURITY_PATCH}}}\n  MKBOOTIMG_ARGS=(\"--header_version\" \"${{BOOT_IMAGE_HEADER_VERSION}}\")\n  MKBOOTIMG_ARGS+=(\"--os_version\" \"${{BOOT_IMAGE_OS_VERSION}}\")\n  MKBOOTIMG_ARGS+=(\"--os_patch_level\" \"${{BOOT_IMAGE_OS_PATCH_LEVEL}}\")\n"""
    if "--os_patch_level" not in text:
        if os_version_block in text:
            text = text.replace(os_version_block, os_version_new, 1)
        else:
            print(
                "::warning::display_release_spoof: mkbootimg header block not found "
                f"in {path}, leaving boot-image os_version/patch_level unchanged"
            )

    gki_spl_old = """      local spl_date=$(printf \"%d-%02d-05\\n\" ${spl_year} ${spl_month})\n\n      gki_add_avb_footer \"${boot_image_path}\" \\\n"""
    gki_spl_new = """      local spl_date=${ABK_GKI_SPL_DATE:-$(printf \"%d-%02d-05\\n\" ${spl_year} ${spl_month})}\n\n      gki_add_avb_footer \"${boot_image_path}\" \\\n"""
    if "ABK_GKI_SPL_DATE" not in text:
        if gki_spl_old in text:
            text = text.replace(gki_spl_old, gki_spl_new, 1)
        else:
            print(
                "::warning::display_release_spoof: gki SPL block not found in "
                f"{path}, leaving the GKI SPL date unchanged"
            )

    write_text(path, text)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <kernel-common-dir>")

    common_dir = Path(sys.argv[1])
    if not common_dir.is_dir():
        raise SystemExit(f"kernel common dir not found: {common_dir}")

    # Runtime release interfaces (uname(), /proc/sys/kernel/osrelease and
    # /proc/version) are deliberately left untouched -- see the module docstring
    # for why. Only boot-image metadata is spoofed.
    kernel_root = common_dir.parent
    build_utils = kernel_root / "build/kernel/build_utils.sh"
    if build_utils.exists():
        patch_build_utils(build_utils)
    else:
        print(
            "::warning::display_release_spoof: no build/kernel/build_utils.sh; "
            "boot-image os_version/patch_level/SPL left unchanged"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
