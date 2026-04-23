"""
导出服务：将清洗后的数据按"已处理"格式导出为 Excel 文件。
列顺序与 Soundbar 7-8月已处理 保持一致。
"""
import uuid
from pathlib import Path
from typing import Optional
import pandas as pd
from sqlalchemy.orm import Session
from app.models.schemas import CleanedDataRecord
from app.core.config import settings

# 已处理格式列定义（天猫/淘宝格式，含 Lv1~Lv5）
PROCESSED_COLUMNS = [
    ("platform", "平台"),
    ("month", "月"),
    ("category_lv1", "Lv1类目名称(逐月固定)"),
    ("category_lv2", "Lv2类目名称(逐月固定)"),
    ("category_lv3", "Lv3类目名称(逐月固定)"),
    ("category_lv4", "Lv4类目名称(逐月固定)"),
    ("category_lv5", "Lv5类目名称(逐月固定)"),
    ("item_id", "宝贝ID"),
    ("item_url", "宝贝链接"),
    ("item_name", "宝贝名称"),
    ("item_image", "宝贝图片"),
    ("ref_price", "参考价格"),
    ("brand_raw", "宝贝品牌"),
    ("shop_name", "宝贝店铺名称"),
    ("sales_qty", "销量"),
    ("sales_amount", "销售额"),
    ("price", "价格"),
    ("brand_std", "品牌"),
    ("model_std", "机型"),
]

PLATFORM_NAME_MAP = {
    "JD": "京东",
    "TM": "天猫",
    "TB": "淘宝",
}


def export_clean_job(
    db: Session,
    clean_job_id: int,
    filename_prefix: str = "已处理数据",
    split_by_platform: bool = True,
) -> list[dict]:
    """
    生成导出文件，返回文件列表 [{"filename": ..., "path": ..., "token": ...}]
    """
    records = db.query(CleanedDataRecord).filter(
        CleanedDataRecord.clean_job_id == clean_job_id
    ).all()

    if not records:
        return []

    # 转为 DataFrame
    field_names = [f for f, _ in PROCESSED_COLUMNS]
    rows = []
    for r in records:
        rows.append({f: getattr(r, f, None) for f in field_names})
    df = pd.DataFrame(rows)

    # 重命名为中文列名
    df = df.rename(columns={f: cn for f, cn in PROCESSED_COLUMNS})
    cn_columns = [cn for _, cn in PROCESSED_COLUMNS]
    df = df[cn_columns]

    export_dir = Path(settings.EXPORT_DIR)
    result_files = []

    if split_by_platform:
        platform_groups = df.groupby("平台")
        for platform_val, group_df in platform_groups:
            # 推断平台简称
            plat_code = str(platform_val)
            for code, name in PLATFORM_NAME_MAP.items():
                if name in plat_code:
                    plat_code = name
                    break
            safe_name = f"{filename_prefix} {plat_code}.xlsx"
            token = uuid.uuid4().hex
            file_path = export_dir / f"{token}_{safe_name}"
            group_df.to_excel(file_path, index=False, engine="openpyxl")
            result_files.append({
                "filename": safe_name,
                "token": token,
                "path": str(file_path),
                "rows": len(group_df),
            })
    else:
        safe_name = f"{filename_prefix}.xlsx"
        token = uuid.uuid4().hex
        file_path = export_dir / f"{token}_{safe_name}"
        df.to_excel(file_path, index=False, engine="openpyxl")
        result_files.append({
            "filename": safe_name,
            "token": token,
            "path": str(file_path),
            "rows": len(df),
        })

    return result_files
