#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts/abk_feature_porting.py"
SPEC = importlib.util.spec_from_file_location("abk_feature_porting", MODULE_PATH)
assert SPEC and SPEC.loader
FEATURE_PORTING = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FEATURE_PORTING
SPEC.loader.exec_module(FEATURE_PORTING)


def write_files(root: Path, files: dict[str, str]) -> None:
    for relpath, content in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def make_pidfd_fixture(root: Path) -> None:
    write_files(
        root,
        {
            "kernel/pid.c": """int pidfd_create(struct pid *pid, unsigned int flags)
{
\tif (flags & ~(O_NONBLOCK | O_RDWR | O_CLOEXEC))
\t\treturn -EINVAL;
\treturn 0;
}

SYSCALL_DEFINE2(pidfd_open, pid_t, pid, unsigned int, flags)
{
\tif (flags & ~PIDFD_NONBLOCK)
\t\treturn -EINVAL;
\treturn 0;
}

static int pidfd_getfd(struct pid *pid, int fd)
{
\treturn fd;
}

SYSCALL_DEFINE3(pidfd_getfd, int, pidfd, int, fd,
\t\tunsigned int, flags)
{
\tif (flags)
\t\treturn -EINVAL;
\treturn 0;
}
""",
            "kernel/fork.c": """const struct file_operations pidfd_fops = {
};

static int copy_process(unsigned long clone_flags)
{
\t/*
\t * This has to happen after we've potentially unshared the file
\t * descriptor table (so that the pidfd doesn't leak into the child
\t * if the fd table isn't shared).
\t */
\tif (clone_flags & CLONE_PIDFD) {
\t\t/* Note that no task has been attached to @pid yet. */
\t\tretval = __pidfd_prepare(pid, O_RDWR | O_CLOEXEC, &pidfile);
\t\tif (retval < 0)
\t\t\tgoto bad_fork_free_pid;
\t\tpidfd = retval;

\t\tretval = put_user(pidfd, args->pidfd);
\t\tif (retval)
\t\t\tgoto bad_fork_put_pidfd;
\t}

\treturn 0;
}
""",
        },
    )


def make_blk_mq_fixture(root: Path) -> None:
    write_files(
        root,
        {
            "include/linux/blkdev.h": """struct request_queue {

\tANDROID_KABI_RESERVE(1);
\tANDROID_KABI_RESERVE(2);
\tANDROID_KABI_RESERVE(3);
\tANDROID_KABI_RESERVE(4);

\t/**
\t * @srcu: Sleepable RCU. Use as lock when type of the request queue
""",
            "block/blk-core.c": """void blk_init_allocated_queue(struct request_queue *q)
{
\tq->nr_requests = BLKDEV_DEFAULT_RQ;
}
""",
            "block/blk-mq.c": """static struct request *__blk_mq_alloc_requests(struct blk_mq_alloc_data *data)
{
\tvoid (*limit_depth)(blk_opf_t, struct blk_mq_alloc_data *) = NULL;
\tstruct request_queue *q = data->q;
\tu64 alloc_time_ns = 0;
\tstruct request *rq;
\tunsigned int tag;

\tif (q->elevator) {
\t\tstruct elevator_queue *e = q->elevator;

\t\tdata->rq_flags |= RQF_ELV;

\t\t/*
\t\t * Flush/passthrough requests are special and go directly to the
\t\t * dispatch list. Don't include reserved tags in the
\t\t * limiting, as it isn't useful.
\t\t */
\t\tif (!op_is_flush(data->cmd_flags) &&
\t\t    !blk_op_is_passthrough(data->cmd_flags) &&
\t\t    e->type->ops.limit_depth &&
\t\t    !(data->flags & BLK_MQ_REQ_RESERVED))
\t\t\tlimit_depth = e->type->ops.limit_depth;
\t}

retry:
\tdata->ctx = blk_mq_get_ctx(q);
\tdata->hctx = blk_mq_map_queue(q, data->cmd_flags, data->ctx);
\tif (!(data->rq_flags & RQF_ELV))
\t\tblk_mq_tag_busy(data->hctx);

\tif (data->flags & BLK_MQ_REQ_RESERVED)
\t\tdata->rq_flags |= RQF_RESV;

\tif (limit_depth)
\t\tlimit_depth(data->cmd_flags, data);

\treturn rq;
}

static int blk_mq_init_allocated_queue(struct blk_mq_tag_set *set)
{
\tq->nr_requests = set->queue_depth;
\treturn 0;
}

static int blk_mq_update_nr_requests(struct blk_mq_tag_set *set, unsigned int nr, int ret)
{
\tif (!ret) {
\t\tq->nr_requests = nr;
\t\tif (blk_mq_is_shared_tags(set->flags)) {
\t\t}
\t}
\treturn ret;
}
""",
            "block/blk-mq-sched.c": """int blk_mq_init_sched(struct request_queue *q, struct elevator_type *e)
{
\tif (!e) {
\t\tblk_queue_flag_clear(QUEUE_FLAG_SQ_SCHED, q);
\t\tq->elevator = NULL;
\t\tq->nr_requests = q->tag_set->queue_depth;
\t\treturn 0;
\t}

\tq->nr_requests = 2 * min_t(unsigned int, q->tag_set->queue_depth,
\t\t\t\t   BLKDEV_DEFAULT_RQ);
\treturn 0;
}
""",
            "block/blk-sysfs.c": """static ssize_t
queue_ra_store(struct request_queue *q, const char *page, size_t count)
{
\treturn count;
}

QUEUE_RW_ENTRY(queue_requests, "nr_requests");
QUEUE_RW_ENTRY(queue_ra, "read_ahead_kb");

static struct attribute *queue_attrs[] = {
\t&queue_requests_entry.attr,
\t&queue_ra_entry.attr,
};
""",
            "block/elevator.c": """static int elevator_switch_mq(struct request_queue *q, struct elevator_type *new_e)
{
\tint ret;

\tret = blk_mq_init_sched(q, new_e);
\tif (ret)
\t\tgoto out;
out:
\treturn ret;
}
""",
            "block/mq-deadline.c": """static void dd_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)
{
\tstruct deadline_data *dd = data->q->elevator->elevator_data;

\tdata->shallow_depth = dd->async_depth;
}

/*
 * Called by __blk_mq_alloc_request(). The shallow_depth value set by this
 * function is used by __blk_mq_get_tag().
 */
static void dd_depth_updated(struct blk_mq_hw_ctx *hctx)
{
\tstruct request_queue *q = hctx->queue;
\tstruct deadline_data *dd = q->elevator->elevator_data;
\tstruct blk_mq_tags *tags = hctx->sched_tags;
\tunsigned int shift = tags->bitmap_tags.sb.shift;

\tdd->async_depth = max(1U, 3 * (1U << shift)  / 4);

\tsbitmap_queue_min_shallow_depth(&tags->bitmap_tags, dd->async_depth);
}

static int dd_init_sched(struct request_queue *q, struct elevator_queue *eq)
{
\tq->elevator = eq;
\treturn 0;
}
""",
            "block/bfq-iosched.c": """static void bfq_depth_updated(struct blk_mq_hw_ctx *hctx)
{
}

static void bfq_update_depths(struct bfq_data *bfqd, struct sbitmap_queue *bt)
{
\tunsigned int depth = 1U << bt->sb.shift;

\tbfqd->full_depth_shift = bt->sb.shift;
}

static int bfq_init_queue(struct request_queue *q)
{
\tbfqd->queue = q;
\treturn 0;
}
""",
            "block/kyber-iosched.c": """static void kyber_depth_updated(struct blk_mq_hw_ctx *hctx)
{
}

static int kyber_init_sched(struct request_queue *q, struct elevator_queue *eq, struct kyber_queue_data *kqd)
{
\teq->elevator_data = kqd;
\tq->elevator = eq;

\treturn 0;
}

static void kyber_depth_updated_impl(struct blk_mq_hw_ctx *hctx)
{
\tstruct kyber_queue_data *kqd = hctx->queue->elevator->elevator_data;
\tstruct blk_mq_tags *tags = hctx->sched_tags;
\tunsigned int shift = tags->bitmap_tags.sb.shift;

\tkqd->async_depth = (1U << shift) * KYBER_ASYNC_PERCENT / 100U;

\tsbitmap_queue_min_shallow_depth(&tags->bitmap_tags, kqd->async_depth);
}
""",
        },
    )


class FeaturePortingRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_pidfd_preparation_accepts_prepare_based_fork_shape(self) -> None:
        make_pidfd_fixture(self.root)

        result = FEATURE_PORTING.patch_pidfd_preparation_compat(self.root)
        self.assertEqual(result["mode"], "patched")

        pid_text = (self.root / "kernel/pid.c").read_text()
        fork_text = (self.root / "kernel/fork.c").read_text()
        self.assertIn("abk_pidfd_has_forbidden_flags", pid_text)
        self.assertIn("if (abk_pidfd_has_forbidden_flags(flags, PIDFD_NONBLOCK))", pid_text)
        self.assertIn("if (abk_pidfd_has_forbidden_flags(flags, 0))", pid_text)
        self.assertIn("phase-three scan-based EEVDF runtime-state and pidfd compat entry executed", pid_text)
        self.assertIn("keep CLONE_PIDFD on legacy pidfd plumbing; pidfs remains deferred", fork_text)

        rerun = FEATURE_PORTING.patch_pidfd_preparation_compat(self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_blk_mq_async_depth_keeps_limit_depth_declaration(self) -> None:
        make_blk_mq_fixture(self.root)

        result = FEATURE_PORTING.patch_blk_mq_async_depth(self.root)
        self.assertEqual(result["mode"], "patched")

        blk_mq_text = (self.root / "block/blk-mq.c").read_text()
        self.assertIn("static void blk_mq_limit_depth(blk_opf_t opf, struct blk_mq_alloc_data *data)", blk_mq_text)
        self.assertIn("void (*limit_depth)(blk_opf_t, struct blk_mq_alloc_data *) = NULL;", blk_mq_text)
        self.assertIn("limit_depth = blk_mq_limit_depth;", blk_mq_text)

    def test_blk_mq_async_depth_repairs_half_patched_header(self) -> None:
        make_blk_mq_fixture(self.root)
        FEATURE_PORTING.patch_blk_mq_async_depth(self.root)

        blk_mq_path = self.root / "block/blk-mq.c"
        broken = blk_mq_path.read_text().replace(
            "\tvoid (*limit_depth)(blk_opf_t, struct blk_mq_alloc_data *) = NULL;\n",
            "",
            1,
        )
        blk_mq_path.write_text(broken)

        self.assertNotIn("void (*limit_depth)(blk_opf_t, struct blk_mq_alloc_data *) = NULL;", blk_mq_path.read_text())
        self.assertIn("limit_depth = blk_mq_limit_depth;", blk_mq_path.read_text())

        result = FEATURE_PORTING.patch_blk_mq_async_depth(self.root)
        self.assertEqual(result["mode"], "patched")
        self.assertIn(
            "void (*limit_depth)(blk_opf_t, struct blk_mq_alloc_data *) = NULL;",
            blk_mq_path.read_text(),
        )


if __name__ == "__main__":
    unittest.main()
