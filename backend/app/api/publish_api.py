from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.analytics_db import get_analytics_db
from app.models.schemas import PublishJob, PublishJobOut
from app.services.publisher import run_publish

router = APIRouter(prefix="/api/publish", tags=["publish"])


@router.post("/run")
def publish_run(
    payload: dict,
    db: Session = Depends(get_db),
    analytics_db: Session = Depends(get_analytics_db),
):
    """
    发布指定 clean_job_id 的匹配结果到分析库。
    支持重复发布（覆盖上次）。
    """
    clean_job_id: int = payload["clean_job_id"]

    result = run_publish(db, analytics_db, clean_job_id)
    published_count = result["published_count"]

    # 记录 publish_job
    job = PublishJob(
        clean_job_id=clean_job_id,
        status="done",
        published_count=published_count,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # 回填 publish_job_id 到 analytics 已发布记录
    from sqlalchemy import text
    analytics_db.execute(
        text("UPDATE published_items SET publish_job_id = :jid WHERE clean_job_id = :cjid AND publish_job_id = 0"),
        {"jid": job.id, "cjid": clean_job_id}
    )
    analytics_db.commit()

    return {
        "code": 0,
        "data": {
            "publish_job_id": job.id,
            "published_count": published_count,
        }
    }


@router.get("/jobs")
def list_publish_jobs(
    clean_job_id: int | None = None,
    db: Session = Depends(get_db),
):
    """列出发布历史，可按 clean_job_id 过滤。"""
    q = db.query(PublishJob).order_by(PublishJob.id.desc())
    if clean_job_id is not None:
        q = q.filter(PublishJob.clean_job_id == clean_job_id)
    jobs = q.limit(50).all()
    return {
        "code": 0,
        "data": [PublishJobOut.model_validate(j) for j in jobs]
    }
