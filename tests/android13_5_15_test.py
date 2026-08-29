#!/usr/bin/env python3
"""Tests for the android13-5.15 target family.

The existing regression suite fixtures are all android14-6.1 shaped, so they
only prove 6.1 still works. These cover the 5.15 branches: the shape-rewriting
helpers, the per-site 5.15 forms, and the two invariants that matter most --
that 6.1 literals are never rewritten on a 6.1 tree, and that a graft which
already wrote files cannot be downgraded to a clean skip.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relpath)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FEATURE_PORTING = _load("abk_feature_porting_5_15", "scripts/abk_feature_porting.py")
BRIDGE_APPLY = _load("abk_dual_abi_bridge_apply_5_15", "scripts/abk_dual_abi_bridge_apply.py")


def write_files(root: Path, files: dict[str, str]) -> None:
    for relpath, content in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


class ShapeRewriteTest(unittest.TestCase):
    """fair_shape_for_tree / blk_shape_for_tree must never fire on 6.1."""

    def test_fair_renames_disarmed_when_tree_has_the_6_1_spelling(self) -> None:
        snippet = "\tupdate_stats_dequeue_fair(cfs_rq, se, flags);\n"
        tree_6_1 = "static void x(void) {\n\tupdate_stats_dequeue_fair(a, b, c);\n}\n"
        self.assertEqual(
            FEATURE_PORTING.fair_shape_for_tree(tree_6_1, snippet),
            snippet,
            "a tree that already uses the _fair spelling must be left alone",
        )

    def test_fair_renames_applied_when_tree_lacks_it(self) -> None:
        snippet = "\tupdate_stats_dequeue_fair(cfs_rq, se, flags);\n"
        tree_5_15 = "static void x(void) {\n\tupdate_stats_dequeue(a, b, c);\n}\n"
        self.assertEqual(
            FEATURE_PORTING.fair_shape_for_tree(tree_5_15, snippet),
            "\tupdate_stats_dequeue(cfs_rq, se, flags);\n",
        )

    def test_dequeue_action_hoist_only_dropped_when_absent(self) -> None:
        snippet = "{\n\tint action = UPDATE_TG;\n\tbool sleep = flags & DEQUEUE_SLEEP;\n"
        with_hoist = "dequeue_entity(...)\n{\n\tint action = UPDATE_TG;\n\tupdate_curr(cfs_rq);\n}\n"
        self.assertEqual(FEATURE_PORTING.fair_shape_for_tree(with_hoist, snippet), snippet)
        without = "dequeue_entity(...)\n{\n\tupdate_curr(cfs_rq);\n}\n"
        self.assertEqual(
            FEATURE_PORTING.fair_shape_for_tree(without, snippet),
            "{\n\tbool sleep = flags & DEQUEUE_SLEEP;\n",
        )

    def test_place_tail_hook_added_only_when_tree_has_it(self) -> None:
        plain, hooked = FEATURE_PORTING._FAIR_5_15_PLACE_TAIL
        self.assertEqual(FEATURE_PORTING.fair_shape_for_tree("no hook here", plain), plain)
        self.assertEqual(FEATURE_PORTING.fair_shape_for_tree(hooked, plain), hooked)

    def test_blk_renames_disarmed_on_6_1(self) -> None:
        snippet = "\tq->nr_requests = BLKDEV_DEFAULT_RQ;\n"
        tree_6_1 = "#define BLKDEV_DEFAULT_RQ 128\nq->nr_requests = BLKDEV_DEFAULT_RQ;\n"
        self.assertEqual(FEATURE_PORTING.blk_shape_for_tree(tree_6_1, snippet), snippet)

    def test_blk_renames_applied_on_5_15(self) -> None:
        snippet = "\tq->nr_requests = BLKDEV_DEFAULT_RQ;\n"
        tree_5_15 = "#define BLKDEV_MAX_RQ 128\nq->nr_requests = BLKDEV_MAX_RQ;\n"
        self.assertEqual(
            FEATURE_PORTING.blk_shape_for_tree(tree_5_15, snippet),
            "\tq->nr_requests = BLKDEV_MAX_RQ;\n",
        )

    def test_blk_opf_t_kept_when_the_typedef_exists(self) -> None:
        snippet = "static void f(blk_opf_t opf)\n"
        self.assertEqual(
            FEATURE_PORTING.blk_shape_for_tree("typedef __u32 blk_opf_t;\n", snippet),
            snippet,
        )
        self.assertEqual(
            FEATURE_PORTING.blk_shape_for_tree("no such typedef\n", snippet),
            "static void f(unsigned int opf)\n",
        )

    def test_bitmap_tags_pointer_form_only_on_pointer_trees(self) -> None:
        snippet = "\tsbitmap_queue_min_shallow_depth(&tags->bitmap_tags, 1);\n"
        embedded = "struct blk_mq_tags { struct sbitmap_queue bitmap_tags; };\n"
        self.assertEqual(FEATURE_PORTING.blk_shape_for_tree(embedded, snippet), snippet)
        pointer = "unsigned int shift = tags->bitmap_tags->sb.shift;\n"
        self.assertEqual(
            FEATURE_PORTING.blk_shape_for_tree(pointer, snippet),
            "\tsbitmap_queue_min_shallow_depth(tags->bitmap_tags, 1);\n",
        )


class ModuleLoaderLayoutTest(unittest.TestCase):
    """abi_bridge must resolve both the split and single-file loader."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_split_layout_resolved(self) -> None:
        write_files(self.root, {
            "kernel/module/main.c": "/* main */\n",
            "kernel/module/version.c": "/* version */\n",
            "kernel/module/internal.h": "/* internal */\n",
        })
        layout = BRIDGE_APPLY.resolve_layout(self.root)
        self.assertFalse(layout["single_file"])
        self.assertEqual(layout["version_c"], self.root / "kernel/module/version.c")
        self.assertEqual(layout["main_c"], self.root / "kernel/module/main.c")
        self.assertIsNotNone(layout["internal_h"])

    def test_single_file_layout_resolved(self) -> None:
        write_files(self.root, {"kernel/module.c": "/* loader */\n"})
        layout = BRIDGE_APPLY.resolve_layout(self.root)
        self.assertTrue(layout["single_file"])
        self.assertEqual(layout["version_c"], self.root / "kernel/module.c")
        self.assertEqual(layout["main_c"], self.root / "kernel/module.c")
        self.assertIsNone(layout["internal_h"], "no internal.h to declare into")

    def test_no_loader_at_all_is_an_error(self) -> None:
        with self.assertRaises(SystemExit):
            BRIDGE_APPLY.resolve_layout(self.root)


class OptionalPatchGuardTest(unittest.TestCase):
    """A graft that already wrote files must not be reported as a clean skip."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_anchor_with_no_writes_is_a_skip(self) -> None:
        guarded = self.root / "untouched.c"
        guarded.write_text("original\n")

        def fn():
            raise SystemExit("anchor missing")

        result = FEATURE_PORTING.optional_patch(fn, "test/cap", guards=[guarded])
        self.assertEqual(result["status"], "blocked_by_missing_anchor")
        self.assertEqual(guarded.read_text(), "original\n")

    def test_missing_anchor_after_a_write_is_re_raised(self) -> None:
        guarded = self.root / "already_written.c"
        guarded.write_text("original\n")

        def fn():
            guarded.write_text("rewritten\n")
            raise SystemExit("anchor missing in a later file")

        with self.assertRaises(SystemExit) as caught:
            FEATURE_PORTING.optional_patch(fn, "test/cap", guards=[guarded])
        message = str(caught.exception)
        self.assertIn("half-patched", message)
        self.assertIn("abk_rollback.sh", message, "must tell the caller how to recover")
        self.assertIn(str(guarded), message, "must name the file it rewrote")

    def test_guards_absent_keeps_the_old_lenient_behaviour(self) -> None:
        def fn():
            raise SystemExit("anchor missing")

        result = FEATURE_PORTING.optional_patch(fn, "test/cap", status="blocked_by_layout")
        self.assertEqual(result["status"], "blocked_by_layout")


class BackupTest(unittest.TestCase):
    """Every child that rewrites kernel sources must leave a rollback snapshot."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_write_text_snapshots_an_existing_file_once(self) -> None:
        path = self.root / "kernel/sys.c"
        path.parent.mkdir(parents=True)
        path.write_text("original\n")

        FEATURE_PORTING.write_text(path, "first\n")
        backup = path.with_suffix(path.suffix + FEATURE_PORTING.ABK_BACKUP_SUFFIX)
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_text(), "original\n")

        FEATURE_PORTING.write_text(path, "second\n")
        self.assertEqual(backup.read_text(), "original\n", "snapshot must not be overwritten")

    def test_write_text_creates_new_files_without_a_backup(self) -> None:
        path = self.root / "reports/report.json"
        path.parent.mkdir(parents=True)
        FEATURE_PORTING.write_text(path, "{}\n")
        backup = path.with_suffix(path.suffix + FEATURE_PORTING.ABK_BACKUP_SUFFIX)
        self.assertFalse(backup.exists(), "nothing to restore for a file we created")

    def test_every_writing_child_shares_the_snapshotting_helper(self) -> None:
        # A child that calls path.write_text() directly leaves nothing for
        # abk_rollback.sh to restore, so the rollback would silently be partial.
        children = [
            "abk_display_spoof.py",
            "abk_dual_abi_bridge_apply.py",
            "abk_abi_fixups.py",
            "abk_security_update_backport.py",
            "abk_feature_porting.py",
            "abk_feature_porting_phase2.py",
        ]
        for name in children:
            offenders = []
            for lineno, line in enumerate(
                (REPO_ROOT / "scripts" / name).read_text().splitlines(), 1
            ):
                if "path.write_text(" not in line:
                    continue
                # The one legitimate call is inside write_text() itself.
                if line.strip() == "path.write_text(text)":
                    continue
                offenders.append(f"{name}:{lineno}: {line.strip()}")
            self.assertEqual(
                offenders,
                [],
                f"{name} bypasses the snapshotting write_text(), so "
                f"abk_rollback.sh cannot restore what it changed",
            )


if __name__ == "__main__":
    unittest.main()
