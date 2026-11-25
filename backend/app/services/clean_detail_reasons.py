"""Explain persisted cleaning decisions without re-running today's rules."""
from app.models.schemas import CleanDuplicateRecord, FilteredItem, MatchResult, ModelRecord


_MATCH_REASONS = {
    "s0": "命中 URL 映射库，采用已保存的商品链接与型号对应关系",
    "historical": "命中历史库中的商品确认结果，复用其型号",
    "s0.2": "命中历史库中的商品确认结果，复用其型号",
    "s0.5": "命中型号匹配规则；具体规则名称和命中词未记录",
    # S1 also accepts brand hints from URL mappings; do not infer which one
    # was used from the current mappings or the raw brand value.
    "s1": "根据品牌线索缩小候选范围，再通过商品名称匹配该品牌下的型号",
    "s2": "从商品名称识别品牌码，再匹配该品牌下的型号",
    "s3": "从商品名称识别品牌名称，再匹配该品牌下的型号",
    "s4": "未识别出品牌，通过商品名称中的长型号码进行兜底匹配",
    "manual": "经人工选择并确认型号",
}


def match_detail_reason(result: MatchResult | None, model: ModelRecord | None) -> str:
    if result is None:
        return "数据已保留，尚无型号匹配结果；请等待匹配完成或检查并补齐。"
    status = result.match_status
    source = result.match_source
    if status == "excluded":
        reason = ("命中同品类的人工排除沉淀记录，自动沿用排除结果；具体命中键未记录"
                  if source == "exclude_reuse" else "已人工排除")
        reason += f"；排除备注：{result.review_note}" if result.review_note else "；具体排除原因未记录"
    elif status == "ignored":
        reason = "已人工忽略，仅在当前任务中不参与后续处理"
        reason += f"；忽略备注：{result.review_note}" if result.review_note else "；具体忽略原因未记录"
    elif status == "disputed":
        reason = f"存在争议，等待复核；争议原因：{result.dispute_reason or result.review_note or '未记录'}"
    elif status == "pending":
        reason = ("尚未识别品牌，未匹配到可用型号，等待人工处理"
                  if result.brand_identified == 0 else "尚未匹配到可用型号，等待人工确认")
        if result.review_note:
            reason += f"；处理备注：{result.review_note}"
    elif status == "invalid_model":
        reason = "原关联型号无效，需重新选择并确认型号"
        if result.review_note:
            reason += f"；处理备注：{result.review_note}"
    else:
        if status == "confirmed":
            reason = "经人工选择并确认型号"
        else:
            reason = _MATCH_REASONS.get(source, "已保存匹配结果，但具体匹配依据未记录")
        if model:
            label = " / ".join(str(value) for value in (model.brand_code, model.series, model.model_code) if value)
            reason += f"；关联型号：{label or '型号名称未记录'}（型号记录 #{model.id}）"
        elif result.model_id is not None:
            reason += f"；关联型号记录 #{result.model_id} 当前已不存在"
        else:
            reason += "；具体型号未记录"
        if status == "text_only":
            reason += "；已找到候选型号，商品链接映射尚待人工确认"
        if result.review_note:
            reason += f"；处理备注：{result.review_note}"
    if result.is_disabled:
        reason += f"；当前结果已禁用：{result.disable_reason or '具体禁用原因未记录'}"
    return reason + "。"


def filter_detail_reason(entry: FilteredItem) -> str:
    if entry.matched_reason and entry.matched_reason.strip():
        return entry.matched_reason
    clues = [value for value in (entry.intervention_rule_name, entry.matched_keyword) if value]
    saved = "、".join(dict.fromkeys(clues))
    return f"已过滤；已保存的规则或关键词：{saved}；完整过滤原因未记录。" if saved else "已过滤；具体过滤原因未记录。"


def duplicate_detail_reason(entry: CleanDuplicateRecord) -> str:
    kept = f"保留原始记录 #{entry.kept_raw_data_id}" if entry.kept_raw_data_id is not None else "保留记录的来源未记录"
    key = entry.dedup_key
    if entry.dedup_basis == "item_id_month_shop" and isinstance(key, dict):
        return f"商品 ID、月份、店铺名称完全相同，按任务清洗顺序去重；{kept}。"
    return f"已作为重复数据剔除；{kept}；具体去重依据未记录。"
