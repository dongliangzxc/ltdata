"""
型号匹配引擎

匹配步骤（依次降级）：
  S1: brand_raw → 精确/包含匹配 brand_code / brand_name → 在候选组里找 model_code/model_name/alias
  S2: item_name 中包含 brand_code → 在对应品牌组找 model_code/model_name/alias
  S3: item_name 中包含 brand_name（≥2字符）→ 在对应品牌组找 model_code/model_name/alias
  S4: 兜底 — model_code（≥5字符）直接出现在 item_name 中（不检查别名，避免短别名误匹配）

同优先级多候选时取 model_code 最长的，减少短码误匹配。
支持重复执行：先删旧结果再写入。
"""
from sqlalchemy.orm import Session
from app.models.schemas import CleanedDataRecord, ModelRecord, ModelAlias, MatchResult


def _norm(s: str | None) -> str:
    return (s or "").upper().strip()


def run_match(db: Session, clean_job_id: int, progress_cb=None) -> dict:
    """
    progress_cb(processed: int, total: int, matched: int) — 每批次调用一次
    """
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

    # ── 预加载别名 {model_id: [alias_code_upper, ...]} ───────────
    alias_map: dict[int, list[str]] = {}
    for a in db.query(ModelAlias).all():
        alias_map.setdefault(a.model_id, []).append(_norm(a.alias_code))

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

        if bu in brand_code_index:
            _add(brand_code_index[bu])
        if bu in brand_name_index:
            _add(brand_name_index[bu])
        if not result:
            for bc, grp in brand_code_index.items():
                if bc and bc in bu:
                    _add(grp)
        if not result:
            for bn, grp in brand_name_index.items():
                if len(bn) >= 2 and bn in bu:
                    _add(grp)

        brand_raw_cache[brand_raw] = result
        return result

    def _best(candidates: list[ModelRecord], item_upper: str, allow_alias: bool = True) -> ModelRecord | None:
        """在候选列表里找命中 item_name 的最优型号（model_code 最长优先，别名次之）。"""
        best: ModelRecord | None = None
        best_len = 0
        for m in candidates:
            mc = _norm(m.model_code)
            mn = _norm(m.model_name)
            hit_len = 0

            if mc and mc in item_upper:
                hit_len = len(mc)
            elif mn and len(mn) >= 3 and mn in item_upper:
                hit_len = len(mn)
            elif allow_alias:
                # 检查别名（最短 4 字符避免误匹配）
                for alias in alias_map.get(m.id, []):
                    if alias and len(alias) >= 4 and alias in item_upper:
                        hit_len = len(alias)
                        break

            if hit_len > best_len:
                best = m
                best_len = hit_len
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
    total = len(cleaned_rows)

    for i, row in enumerate(cleaned_rows):
        item_upper = _norm(row.item_name)
        best_model: ModelRecord | None = None
        brand_identified = False
        match_source: str | None = None

        # S1: 用 brand_raw 缩窄候选
        if row.brand_raw:
            brand_identified = True
            candidates = _candidates_by_brand_raw(row.brand_raw)
            if candidates:
                m = _best(candidates, item_upper)
                if m:
                    best_model = m
                    match_source = "s1"

        # S2: item_name 里找 brand_code
        if best_model is None:
            for bc, grp in brand_code_index.items():
                if bc and bc in item_upper:
                    brand_identified = True
                    m = _best(grp, item_upper)
                    if m:
                        if len(_norm(m.model_code)) > len(_norm(best_model.model_code) if best_model else ""):
                            best_model = m
                            match_source = "s2"

        # S3: item_name 里找 brand_name
        if best_model is None:
            for bn, grp in brand_name_index.items():
                if len(bn) >= 2 and bn in item_upper:
                    brand_identified = True
                    m = _best(grp, item_upper)
                    if m:
                        if len(_norm(m.model_code)) > len(_norm(best_model.model_code) if best_model else ""):
                            best_model = m
                            match_source = "s3"

        # S4: 仅在品牌完全未识别时才做全局长码兜底
        if best_model is None and not brand_identified:
            best_model = _best(long_code_models, item_upper, allow_alias=False)
            if best_model:
                match_source = "s4"

        if best_model:
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=best_model.id,
                match_status="matched",
                matched_by="auto",
                match_source=match_source,
            ))
            matched_count += 1
        else:
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=None,
                match_status="pending",
                matched_by="auto",
                match_source=None,
            ))

        if len(results) >= BATCH:
            db.bulk_save_objects(results)
            db.commit()
            if progress_cb:
                progress_cb(i + 1, total, matched_count)
            results = []

    if results:
        db.bulk_save_objects(results)
        db.commit()

    return {"total": total, "matched": matched_count, "pending": total - matched_count}
