"""
型号匹配引擎

匹配策略（优先级递减）：
  P1: brand_code 在 item_name 中 + model_code 在 item_name 中
  P2: brand_name 在 item_name 中 + model_code 在 item_name 中
  P3: 仅 model_code 在 item_name 中（model_code 长度 >= 5 才启用，避免误匹配）

同优先级有多个候选时，取 model_code 最长的（减少短码误匹配）。
支持重复执行：先删除该 clean_job 的旧匹配结果，再重新写入。
"""
from sqlalchemy.orm import Session
from app.models.schemas import CleanedDataRecord, ModelRecord, MatchResult


def run_match(db: Session, clean_job_id: int) -> dict:
    """
    对一次清洗任务的所有结果执行型号匹配，写入 match_results。
    返回: {"total": N, "matched": M, "pending": P}
    """
    # 删除旧匹配结果（支持重复执行）
    db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).delete(
        synchronize_session=False
    )

    # 加载全部型号，构建内存索引
    all_models = db.query(ModelRecord).all()

    # 按 brand_code 分组：brand_code_upper → [model list]
    brand_index: dict[str, list[ModelRecord]] = {}
    for m in all_models:
        key = (m.brand_code or "").upper().strip()
        if key:
            brand_index.setdefault(key, []).append(m)

    # 同时建 brand_name 索引
    brand_name_index: dict[str, list[ModelRecord]] = {}
    for m in all_models:
        key = (m.brand_name or "").upper().strip()
        if key:
            brand_name_index.setdefault(key, []).append(m)

    # P3 候选：model_code 足够长的所有型号
    long_code_models = [m for m in all_models if len((m.model_code or "").strip()) >= 5]

    # 加载该 clean_job 的全部 cleaned_data
    cleaned_rows = (
        db.query(CleanedDataRecord)
        .filter(CleanedDataRecord.clean_job_id == clean_job_id)
        .all()
    )

    results: list[MatchResult] = []
    matched_count = 0

    for row in cleaned_rows:
        item_upper = (row.item_name or "").upper()
        best_model: ModelRecord | None = None
        best_priority = 99

        def _try_match_brand_group(models_in_brand: list[ModelRecord], priority: int):
            nonlocal best_model, best_priority
            for m in models_in_brand:
                mc = (m.model_code or "").strip()
                mn = (m.model_name or "").strip()
                # model_code 或 model_name 在 item_name 中
                hit = (mc and mc.upper() in item_upper) or (mn and len(mn) >= 3 and mn.upper() in item_upper)
                if hit:
                    if priority < best_priority or (
                        priority == best_priority
                        and len(mc) > len((best_model.model_code or "") if best_model else "")
                    ):
                        best_model = m
                        best_priority = priority

        # P1: brand_code 匹配
        for bc, group in brand_index.items():
            if bc in item_upper:
                _try_match_brand_group(group, 1)

        # P2: brand_name 匹配（brand_name 至少 2 个字符才参与）
        if best_priority > 1:
            for bn, group in brand_name_index.items():
                if len(bn) >= 2 and bn in item_upper:
                    _try_match_brand_group(group, 2)

        # P3: 仅 model_code 匹配（无品牌线索时兜底）
        if best_model is None:
            for m in long_code_models:
                mc = (m.model_code or "").strip().upper()
                if mc and mc in item_upper:
                    cur_len = len(mc)
                    best_len = len((best_model.model_code or "").strip()) if best_model else 0
                    if cur_len > best_len:
                        best_model = m
                        best_priority = 3

        if best_model:
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=best_model.id,
                match_status="matched",
                matched_by="auto",
            ))
            matched_count += 1
        else:
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=None,
                match_status="pending",
                matched_by="auto",
            ))

    db.bulk_save_objects(results)
    db.commit()

    total = len(cleaned_rows)
    pending = total - matched_count
    return {"total": total, "matched": matched_count, "pending": pending}
