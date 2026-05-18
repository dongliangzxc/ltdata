"""
型号匹配引擎

匹配流程为瀑布式降级：每条数据依次尝试各阶段，命中即停止，不再进入后续阶段。

  S0     ── URL精确匹配
           从宝贝链接提取 (platform, item_id)，查 item_url_mappings 表。
           人工维护的 URL→型号映射，置信度最高。命中 → url_matched。

  S0.2   ── 历史库匹配
           同样用 (platform, item_id)，查 historical_mappings 表（批量导入的历史对照）。
           命中 → matched。

  S0.5   ── 显式规则匹配
           按 priority 遍历 match_rules 表，对商品名做精确或包含匹配。
           适用于文本规律明显但 URL 不固定的商品（如套装、礼盒等）。
           命中 → matched。

  S1     ── brand_raw 缩窄候选
           用原始品牌字段 brand_raw 定位品牌（依次尝试：精确等于 brand_code →
           精确等于 brand_name → brand_code 包含于 brand_raw → brand_name 包含于 brand_raw），
           再在该品牌候选组内搜索商品名（model_code / model_name / alias）。
           标记 brand_identified=1。

  S2     ── 商品名里找 brand_code
           S1 品牌未识别时，扫描商品名，找哪个 brand_code 出现其中，
           再在对应品牌组内搜索型号。标记 brand_identified=1。

  S3     ── 商品名里找 brand_name
           S2 仍未命中，改用 brand_name（≥2字符）在商品名中匹配，逻辑同 S2。
           标记 brand_identified=1。

  S4     ── 全局长码兜底（仅限品牌完全未识别时）
           S1/S2/S3 均未识别出品牌，才触发此阶段。
           对所有 model_code ≥5 字符的型号，直接检查商品名是否包含该 model_code。
           不检查别名（别名较短，无品牌约束下容易误匹配）。

型号候选评分规则：多个候选均命中时，取 model_code 最长者（长码更精确，短码误匹配率高）。

text_only 状态：S1-S4 文本命中，但商品有 URL 且该 URL 不在 url_map 中。
  表示型号已找到，但 URL 映射尚未建立，需在"URL待审"页面人工确认；
  确认后自动写入 url_mappings，下次同款商品直接走 S0。

brand_identified 标记：S1/S2/S3 任意阶段识别到品牌即置 1，即使最终未找到型号（pending）。
  用于在匹配确认页过滤"未识别品牌"条目，辅助人工处理。

支持重复执行：每次运行先删除该 clean_job 的旧结果再重新写入。
"""
from sqlalchemy.orm import Session
from app.models.schemas import CleanedDataRecord, ModelRecord, ModelAlias, MatchResult, MatchResultCandidate, ItemUrlMapping, MatchRule, HistoricalMapping
from app.utils.url_utils import extract_item_id
from app.services.attribute_matcher import run_attribute_matching


def _norm(s: str | None) -> str:
    return (s or "").upper().strip()


def run_match(db: Session, clean_job_id: int, progress_cb=None) -> dict:
    """
    progress_cb(processed: int, total: int, matched: int) — 每批次调用一次
    """
    # ── 删除旧结果（支持重跑）────────────────────────────────────
    old_mr_ids = [
        r.id for r in db.query(MatchResult.id)
        .filter(MatchResult.clean_job_id == clean_job_id)
        .all()
    ]
    if old_mr_ids:
        db.query(MatchResultCandidate).filter(
            MatchResultCandidate.match_result_id.in_(old_mr_ids)
        ).delete(synchronize_session=False)
    db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).delete(
        synchronize_session=False
    )

    # ── S0: 预加载 URL 映射表 ─────────────────────────────────────
    url_map: dict[tuple[str, str], int] = {}        # model_id 已知的条目
    url_brand_map: dict[tuple[str, str], str] = {}  # 品牌已知但 model_id=NULL 的条目
    for um in db.query(ItemUrlMapping).all():
        if um.model_id:
            url_map[(um.platform, um.item_id)] = um.model_id
        elif um.brand_code:
            url_brand_map[(um.platform, um.item_id)] = um.brand_code

    # ── S0.5: 预加载显式匹配规则（按 priority 升序）────────────────
    explicit_rules = (
        db.query(MatchRule)
        .filter(MatchRule.is_active == 1)
        .order_by(MatchRule.priority)
        .all()
    )

    # ── S0.2: 预加载历史库映射 ────────────────────────────────────
    # key=(platform_lower, item_id), value=model_id
    hist_map: dict[tuple[str, str], int | None] = {}
    for hm in db.query(HistoricalMapping).all():
        hist_map[(hm.platform.lower(), hm.item_id)] = hm.model_id

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

    def _top_candidates(
        candidates: list[ModelRecord],
        item_upper: str,
        match_source: str,
        allow_alias: bool = True,
        n: int = 5,
    ) -> list[tuple]:
        """返回按 score 降序排列的前 n 个命中候选 (model, score, source)。"""
        scored = []
        for m in candidates:
            mc = _norm(m.model_code)
            mn = _norm(m.model_name) if m.model_name else None
            hit_len = 0

            if mc and mc in item_upper:
                hit_len = len(mc)
            elif mn and len(mn) >= 3 and mn in item_upper:
                hit_len = len(mn)
            elif allow_alias:
                for alias in alias_map.get(m.id, []):
                    if alias and len(alias) >= 4 and alias in item_upper:
                        hit_len = len(alias)
                        break

            if hit_len > 0:
                scored.append((m, hit_len, match_source))

        scored.sort(key=lambda x: -x[1])
        return scored[:n]

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
    # raw_data_id → list of (model, score, source) for S1-S4 hits
    raw_data_candidates: dict[int, list[tuple]] = {}

    for i, row in enumerate(cleaned_rows):
        item_upper = _norm(row.item_name)

        # ── S0: URL精确匹配 ────────────────────────────────────
        url_info = extract_item_id(row.item_url) if row.item_url else None
        url_brand_hint: str | None = None
        if url_info:
            platform, item_id = url_info
            url_model_id = url_map.get((platform, item_id))
            if url_model_id:
                results.append(MatchResult(
                    clean_job_id=clean_job_id,
                    raw_data_id=row.raw_data_id,
                    model_id=url_model_id,
                    match_status="url_matched",
                    matched_by="auto",
                    match_source="s0",
                ))
                matched_count += 1
                if len(results) >= BATCH:
                    db.bulk_save_objects(results)
                    db.commit()
                    if progress_cb:
                        progress_cb(i + 1, total, matched_count)
                    results = []
                continue  # 跳过 S1-S4
            # model_id=NULL 但 brand_code 有值：作为 S1 品牌线索
            url_brand_hint = url_brand_map.get((platform, item_id))

        # ── S0.2: 历史库精确匹配 ─────────────────────────────────
        hist_key = ((row.platform or "").lower(), row.item_id) if row.item_id else None
        hist_hit = hist_key in hist_map if hist_key else False
        if hist_hit:
            hist_model_id = hist_map[hist_key]
            if hist_model_id:
                # 已知商品且有型号 → matched
                results.append(MatchResult(
                    clean_job_id=clean_job_id,
                    raw_data_id=row.raw_data_id,
                    model_id=hist_model_id,
                    match_status="matched",
                    matched_by="auto",
                    match_source="historical",
                    brand_identified=1,
                ))
                matched_count += 1
                if len(results) >= BATCH:
                    db.bulk_save_objects(results)
                    db.commit()
                    if progress_cb:
                        progress_cb(i + 1, total, matched_count)
                    results = []
                continue  # 跳过 S0.5 / S1-S4
            else:
                # 已知商品但无型号 → pending，跳过 S1-S4（防止 S4 误匹配）
                results.append(MatchResult(
                    clean_job_id=clean_job_id,
                    raw_data_id=row.raw_data_id,
                    model_id=None,
                    match_status="pending",
                    matched_by="auto",
                    match_source="historical",
                    brand_identified=1,
                ))
                if len(results) >= BATCH:
                    db.bulk_save_objects(results)
                    db.commit()
                    if progress_cb:
                        progress_cb(i + 1, total, matched_count)
                    results = []
                continue  # 跳过 S0.5 / S1-S4

        # ── S0.5: 显式规则匹配 ─────────────────────────────────────
        s05_model_id: int | None = None
        for rule in explicit_rules:
            kw = rule.keyword.upper()
            if rule.match_type == "exact":
                if item_upper == kw:
                    s05_model_id = rule.model_id
                    break
            else:  # contains
                if kw in item_upper:
                    s05_model_id = rule.model_id
                    break

        if s05_model_id is not None:
            status = "matched"
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=s05_model_id,
                match_status=status,
                matched_by="auto",
                match_source="s0.5",
                brand_identified=1,
            ))
            matched_count += 1
            if len(results) >= BATCH:
                db.bulk_save_objects(results)
                db.commit()
                if progress_cb:
                    progress_cb(i + 1, total, matched_count)
                results = []
            continue  # 跳过 S1-S4

        # ── S1-S4 文本匹配 ─────────────────────────────────────
        best_model: ModelRecord | None = None
        brand_identified = False
        match_source: str | None = None
        row_candidates: list[tuple] = []

        if url_brand_hint:
            # URL 映射中有品牌线索：只在该品牌下查型号，跳过 S2/S3/S4
            candidates = _candidates_by_brand_raw(url_brand_hint)
            if candidates:
                brand_identified = True
                top = _top_candidates(candidates, item_upper, "s1")
                row_candidates.extend(top)
                if top:
                    best_model = top[0][0]
                    match_source = "s1"
        else:
            # S1: 用 brand_raw 缩窄候选
            if row.brand_raw:
                candidates = _candidates_by_brand_raw(row.brand_raw)
                if candidates:
                    brand_identified = True
                    top = _top_candidates(candidates, item_upper, "s1")
                    row_candidates.extend(top)
                    if top:
                        best_model = top[0][0]
                        match_source = "s1"

            # S2: item_name 里找 brand_code
            if best_model is None:
                for bc, grp in brand_code_index.items():
                    if bc and bc in item_upper:
                        brand_identified = True
                        top = _top_candidates(grp, item_upper, "s2")
                        row_candidates.extend(top)
                        if top:
                            if len(_norm(top[0][0].model_code)) > len(_norm(best_model.model_code) if best_model else ""):
                                best_model = top[0][0]
                                match_source = "s2"

            # S3: item_name 里找 brand_name
            if best_model is None:
                for bn, grp in brand_name_index.items():
                    if len(bn) >= 2 and bn in item_upper:
                        brand_identified = True
                        top = _top_candidates(grp, item_upper, "s3")
                        row_candidates.extend(top)
                        if top:
                            if len(_norm(top[0][0].model_code)) > len(_norm(best_model.model_code) if best_model else ""):
                                best_model = top[0][0]
                                match_source = "s3"

            # S4: 仅在品牌完全未识别时才做全局长码兜底
            if best_model is None and not brand_identified:
                top = _top_candidates(long_code_models, item_upper, "s4", allow_alias=False)
                row_candidates.extend(top)
                if top:
                    best_model = top[0][0]
                    match_source = "s4"

        # 记录候选（仅当有多于1个候选或best_model有候选时）
        if row_candidates:
            raw_data_candidates[row.raw_data_id] = row_candidates

        if best_model:
            # url_info 不为 None → URL存在但不在映射表 → 需人工审核
            status = "text_only" if url_info else "matched"
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=best_model.id,
                match_status=status,
                matched_by="auto",
                match_source=match_source,
                brand_identified=1 if brand_identified else 0,
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
                brand_identified=1 if brand_identified else 0,
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

    # ── 写入候选记录 ──────────────────────────────────────────────
    if raw_data_candidates:
        # 查询所有新写入的 match_results，以 raw_data_id 为键
        mr_by_raw: dict[int, int] = {
            r.raw_data_id: r.id
            for r in db.query(MatchResult.raw_data_id, MatchResult.id)
            .filter(MatchResult.clean_job_id == clean_job_id)
            .all()
        }
        candidate_records = []
        for raw_data_id, cands in raw_data_candidates.items():
            mr_id = mr_by_raw.get(raw_data_id)
            if mr_id is None:
                continue
            # 去重：同一 model_id 保留最高分
            seen: dict[int, tuple] = {}
            for model, score, source in cands:
                if model.id not in seen or score > seen[model.id][1]:
                    seen[model.id] = (model, score, source)
            sorted_cands = sorted(seen.values(), key=lambda x: -x[1])[:5]
            for rank, (model, score, source) in enumerate(sorted_cands, start=1):
                candidate_records.append(MatchResultCandidate(
                    match_result_id=mr_id,
                    model_id=model.id,
                    match_source=source,
                    score=score,
                    rank=rank,
                ))
        if candidate_records:
            db.bulk_save_objects(candidate_records)
            db.commit()

    # 触发属性匹配（仅对 matched/url_matched 状态）
    matched_result_ids = [
        r.id for r in db.query(MatchResult)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.match_status.in_(["matched", "url_matched"]),
        )
        .all()
    ]
    if matched_result_ids:
        run_attribute_matching(db, matched_result_ids)

    return {"total": total, "matched": matched_count, "pending": total - matched_count}
