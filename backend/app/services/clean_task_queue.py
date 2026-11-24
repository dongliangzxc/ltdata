"""Durable cleaning queue. One database advisory lock bounds heavy execution."""
import hashlib
import logging
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.database import engine, get_db
from app.models.schemas import CleanJobRecord, CleanTaskRun, MatchResult

logger = logging.getLogger(__name__)
BUSY_CLEAN_STATUSES = {"queued", "created", "cleaning", "matching", "processing"}


def lock_idle_clean_jobs(db: Session, job_ids, *, allow_failed: bool = False, require_all: bool = True):
    job_ids = sorted(set(job_ids))
    query = db.query(CleanJobRecord).filter(CleanJobRecord.id.in_(job_ids)).populate_existing()

    def check(jobs):
        if require_all and len(jobs) != len(job_ids):
            raise HTTPException(404, "清洗任务不存在")
        if any(job.status in BUSY_CLEAN_STATUSES for job in jobs) or db.query(CleanTaskRun.id).filter(
            CleanTaskRun.clean_job_id.in_(job_ids), CleanTaskRun.state.in_(["queued", "running"]),
        ).first():
            raise HTTPException(409, "任务正在排队或处理中，请完成后再操作")
        if not allow_failed and any(job.status in {"failed", "error"} for job in jobs):
            raise HTTPException(409, "任务尚未处理完成，请先重试")

    # Reject busy jobs without waiting on the FK parent locks held by output
    # inserts. All callers enter before mutation; end the read transaction so a
    # locking read followed by downstream checks sees manual edits that finished
    # while waiting, even under MySQL REPEATABLE READ.
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("必须在修改数据前获取清洗任务锁")
    check(query.all())
    db.commit()
    jobs = query.order_by(CleanJobRecord.id).with_for_update().all()
    check(jobs)
    return jobs


def ensure_clean_job_idle(db: Session, job_id: int, *, allow_failed: bool = False) -> CleanJobRecord:
    return lock_idle_clean_jobs(db, [job_id], allow_failed=allow_failed)[0]


def enqueue_clean_job(db: Session, job: CleanJobRecord, *, mode="full",
                      snapshot_start_id=None, snapshot_end_id=None, input_count=None) -> CleanTaskRun:
    """Caller commits snapshot and queue atomically. No in-memory task handles."""
    run = db.query(CleanTaskRun).filter_by(clean_job_id=job.id).with_for_update().first()
    if run is not None and run.state in {"queued", "running"}:
        raise HTTPException(409, "任务已在队列中，请勿重复提交")
    if run is None:
        run = CleanTaskRun(clean_job_id=job.id)
        db.add(run)
    if mode not in {"full", "incremental", "completion"}:
        raise ValueError("未知清洗执行方式")
    if mode == "incremental" and (
        not snapshot_start_id or not snapshot_end_id or snapshot_start_id > snapshot_end_id or not input_count
    ):
        raise ValueError("追加数据范围为空或不完整，不能执行")
    if mode == "completion" and (
        not input_count or input_count <= 0
        or ((snapshot_start_id is None) != (snapshot_end_id is None))
        or (snapshot_start_id is not None and (snapshot_start_id <= 0 or snapshot_start_id > snapshot_end_id))
    ):
        raise ValueError("补齐数据范围为空或不完整，不能执行")
    run.mode = mode
    run.snapshot_start_id = snapshot_start_id if mode in {"incremental", "completion"} else None
    run.snapshot_end_id = snapshot_end_id if mode in {"incremental", "completion"} else None
    run.input_count = input_count if mode in {"incremental", "completion"} else (job.row_in or 0)
    run.state, run.stage = "queued", "排队中"
    run.processed, run.total = 0, run.input_count
    run.queued_at = datetime.utcnow()
    run.started_at = run.finished_at = run.worker_token = None
    job.status, job.progress, job.progress_stage, job.error_msg = "queued", 0, "排队中", None
    db.flush()
    return run


@contextmanager
def clean_execution_lock(bind=engine):
    """Held on a dedicated connection throughout execution, across all workers.

    SQLite uses a file lock for local development; production MySQL GET_LOCK is
    shared by the separate API and worker containers and released on disconnect.
    """
    with bind.connect() as connection:
        if bind.dialect.name == "mysql":
            key = "ltdata:clean:" + hashlib.sha256((bind.url.database or "").encode()).hexdigest()[:24]
            acquired = connection.execute(text("SELECT GET_LOCK(:key, 0)"), {"key": key}).scalar() == 1
            connection.commit()
            try:
                yield connection if acquired else None
            finally:
                connection.rollback()
                if acquired and not connection.invalidated:
                    connection.execute(text("SELECT RELEASE_LOCK(:key)"), {"key": key})
                    connection.commit()
        else:
            import fcntl
            database = str(Path(bind.url.database).resolve()) if bind.url.database not in (None, ":memory:") else str(id(bind))
            key = hashlib.sha256(database.encode()).hexdigest()[:24]
            with (Path(tempfile.gettempdir()) / f"ltdata-clean-{key}.lock").open("a") as lock:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError:
                    acquired = False
                try:
                    yield connection if acquired else None
                finally:
                    if acquired:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def clean_heavy_slot(db: Session = Depends(get_db)):
    """Keep older synchronous entry points from running alongside the worker."""
    if not settings.CLEAN_BACKGROUND_ENABLED:
        yield
        return
    with clean_execution_lock(db.get_bind()) as connection:
        if connection is None:
            raise HTTPException(409, "后台正在处理清洗任务，请稍后重试")
        yield


async def guard_queued_match_mutation(request: Request, db: Session = Depends(get_db)):
    """Deep links and old pages must not edit a job being rebuilt by the worker."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    job_ids, match_ids = set(), set()

    def add(target, value):
        try:
            target.add(int(value))
        except (TypeError, ValueError):
            pass

    for key in ("clean_job_id", "target_clean_job_id"):
        add(job_ids, request.path_params.get(key))
        add(job_ids, request.query_params.get(key))
    add(match_ids, request.path_params.get("match_id"))
    if "application/json" in request.headers.get("content-type", ""):
        payload = await request.json()
        if isinstance(payload, dict):
            for key in ("clean_job_id", "target_clean_job_id"):
                add(job_ids, payload.get(key))
            for key in ("ids", "match_ids", "match_result_ids"):
                if isinstance(payload.get(key), list):
                    for value in payload[key]:
                        add(match_ids, value)
    if match_ids:
        job_ids.update(value for value, in db.query(MatchResult.clean_job_id).filter(MatchResult.id.in_(match_ids)))
    query = db.query(CleanTaskRun.id).filter(CleanTaskRun.state.in_(["queued", "running"]))
    # Unscoped bulk actions can affect multiple jobs, so wait until the queue is
    # idle rather than modifying a partial rebuild through a global filter.
    if job_ids and "same-title" not in request.url.path:
        query = query.filter(CleanTaskRun.clean_job_id.in_(job_ids))
    if query.first():
        raise HTTPException(409, "涉及的任务正在排队或处理中，请完成后再操作")
    if not job_ids or "same-title" in request.url.path:
        job_ids = {value for value, in db.query(CleanJobRecord.id)}
    if job_ids:
        lock_idle_clean_jobs(db, job_ids, require_all=False)


def recover_interrupted_runs(db: Session) -> int:
    """Only call while holding the execution lock. Queued runs remain queued."""
    runs = db.query(CleanTaskRun).filter_by(state="running").all()
    for run in runs:
        run.state, run.stage, run.finished_at = "failed", "已中断", datetime.utcnow()
        job = db.get(CleanJobRecord, run.clean_job_id)
        if job:
            job.status, job.progress_stage = "failed", "已中断"
            job.error_msg = "后台执行进程中断，请点击重试；任务数据范围已保留"
    db.commit()
    return len(runs)


class LostCleanOwnership(RuntimeError):
    pass


class CleanProgressWriter:
    def __init__(self, db: Session, run_id: int, token: str, session_factory=None):
        bind = db.get_bind()
        target_engine = getattr(bind, "engine", bind)
        self.db, self.run_id, self.token = db, run_id, token
        self.session_factory = session_factory or (lambda: Session(target_engine))
        self.last_stage, self.last_write = None, 0.0

    def __call__(self, stage: str, processed: int, total: int):
        now = time.monotonic()
        if stage == self.last_stage and processed < total and now - self.last_write < 1.0:
            return
        values = dict(stage=stage, processed=processed, total=total)

        def write(db):
            changed = db.query(CleanTaskRun).filter_by(
                id=self.run_id, worker_token=self.token, state="running",
            ).update(values, synchronize_session=False)
            if changed != 1:
                raise LostCleanOwnership("任务已中断或执行权已失效")

        if self.db.get_bind().dialect.name == "mysql":
            # A separate run row avoids FK locks held on clean_jobs by output
            # inserts. Never commit cleaning output merely to publish progress.
            with self.session_factory() as progress_db:
                write(progress_db)
                progress_db.commit()
        else:
            # SQLite has a database-wide writer lock. Persist with the worker's
            # existing transaction at its natural commit boundaries.
            write(self.db)
            self.db.flush()
        self.last_stage, self.last_write = stage, now


def execute_next_run(db: Session, *, executor=None, progress_factory=CleanProgressWriter) -> bool:
    """Claim one FIFO task; caller holds clean_execution_lock for the whole call."""
    run = db.query(CleanTaskRun).filter_by(state="queued").order_by(
        CleanTaskRun.queued_at, CleanTaskRun.id,
    ).with_for_update().first()
    if run is None:
        db.rollback()
        return False
    job = db.get(CleanJobRecord, run.clean_job_id)
    job_was_queued = job is not None and job.status == "queued"
    token = str(uuid.uuid4())
    run.state, run.stage, run.worker_token, run.started_at = "running", "准备清洗", token, datetime.utcnow()
    run_id, job_id = run.id, run.clean_job_id
    if job_was_queued and run.mode in {"incremental", "completion"}:
        # Publish the start before the append's single output transaction.
        job.status, job.progress_stage = "cleaning", "准备清洗"
    db.commit()
    progress = progress_factory(db, run_id, token)
    try:
        if not job_was_queued:
            raise RuntimeError("任务状态异常，未开始执行")
        if executor is None:
            from app.api.clean import _run_clean_and_match_for_job, _run_incremental_clean_and_match_for_job, _run_completion_for_job
            executor = {"incremental": _run_incremental_clean_and_match_for_job,
                        "completion": _run_completion_for_job}.get(run.mode, _run_clean_and_match_for_job)
        if run.mode in {"incremental", "completion"}:
            executor(db, job, stage_progress_cb=progress,
                     snapshot_id_range=(run.snapshot_start_id, run.snapshot_end_id), expected_count=run.input_count)
        elif run.mode == "full":
            executor(db, job, stage_progress_cb=progress)
        else:
            raise RuntimeError("未知清洗执行方式，请检查任务")
        run = db.query(CleanTaskRun).filter_by(id=run_id, worker_token=token, state="running").populate_existing().first()
        if run is None:
            raise LostCleanOwnership("任务执行权已失效")
        run.state, run.stage, run.finished_at = "done", "处理完成", datetime.utcnow()
        job.status, job.progress, job.progress_stage = "reviewing", 100, "处理完成"
        job.error_msg = None
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("clean task failed job=%s", job_id)
        run = db.query(CleanTaskRun).filter_by(id=run_id, worker_token=token, state="running").populate_existing().first()
        if run is not None:
            run.state, run.stage, run.finished_at = "failed", "失败", datetime.utcnow()
            job = db.get(CleanJobRecord, job_id)
            if job:
                error = "数据库处理失败，请重试；详细原因已记录" if isinstance(exc, SQLAlchemyError) else str(exc)[:500]
                job.status, job.progress_stage, job.error_msg = "failed", "失败", error
            db.commit()
    return True


def run_worker(stop: threading.Event, bind=engine):
    while not stop.is_set():
        worked = False
        try:
            with clean_execution_lock(bind) as connection:
                if connection is not None:
                    with Session(bind=connection, expire_on_commit=False) as db:
                        recover_interrupted_runs(db)
                        if not stop.is_set():
                            worked = execute_next_run(db)
        except Exception:
            logger.exception("clean worker iteration failed")
        if not worked:
            stop.wait(2.0)
