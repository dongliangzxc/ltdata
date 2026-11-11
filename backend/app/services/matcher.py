"""
型号匹配引擎

匹配流程为瀑布式降级：每条数据依次尝试各阶段，命中即停止，不再进入后续阶段。

  S0     ── URL精确匹配
           从宝贝链接提取 (platform, item_id)，查 item_url_mappings 表。
           人工维护的 URL→型号映射，置信度最高。命中 → url_matched。

  S0.1   ── 人工排除沉淀库沿用
           同品类内，命中 item_exclusions（优先 platform+item_id，回退规范化标题）
           的自动标记为 excluded（match_source=exclude_reuse），不再走后续阶段。
           URL 映射命中（S0）优先于此阶段。

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
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from app.models.schemas import CleanedDataRecord, ModelRecord, ModelAlias, MatchResult, MatchResultAttr, MatchResultCandidate, MatchResultExtraValue, ItemUrlMapping, MatchRule, HistoricalMapping, CleanJobRecord, RawDataRecord
from app.utils.url_utils import extract_item_id
from app.utils.text_utils import title_key
from app.services.attribute_matcher import run_attribute_matching
from app.services.price_auditor import audit_price

logger = logging.getLogger(__name__)


@dataclass
class MatchContext:
    """匹配上下文：URL 映射、显式规则、品牌索引、别名等预加载结构，
    供整批 run_match 与单条 run_match_for_result 共用。"""
    job_category_code: str | None
    url_map: dict = field(default_factory=dict)
    url_brand_map: dict = field(default_factory=dict)
    valid_model_ids: set = field(default_factory=set)
    explicit_rules: list = field(default_factory=list)
    brand_code_index: dict = field(default_factory=dict)
    brand_name_index: dict = field(default_factory=dict)
    # 品牌码/品牌名的 1/2 字符前缀索引与顺序映射（S2/S3 提速：避免每行遍历全部品牌）
    brand_code_prefix: dict = field(default_factory=dict)
    brand_name_prefix: dict = field(default_factory=dict)
    brand_code_order: dict = field(default_factory=dict)
    brand_name_order: dict = field(default_factory=dict)
    # 长码型号的（型号码/型号名/别名）前缀索引与顺序映射（S4 提速）
    model_prefix: dict = field(default_factory=dict)
    long_code_model_order: dict = field(default_factory=dict)
    long_code_models: list = field(default_factory=list)
    alias_map: dict = field(default_factory=dict)
    brand_raw_cache: dict = field(default_factory=dict)
    exclusion_url_keys: set = field(default_factory=set)
    exclusion_name_keys: set = field(default_factory=set)
    url_reusable_model_ids: set = field(default_factory=set)
    # 历史库内存索引（run_match 预载，消除 _history_lookup 逐行 N+1 查询）：
    # None 表示未加载，_history_lookup 回退逐条查库。键为 (平台小写, 键值)。
    hist_item_id: dict | None = None
    hist_item_url: dict | None = None
    hist_item_name_norm: dict | None = None
    # 已加载「全量（含无月份行）」历史的平台；仅按月加载子集的平台不在其中
    hist_full_platforms: set = field(default_factory=set)


def _load_match_context(db: Session, category_code: str | None) -> MatchContext:
    """加载给定品类下的匹配上下文；category_code=None 时不做品类过滤，
    保留 run_match 原有行为（全部有效型号进入 valid_model_ids）。"""
    ctx = MatchContext(job_category_code=category_code)

    model_query = db.query(ModelRecord)
    if category_code:
        model_query = model_query.filter(ModelRecord.category_code == category_code)
    model_rows = model_query.all()
    ctx.valid_model_ids = {m.id for m in model_rows if _is_valid_model(m)}
    # URL 映射可复用型号：本品类 active 且品牌非占位的型号即可被 URL 直接复用
    # （type 允许为空——video_doorbell 等按品牌级归类的品类，人工确认往往落在
    # 型号码为空的占位型号上，若不放开则同链接已确认商品无法自动复用）。
    ctx.url_reusable_model_ids = {
        m.id
        for m in model_rows
        if m.status == "active" and not _is_generic_brand_code(m.brand_code)
    }

    for um in db.query(ItemUrlMapping).all():
        if um.model_id and um.model_id in ctx.url_reusable_model_ids:
            ctx.url_map[(um.platform, um.item_id)] = um.model_id
        elif um.brand_code:
            ctx.url_brand_map[(um.platform, um.item_id)] = um.brand_code

    ctx.explicit_rules = (
        db.query(MatchRule)
        .filter(MatchRule.is_active == 1, MatchRule.model_id.in_(ctx.valid_model_ids))
        .order_by(MatchRule.priority)
        .all()
    )

    all_models = [m for m in model_rows if m.id in ctx.valid_model_ids]

    for m in all_models:
        key = _norm(m.brand_code)
        if key:
            ctx.brand_code_index.setdefault(key, []).append(m)
    for m in all_models:
        key = _norm(m.brand_name)
        if len(key) >= 2:
            ctx.brand_name_index.setdefault(key, []).append(m)
    ctx.long_code_models = [m for m in all_models if len(_norm(m.model_code)) >= 5]

    # ── 前缀索引：把「每行遍历全部品牌/型号」剪枝为「只查文本中出现的前缀」──
    ctx.brand_code_order = {key: i for i, key in enumerate(ctx.brand_code_index)}
    for key in ctx.brand_code_index:
        for p in _key_prefixes(key):
            ctx.brand_code_prefix.setdefault(p, []).append(key)
    ctx.brand_name_order = {key: i for i, key in enumerate(ctx.brand_name_index)}
    for key in ctx.brand_name_index:
        for p in _key_prefixes(key):
            ctx.brand_name_prefix.setdefault(p, []).append(key)
    ctx.long_code_model_order = {m.id: i for i, m in enumerate(ctx.long_code_models)}
    for m in ctx.long_code_models:
        probe_keys = []
        mc = _norm(m.model_code)
        if mc:
            probe_keys.append(mc)
        mn = _norm(m.model_name) if m.model_name else None
        if mn and len(mn) >= 3:
            probe_keys.append(mn)
        for alias in ctx.alias_map.get(m.id, []):
            if alias and len(alias) >= 4:
                probe_keys.append(alias)
        for probe in probe_keys:
            for p in _key_prefixes(probe):
                ctx.model_prefix.setdefault(p, []).append(m)

    for a in db.query(ModelAlias).all():
        ctx.alias_map.setdefault(a.model_id, []).append(_norm(a.alias_code))

    # 人工排除沉淀库：同品类内命中即自动沿用排除（S0.1）
    from app.services.exclusion_store import load_exclusion_index
    ctx.exclusion_url_keys, ctx.exclusion_name_keys = load_exclusion_index(db, category_code)

    return ctx


def _is_excluded(ctx: MatchContext, platform: str | None, item_id: str | None, item_name: str | None) -> bool:
    """S0.1：命中人工排除沉淀库（链接优先，标题兜底）。"""
    if not ctx.exclusion_url_keys and not ctx.exclusion_name_keys:
        return False
    if platform and item_id and (platform.lower(), item_id) in ctx.exclusion_url_keys:
        return True
    key = title_key(item_name)
    return bool(key) and key in ctx.exclusion_name_keys


def _norm(s: str | None) -> str:
    return (s or "").upper().strip()


def _is_placeholder_code(s: str | None) -> bool:
    value = _norm(s)
    return value == "" or set(value) == {"-"}


_GENERIC_BRAND_CODES = {
    "其他", "其他品牌", "无品牌", "未知品牌", "未知", "未识别品牌", "UNKNOWN", "OTHER",
}


def _is_generic_brand_code(s: str | None) -> bool:
    """品牌占位/通用品牌（不可作为自动复用型号）。"""
    return _is_placeholder_code(s) or _norm(s) in _GENERIC_BRAND_CODES


def _is_valid_model(m: ModelRecord) -> bool:
    return not _is_placeholder_code(m.brand_code) and not _is_placeholder_code(m.model_code)


def _normalize_history_name(s: str | None) -> str:
    return " ".join((s or "").upper().split())


def _month_parts(month_value) -> tuple[int | None, int | None]:
    if month_value is None:
        return None, None
    try:
        month_int = int(month_value)
    except (TypeError, ValueError):
        return None, None
    if month_int < 10000:
        return None, None
    return month_int // 100, month_int % 100


def _period_candidates(row) -> list[tuple[int | None, int | None, str | None]]:
    year, month_num = _month_parts(getattr(row, "month", None))
    week = getattr(row, "week", None)
    if year and month_num:
        if week:
            return [(year, month_num, str(week)), (year, month_num, None)]
        return [(year, month_num, None)]
    return [(None, None, None)]


def _apply_history_period(query, year: int | None, month_num: int | None, week: str | None):
    if year is None or month_num is None:
        return query.order_by(HistoricalMapping.updated_at.desc(), HistoricalMapping.id.desc())
    query = query.filter(HistoricalMapping.year == year, HistoricalMapping.month_num == month_num)
    if week:
        return query.filter(HistoricalMapping.week == week).order_by(HistoricalMapping.updated_at.desc(), HistoricalMapping.id.desc())
    return query.filter(HistoricalMapping.week.is_(None)).order_by(HistoricalMapping.updated_at.desc(), HistoricalMapping.id.desc())


def _history_lookup(db: Session, row: CleanedDataRecord, ctx: MatchContext | None = None) -> "HistoricalMapping | _HistoryHit | None":
    row_platform = (row.platform or "").lower()
    parsed = extract_item_id(row.item_url) if row.item_url else None
    keys = []
    if row_platform and row.item_id:
        keys.append(("item_id", row_platform, row.item_id))
    if parsed:
        parsed_platform, parsed_item_id = parsed
        keys.append(("item_id", parsed_platform, parsed_item_id))
    if row_platform and row.item_url:
        keys.append(("item_url", row_platform, row.item_url))
    item_name_norm = _normalize_history_name(row.item_name)
    if row_platform and item_name_norm:
        keys.append(("item_name", row_platform, item_name_norm))

    seen = set()
    deduped_keys = []
    for key in keys:
        if key not in seen:
            deduped_keys.append(key)
            seen.add(key)

    # ── 内存索引路径（run_match 已把任务所需历史库预载进 ctx）──────
    if ctx is not None and ctx.hist_item_id is not None:
        indexes = {
            "item_id": ctx.hist_item_id,
            "item_url": ctx.hist_item_url,
            "item_name": ctx.hist_item_name_norm,
        }
        return _history_lookup_in_memory(indexes, ctx.hist_full_platforms, row, deduped_keys)

    for key_type, platform, value in deduped_keys:
        for year, month_num, week in _period_candidates(row):
            q = db.query(HistoricalMapping).filter(HistoricalMapping.platform == platform.lower())
            if key_type == "item_id":
                q = q.filter(HistoricalMapping.item_id == value)
            elif key_type == "item_url":
                q = q.filter(HistoricalMapping.item_url == value)
            else:
                q = q.filter(HistoricalMapping.item_name_norm == value)
            hit = _apply_history_period(q, year, month_num, week).first()
            if hit:
                return hit
    return None


class _HistoryHit:
    """内存索引命中的轻量结果：调用方只使用 model_id。"""

    __slots__ = ("model_id",)

    def __init__(self, model_id):
        self.model_id = model_id


def _history_lookup_in_memory(
    indexes: dict,
    full_platforms: set,
    row: CleanedDataRecord,
    deduped_keys: list,
) -> _HistoryHit | None:
    """与逐条查库同语义：按键顺序、周期偏好取第一条，命中键内按
    (updated_at desc, id desc) 取最新。无月份行要求平台已全量加载
    （_build_history_index 保证：任务含无月份行时加载平台全量）。"""
    year, month_num = _month_parts(getattr(row, "month", None))
    week = str(getattr(row, "week", None)) if getattr(row, "week", None) is not None else None
    if year and month_num:
        periods = [(year, month_num, week), (year, month_num, None)]
    else:
        periods = [(None, None, None)]

    for key_type, platform, value in deduped_keys:
        # 与索引键一致的大小写归一化（平台已小写；键值 casefold 对齐 MySQL ci 排序规则）
        bucket = indexes[key_type].get((platform, value.casefold()))
        if not bucket:
            continue
        for p_year, p_month, p_week in periods:
            best: tuple | None = None
            for rec_year, rec_month, rec_week, updated_at, rid, model_id in bucket:
                if p_year is None:
                    if platform not in full_platforms:
                        continue  # 未全量加载，无法按无月份周期判定，跳过该周期
                    matched = True
                else:
                    matched = rec_year == p_year and rec_month == p_month
                    if matched and p_week is not None:
                        matched = rec_week == p_week
                    elif matched:
                        matched = rec_week is None
                if not matched:
                    continue
                sort_key = (updated_at if updated_at is not None else datetime.min, rid)
                if best is None or sort_key > best[0]:
                    best = (sort_key, model_id)
            if best is not None:
                return _HistoryHit(best[1])
    return None


def _build_history_index(db: Session, ctx: MatchContext, rows: list) -> None:
    """一次性加载任务所需的历史库数据到 ctx 内存索引，替代 _history_lookup 的逐行查询。

    按月任务只加载对应 (平台, 年月) 子集；存在无月份的行时回退加载平台全量，
    保证 (None, None, None) 周期判定与逐条查库一致。加载行只取查找所需列。
    """
    platforms = {(r.platform or "").lower() for r in rows if r.platform}
    if not platforms:
        return
    has_monthless = False
    periods: set[tuple[int, int]] = set()
    for r in rows:
        year, month_num = _month_parts(getattr(r, "month", None))
        if year and month_num:
            periods.add((year, month_num))
        else:
            has_monthless = True

    query = (
        db.query(
            HistoricalMapping.platform,
            HistoricalMapping.item_id,
            HistoricalMapping.item_url,
            HistoricalMapping.item_name_norm,
            HistoricalMapping.year,
            HistoricalMapping.month_num,
            HistoricalMapping.week,
            HistoricalMapping.updated_at,
            HistoricalMapping.id,
            HistoricalMapping.model_id,
        )
        # func.lower 归一化平台：对齐 MySQL ci 排序规则（历史库平台可能存成 JD/Tmall 等）
        .filter(func.lower(HistoricalMapping.platform).in_(platforms))
    )
    if not has_monthless:
        query = query.filter(or_(
            and_(HistoricalMapping.year == y, HistoricalMapping.month_num == m)
            for y, m in periods
        ))

    ctx.hist_item_id = {}
    ctx.hist_item_url = {}
    ctx.hist_item_name_norm = {}
    for row in query.all():
        # 键值大小写归一化，对齐 MySQL ci 排序规则下逐条查库的匹配行为
        platform = (row.platform or "").lower()
        record = (row.year, row.month_num, row.week, row.updated_at, row.id, row.model_id)
        if row.item_id:
            ctx.hist_item_id.setdefault((platform, row.item_id.casefold()), []).append(record)
        if row.item_url:
            ctx.hist_item_url.setdefault((platform, row.item_url.casefold()), []).append(record)
        if row.item_name_norm:
            ctx.hist_item_name_norm.setdefault((platform, row.item_name_norm.casefold()), []).append(record)
    if has_monthless:
        ctx.hist_full_platforms = platforms


def _candidates_by_brand_raw(ctx: MatchContext, brand_raw: str) -> list[ModelRecord]:
    """按 brand_raw 缩窄品牌候选：依次尝试 brand_code 精确 / brand_name 精确 /
    brand_code 包含 / brand_name 包含。命中结果按 ctx.brand_raw_cache 缓存复用。"""
    if brand_raw in ctx.brand_raw_cache:
        return ctx.brand_raw_cache[brand_raw]
    bu = _norm(brand_raw)
    result: list[ModelRecord] = []
    seen: set[int] = set()

    def _add(lst: list[ModelRecord]):
        for m in lst:
            if m.id not in seen:
                result.append(m)
                seen.add(m.id)

    if bu in ctx.brand_code_index:
        _add(ctx.brand_code_index[bu])
    if bu in ctx.brand_name_index:
        _add(ctx.brand_name_index[bu])
    if not result:
        for bc, grp in ctx.brand_code_index.items():
            if bc and bc in bu:
                _add(grp)
    if not result:
        for bn, grp in ctx.brand_name_index.items():
            if len(bn) >= 2 and bn in bu:
                _add(grp)

    ctx.brand_raw_cache[brand_raw] = result
    return result


def _top_candidates(
    ctx: MatchContext,
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
            for alias in ctx.alias_map.get(m.id, []):
                if alias and len(alias) >= 4 and alias in item_upper:
                    hit_len = len(alias)
                    break

        if hit_len > 0:
            scored.append((m, hit_len, match_source))

    scored.sort(key=lambda x: -x[1])
    return scored[:n]


def _grams(text: str) -> set[str]:
    """文本的一元/二元字符集合，用于按品牌/型号前缀剪枝候选。

    只含 1/2 字符前缀：若某键（品牌码/品牌名/型号码等）是文本的子串，
    其前 1 或 2 个字符必然出现在该位置的 grams 中，因此剪枝不丢失命中；
    后续仍保留逐键的 `in` 精确判定，语义与剪枝前完全一致。
    """
    if not text:
        return set()
    grams = set()
    for i in range(len(text)):
        grams.add(text[i])
        if i + 1 < len(text):
            grams.add(text[i : i + 2])
    return grams


def _key_prefixes(key: str) -> list[str]:
    return [p for p in {key[:1], key[:2]} if p]


def _index_keys_by_grams(prefix_index: dict, order: dict, grams: set) -> list:
    """返回前缀出现在 grams 中的索引键，按索引插入顺序排序。

    顺序保持与直接遍历索引一致，确保并列同分时的选取结果不变。
    """
    keys = []
    seen = set()
    for g in grams:
        for key in prefix_index.get(g, ()):
            if key not in seen:
                seen.add(key)
                keys.append(key)
    keys.sort(key=order.__getitem__)
    return keys


def _match_text_stages(
    raw,
    item_upper: str,
    url_brand_hint: str | None,
    ctx: MatchContext,
    stage_time: dict | None = None,
) -> tuple[ModelRecord | None, str | None, bool, list[tuple]]:
    """S1-S4 文本匹配主体。返回 (best_model, match_source, brand_identified, row_candidates)。

    - S1: url_brand_hint 或 raw.brand_raw 缩窄品牌 → 品牌内取型号。
    - S2: 商品名里找 brand_code。
    - S3: 商品名里找 brand_name。
    - S4: 品牌完全未识别时的全局长码兜底。

    ``stage_time`` 非空时累计各阶段耗时（诊断用）。
    """
    best_model: ModelRecord | None = None
    brand_identified = False
    match_source: str | None = None
    row_candidates: list[tuple] = []

    def _acc(stage: str, t0: float) -> None:
        if stage_time is not None:
            stage_time[stage] = stage_time.get(stage, 0.0) + (time.perf_counter() - t0)

    if url_brand_hint:
        # URL 映射中有品牌线索：只在该品牌下查型号，跳过 S2/S3/S4
        _t0 = time.perf_counter()
        candidates = _candidates_by_brand_raw(ctx, url_brand_hint)
        if candidates:
            brand_identified = True
            top = _top_candidates(ctx, candidates, item_upper, "s1")
            row_candidates.extend(top)
            if top:
                best_model = top[0][0]
                match_source = "s1"
        _acc("s1", _t0)
    else:
        # S1: 用 brand_raw 缩窄候选
        if raw.brand_raw:
            _t0 = time.perf_counter()
            candidates = _candidates_by_brand_raw(ctx, raw.brand_raw)
            if candidates:
                brand_identified = True
                top = _top_candidates(ctx, candidates, item_upper, "s1")
                row_candidates.extend(top)
                if top:
                    best_model = top[0][0]
                    match_source = "s1"
            _acc("s1", _t0)

        # S2: item_name 里找 brand_code（前缀索引剪枝）
        if best_model is None:
            _t0 = time.perf_counter()
            grams = _grams(item_upper)
            for bc in _index_keys_by_grams(ctx.brand_code_prefix, ctx.brand_code_order, grams):
                if bc in item_upper:
                    brand_identified = True
                    top = _top_candidates(ctx, ctx.brand_code_index[bc], item_upper, "s2")
                    row_candidates.extend(top)
                    if top:
                        if len(_norm(top[0][0].model_code)) > len(_norm(best_model.model_code) if best_model else ""):
                            best_model = top[0][0]
                            match_source = "s2"
            _acc("s2", _t0)

        # S3: item_name 里找 brand_name
        if best_model is None:
            _t0 = time.perf_counter()
            for bn in _index_keys_by_grams(ctx.brand_name_prefix, ctx.brand_name_order, grams):
                if len(bn) >= 2 and bn in item_upper:
                    brand_identified = True
                    top = _top_candidates(ctx, ctx.brand_name_index[bn], item_upper, "s3")
                    row_candidates.extend(top)
                    if top:
                        if len(_norm(top[0][0].model_code)) > len(_norm(best_model.model_code) if best_model else ""):
                            best_model = top[0][0]
                            match_source = "s3"
            _acc("s3", _t0)

        # S4: 仅在品牌完全未识别时才做全局长码兜底（前缀剪枝）
        if best_model is None and not brand_identified:
            _t0 = time.perf_counter()
            pruned = []
            seen = set()
            for g in grams:
                for m in ctx.model_prefix.get(g, ()):
                    if m.id not in seen:
                        seen.add(m.id)
                        pruned.append(m)
            pruned.sort(key=lambda m: ctx.long_code_model_order[m.id])
            top = _top_candidates(ctx, pruned, item_upper, "s4", allow_alias=False)
            row_candidates.extend(top)
            if top:
                best_model = top[0][0]
                match_source = "s4"
            _acc("s4", _t0)

    return best_model, match_source, brand_identified, row_candidates


def run_match(db: Session, clean_job_id: int, progress_cb=None, commit: bool = True) -> dict:
    """
    progress_cb(processed: int, total: int, matched: int) — 每批次调用一次
    """
    _t0 = time.perf_counter()
    # ── 删除旧结果（支持重跑）────────────────────────────────────
    # ``ignored`` is a task-local manual decision.  Matching is deliberately
    # rebuildable, so retain the decision by raw_data_id before deleting the
    # old rows and restore it below.  It is not loaded from item_exclusions:
    # that table represents the separate cross-task ``excluded`` behaviour.
    ignored_snapshot = {
        raw_data_id: (
            review_note, reviewed_at,
            prev_match_status, prev_model_id, prev_matched_by,
            prev_match_source, prev_dispute_reason, prev_review_note, prev_reviewed_at,
        )
        for (
            raw_data_id, review_note, reviewed_at,
            prev_match_status, prev_model_id, prev_matched_by,
            prev_match_source, prev_dispute_reason, prev_review_note, prev_reviewed_at,
        ) in db.query(
            MatchResult.raw_data_id,
            MatchResult.review_note,
            MatchResult.reviewed_at,
            MatchResult.prev_match_status,
            MatchResult.prev_model_id,
            MatchResult.prev_matched_by,
            MatchResult.prev_match_source,
            MatchResult.prev_dispute_reason,
            MatchResult.prev_review_note,
            MatchResult.prev_reviewed_at,
        )
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.match_status == "ignored",
        )
        .all()
    }

    old_mr_ids = [
        r.id for r in db.query(MatchResult.id)
        .filter(MatchResult.clean_job_id == clean_job_id)
        .all()
    ]
    # 重跑匹配会删除旧 match_results，人工填写的扩展字段值按 raw_data_id 暂存后恢复，
    # 避免分析师重新清洗后又要重填「智能」等人工标记。
    extra_value_snapshot: dict[int, dict[str, str]] = {}
    if old_mr_ids:
        old_raw_by_mr = {
            mr_id: raw_id
            for mr_id, raw_id in db.query(MatchResult.id, MatchResult.raw_data_id)
            .filter(MatchResult.id.in_(old_mr_ids))
            .all()
        }
        for row in (
            db.query(MatchResultExtraValue)
            .filter(
                MatchResultExtraValue.match_result_id.in_(old_mr_ids),
                MatchResultExtraValue.source == "manual",
            )
            .all()
        ):
            raw_id = old_raw_by_mr.get(row.match_result_id)
            if raw_id is None or row.field_value is None:
                continue
            extra_value_snapshot.setdefault(raw_id, {})[row.field_key] = row.field_value

    if old_mr_ids:
        db.query(MatchResultAttr).filter(
            MatchResultAttr.match_result_id.in_(old_mr_ids)
        ).delete(synchronize_session=False)
        db.query(MatchResultCandidate).filter(
            MatchResultCandidate.match_result_id.in_(old_mr_ids)
        ).delete(synchronize_session=False)
        db.query(MatchResultExtraValue).filter(
            MatchResultExtraValue.match_result_id.in_(old_mr_ids)
        ).delete(synchronize_session=False)
    db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).delete(
        synchronize_session=False
    )
    _t1 = time.perf_counter()

    clean_job = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
    job_category_code = None
    if clean_job:
        job_category_code = clean_job.category_code or clean_job.dispatch_category_code

    ctx = _load_match_context(db, job_category_code)
    url_map = ctx.url_map
    url_brand_map = ctx.url_brand_map
    valid_model_ids = ctx.valid_model_ids
    explicit_rules = ctx.explicit_rules
    _t2 = time.perf_counter()

    # ── 加载清洗数据 ──────────────────────────────────────────────
    cleaned_rows = (
        db.query(CleanedDataRecord)
        .filter(CleanedDataRecord.clean_job_id == clean_job_id)
        .all()
    )
    _t3 = time.perf_counter()
    # 历史库一次性载入内存索引，避免逐行 N+1 查询（headphone 2.3 万行曾耗时约 5 分钟）
    _build_history_index(db, ctx, cleaned_rows)
    _t3b = time.perf_counter()

    results: list[MatchResult] = []
    matched_count = 0
    ignored_count = 0
    BATCH = 500
    total = len(cleaned_rows)
    # raw_data_id → list of (model, score, source) for S1-S4 hits
    raw_data_candidates: dict[int, list[tuple]] = {}
    stage_time: dict[str, float] = {}

    def _acc(stage: str, t0: float) -> None:
        stage_time[stage] = stage_time.get(stage, 0.0) + (time.perf_counter() - t0)

    for i, row in enumerate(cleaned_rows):
        # A task-local ignored row must not enter any matching stage, even on
        # a rerun.  Restore only the minimal manual metadata needed by the
        # ignored tab; no model, attributes, URL mapping, or exclusion-store
        # entry is carried over.
        if row.raw_data_id in ignored_snapshot:
            (
                review_note, reviewed_at,
                prev_match_status, prev_model_id, prev_matched_by,
                prev_match_source, prev_dispute_reason, prev_review_note, prev_reviewed_at,
            ) = ignored_snapshot[row.raw_data_id]
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=None,
                match_status="ignored",
                matched_by="manual",
                match_source="manual",
                review_note=review_note,
                reviewed_at=reviewed_at,
                prev_match_status=prev_match_status,
                prev_model_id=prev_model_id,
                prev_matched_by=prev_matched_by,
                prev_match_source=prev_match_source,
                prev_dispute_reason=prev_dispute_reason,
                prev_review_note=prev_review_note,
                prev_reviewed_at=prev_reviewed_at,
            ))
            ignored_count += 1
            if len(results) >= BATCH:
                db.bulk_save_objects(results)
                if commit:
                    db.commit()
                else:
                    db.flush()
                if progress_cb:
                    progress_cb(i + 1, total, matched_count)
                results = []
            continue

        _t_stage = time.perf_counter()
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
                    if commit:
                        db.commit()
                    else:
                        db.flush()
                    if progress_cb:
                        progress_cb(i + 1, total, matched_count)
                    results = []
                _acc("s0", _t_stage)
                continue  # 跳过 S1-S4
            # model_id=NULL 但 brand_code 有值：作为 S1 品牌线索
            url_brand_hint = url_brand_map.get((platform, item_id))
        _acc("s0", _t_stage)

        # ── S0.1: 人工排除沉淀库沿用 ───────────────────────────────
        _t_stage = time.perf_counter()
        if _is_excluded(ctx, *(url_info or (None, None)), row.item_name):
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=None,
                match_status="excluded",
                matched_by="auto",
                match_source="exclude_reuse",
            ))
            if len(results) >= BATCH:
                db.bulk_save_objects(results)
                if commit:
                    db.commit()
                else:
                    db.flush()
                if progress_cb:
                    progress_cb(i + 1, total, matched_count)
                results = []
            _acc("s01", _t_stage)
            continue
        _acc("s01", _t_stage)

        # ── S0.2: 历史库精确匹配 ─────────────────────────────────
        _t_stage = time.perf_counter()
        hist_hit = _history_lookup(db, row, ctx)
        if hist_hit:
            historical_model_id = hist_hit.model_id if hist_hit.model_id in valid_model_ids else None
            historical_status = "matched" if historical_model_id else "pending"
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=historical_model_id,
                match_status=historical_status,
                matched_by="auto",
                match_source="historical",
                brand_identified=1,
            ))
            if historical_model_id:
                matched_count += 1
            if len(results) >= BATCH:
                db.bulk_save_objects(results)
                if commit:
                    db.commit()
                else:
                    db.flush()
                if progress_cb:
                    progress_cb(i + 1, total, matched_count)
                results = []
            continue  # 跳过 S0.5 / S1-S4
        _acc("hist", _t_stage)

        # ── S0.5: 显式规则匹配 ─────────────────────────────────────
        _t_stage = time.perf_counter()
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
                if commit:
                    db.commit()
                else:
                    db.flush()
                if progress_cb:
                    progress_cb(i + 1, total, matched_count)
                results = []
            _acc("s05", _t_stage)
            continue  # 跳过 S1-S4
        _acc("s05", _t_stage)

        # ── S1-S4 文本匹配 ─────────────────────────────────────
        _t_stage = time.perf_counter()
        best_model, match_source, brand_identified, row_candidates = _match_text_stages(
            row, item_upper, url_brand_hint, ctx, stage_time=stage_time,
        )
        _acc("s14", _t_stage)

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
            if commit:
                db.commit()
            else:
                db.flush()
            if progress_cb:
                progress_cb(i + 1, total, matched_count)
            results = []

    if results:
        db.bulk_save_objects(results)
        if commit:
            db.commit()
        else:
            db.flush()
    _t4 = time.perf_counter()

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
            if commit:
                db.commit()
            else:
                db.flush()

    # ── 恢复重跑前暂存的人工扩展字段值 ─────────────────────────────
    if extra_value_snapshot:
        if commit:
            db.commit()
        else:
            db.flush()
        new_mr_by_raw = {
            raw_id: mr_id
            for raw_id, mr_id in db.query(MatchResult.raw_data_id, MatchResult.id)
            .filter(MatchResult.clean_job_id == clean_job_id)
            .all()
        }
        restored = []
        for raw_id, values in extra_value_snapshot.items():
            mr_id = new_mr_by_raw.get(raw_id)
            if mr_id is None:
                continue
            for field_key, field_value in values.items():
                restored.append(MatchResultExtraValue(
                    match_result_id=mr_id,
                    field_key=field_key,
                    field_value=field_value,
                    source="manual",
                ))
        if restored:
            db.bulk_save_objects(restored)
            if commit:
                db.commit()
            else:
                db.flush()

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
        run_attribute_matching(db, matched_result_ids, commit=commit)
        if commit:
            try:
                audit_price(db, matched_result_ids, commit=commit)
            except Exception:
                logger.exception("Price audit failed after matching clean_job_id=%s", clean_job_id)
                db.rollback()
        else:
            audit_price(db, matched_result_ids, commit=commit)

    logger.info(
        "run_match job=%s total=%d matched=%d ignored=%d old=%.1fs ctx=%.1fs load=%.1fs hist=%.1fs loop=%.1fs cand=%.1fs total=%.1fs s0=%.1fs s01=%.1fs s0_2=%.1fs s05=%.1fs s14=%.1fs(s1=%.1fs s2=%.1fs s3=%.1fs s4=%.1fs)",
        clean_job_id, total, matched_count, ignored_count,
        _t1 - _t0, _t2 - _t1, _t3 - _t2, _t3b - _t3, _t4 - _t3b, time.perf_counter() - _t4, time.perf_counter() - _t0,
        stage_time.get("s0", 0.0), stage_time.get("s01", 0.0), stage_time.get("hist", 0.0),
        stage_time.get("s05", 0.0), stage_time.get("s14", 0.0),
        stage_time.get("s1", 0.0), stage_time.get("s2", 0.0), stage_time.get("s3", 0.0), stage_time.get("s4", 0.0),
    )
    return {
        "total": total,
        "matched": matched_count,
        "ignored": ignored_count,
        "pending": total - matched_count - ignored_count,
    }


def run_match_for_result(
    db: Session,
    match_result_id: int,
    commit: bool = True,
) -> MatchResult:
    """按 match_result 当前 clean_job 品类跑一次单条匹配，就地更新 match_status/model_id/
    match_source/matched_by/brand_identified 及关联候选。适用于「转移到其他任务后重跑」等场景。

    调用方需保证：
      - match_result 状态已重置为 pending；
      - 旧的 MatchResultCandidate / MatchResultAttr 已清空（本函数不再删除）。
    """
    mr = db.query(MatchResult).filter(MatchResult.id == match_result_id).first()
    if not mr:
        raise ValueError(f"match_result {match_result_id} 不存在")

    raw = db.query(RawDataRecord).filter(RawDataRecord.id == mr.raw_data_id).first()
    if not raw:
        # 找不到原始记录，保持 pending
        mr.match_status = "pending"
        mr.model_id = None
        mr.match_source = None
        if commit:
            db.commit()
        return mr

    clean_job = db.query(CleanJobRecord).filter(CleanJobRecord.id == mr.clean_job_id).first()
    job_category_code = None
    if clean_job:
        job_category_code = clean_job.category_code or clean_job.dispatch_category_code

    ctx = _load_match_context(db, job_category_code)

    item_upper = _norm(raw.item_name)

    # ── S0: URL 精确匹配 ─────────────────────────────────────
    url_info = extract_item_id(raw.item_url) if raw.item_url else None
    url_brand_hint: str | None = None
    if url_info:
        platform, item_id = url_info
        url_model_id = ctx.url_map.get((platform, item_id))
        if url_model_id:
            mr.model_id = url_model_id
            mr.match_status = "url_matched"
            mr.matched_by = "auto"
            mr.match_source = "s0"
            mr.brand_identified = 1
            if commit:
                db.commit()
            return mr
        url_brand_hint = ctx.url_brand_map.get((platform, item_id))

    # ── S0.1: 人工排除沉淀库沿用 ───────────────────────────────
    if _is_excluded(ctx, *(url_info or (None, None)), raw.item_name):
        mr.model_id = None
        mr.match_status = "excluded"
        mr.matched_by = "auto"
        mr.match_source = "exclude_reuse"
        mr.brand_identified = 0
        if commit:
            db.commit()
        return mr

    # ── S0.2: 历史库精确匹配 ─────────────────────────────────
    hist_hit = _history_lookup(db, raw, ctx)
    if hist_hit:
        historical_model_id = hist_hit.model_id if hist_hit.model_id in ctx.valid_model_ids else None
        mr.model_id = historical_model_id
        mr.match_status = "matched" if historical_model_id else "pending"
        mr.matched_by = "auto"
        mr.match_source = "historical"
        mr.brand_identified = 1
        if commit:
            db.commit()
        return mr

    # ── S0.5: 显式规则匹配 ───────────────────────────────────
    s05_model_id: int | None = None
    for rule in ctx.explicit_rules:
        kw = rule.keyword.upper()
        if rule.match_type == "exact":
            if item_upper == kw:
                s05_model_id = rule.model_id
                break
        else:
            if kw in item_upper:
                s05_model_id = rule.model_id
                break

    if s05_model_id is not None:
        mr.model_id = s05_model_id
        mr.match_status = "matched"
        mr.matched_by = "auto"
        mr.match_source = "s0.5"
        mr.brand_identified = 1
        if commit:
            db.commit()
        return mr

    # ── S1-S4 文本匹配 ───────────────────────────────────────
    best_model, match_source, brand_identified, row_candidates = _match_text_stages(
        raw, item_upper, url_brand_hint, ctx,
    )

    if row_candidates:
        seen: dict[int, tuple] = {}
        for model, score, source in row_candidates:
            if model.id not in seen or score > seen[model.id][1]:
                seen[model.id] = (model, score, source)
        sorted_cands = sorted(seen.values(), key=lambda x: -x[1])[:5]
        for rank, (model, score, source) in enumerate(sorted_cands, start=1):
            db.add(MatchResultCandidate(
                match_result_id=mr.id,
                model_id=model.id,
                match_source=source,
                score=score,
                rank=rank,
            ))

    if best_model:
        # url_info 不为 None → URL存在但不在映射表，需人工审核
        mr.match_status = "text_only" if url_info else "matched"
        mr.model_id = best_model.id
        mr.match_source = match_source
        mr.brand_identified = 1 if brand_identified else 0
    else:
        mr.match_status = "pending"
        mr.model_id = None
        mr.match_source = None
        mr.brand_identified = 1 if brand_identified else 0

    mr.matched_by = "auto"

    if commit:
        db.commit()
    return mr
