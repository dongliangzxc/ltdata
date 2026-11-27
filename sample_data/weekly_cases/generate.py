"""Regenerate isolated manual acceptance files (business month 209901)."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import csv
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent
HEADERS = ["month", "week", "platform", "item_id", "item_name", "sales_qty", "sales_amount", "price", "shop_name"]
MONTH = 209901
SKU = "WEEKLY-ACCEPT-A"


def row(sku, week, qty):
    return [MONTH, week, "jd", sku, "周度验收测试耳机", qty, qty * 100, 100, "周度验收测试店铺"]


def workbook(name, headers, rows):
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    book.active.title = "数据"
    book.active.append(headers)
    for values in rows:
        book.active.append(values)
    book.save(path)


def main():
    base = [row(SKU, week, qty) for week, qty in [(1, 10), ("2", 20), (3.0, 30), (" 4 ", 40), (5, 50)]]
    workbook("01_周度_五周数字和字符串.xlsx", HEADERS, base)
    workbook("02_周度_重复上传.xlsx", HEADERS, base)
    workbook("03_周度_第2周追加.xlsx", HEADERS, [row(SKU, 2, 20), row("WEEKLY-ACCEPT-B", "2", 7)])
    month_headers = [col for col in HEADERS if col != "week"]
    monthly = row(SKU, None, 150)
    workbook("04_月度_同商品.xlsx", month_headers, [[v for i, v in enumerate(monthly) if i != 1]])
    manual = row("WEEKLY-ACCEPT-C", None, 8)
    workbook("05_周度_手动指定第3周.xlsx", month_headers, [[v for i, v in enumerate(manual) if i != 1]])
    supplement_headers = ["item_id", "item_name", "sales_qty", "sales_amount", "price", "shop_name"]
    workbook("06_补充_目标任务继承周期.xlsx", supplement_headers, [
        [SKU, "周度验收测试耳机", 20, 2000, 100, "周度验收测试店铺"],
        ["WEEKLY-ACCEPT-D", "周度验收测试耳机", 9, 900, 100, "周度验收测试店铺"],
    ])
    workbook("07_补充_周次冲突.xlsx", HEADERS, [row("WEEKLY-ACCEPT-CONFLICT", 1, 1)])
    alias_headers = ["周次" if col == "week" else col for col in HEADERS]
    workbook("08_可选_周次列名.xlsx", alias_headers, [row("WEEKLY-ACCEPT-ALIAS", "3", 1)])
    with (ROOT / "09_可选_字符串周次.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerow(row("WEEKLY-ACCEPT-CSV", "1", 1))
    invalid = {"0": 0, "6": 6, "小数": 2.5, "第3周": "第3周", "W03": "W03", "03": "03",
               "文本3.0": "3.0", "空值": None, "布尔值": True, "全角数字": "３"}
    for label, value in invalid.items():
        workbook(f"invalid/周次_{label}.xlsx", HEADERS, [row(f"WEEKLY-ACCEPT-BAD-{label}", value, 1)])
    archive = ROOT / "周度验收测试文件.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file() and (path.suffix in {".xlsx", ".csv"} or path.name == "README.md"):
                bundle.write(path, path.relative_to(ROOT))
    print(f"Generated {len(list(ROOT.rglob('*.xlsx')))} workbooks, 1 CSV and {archive}")


if __name__ == "__main__":
    main()
