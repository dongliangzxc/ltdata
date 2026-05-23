"""
数据分发 API
POST /run           — 对指定 file_id 执行分发
GET  /batches       — 列出所有分发批次
GET  /batches/{id}/stats — 某批次各品类行数明细
GET  /rules         — 规则列表（支持 platform / category_code 过滤）
POST /rules         — 新增规则
PUT  /rules/{id}    — 修改规则
DELETE /rules/{id}  — 删除规则
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.schemas import (
    Category, DispatchRule, DispatchBatch, DispatchItem,
    DispatchRuleIn, DispatchRuleOut, DispatchBatchOut,
    RawDataRecord, UploadFileRecord,
)

router = APIRouter(prefix="/api/dispatch", tags=["dispatch"])

DISPATCH_PAGE_SIZE = 2000


def _field_value(row: RawDataRecord, field: str) -> str:
    """从 raw_data 行取指定字段值，返回空字符串如果字段不存在"""
    field_map = {
        "category_lv0": row.category_lv0,
        "category_lv1": row.category_lv1,
        "category_lv2": row.category_lv2,
        "category_lv3": row.category_lv3,
        "category_lv4": row.category_lv4,
        "category_lv5": row.category_lv5,
        "item_name": row.item_name,
    }
    return (field_map.get(field) or "")


def _rule_matches(row: RawDataRecord, rule: DispatchRule) -> bool:
    """判断一条规则是否命中该行"""
    val = _field_value(row, rule.field)
    if rule.match_type == "contains":
        main_match = rule.value in val
    elif rule.match_type == "equals":
        main_match = val == rule.value
    else:
        main_match = False

    if not main_match:
        return False

    if rule.item_name_keyword:
        return rule.item_name_keyword in (row.item_name or "")

    return True


@router.post("/run", response_model=DispatchBatchOut)
def run_dispatch(payload: dict, db: Session = Depends(get_db)):
    """对指定 file_id 执行分发，返回新建的 batch"""
    file_id: int = payload.get("file_id")
    if not file_id:
        raise HTTPException(status_code=400, detail="file_id 不能为空")

    file_record = db.query(UploadFileRecord).filter(UploadFileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    platform = (file_record.platform or "").lower()

    # 1. 创建 batch
    batch = DispatchBatch(file_id=file_id, status="running")
    db.add(batch)
    db.commit()
    db.refresh(batch)
    batch_id = batch.id

    try:
        total_rows = (
            db.query(func.count(RawDataRecord.id))
            .filter(RawDataRecord.file_id == file_id)
            .scalar()
            or 0
        )

        # 2. 取匹配平台（或 platform IS NULL）的 active 规则，按 priority ASC
        rules = (
            db.query(DispatchRule)
            .filter(
                DispatchRule.is_active == 1,
                (DispatchRule.platform == None) | (DispatchRule.platform == platform),
            )
            .order_by(DispatchRule.priority, DispatchRule.id)
            .all()
        )

        # 3. 分页读取 raw_data 少量字段并批量插入，避免大文件分发时占满内存
        dispatched_rows = 0
        unmatched_rows = 0
        last_id = 0

        while True:
            rows = (
                db.query(
                    RawDataRecord.id,
                    RawDataRecord.category_lv0,
                    RawDataRecord.category_lv1,
                    RawDataRecord.category_lv2,
                    RawDataRecord.category_lv3,
                    RawDataRecord.category_lv4,
                    RawDataRecord.category_lv5,
                    RawDataRecord.item_name,
                )
                .filter(RawDataRecord.file_id == file_id, RawDataRecord.id > last_id)
                .order_by(RawDataRecord.id)
                .limit(DISPATCH_PAGE_SIZE)
                .all()
            )
            if not rows:
                break

            insert_rows = []
            for row in rows:
                matched = False
                for rule in rules:
                    if _rule_matches(row, rule):
                        insert_rows.append({
                            "batch_id": batch_id,
                            "raw_data_id": row.id,
                            "category_code": rule.category_code,
                            "matched_rule_id": rule.id,
                        })
                        dispatched_rows += 1
                        matched = True
                        break
                if not matched:
                    unmatched_rows += 1

            if insert_rows:
                db.execute(DispatchItem.__table__.insert(), insert_rows)
                db.flush()
            last_id = rows[-1].id

        # 4. 更新 batch
        batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).one()
        batch.status = "done"
        batch.total_rows = total_rows
        batch.dispatched_rows = dispatched_rows
        batch.unmatched_rows = unmatched_rows
        batch.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(batch)
        return batch
    except Exception:
        db.rollback()
        batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).one()
        batch.status = "error"
        batch.finished_at = datetime.utcnow()
        db.commit()
        raise


@router.get("/batches", response_model=list[DispatchBatchOut])
def list_batches(
    file_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """列出所有分发批次，可按 file_id 过滤"""
    q = db.query(DispatchBatch)
    if file_id:
        q = q.filter(DispatchBatch.file_id == file_id)
    return q.order_by(DispatchBatch.created_at.desc()).all()


@router.get("/batches/{batch_id}/stats")
def get_batch_stats(batch_id: int, db: Session = Depends(get_db)):
    """某批次各品类行数与规则命中明细"""
    batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    category_rows = (
        db.query(
            DispatchItem.category_code,
            Category.name.label("category_name"),
            func.count(DispatchItem.id).label("count"),
        )
        .outerjoin(Category, DispatchItem.category_code == Category.code)
        .filter(DispatchItem.batch_id == batch_id)
        .group_by(DispatchItem.category_code, Category.name)
        .order_by(func.count(DispatchItem.id).desc(), DispatchItem.category_code)
        .all()
    )

    rule_category_code = func.coalesce(DispatchRule.category_code, DispatchItem.category_code).label("category_code")
    rule_rows = (
        db.query(
            DispatchItem.matched_rule_id.label("rule_id"),
            rule_category_code,
            Category.name.label("category_name"),
            DispatchRule.field,
            DispatchRule.match_type,
            DispatchRule.value,
            DispatchRule.item_name_keyword,
            DispatchRule.platform,
            DispatchRule.priority,
            DispatchRule.is_active,
            func.count(DispatchItem.id).label("count"),
        )
        .outerjoin(DispatchRule, DispatchItem.matched_rule_id == DispatchRule.id)
        .outerjoin(Category, rule_category_code == Category.code)
        .filter(DispatchItem.batch_id == batch_id, DispatchItem.matched_rule_id.isnot(None))
        .group_by(
            DispatchItem.matched_rule_id,
            rule_category_code,
            Category.name,
            DispatchRule.field,
            DispatchRule.match_type,
            DispatchRule.value,
            DispatchRule.item_name_keyword,
            DispatchRule.platform,
            DispatchRule.priority,
            DispatchRule.is_active,
        )
        .order_by(func.count(DispatchItem.id).desc(), DispatchRule.priority, DispatchItem.matched_rule_id)
        .all()
    )

    return {
        "batch_id": batch_id,
        "total_rows": batch.total_rows,
        "dispatched_rows": batch.dispatched_rows,
        "unmatched_rows": batch.unmatched_rows,
        "categories": [
            {
                "category_code": row.category_code,
                "category_name": row.category_name,
                "count": row.count,
            }
            for row in category_rows
        ],
        "rules": [
            {
                "rule_id": row.rule_id,
                "category_code": row.category_code,
                "category_name": row.category_name,
                "field": row.field,
                "match_type": row.match_type,
                "value": row.value,
                "item_name_keyword": row.item_name_keyword,
                "platform": row.platform,
                "priority": row.priority,
                "is_active": row.is_active,
                "count": row.count,
            }
            for row in rule_rows
        ],
    }


@router.get("/rules", response_model=list[DispatchRuleOut])
def list_rules(
    platform: Optional[str] = Query(None),
    category_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(DispatchRule)
    if platform:
        q = q.filter(DispatchRule.platform == platform)
    if category_code:
        q = q.filter(DispatchRule.category_code == category_code)
    return q.order_by(DispatchRule.priority, DispatchRule.id).all()


@router.post("/rules", response_model=DispatchRuleOut)
def create_rule(body: DispatchRuleIn, db: Session = Depends(get_db)):
    rule = DispatchRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/rules/{rule_id}", response_model=DispatchRuleOut)
def update_rule(rule_id: int, body: DispatchRuleIn, db: Session = Depends(get_db)):
    rule = db.query(DispatchRule).filter(DispatchRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(DispatchRule).filter(DispatchRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    db.delete(rule)
    db.commit()
    return {"message": "已删除"}
