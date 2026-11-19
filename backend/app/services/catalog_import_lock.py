"""Serialize imports sharing brand/model master data across API processes."""
from contextlib import contextmanager
import hashlib
import logging
from pathlib import Path
import tempfile

from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.database import get_db


logger = logging.getLogger(__name__)
IMPORT_BUSY_MESSAGE = "正在导入型号或映射数据，请等待当前导入完成后重试"


def catalog_lock_key(bind):
    database = bind.url.database or ""
    if bind.dialect.name != "mysql":
        database = str(Path(database).resolve()) if database not in ("", ":memory:") else str(id(bind))
    return "ltdata:catalog-import:" + hashlib.sha256(database.encode()).hexdigest()[:24]


@contextmanager
def catalog_execution_lock(bind):
    """Use a dedicated connection: endpoint commits must not release/reuse it.

    Brands are shared across categories, so all model/URL import entry points
    share one lock. Normal list/read requests do not take this lock.
    """
    key = catalog_lock_key(bind)
    if bind.dialect.name == "mysql":
        with bind.connect() as connection:
            acquired = False
            try:
                result = connection.execute(text("SELECT GET_LOCK(:key, 0)"), {"key": key}).scalar()
                acquired = result == 1
                connection.commit()
                if result is None:
                    raise HTTPException(503, "暂时无法启动导入，请稍后重试")
                yield acquired
            finally:
                if acquired:
                    try:
                        connection.rollback()
                        if not connection.invalidated:
                            released = connection.execute(text("SELECT RELEASE_LOCK(:key)"), {"key": key}).scalar()
                            connection.commit()
                            if released != 1:
                                connection.invalidate()
                    except Exception:
                        # A pooled physical connection must never keep a lock.
                        connection.invalidate()
                        logger.exception("Could not release catalog import lock; connection discarded")
    else:
        import fcntl
        with (Path(tempfile.gettempdir()) / (key.replace(":", "-") + ".lock")).open("a") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                acquired = False
            try:
                yield acquired
            finally:
                if acquired:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def catalog_import_slot(db: Session = Depends(get_db)):
    """Reject overlapping imports promptly and roll back every failure path."""
    bind = db.get_bind()
    with catalog_execution_lock(bind) as acquired:
        if not acquired:
            raise HTTPException(409, IMPORT_BUSY_MESSAGE)
        # Authentication may already have opened a REPEATABLE READ snapshot.
        # Start fresh after taking the lock, before any import writes occur.
        if bind.dialect.name == "mysql":
            db.rollback()
        try:
            yield
        except OperationalError as exc:
            code = exc.orig.args[0] if getattr(exc.orig, "args", ()) else None
            if code in (1205, 1213):
                raise HTTPException(409, "其他操作正在修改型号或映射数据，本次导入已回滚，请稍后重试") from exc
            raise
        finally:
            # Includes failures during automatic brand/model creation, before
            # the URL writer is reached. Release row locks before the mutex.
            db.rollback()
