"""
型号匹配引擎

匹配步骤（依次降级）：
  S1: brand_raw → 精确/包含匹配 brand_code / brand_name → 在候选组里找 model_code/model_name
  S2: item_name 中包含 brand_code → 在对应品牌组找 model_code/model_name
  S3: item_name 中包含 brand_name（≥2字符）→ 在对应品牌组找 model_code/model_name
  S4: 兜底 — model_code（≥5字符）直接出现在 item_name 中

同优先级多候选时取 model_code 最长的，减少短码误匹配。
支持重复执行：先删旧结果再写入。
"""
from sqlalchemy.orm import Session
from app.models.schemas import CleanedDataRecord, ModelRecord, MatchResult


def _norm(s: str | None) -> str:
    return (s or "").upper().strip()


def run_match(db: Session, clean_job_id: int) -> dict:
    # ── 删除旧结果（支持重跑）────────────────────────────────────
    db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).delete(
        synchronize_session=False
    )

    # ── 构建内存索引 ─────────────────────────────────────────────
    all_models = db.query(ModelRecord).all()

    brand_code_index: dict[str, list[ModelRecord]] = {}
    for m in all_models:
        key = _norm(m.brand_code)
        if key:
            brand_code_index.setdefault(key, []).append(m)

    brand_name_index: dict[str, list[ModelRecord]] = {}
    for m in all_models:
        key = _norm(m.brand_name)
        if len(key) >= 2:
            brand_name_index.setdefault(key, []).append(m)

    # S4 候选：model_code 足够长（≥5）的全量型号
    long_code_models = [m for m in all_models if len(_norm(m.model_code)) >= 5]

    # ── brand_raw → 候选列表缓存 ─────────────────────────────────
    brand_raw_cache: dict[str, list[ModelRecord]] = {}

    def _candidates_by_brand_raw(brand_raw: str) -> list[ModelRecord]:
        if brand_raw in brand_raw_cache:
            return brand_raw_cache[brand_raw]
        bu = _norm(brand_raw)
        result: list[ModelRecord] = []
        seen: set[int] = set()

        def _add(lst: list[ModelRecord]):
            for m in lst:
                if m.id not in seen:
                    result.append(m)
                    seen.add(m.id)

        # 1) brand_raw 精确等于 brand_code
        if bu in brand_code_index:
            _add(brand_code_index[bu])
        # 2) brand_raw 精确等于 brand_name
        if bu in brand_name_index:
            _add(brand_name_index[bu])
        # 3) brand_code 是 brand_raw 的子串（如 brand_raw="锐族RUIZU" 含 "RUIZU"）
        if not result:
            for bc, grp in brand_code_index.items():
                if bc and bc in bu:
                    _add(grp)
        # 4) brand_name 是 brand_raw 的子串
        if not result:
            for bn, grp in brand_name_index.items():
                if len(bn) >= 2 and bn in bu:
                    _add(grp)

        brand_raw_cache[brand_raw] = result
        return result

    def _best(candidates: list[ModelRecord], item_upper: str) -> ModelRecord | None:
        """在候选列表里找命中 item_name 的最优型号（model_code 最长优先）"""
        best: ModelRecord | None = None
        best_len = 0
        for m in candidates:
            mc = _norm(m.model_code)
            mn = _norm(m.model_name)
            if (mc and mc in item_upper) or (mn and len(mn) >= 3 and mn in item_upper):
                cur = len(mc)
                if cur > best_len:
                    best = m
                    best_len = cur
        return best

    # ── 加载清洗数据 ──────────────────────────────────────────────
    cleaned_rows = (
        db.query(CleanedDataRecord)
        .filter(CleanedDataRecord.clean_job_id == clean_job_id)
        .all()
    )

    results: list[MatchResult] = []
    matched_count = 0
    BATCH = 500

    for row in cleaned_rows:
        item_upper = _norm(row.item_name)
        best_model: ModelRecord | None = None

        # S1: 用 brand_raw 缩窄候选
        if row.brand_raw:
            candidates = _candidates_by_brand_raw(row.brand_raw)
            best_model = _best(candidates, item_upper)

        # S2: item_name 里找 brand_code（处理"飞利浦（PHILIPS）"等英文码直接出现在名称中的情况）
        if best_model is None:
            for bc, grp in brand_code_index.items():
                if bc and bc in item_upper:
                    m = _best(grp, item_upper)
                    if m:
                        if len(_norm(m.model_code)) > len(_norm(best_model.model_code) if best_model else ""):
                            best_model = m

        # S3: item_name 里找 brand_name
        if best_model is None:
            for bn, grp in brand_name_index.items():
                if len(bn) >= 2 and bn in item_upper:
                    m = _best(grp, item_upper)
                    if m:
                        if len(_norm(m.model_code)) > len(_norm(best_model.model_code) if best_model else ""):
                            best_model = m

        # S4: 无品牌线索时用长 model_code 兜底
        if best_model is None:
            best_model = _best(long_code_models, item_upper)

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

        if len(results) >= BATCH:
            db.bulk_save_objects(results)
            db.commit()
            results = []

    if results:
        db.bulk_save_objects(results)
        db.commit()

    total = len(cleaned_rows)
    return {"total": total, "matched": matched_count, "pending": total - matched_count}
