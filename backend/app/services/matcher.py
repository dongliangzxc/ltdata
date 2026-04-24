"""
型号匹配引擎

匹配策略（优先级递减）：
  P1: brand_raw 对应 brand_code/brand_name 的型号组中，model_code/model_name 在 item_name 中
  P2: 不限品牌，model_code/model_name 在 item_name 中（model_code 长度 >= 5 才启用，避免误匹配）

优化：
  - 先用 brand_raw 字段缩窄候选型号范围，减少遍历量
  - brand_raw → 标准化 brand_code/brand_name 的映射缓存
  - 同优先级有多个候选时，取 model_code 最长的（减少短码误匹配）

支持重复执行：先删除该 clean_job 的旧匹配结果，再重新写入。
"""
from sqlalchemy.orm import Session
from app.models.schemas import CleanedDataRecord, ModelRecord, MatchResult


def _normalize(s: str) -> str:
    """转大写 + 去首尾空白，用于比较"""
    return (s or "").upper().strip()


def run_match(db: Session, clean_job_id: int) -> dict:
    """
    对一次清洗任务的所有结果执行型号匹配，写入 match_results。
    返回: {"total": N, "matched": M, "pending": P}
    """
    # 删除旧匹配结果（支持重复执行）
    db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).delete(
        synchronize_session=False
    )

    # ── 加载全部型号，构建内存索引 ────────────────────────────────
    all_models = db.query(ModelRecord).all()

    # brand_code_upper → [model list]
    brand_code_index: dict[str, list[ModelRecord]] = {}
    for m in all_models:
        key = _normalize(m.brand_code)
        if key:
            brand_code_index.setdefault(key, []).append(m)

    # brand_name_upper → [model list]（brand_name 至少 2 字符）
    brand_name_index: dict[str, list[ModelRecord]] = {}
    for m in all_models:
        key = _normalize(m.brand_name)
        if len(key) >= 2:
            brand_name_index.setdefault(key, []).append(m)

    # P2 候选池：model_code 长度 >= 5 的全量型号（无品牌线索时兜底）
    long_code_models = [m for m in all_models if len(_normalize(m.model_code)) >= 5]

    # ── brand_raw → 候选型号列表 缓存（避免每条数据重复查索引）────
    brand_raw_cache: dict[str, list[ModelRecord]] = {}

    def _candidates_for_brand(brand_raw: str) -> list[ModelRecord]:
        """根据 brand_raw 返回可能匹配的型号列表（P1 用）"""
        key = brand_raw
        if key in brand_raw_cache:
            return brand_raw_cache[key]

        brand_upper = _normalize(brand_raw)
        result: list[ModelRecord] = []
        seen_ids: set[int] = set()

        # 1) brand_raw 精确匹配 brand_code
        if brand_upper in brand_code_index:
            for m in brand_code_index[brand_upper]:
                if m.id not in seen_ids:
                    result.append(m)
                    seen_ids.add(m.id)

        # 2) brand_raw 精确匹配 brand_name
        if brand_upper in brand_name_index:
            for m in brand_name_index[brand_upper]:
                if m.id not in seen_ids:
                    result.append(m)
                    seen_ids.add(m.id)

        # 3) brand_raw 包含 brand_code（处理"飞利浦（PHILIPS）"这类组合写法）
        if not result:
            for bc, group in brand_code_index.items():
                if bc and bc in brand_upper:
                    for m in group:
                        if m.id not in seen_ids:
                            result.append(m)
                            seen_ids.add(m.id)

        # 4) brand_raw 包含 brand_name（如"爱国者（aigo）"）
        if not result:
            for bn, group in brand_name_index.items():
                if len(bn) >= 2 and bn in brand_upper:
                    for m in group:
                        if m.id not in seen_ids:
                            result.append(m)
                            seen_ids.add(m.id)

        brand_raw_cache[key] = result
        return result

    def _best_in_group(candidates: list[ModelRecord], item_upper: str) -> ModelRecord | None:
        """在候选列表里找 model_code/model_name 命中 item_name 的最优型号（取 model_code 最长的）"""
        best: ModelRecord | None = None
        best_len = 0
        for m in candidates:
            mc = _normalize(m.model_code)
            mn = _normalize(m.model_name)
            hit = (mc and mc in item_upper) or (mn and len(mn) >= 3 and mn in item_upper)
            if hit:
                cur_len = len(mc)
                if cur_len > best_len:
                    best = m
                    best_len = cur_len
        return best

    # ── 加载该 clean_job 的全部 cleaned_data ─────────────────────
    cleaned_rows = (
        db.query(CleanedDataRecord)
        .filter(CleanedDataRecord.clean_job_id == clean_job_id)
        .all()
    )

    results: list[MatchResult] = []
    matched_count = 0
    BATCH = 500  # 每批次 bulk_save，避免内存过大

    for i, row in enumerate(cleaned_rows):
        item_upper = _normalize(row.item_name)
        best_model: ModelRecord | None = None

        # P1: 先用 brand_raw 缩窄候选范围
        if row.brand_raw:
            candidates = _candidates_for_brand(row.brand_raw)
            best_model = _best_in_group(candidates, item_upper)

        # P1 fallback：brand_raw 为空时，扫描全量品牌索引
        if best_model is None and not row.brand_raw:
            for bc, group in brand_code_index.items():
                if bc and bc in item_upper:
                    m = _best_in_group(group, item_upper)
                    if m:
                        mc_len = len(_normalize(m.model_code))
                        best_len = len(_normalize(best_model.model_code)) if best_model else 0
                        if mc_len > best_len:
                            best_model = m

        # P2: 无品牌线索 or P1 未命中时，用长 model_code 兜底
        if best_model is None:
            best_model = _best_in_group(long_code_models, item_upper)

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

        # 分批写入，避免内存积压
        if len(results) >= BATCH:
            db.bulk_save_objects(results)
            db.commit()
            results = []

    if results:
        db.bulk_save_objects(results)
        db.commit()

    total = len(cleaned_rows)
    pending = total - matched_count
    return {"total": total, "matched": matched_count, "pending": pending}
