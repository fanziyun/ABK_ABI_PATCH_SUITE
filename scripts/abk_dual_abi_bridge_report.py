#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text()


def sha256_text(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_makefile_version(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in read_text(root / "Makefile").splitlines():
        for key in ("VERSION", "PATCHLEVEL", "SUBLEVEL", "EXTRAVERSION"):
            prefix = f"{key} = "
            if line.startswith(prefix):
                values[key.lower()] = line[len(prefix) :].strip()
    return values


def run_kernelversion(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["make", "-s", "-C", str(root), "kernelversion"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def config_value(defconfig: Path, key: str) -> str | None:
    prefix = f"{key}="
    for line in read_text(defconfig).splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None


def extract_brace_block(text: str, anchor: str) -> str | None:
    start = text.find(anchor)
    if start < 0:
        return None
    line_start = text.rfind("\n", 0, start) + 1
    brace_start = text.find("{", start)
    if brace_start < 0:
        return None
    depth = 0
    for idx in range(brace_start, len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = text.find("\n", idx)
                if end < 0:
                    end = len(text)
                else:
                    end += 1
                return text[line_start:end]
    return None


def extract_macro(text: str, macro_name: str) -> str | None:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith(f"#define {macro_name}"):
            collected = [line]
            cursor = idx + 1
            while collected[-1].rstrip().endswith("\\") and cursor < len(lines):
                collected.append(lines[cursor])
                cursor += 1
            return "\n".join(collected) + "\n"
    return None


def extract_source_blocks(root: Path) -> dict[str, str | None]:
    version_c = read_text(root / "kernel/module/version.c")
    vermagic_h = read_text(root / "include/linux/vermagic.h")
    module_h = read_text(root / "include/linux/module.h")
    return {
        "same_magic": extract_brace_block(version_c, "int same_magic("),
        "check_version": extract_brace_block(version_c, "int check_version("),
        "check_modstruct_version": extract_brace_block(version_c, "int check_modstruct_version("),
        "module_layout_function": extract_brace_block(version_c, "void module_layout("),
        "module_layout_struct": extract_brace_block(module_h, "struct module_layout {"),
        "vermagic_macro": extract_macro(vermagic_h, "VERMAGIC_STRING"),
    }


def find_symvers(root: Path) -> dict[str, Path | None]:
    result: dict[str, Path | None] = {"module": None, "vmlinux": None}
    module_path = root / "Module.symvers"
    vmlinux_path = root / "vmlinux.symvers"
    if module_path.is_file():
        result["module"] = module_path
    if vmlinux_path.is_file():
        result["vmlinux"] = vmlinux_path
    return result


def parse_symvers(path: Path | None) -> set[str]:
    if path is None:
        return set()
    symbols: set[str] = set()
    for line in read_text(path).splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            symbols.add(parts[1])
    return symbols


def list_android_abi_files(root: Path) -> list[str]:
    abi_dir = root / "android"
    if not abi_dir.is_dir():
        return []
    return sorted(path.name for path in abi_dir.glob("abi_gki_aarch64*"))


def compare_blocks(current: dict[str, str | None], mainline: dict[str, str | None]) -> dict[str, dict[str, object]]:
    compared: dict[str, dict[str, object]] = {}
    for key in sorted(current):
        current_block = current.get(key)
        mainline_block = mainline.get(key)
        compared[key] = {
            "current_present": current_block is not None,
            "mainline_present": mainline_block is not None,
            "equal": current_block == mainline_block and current_block is not None,
            "current_sha256": sha256_text(current_block),
            "mainline_sha256": sha256_text(mainline_block),
        }
    return compared


def summarize_symvers(current_paths: dict[str, Path | None], mainline_paths: dict[str, Path | None]) -> dict[str, object]:
    current_symbols = parse_symvers(current_paths["module"]) | parse_symvers(current_paths["vmlinux"])
    mainline_symbols = parse_symvers(mainline_paths["module"]) | parse_symvers(mainline_paths["vmlinux"])
    shared = current_symbols & mainline_symbols
    return {
        "current_paths": {key: (str(path) if path else None) for key, path in current_paths.items()},
        "mainline_paths": {key: (str(path) if path else None) for key, path in mainline_paths.items()},
        "current_symbol_count": len(current_symbols),
        "mainline_symbol_count": len(mainline_symbols),
        "shared_symbol_count": len(shared),
        "current_only_symbol_count": len(current_symbols - mainline_symbols),
        "mainline_only_symbol_count": len(mainline_symbols - current_symbols),
        "comparable": bool(current_symbols) and bool(mainline_symbols),
    }


def collect_report(current_common: Path, defconfig: Path, mainline_root: Path) -> dict[str, object]:
    current_make = parse_makefile_version(current_common)
    mainline_make = parse_makefile_version(mainline_root)
    current_blocks = extract_source_blocks(current_common)
    mainline_blocks = extract_source_blocks(mainline_root)
    current_symvers = find_symvers(current_common)
    mainline_symvers = find_symvers(mainline_root)

    current_kernelversion = run_kernelversion(current_common)
    mainline_kernelversion = run_kernelversion(mainline_root)
    current_modversions = config_value(defconfig, "CONFIG_MODVERSIONS")
    current_localversion = config_value(defconfig, "CONFIG_LOCALVERSION")
    current_same_magic = current_blocks["same_magic"] or ""

    notes: list[str] = []
    if current_modversions != "y":
        notes.append("Current defconfig does not expose CONFIG_MODVERSIONS=y in DEFCONFIG.")
    else:
        notes.append("Current defconfig enables CONFIG_MODVERSIONS, so bridge work must handle module_layout and symbol CRCs.")
    if not current_symvers["module"] and not current_symvers["vmlinux"]:
        notes.append("Current build tree does not yet expose Module.symvers/vmlinux.symvers; symbol CRC bridge work will need a built symbol dump.")
    if not mainline_symvers["module"] and not mainline_symvers["vmlinux"]:
        notes.append("Mainline 7.0.12 family tree does not yet expose Module.symvers/vmlinux.symvers; compare against source first, symbol CRCs later.")
    if "strcspn" in current_same_magic:
        notes.append("Current same_magic() ignores the kernel version prefix when module CRCs are present, which reduces the vermagic bridge scope.")
    if current_blocks["module_layout_struct"] != mainline_blocks["module_layout_struct"]:
        notes.append("module_layout struct differs between current and mainline trees; structure-level compatibility will likely require fixups or selective bypass.")

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "bridge_policy": {
            "default_mode": "global_7012",
            "default_scope": "all_7_0_12_family_modules",
            "experimental_mode": "broader_override",
            "allowlist_drives_default": False,
        },
        "current": {
            "path": str(current_common),
            "kernelversion": current_kernelversion,
            "makefile_version": current_make,
            "defconfig": str(defconfig),
            "config_modversions": current_modversions,
            "config_localversion": current_localversion,
            "android_abi_files": list_android_abi_files(current_common),
        },
        "mainline": {
            "path": str(mainline_root),
            "kernelversion": mainline_kernelversion,
            "makefile_version": mainline_make,
        },
        "source_comparison": compare_blocks(current_blocks, mainline_blocks),
        "symvers": summarize_symvers(current_symvers, mainline_symvers),
        "notes": notes,
        "status": {
            "bridge_global_7012_enabled": True,
            "basic_loader_compat_applied": True,
            "runtime_abi_followups_deferred": True,
        },
    }


def render_markdown(report: dict[str, object]) -> str:
    current = report["current"]
    mainline = report["mainline"]
    source = report["source_comparison"]
    symvers = report["symvers"]
    notes = report["notes"]
    policy = report["bridge_policy"]
    status = report["status"]

    lines = [
        "# ABK Dual ABI/KMI Bridge Report",
        "",
        f"- Generated: `{report['generated_at_utc']}`",
        f"- Current tree: `{current['path']}`",
        f"- Current kernelversion: `{current['kernelversion']}`",
        f"- Mainline tree: `{mainline['path']}`",
        f"- Mainline kernelversion: `{mainline['kernelversion']}`",
        "",
        "**Bridge Policy**",
        f"- Default mode: `{policy['default_mode']}`",
        f"- Default scope: `{policy['default_scope']}`",
        f"- Experimental mode: `{policy['experimental_mode']}`",
        "",
        "**Current Facts**",
        f"- DEFCONFIG: `{current['defconfig']}`",
        f"- `CONFIG_MODVERSIONS`: `{current['config_modversions']}`",
        f"- `CONFIG_LOCALVERSION`: `{current['config_localversion']}`",
        f"- Android ABI lists: `{', '.join(current['android_abi_files']) if current['android_abi_files'] else 'none found'}`",
        "",
        "**Source Comparison**",
        "",
        "| Block | Equal | Current | Mainline |",
        "| --- | --- | --- | --- |",
    ]
    for key, values in source.items():
        lines.append(
            f"| `{key}` | `{values['equal']}` | `{values['current_present']}` | `{values['mainline_present']}` |"
        )
    lines.extend(
        [
            "",
            "**Symvers Availability**",
            f"- Current `Module.symvers`: `{symvers['current_paths']['module']}`",
            f"- Current `vmlinux.symvers`: `{symvers['current_paths']['vmlinux']}`",
            f"- Mainline `Module.symvers`: `{symvers['mainline_paths']['module']}`",
            f"- Mainline `vmlinux.symvers`: `{symvers['mainline_paths']['vmlinux']}`",
            f"- Comparable symbol sets: `{symvers['comparable']}`",
            f"- Current symbol count: `{symvers['current_symbol_count']}`",
            f"- Mainline symbol count: `{symvers['mainline_symbol_count']}`",
            f"- Shared symbol count: `{symvers['shared_symbol_count']}`",
            "",
            "**Notes**",
        ]
    )
    lines.extend(f"- {note}" for note in notes)
    lines.extend(
        [
            "",
            "**Bridge Status**",
            f"- `bridge_global_7012_enabled`: `{status['bridge_global_7012_enabled']}`",
            f"- `basic_loader_compat_applied`: `{status['basic_loader_compat_applied']}`",
            f"- `runtime_abi_followups_deferred`: `{status['runtime_abi_followups_deferred']}`",
            "",
            "**Suggested Next Steps**",
            "- Treat global `7.0.12`-family bridge as the default loader path, not a name-prefix allowlist exception.",
            "- Produce `Module.symvers` / `vmlinux.symvers` for both trees before tightening runtime ABI compatibility around symbol CRCs.",
            "- Use representative third-party `7.0.12` LKMs as validation samples, but do not gate default bridge coverage on sample prefixes.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        raise SystemExit(
            f"usage: {argv[0]} <current-common-root> <defconfig> <mainline-7012-root> <output-dir>"
        )

    current_common = Path(argv[1])
    defconfig = Path(argv[2])
    mainline_root = Path(argv[3])
    output_dir = Path(argv[4])

    output_dir.mkdir(parents=True, exist_ok=True)
    report = collect_report(current_common, defconfig, mainline_root)

    (output_dir / "bridge_report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "bridge_report.md").write_text(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
