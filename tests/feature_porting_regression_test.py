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


def make_io_uring_fixture(root: Path, *, exact_comment_shape: bool) -> None:
    if exact_comment_shape:
        nowait_block = """\t\t/*\n\t\t * If REQ_F_NOWAIT is set, then don't wait or retry with\n\t\t * poll. -EAGAIN is final for that case.\n\t\t */\n\t\tif (req->flags & REQ_F_NOWAIT)\n\t\t\tbreak;\n"""
    else:
        nowait_block = """\t\t/* 6.1.25 keeps NOWAIT final here, but not the newer comment block. */\n\t\tif (req->flags & REQ_F_NOWAIT)\n\t\t\tbreak;\n"""

    write_files(
        root,
        {
            "io_uring/io_uring.c": f"""static void io_prep_async_work(struct io_kiocb *req)
{{
\tif (req->file && !io_req_ffs_set(req))
\t\treturn;
}}

struct io_wq_work *io_wq_free_work(struct io_wq_work *work)
{{
\tstruct io_kiocb *req = container_of(work, struct io_kiocb, work);

\treq = io_put_req_find_next(req);
\treturn req ? &req->work : NULL;
}}

void io_wq_submit_work(struct io_wq_work *work)
{{
\tstruct io_kiocb *req = container_of(work, struct io_kiocb, work);

\twhile (1) {{
{nowait_block}\t}}
}}

static void io_queue_async(struct io_kiocb *req, int ret)
\t__must_hold(&req->ctx->uring_lock)
{{
\tif (ret)
\t\treturn;
}}
""",
            "io_uring/filetable.c": """static int io_file_bitmap_get(struct io_ring_ctx *ctx)
{
\tstruct io_file_table *table = &ctx->file_table;

\tif (!table->bitmap)
\t\treturn -ENFILE;

\tdo {
\t\treturn 0;
\t} while (0);
}
""",
            "io_uring/filetable.h": """unsigned int io_file_get_flags(struct file *file);
#define FFS_NOWAIT\t\t0x1UL
""",
            "io_uring/refs.h": """static inline bool req_ref_put_and_test(struct io_kiocb *req)
{
\treturn false;
}

static inline void __io_req_set_refcount(struct io_kiocb *req, int nr)
{
}
""",
            "io_uring/opdef.c": """const struct io_op_def io_op_defs[] = {
};
""",
        },
    )


def make_fd_alloc_fixture(
    root: Path,
    *,
    with_fdt_words: bool,
    alloc_signature: str | None = None,
    alloc_locals: str | None = None,
    alloc_capacity_block: str | None = None,
) -> None:
    helper_anchor = "#define fdt_words(fdt) ((fdt)->max_fds / BITS_PER_LONG) // words in ->open_fds\n\n"
    alloc_signature = alloc_signature or "static struct fdtable * alloc_fdtable(unsigned int nr)"
    alloc_locals = alloc_locals or "\tstruct fdtable *fdt;\n\tvoid *data;\n\n"
    alloc_capacity_block = alloc_capacity_block or """\tnr /= (1024 / sizeof(struct file *));\n\tnr = roundup_pow_of_two(nr + 1);\n\tnr *= (1024 / sizeof(struct file *));\n\tnr = ALIGN(nr, BITS_PER_LONG);\n"""

    write_files(
        root,
        {
            "fs/file.c": f"""{helper_anchor if with_fdt_words else ""}{alloc_signature}
{{
{alloc_locals}\
\t/*
\t * Figure out how many fds we actually want to support in this fdtable.
\t * Allocation steps are keyed to the size of the fdarray, since it
\t * grows far faster than any of the other dynamic data. We try to fit
\t * the fdarray into comfortable page-tuned chunks: starting at 1024B
\t * and growing in powers of two from there on.
\t */
{alloc_capacity_block}\
\t/*
\t * Note that this can drive nr *below* what we had passed if sysctl_nr_open
\t * had been set lower between the check in expand_files() and here.  Deal
\t * with that in caller, it's cheaper that way.
\t *
\t * We make sure that nr remains a multiple of BITS_PER_LONG - otherwise
\t * bitmaps handling below becomes unpleasant, to put it mildly...
\t */
\tif (unlikely(nr > sysctl_nr_open))
\t\tnr = ((sysctl_nr_open - 1) | (BITS_PER_LONG - 1)) + 1;

\tfdt = kmalloc(sizeof(struct fdtable), GFP_KERNEL_ACCOUNT);
\tif (!fdt)
\t\tgoto out;
\tfdt->max_fds = nr;
\tdata = kvmalloc_array(nr, sizeof(struct file *), GFP_KERNEL_ACCOUNT);
\tif (!data)
\t\tgoto out_fdt;
\tfdt->fd = data;

\tdata = kvmalloc(max_t(size_t,
\t\t\t\t 2 * nr / BITS_PER_BYTE + BITBIT_SIZE(nr), L1_CACHE_BYTES),
\t\t\t\t GFP_KERNEL_ACCOUNT);
\tif (!data)
\t\tgoto out_arr;
\tfdt->open_fds = data;
\tdata += nr / BITS_PER_BYTE;
\tfdt->close_on_exec = data;
\tdata += nr / BITS_PER_BYTE;
\tfdt->full_fds_bits = data;

\treturn fdt;

out_arr:
\tkvfree(fdt->fd);
out_fdt:
\tkfree(fdt);
out:
\treturn NULL;
}}

static int expand_fdtable(struct files_struct *files, unsigned int nr)
{{
\treturn 0;
}}

static int expand_files(struct files_struct *files, unsigned int nr)
{{
\tint expanded = 0;
\tstruct fdtable *fdt;

repeat:
\tfdt = files_fdtable(files);

\t/* Do we need to expand? */
\tif (nr < fdt->max_fds)
\t\treturn expanded;

\t/* Can we expand? */
\tif (nr >= sysctl_nr_open)
\t\treturn -EMFILE;

\treturn expanded;
}}

static int alloc_fd(struct files_struct *files, unsigned start, unsigned end, unsigned flags)
{{
\tstruct fdtable *fdt = files_fdtable(files);
\tunsigned int fd = start;
\tint error;

repeat:
\tif (fd < fdt->max_fds)
\t\tfd = find_next_fd(fdt, fd);

\t/*
\t * N.B. For clone tasks sharing a files structure, this test
\t * will limit the total number of files that can be opened.
\t */
\terror = -EMFILE;
\tif (fd >= end)
\t\tgoto out;

\terror = expand_files(files, fd);
\tif (error < 0)
\t\tgoto out;

\t/*
\t * If we needed to expand the fs array we
\t * might have blocked - try again.
\t */
\tif (error)
\t\tgoto repeat;

\treturn fd;
out:
\treturn error;
}}

int get_unused_fd_flags(unsigned flags)
{{
\treturn __get_unused_fd_flags(flags, rlimit(RLIMIT_NOFILE));
}}
""",
        },
    )


def make_refactored_fd_alloc_fixture(root: Path) -> None:
    """Fixture mirroring the post-2025-08 android13-5.15-lts (SUBLEVEL 211) shape.

    The Al Viro fdtable refactor backport gave alloc_fdtable() a slot-count
    parameter, a roundup_pow_of_two() capacity and ERR_PTR()/IS_ERR() failure
    reporting; expand_files()/alloc_fd()/get_unused_fd_flags() kept their
    legacy text, so the helper prechecks can still land there.
    """
    write_files(
        root,
        {
            "fs/file.c": """#define fdt_words(fdt) ((fdt)->max_fds / BITS_PER_LONG) // words in ->open_fds

static struct fdtable *alloc_fdtable(unsigned int slots_wanted)
{
\tstruct fdtable *fdt;
\tunsigned int nr;
\tvoid *data;

\t/*
\t * Figure out how many fds we actually want to support in this fdtable.
\t * Allocation steps are keyed to the size of the fdarray, since it
\t * grows far faster than any of the other dynamic data. We try to fit
\t * the fdarray into comfortable page-tuned chunks: starting at 1024B
\t * and growing in powers of two from there on.  Since we called only
\t * with slots_wanted > BITS_PER_LONG (embedded instance in files->fdtab
\t * already gives BITS_PER_LONG slots), the above boils down to
\t * 1.  use the smallest power of two large enough to give us that many
\t * slots.
\t * 2.  on 32bit skip 64 and 128 - the minimal capacity we want there is
\t * 256 slots (i.e. 1Kb fd array).
\t * 3.  on 64bit don't skip anything, 1Kb fd array means 128 slots there
\t * and we are never going to be asked for 64 or less.
\t */
\tif (IS_ENABLED(CONFIG_32BIT) && slots_wanted < 256)
\t\tnr = 256;
\telse
\t\tnr = roundup_pow_of_two(slots_wanted);
\t/*
\t * Note that this can drive nr *below* what we had passed if sysctl_nr_open
\t * had been set lower between the check in expand_files() and here.
\t *
\t * We make sure that nr remains a multiple of BITS_PER_LONG - otherwise
\t * bitmaps handling below becomes unpleasant, to put it mildly...
\t */
\tif (unlikely(nr > sysctl_nr_open)) {
\t\tnr = round_down(sysctl_nr_open, BITS_PER_LONG);
\t\tif (nr < slots_wanted)
\t\t\treturn ERR_PTR(-EMFILE);
\t}

\t/*
\t * Check if the allocation size would exceed INT_MAX. kvmalloc_array()
\t * and kvmalloc() will warn if the allocation size is greater than
\t * INT_MAX, as filp_cachep objects are not __GFP_NOWARN.
\t *
\t * This can happen when sysctl_nr_open is set to a very high value and
\t * a process tries to use a file descriptor near that limit. For example,
\t * if sysctl_nr_open is set to 1073741816 (0x3ffffff8) - which is what
\t * systemd typically sets it to - then trying to use a file descriptor
\t * close to that value will require allocating a file descriptor table
\t * that exceeds 8GB in size.
\t */
\tif (unlikely(nr > INT_MAX / sizeof(struct file *)))
\t\treturn ERR_PTR(-EMFILE);

\tfdt = kmalloc(sizeof(struct fdtable), GFP_KERNEL_ACCOUNT);
\tif (!fdt)
\t\tgoto out;
\tfdt->max_fds = nr;
\tdata = kvmalloc_array(nr, sizeof(struct file *), GFP_KERNEL_ACCOUNT);
\tif (!data)
\t\tgoto out_fdt;
\tfdt->fd = data;

\tdata = kvmalloc(max_t(size_t,
\t\t\t\t 2 * nr / BITS_PER_BYTE + BITBIT_SIZE(nr), L1_CACHE_BYTES),
\t\t\t\t GFP_KERNEL_ACCOUNT);
\tif (!data)
\t\tgoto out_arr;
\tfdt->open_fds = data;
\tdata += nr / BITS_PER_BYTE;
\tfdt->close_on_exec = data;
\tdata += nr / BITS_PER_BYTE;
\tfdt->full_fds_bits = data;

\treturn fdt;

out_arr:
\tkvfree(fdt->fd);
out_fdt:
\tkfree(fdt);
out:
\treturn ERR_PTR(-ENOMEM);
}

static int expand_fdtable(struct files_struct *files, unsigned int nr)
\t__releases(files->file_lock)
\t__acquires(files->file_lock)
{
\tstruct fdtable *new_fdt, *cur_fdt;

\tspin_unlock(&files->file_lock);
\tnew_fdt = alloc_fdtable(nr + 1);

\t/* make sure all fd_install() have seen resize_in_progress
\t * or have finished their rcu_read_lock_sched() section.
\t */
\tif (atomic_read(&files->count) > 1)
\t\tsynchronize_rcu();

\tspin_lock(&files->file_lock);
\tif (IS_ERR(new_fdt))
\t\treturn PTR_ERR(new_fdt);
\tcur_fdt = files_fdtable(files);
\tBUG_ON(nr < cur_fdt->max_fds);
\tcopy_fdtable(new_fdt, cur_fdt);
\trcu_assign_pointer(files->fdt, new_fdt);
\tif (cur_fdt != &files->fdtab)
\t\tcall_rcu(&cur_fdt->rcu, free_fdtable_rcu);
\t/* coupled with smp_rmb() in fd_install() */
\tsmp_wmb();
\treturn 1;
}

static int expand_files(struct files_struct *files, unsigned int nr)
\t__releases(files->file_lock)
\t__acquires(files->file_lock)
{
\tstruct fdtable *fdt;
\tint expanded = 0;

repeat:
\tfdt = files_fdtable(files);

\t/* Do we need to expand? */
\tif (nr < fdt->max_fds)
\t\treturn expanded;

\t/* Can we expand? */
\tif (nr >= sysctl_nr_open)
\t\treturn -EMFILE;

\tif (unlikely(files->resize_in_progress)) {
\t\tspin_unlock(&files->file_lock);
\t\texpanded = 1;
\t\twait_event(files->resize_wait, !files->resize_in_progress);
\t\tspin_lock(&files->file_lock);
\t\tgoto repeat;
\t}

\t/* All good, so we try */
\tfiles->resize_in_progress = true;
\texpanded = expand_fdtable(files, nr);
\tfiles->resize_in_progress = false;

\twake_up_all(&files->resize_wait);
\treturn expanded;
}

static int alloc_fd(unsigned start, unsigned end, unsigned flags)
{
\tstruct files_struct *files = current->files;
\tunsigned int fd;
\tint error;
\tstruct fdtable *fdt;

\tspin_lock(&files->file_lock);
repeat:
\tfdt = files_fdtable(files);
\tfd = start;
\tif (fd < files->next_fd)
\t\tfd = files->next_fd;

\tif (fd < fdt->max_fds)
\t\tfd = find_next_fd(fdt, fd);

\t/*
\t * N.B. For clone tasks sharing a files structure, this test
\t * will limit the total number of files that can be opened.
\t */
\terror = -EMFILE;
\tif (fd >= end)
\t\tgoto out;

\terror = expand_files(files, fd);
\tif (error < 0)
\t\tgoto out;

\t/*
\t * If we needed to expand the fs array we
\t * might have blocked - try again.
\t */
\tif (error)
\t\tgoto repeat;

\tif (start <= files->next_fd)
\t\tfiles->next_fd = fd + 1;

\t__set_open_fd(fd, fdt);
\tif (flags & O_CLOEXEC)
\t\t__set_close_on_exec(fd, fdt);
\telse
\t\t__clear_close_on_exec(fd, fdt);
\terror = fd;
out:
\tspin_unlock(&files->file_lock);
\treturn error;
}

int get_unused_fd_flags(unsigned flags)
{
\treturn __get_unused_fd_flags(flags, rlimit(RLIMIT_NOFILE));
}
""",
        },
    )


def make_slub_fixture(root: Path) -> None:
    write_files(
        root,
        {
            "mm/slub.c": """/*
 * Inlined fastpath so that allocation functions (kmalloc, kmem_cache_alloc)
 */
static __always_inline void *slab_alloc_node(struct kmem_cache *s, struct list_lru *lru,
\t\t\t\t\t     gfp_t gfpflags, int node, unsigned long addr)
{
\tvoid *object;

\tif (!object) {
\t\treturn NULL;
\t} else {
\t\tvoid *next_object = get_freepointer_safe(s, object);

\t\t/*
\t\t * The cmpxchg will only match if there was no additional
\t\t * operation and if we are on the right processor.
\t\t */
\t\treturn next_object;
\t}
}

int kmem_cache_alloc_bulk(struct kmem_cache *s, gfp_t flags, size_t size,
\t\t\t\t void **p)
{
\tstruct kmem_cache_cpu *c;
\tvoid *object;
\tint i;

\tfor (i = 0; i < size; i++) {
\t\tobject = p[i];
\t\tc->freelist = get_freepointer(s, object);
\t\tp[i] = object;
\t\tmaybe_wipe_obj_freeptr(s, p[i]);
\t}
\treturn 0;
}

void kmem_cache_free(struct kmem_cache *s, void *x)
{
\ts = cache_from_obj(s, x);
\tif (!s)
\t\treturn;
\ttrace_kmem_cache_free(_RET_IP_, x, s);
\tslab_free(s, virt_to_slab(x), x, NULL, &x, 1, _RET_IP_);
}

static __always_inline void maybe_wipe_obj_freeptr(struct kmem_cache *s,
\t\t\t\t\t\t   void *obj)
{
}

static size_t build_detached_freelist(struct kmem_cache *s, void **p, size_t size,
\t\t\t\t      struct detached_freelist *df)
{
\tvoid *object;
\tstruct folio *folio;
\tsize_t same;

\tobject = p[--size];
\tfolio = virt_to_folio(object);
\tif (!s) {
\t\t/* Handle kalloc'ed objects */
\t\tif (unlikely(!folio_test_slab(folio))) {
\t\t\tfree_large_kmalloc(folio, object);
\t\t\tdf->slab = NULL;
\t\t\treturn size;
\t\t}
\t\t/* Derive kmem_cache from object */
\t\tdf->slab = folio_slab(folio);
\t\tdf->s = df->slab->slab_cache;
\t} else {
\t\tdf->slab = folio_slab(folio);
\t\tdf->s = cache_from_obj(s, object); /* Support for memcg */
\t}
\treturn same;
}
""",
        },
    )


def make_close_range_fixture(root: Path, *, raw_dereference: bool) -> None:
    file_load = "file = rcu_dereference_raw(fdt->fd[fd]);" if raw_dereference else "file = fdt->fd[fd];"

    write_files(
        root,
        {
            "fs/file.c": f"""static struct file *pick_file(struct files_struct *files, unsigned fd)
{{
\tstruct fdtable *fdt = files_fdtable(files);
\tstruct file *file;

\tif (fd >= fdt->max_fds)
\t\treturn NULL;

\tfd = array_index_nospec(fd, fdt->max_fds);
\t{file_load}
\tif (file) {{
\t\trcu_assign_pointer(fdt->fd[fd], NULL);
\t\t__put_unused_fd(files, fd);
\t}}
\treturn file;
}}

static inline void __range_close(struct files_struct *cur_fds, unsigned int fd,
\t\t\t\t unsigned int max_fd)
{{
\tunsigned n;

\trcu_read_lock();
\tn = last_fd(files_fdtable(cur_fds));
\trcu_read_unlock();
\tmax_fd = min(max_fd, n);

\twhile (fd <= max_fd) {{
\t\tstruct file *file;

\t\tspin_lock(&cur_fds->file_lock);
\t\tfile = pick_file(cur_fds, fd++);
\t\tspin_unlock(&cur_fds->file_lock);

\t\tif (file) {{
\t\t\t/* found a valid file to close */
\t\t\tfilp_close(file, cur_fds);
\t\t\tcond_resched();
\t\t}}
\t}}
}}

int __close_range(unsigned fd, unsigned max_fd, unsigned int flags)
{{
\treturn 0;
}}
""",
        },
    )


def make_fair_fixture(root: Path, *, drifted_reweight: bool) -> None:
    if drifted_reweight:
        reweight_fn = """static void reweight_entity(struct cfs_rq *cfs_rq, struct sched_entity *se,
\t\t\t    unsigned long weight)
{
\tif (se->on_rq) {
\t\t/* commit outstanding execution time */
\t\tif (cfs_rq->curr == se)
\t\t\tupdate_curr(cfs_rq);

\t\tupdate_load_sub(&cfs_rq->load, se->load.weight);
\t}
\tdequeue_load_avg(cfs_rq, se);

\tupdate_load_set(&se->load, weight);

#ifdef CONFIG_SMP
\tdo {
\t\tu32 divider = get_pelt_divider(&se->avg);

\t\tse->avg.load_avg = div_u64(se_weight(se) * se->avg.load_sum, divider);
\t} while (0);
#endif

\tenqueue_load_avg(cfs_rq, se);
\tif (se->on_rq)
\t\tupdate_load_add(&cfs_rq->load, se->load.weight);

}
"""
    else:
        reweight_fn = """static void reweight_entity(struct cfs_rq *cfs_rq, struct sched_entity *se,
\t\t\t    unsigned long weight)
{
\tif (se->on_rq) {
\t\t/* commit outstanding execution time */
\t\tif (cfs_rq->curr == se)
\t\t\tupdate_curr(cfs_rq);
\t\tupdate_load_sub(&cfs_rq->load, se->load.weight);
\t}
\tdequeue_load_avg(cfs_rq, se);

\tupdate_load_set(&se->load, weight);

#ifdef CONFIG_SMP
\tdo {
\t\tu32 divider = get_pelt_divider(&se->avg);

\t\tse->avg.load_avg = div_u64(se_weight(se) * se->avg.load_sum, divider);
\t} while (0);
#endif

\tenqueue_load_avg(cfs_rq, se);
\tif (se->on_rq)
\t\tupdate_load_add(&cfs_rq->load, se->load.weight);

}
"""

    write_files(
        root,
        {
            "kernel/sched/fair.c": f"""static inline bool entity_before(struct sched_entity *a,
\t\t\t\t      struct sched_entity *b)
{{
\treturn false;
}}

static u64 sched_vslice(struct cfs_rq *cfs_rq, struct sched_entity *se)
{{
\treturn calc_delta_fair(sched_slice(cfs_rq, se), se);
}}

#ifdef CONFIG_SMP
static inline void
enqueue_load_avg(struct cfs_rq *cfs_rq, struct sched_entity *se) {{ }}
static inline void
dequeue_load_avg(struct cfs_rq *cfs_rq, struct sched_entity *se) {{ }}
#endif

{reweight_fn}
static struct sched_entity *__pick_next_entity(struct sched_entity *se)
{{
\treturn se;
}}

static void
place_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int initial)
{{
\tu64 vruntime = cfs_rq->min_vruntime;

\tif (entity_is_long_sleeper(se))
\t\tse->vruntime = vruntime;
\telse
\t\tse->vruntime = max_vruntime(se->vruntime, vruntime);
}}

enqueue_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int flags)
{{
\tstruct sched_entity *curr = cfs_rq->curr;

\tif (flags & ENQUEUE_WAKEUP)
\t\tplace_entity(cfs_rq, se, 0);
\t/* Entity has migrated, no longer consider this task hot */
\tif (flags & ENQUEUE_MIGRATED)
\t\tse->exec_start = 0;

\tcheck_schedstat_required();
\tupdate_stats_enqueue_fair(cfs_rq, se, flags);
\tcheck_spread(cfs_rq, se);
\tif (!curr)
\t\t__enqueue_entity(cfs_rq, se);
\tse->on_rq = 1;
}}

check_preempt_tick(struct cfs_rq *cfs_rq, struct sched_entity *curr)
{{
\tstruct sched_entity *se;
\ts64 delta;
\tu64 ideal_runtime = 0;

\tse = __pick_first_entity(cfs_rq);
\tdelta = curr->vruntime - se->vruntime;

\tif (delta < 0)
\t\treturn;

\tif (delta > ideal_runtime)
\t\tresched_curr(rq_of(cfs_rq));
}}

void set_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *se)
{{
\tif (se->on_rq) {{
\t\tupdate_stats_wait_end_fair(cfs_rq, se);
\t\t__dequeue_entity(cfs_rq, se);
\t\tupdate_load_avg(cfs_rq, se, UPDATE_TG);
\t}}
}}

static struct sched_entity *
pick_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *curr)
{{
\tstruct sched_entity *left = __pick_first_entity(cfs_rq);
\tstruct sched_entity *se = NULL;

\ttrace_android_rvh_pick_next_entity(cfs_rq, curr, &se);
\tif (se)
\t\tgoto done;

\t/*
\t * If curr is set we have to see if its left of the leftmost entity
\t * still in the tree, provided there was anything in the tree at all.
\t */
\tif (!left || (curr && entity_before(curr, left)))
\t\tleft = curr;

\tse = left; /* ideally we run the leftmost entity */

\t/*
\t * Avoid running the skip buddy, if running something else can
\t * be done without getting too unfair.
\t */
\tif (cfs_rq->skip && cfs_rq->skip == se) {{
\t\tstruct sched_entity *second;

\t\tif (se == curr) {{
\t\t\tsecond = __pick_first_entity(cfs_rq);
\t\t}} else {{
\t\t\tsecond = __pick_next_entity(se);
\t\t\tif (!second || (curr && entity_before(curr, second)))
\t\t\t\tsecond = curr;
\t\t}}

\t\tif (second && wakeup_preempt_entity(second, left) < 1)
\t\t\tse = second;
\t}}

\tif (cfs_rq->next && wakeup_preempt_entity(cfs_rq->next, left) < 1) {{
\t\t/*
\t\t * Someone really wants this to run. If it's not unfair, run it.
\t\t */
\t\tse = cfs_rq->next;
\t}} else if (cfs_rq->last && wakeup_preempt_entity(cfs_rq->last, left) < 1) {{
\t\t/*
\t\t * Prefer last buddy, try to return the CPU to a preempted task.
\t\t */
\t\tse = cfs_rq->last;
\t}}

done:
\treturn se;
}}

static void put_prev_entity(struct cfs_rq *cfs_rq, struct sched_entity *prev)
{{
\tif (prev->on_rq) {{
\t\tupdate_stats_wait_start_fair(cfs_rq, prev);
\t\t/* Put 'current' back into the tree. */
\t\t__enqueue_entity(cfs_rq, prev);
\t\t/* in !on_rq case, update occurred at dequeue */
\t\tupdate_load_avg(cfs_rq, prev, 0);
\t}}
}}

static void
dequeue_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int flags)
{{
\tint action = UPDATE_TG;

\tupdate_stats_dequeue_fair(cfs_rq, se, flags);

\tclear_buddies(cfs_rq, se);

\tif (se != cfs_rq->curr)
\t\t__dequeue_entity(cfs_rq, se);
\tse->on_rq = 0;
\taccount_entity_dequeue(cfs_rq, se);

\tif (!(flags & DEQUEUE_SLEEP))
\t\tse->vruntime -= cfs_rq->min_vruntime;
}}

entity_tick(struct cfs_rq *cfs_rq, struct sched_entity *curr, int queued)
{{
\tif (cfs_rq->nr_running > 1)
\t\tcheck_preempt_tick(cfs_rq, curr);
\ttrace_android_rvh_entity_tick(cfs_rq, curr);
}}
""",
        },
    )


class FeaturePortingRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def assert_count(self, text: str, needle: str, expected: int = 1) -> None:
        self.assertEqual(text.count(needle), expected, needle)

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

    def test_blk_mq_async_depth_uses_explicit_resize_type(self) -> None:
        make_blk_mq_fixture(self.root)

        result = FEATURE_PORTING.patch_blk_mq_async_depth(self.root)
        self.assertEqual(result["mode"], "patched")

        blk_mq_text = (self.root / "block/blk-mq.c").read_text()
        self.assertIn("unsigned long new_async_depth;", blk_mq_text)
        self.assertIn("new_async_depth = q->async_depth * nr / q->nr_requests;", blk_mq_text)
        self.assertIn("q->async_depth = min_t(unsigned long, new_async_depth, UINT_MAX);", blk_mq_text)
        self.assertNotIn("max(q->async_depth * nr / q->nr_requests, 1U)", blk_mq_text)

        FEATURE_PORTING.patch_blk_mq_async_depth(self.root)
        rerun_text = (self.root / "block/blk-mq.c").read_text()
        self.assertEqual(rerun_text.count("new_async_depth = q->async_depth * nr / q->nr_requests;"), 1)

    def test_io_uring_nowait_core_accepts_61_25_comment_drift(self) -> None:
        make_io_uring_fixture(self.root, exact_comment_shape=False)

        result = FEATURE_PORTING.patch_io_uring_nowait_core(self.root, self.root)
        self.assertEqual(result["mode"], "patched")

        core_text = (self.root / "io_uring/io_uring.c").read_text()
        refs_text = (self.root / "io_uring/refs.h").read_text()
        self.assertIn("only keep NOWAIT final when the request explicitly requested it", core_text)
        self.assertIn("req_ref_put_and_test_atomic", refs_text)
        self.assert_count(
            core_text,
            "/* ABK feature_porting: only keep NOWAIT final when the request explicitly requested it. */",
        )

        rerun = FEATURE_PORTING.patch_io_uring_nowait_core(self.root, self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_io_uring_nowait_core_keeps_partial_comment_marker_idempotent(self) -> None:
        make_io_uring_fixture(self.root, exact_comment_shape=False)

        io_uring_path = self.root / "io_uring/io_uring.c"
        partial = io_uring_path.read_text().replace(
            "\t\tif (req->flags & REQ_F_NOWAIT)\n",
            "\t\t/* ABK feature_porting: only keep NOWAIT final when the request explicitly requested it. */\n"
            "\t\tif (req->flags & REQ_F_NOWAIT)\n",
            1,
        )
        io_uring_path.write_text(partial)

        result = FEATURE_PORTING.patch_io_uring_nowait_core(self.root, self.root)
        self.assertEqual(result["mode"], "patched")

        core_text = io_uring_path.read_text()
        self.assertIn("io_uring NOWAIT core issue path graft", core_text)
        self.assert_count(
            core_text,
            "/* ABK feature_porting: only keep NOWAIT final when the request explicitly requested it. */",
        )

        rerun = FEATURE_PORTING.patch_io_uring_nowait_core(self.root, self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_io_uring_nowait_core_keeps_existing_comment_shape(self) -> None:
        make_io_uring_fixture(self.root, exact_comment_shape=True)

        result = FEATURE_PORTING.patch_io_uring_nowait_core(self.root, self.root)
        self.assertEqual(result["mode"], "patched")

        core_text = (self.root / "io_uring/io_uring.c").read_text()
        self.assertIn("io_uring NOWAIT core issue path graft", core_text)
        self.assertCountEqual(
            [line for line in core_text.splitlines() if "only keep NOWAIT final" in line],
            ["\t\t/* ABK feature_porting: only keep NOWAIT final when the request explicitly requested it. */"],
        )

    def test_io_uring_nowait_core_accepts_space_indented_nowait_line(self) -> None:
        make_io_uring_fixture(self.root, exact_comment_shape=False)

        io_uring_path = self.root / "io_uring/io_uring.c"
        drifted = io_uring_path.read_text().replace(
            "\t\t/* 6.1.25 keeps NOWAIT final here, but not the newer comment block. */\n\t\tif (req->flags & REQ_F_NOWAIT)\n\t\t\tbreak;\n",
            "        /* 6.1.25 keeps NOWAIT final here, but not the newer comment block. */\n\n        if (req->flags & REQ_F_NOWAIT)\n                break;\n",
            1,
        )
        io_uring_path.write_text(drifted)

        result = FEATURE_PORTING.patch_io_uring_nowait_core(self.root, self.root)
        self.assertEqual(result["mode"], "patched")

        core_text = io_uring_path.read_text()
        self.assertIn("        /* ABK feature_porting: only keep NOWAIT final when the request explicitly requested it. */", core_text)
        self.assert_count(
            core_text,
            "/* ABK feature_porting: only keep NOWAIT final when the request explicitly requested it. */",
        )

        rerun = FEATURE_PORTING.patch_io_uring_nowait_core(self.root, self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_io_uring_nowait_core_accepts_bare_nowait_line(self) -> None:
        make_io_uring_fixture(self.root, exact_comment_shape=False)

        io_uring_path = self.root / "io_uring/io_uring.c"
        drifted = io_uring_path.read_text().replace(
            "\t\t/* 6.1.25 keeps NOWAIT final here, but not the newer comment block. */\n\t\tif (req->flags & REQ_F_NOWAIT)\n\t\t\tbreak;\n",
            "\t\tif (req->flags & REQ_F_NOWAIT)\n\t\t\tbreak;\n",
            1,
        )
        io_uring_path.write_text(drifted)

        result = FEATURE_PORTING.patch_io_uring_nowait_core(self.root, self.root)
        self.assertEqual(result["mode"], "patched")

        core_text = io_uring_path.read_text()
        self.assert_count(
            core_text,
            "/* ABK feature_porting: only keep NOWAIT final when the request explicitly requested it. */",
        )

        rerun = FEATURE_PORTING.patch_io_uring_nowait_core(self.root, self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_fd_alloc_hotpath_accepts_61_57_helperless_shape(self) -> None:
        make_fd_alloc_fixture(self.root, with_fdt_words=False)

        result = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(result["mode"], "patched")

        text = (self.root / "fs/file.c").read_text()
        self.assertIn("abk_fdtable_slots_wanted", text)
        self.assertIn("abk_expand_files_needed", text)
        self.assert_count(text, "/* ABK feature_porting: fd allocation hotpath helper graft. */")

        rerun = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_fd_alloc_hotpath_keeps_macro_anchor_shape(self) -> None:
        make_fd_alloc_fixture(self.root, with_fdt_words=True)

        result = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(result["mode"], "patched")

        text = (self.root / "fs/file.c").read_text()
        self.assertIn("#define fdt_words(fdt) ((fdt)->max_fds / BITS_PER_LONG) // words in ->open_fds", text)
        self.assertIn("abk_fdtable_slots_wanted", text)
        self.assert_count(text, "/* ABK feature_porting: fd allocation hotpath helper graft. */")

    def test_fd_alloc_hotpath_accepts_drifted_alloc_fdtable_signature(self) -> None:
        make_fd_alloc_fixture(
            self.root,
            with_fdt_words=False,
            alloc_signature="""static struct fdtable *
alloc_fdtable(unsigned int nr)""",
        )

        result = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(result["mode"], "patched")

        text = (self.root / "fs/file.c").read_text()
        self.assertIn("unsigned int slots_wanted;", text)
        self.assertIn("slots_wanted = abk_fdtable_slots_wanted(nr);", text)
        self.assertIn("if (unlikely(nr > INT_MAX / sizeof(struct file *)))", text)
        self.assert_count(text, "/* ABK feature_porting: fd allocation hotpath helper graft. */")

        rerun = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_fd_alloc_hotpath_accepts_slots_wanted_signature(self) -> None:
        make_fd_alloc_fixture(
            self.root,
            with_fdt_words=False,
            alloc_signature="static struct fdtable *alloc_fdtable(unsigned int slots_wanted)",
            alloc_locals="""\tstruct fdtable *fdt;\n\tunsigned int nr;\n\tvoid *data;\n\n""",
            alloc_capacity_block="""\tnr = ALIGN(slots_wanted, BITS_PER_LONG);\n""",
        )

        result = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(result["mode"], "patched")

        text = (self.root / "fs/file.c").read_text()
        self.assertIn("static struct fdtable *alloc_fdtable(unsigned int slots_wanted)", text)
        self.assertIn("slots_wanted = abk_fdtable_slots_wanted(slots_wanted);", text)
        self.assertIn("if (unlikely(nr > INT_MAX / sizeof(struct file *)))", text)
        self.assert_count(text, "/* ABK feature_porting: fd allocation hotpath helper graft. */")

        rerun = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_fd_alloc_hotpath_accepts_space_indented_slots_wanted_capacity(self) -> None:
        make_fd_alloc_fixture(
            self.root,
            with_fdt_words=False,
            alloc_signature="static struct fdtable *alloc_fdtable(unsigned int slots_wanted)",
            alloc_locals="""\tstruct fdtable *fdt;\n\tunsigned int nr;\n\tvoid *data;\n\n""",
            alloc_capacity_block="""        nr = ALIGN(slots_wanted, BITS_PER_LONG);\n""",
        )

        result = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(result["mode"], "patched")

        text = (self.root / "fs/file.c").read_text()
        self.assertIn("        slots_wanted = abk_fdtable_slots_wanted(slots_wanted);", text)
        self.assertIn("        nr = ALIGN(slots_wanted, BITS_PER_LONG);", text)
        self.assertIn("if (unlikely(nr > INT_MAX / sizeof(struct file *)))", text)
        self.assert_count(text, "/* ABK feature_porting: fd allocation hotpath helper graft. */")

        rerun = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_fd_alloc_hotpath_accepts_crossline_slots_wanted_signature(self) -> None:
        make_fd_alloc_fixture(
            self.root,
            with_fdt_words=False,
            alloc_signature="""static struct fdtable *
alloc_fdtable(unsigned int slots_wanted)""",
            alloc_locals="""\tstruct fdtable *fdt;\n\tunsigned int nr;\n\tvoid *data;\n\n""",
            alloc_capacity_block="""        nr = ALIGN(slots_wanted, BITS_PER_LONG);\n""",
        )

        result = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(result["mode"], "patched")

        text = (self.root / "fs/file.c").read_text()
        self.assertIn("alloc_fdtable(unsigned int slots_wanted)", text)
        self.assertIn("        slots_wanted = abk_fdtable_slots_wanted(slots_wanted);", text)
        self.assertIn("if (unlikely(nr > INT_MAX / sizeof(struct file *)))", text)
        self.assert_count(text, "/* ABK feature_porting: fd allocation hotpath helper graft. */")

        rerun = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_fd_alloc_hotpath_accepts_refactored_upstream_shape(self) -> None:
        make_refactored_fd_alloc_fixture(self.root)

        result = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(result["mode"], "patched")
        self.assertIn("upstream_shape", result)

        text = (self.root / "fs/file.c").read_text()
        # The refactored capacity stays upstream: no rewrite, no spurious
        # slots_wanted local, and no dead slot-count helper.
        self.assertIn("nr = roundup_pow_of_two(slots_wanted);", text)
        self.assertIn("return ERR_PTR(-EMFILE);", text)
        self.assertNotIn("\tunsigned int slots_wanted;\n", text)
        self.assertNotIn("abk_fdtable_slots_wanted", text)
        # The expand_files()/alloc_fd() prechecks do land.
        self.assertIn("abk_expand_files_needed", text)
        self.assertIn("if (!abk_expand_files_needed(fdt, nr))", text)
        self.assertIn("if (abk_expand_files_needed(fdt, fd)) {", text)
        self.assert_count(text, "/* ABK feature_porting: fd allocation hotpath helper graft. */")

        rerun = FEATURE_PORTING.patch_fd_alloc_hotpath(self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_slab_alloc_free_hotpath_keeps_c89_declarations(self) -> None:
        make_slub_fixture(self.root)

        result = FEATURE_PORTING.patch_slab_alloc_free_hotpath(self.root)
        self.assertEqual(result["mode"], "patched")

        text = (self.root / "mm/slub.c").read_text()
        bulk_start = text.index("int kmem_cache_alloc_bulk(")
        bulk_end = text.index("void kmem_cache_free(", bulk_start)
        bulk_text = text[bulk_start:bulk_end]
        decl_idx = text.index("\tvoid *next_object;\n", bulk_start)
        loop_idx = text.index("\tfor (i = 0; i < size; i++) {\n", bulk_start)
        self.assertIn("abk_slab_next_object", text)
        self.assertIn("\t\tnext_object = abk_slab_next_object(s, object);\n", bulk_text)
        self.assertNotIn("\t\tvoid *next_object = abk_slab_next_object(s, object);\n", bulk_text)
        self.assertLess(decl_idx, loop_idx)
        self.assert_count(text, "/* ABK feature_porting: slab alloc/free hotpath helper graft. */")

        rerun = FEATURE_PORTING.patch_slab_alloc_free_hotpath(self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_close_range_hotpath_accepts_61_141_pick_file_shape(self) -> None:
        make_close_range_fixture(self.root, raw_dereference=True)

        result = FEATURE_PORTING.patch_close_range_hotpath(self.root)
        self.assertEqual(result["mode"], "patched")

        text = (self.root / "fs/file.c").read_text()
        self.assertIn("if (!fd_is_open(fd, fdt))", text)
        self.assertIn("abk_close_range_limit", text)
        self.assertIn("abk_pick_file_for_close", text)
        self.assert_count(text, "/* ABK feature_porting: close_range() bitmap hotpath graft. */")

        rerun = FEATURE_PORTING.patch_close_range_hotpath(self.root)
        self.assertEqual(rerun["mode"], "already_patched")

    def test_sched_pick_logic_accepts_drifted_reweight_shape(self) -> None:
        make_fair_fixture(self.root, drifted_reweight=True)

        result = FEATURE_PORTING.patch_sched_pick_logic(self.root)
        self.assertEqual(result["mode"], "patched")

        phase3 = FEATURE_PORTING.patch_sched_runtime_state_phase3(self.root)
        self.assertEqual(phase3["mode"], "patched")

        fair_text = (self.root / "kernel/sched/fair.c").read_text()
        self.assertIn("bool queued = se->on_rq;", fair_text)
        self.assertIn("abk_eevdf_scale_rel_deadline", fair_text)
        self.assertIn("place_entity(cfs_rq, se, 0);", fair_text)
        self.assert_count(fair_text, "/* ABK feature_porting: scan-based EEVDF runtime-state graft. */")
        self.assert_count(
            fair_text,
            "/* ABK feature_porting: phase-3 preserve lag/deadline across both current and queued reweight paths. */",
        )

        rerun = FEATURE_PORTING.patch_sched_pick_logic(self.root)
        self.assertEqual(rerun["mode"], "already_patched")
        rerun_phase3 = FEATURE_PORTING.patch_sched_runtime_state_phase3(self.root)
        self.assertEqual(rerun_phase3["mode"], "already_patched")


if __name__ == "__main__":
    unittest.main()
