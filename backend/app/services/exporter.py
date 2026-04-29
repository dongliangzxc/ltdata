"""
导出服务：基于型号匹配结果，按品类分 Sheet 导出。
- 已匹配/已确认的条目 → 按 category_name 分 Sheet，含动态规格列
- 待确认条目 → 单独"待确认" Sheet，无规格列
- 规格列按品类过滤：每个 Sheet 只显示本品类（category_code）的规格列
- 约定：models.category_name 与 metadata_specs.category_code 使用相同的品类码（如 SOUNDBAR）
- 规格值从 model_specs 查询
"""
import uuid
from pathlib import Path
import pandas as pd
from sqlalchemy.orm import Session
from app.models.schemas import (
    MatchResult, RawDataRecord, ModelRecord,
    ModelSpec, MetadataSpec,
)
from app.core.config import settings

# 基础列：字段名 → 中文表头
BASE_COLS = [
    ("platform",      "平台"),
    ("month",         "月"),
    ("category_lv1",  "Lv1类目名称"),
    ("category_lv2",  "Lv2类目名称"),
    ("category_lv3",  "Lv3类目名称"),
    ("category_lv4",  "Lv4类目名称"),
    ("category_lv5",  "Lv5类目名称"),
    ("item_id",       "宝贝ID"),
    ("item_url",      "宝贝链接"),
    ("item_name",     "宝贝名称"),
    ("item_image",    "宝贝图片"),
    ("ref_price",     "参考价格"),
    ("brand_raw",     "宝贝品牌"),
    ("shop_name",     "宝贝店铺名称"),
    ("sales_qty",     "销量"),
    ("sales_amount",  "销售额"),
    ("price",         "价格"),
    ("brand_std",     "品牌"),
    ("model_code",    "型号"),
]

BASE_FIELD_NAMES = [f for f, _ in BASE_COLS]
BASE_CN_NAMES    = [cn for _, cn in BASE_COLS]


def export_match_job(
    db: Session,
    clean_job_id: int,
    filename_prefix: str = "已处理数据",
) -> list[dict]:
    """
    生成导出文件，返回 [{"filename": ..., "token": ..., "path": ..., "rows": ..., "pending_rows": ...}]
    """
    # ── 1. 预加载所有 metadata_specs，按 category_code 分组 ──────
    all_spec_defs = db.query(MetadataSpec).order_by(MetadataSpec.id).all()
    # { category_code: [spec_name, ...] }
    category_spec_names: dict[str, list[str]] = {}
    for s in all_spec_defs:
        category_spec_names.setdefault(s.category_code, []).append(s.spec_name)

    # ── 2. 查已匹配 / 已确认的条目 ───────────────────────────────
    matched_rows = (
        db.query(MatchResult, RawDataRecord, ModelRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .join(ModelRecord,   MatchResult.model_id     == ModelRecord.id)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.match_status.in_(["matched", "confirmed"]),
        )
        .all()
    )

    # ── 3. 批量拉取规格值 {model_id: {spec_name: spec_value}} ────
    model_ids = list({mr.model_id for mr, _, _ in matched_rows})
    spec_map: dict[int, dict[str, str]] = {}
    if model_ids:
        spec_rows = (
            db.query(ModelSpec)
            .filter(ModelSpec.model_id.in_(model_ids))
            .all()
        )
        for s in spec_rows:
            spec_map.setdefault(s.model_id, {})[s.spec_name] = s.spec_value or ""

    # ── 4. 按 category_name 分组构建数据行 ───────────────────────
    category_data: dict[str, list[dict]] = {}
    for mr, rd, m in matched_rows:
        row: dict = {}
        for field in BASE_FIELD_NAMES:
            if field == "brand_std":
                row[field] = rd.brand_std or rd.brand_raw or ""
            elif field == "model_code":
                row[field] = m.model_code or ""
            else:
                row[field] = getattr(rd, field, None)

        model_specs = spec_map.get(mr.model_id, {})
        cat = m.category_name or "未知品类"
        # 按本品类规格列预填空字符串，再覆盖实际值（保持缺失规格为 "" 而非 NaN）
        # 注意：models.category_name 与 metadata_specs.category_code 使用同一品类码
        for sn in category_spec_names.get(cat, []):
            row[sn] = model_specs.get(sn, "")

        category_data.setdefault(cat, []).append(row)

    # ── 5. 查待确认条目 ──────────────────────────────────────────
    pending_rows = (
        db.query(MatchResult, RawDataRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.match_status == "pending",
        )
        .all()
    )
    pending_data: list[dict] = []
    for mr, rd in pending_rows:
        row = {}
        for field in BASE_FIELD_NAMES:
            if field in ("brand_std", "model_code"):
                row[field] = ""
            else:
                row[field] = getattr(rd, field, None)
        pending_data.append(row)

    # ── 6. 写 Excel（多 Sheet）────────────────────────────────────
    if not category_data and not pending_data:
        return []

    export_dir = Path(settings.EXPORT_DIR)
    token = uuid.uuid4().hex
    safe_name = f"{filename_prefix}.xlsx"
    file_path = export_dir / f"{token}_{safe_name}"

    total_rows = sum(len(v) for v in category_data.values())

    with pd.ExcelWriter(str(file_path), engine="openpyxl") as writer:
        for cat, rows in category_data.items():
            # category_name 与 category_code 同值，直接用 cat 查本品类规格列
            cat_spec_names = category_spec_names.get(cat, [])
            df = pd.DataFrame(rows, columns=BASE_FIELD_NAMES + cat_spec_names)
            df.columns = BASE_CN_NAMES + cat_spec_names
            df.to_excel(writer, sheet_name=cat[:31], index=False)

        if pending_data:
            df_pending = pd.DataFrame(pending_data, columns=BASE_FIELD_NAMES)
            df_pending.columns = BASE_CN_NAMES
            df_pending.to_excel(writer, sheet_name="待确认", index=False)

    return [{
        "filename": safe_name,
        "token": token,
        "path": str(file_path),
        "rows": total_rows,
        "pending_rows": len(pending_data),
    }]
