"""修正规则 CRUD API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.schemas import CorrectionRule, CorrectionRuleIn, CorrectionRuleOut
from app.services.correction_engine import apply_correction_rules

router = APIRouter(prefix="/api/correction-rules", tags=["correction-rules"])


@router.get("", response_model=list[CorrectionRuleOut])
def list_rules(db: Session = Depends(get_db)):
    return db.query(CorrectionRule).order_by(CorrectionRule.priority, CorrectionRule.id).all()


@router.post("", response_model=CorrectionRuleOut, status_code=201)
def create_rule(payload: CorrectionRuleIn, db: Session = Depends(get_db)):
    rule = CorrectionRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/{rule_id}", response_model=CorrectionRuleOut)
def update_rule(rule_id: int, payload: CorrectionRuleIn, db: Session = Depends(get_db)):
    rule = db.query(CorrectionRule).filter(CorrectionRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    for k, v in payload.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(CorrectionRule).filter(CorrectionRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    db.delete(rule)
    db.commit()


@router.post("/apply/{clean_job_id}")
def apply_rules(clean_job_id: int, db: Session = Depends(get_db)):
    """手动对某清洗任务重跑修正规则"""
    result = apply_correction_rules(db, clean_job_id)
    return {"clean_job_id": clean_job_id, **result}
