#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit(f"usage: {argv[0]} <current-common-root> <output-dir>")

    current_common = Path(argv[1])
    output_dir = Path(argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_common_root": str(current_common),
        "status": "queued",
        "batch": "sec_meta_batch_001",
        "notes": [
            "First executable security child run exports a formal queue only.",
            "Actual low-risk patch batches should be attached after bridge/fixup review.",
            "See docs/security_backport_sources.md for the source ledger.",
        ],
    }

    (output_dir / "security_backport_queue.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "security_backport_queue.md").write_text(
        "# ABK Security Update Backport Queue\n\n"
        f"- Generated: `{report['generated_at_utc']}`\n"
        f"- Current tree: `{report['current_common_root']}`\n"
        f"- Batch: `{report['batch']}`\n"
        f"- Status: `{report['status']}`\n\n"
        "## Notes\n\n"
        + "\n".join(f"- {note}" for note in report["notes"])
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
