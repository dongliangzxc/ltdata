# P12 — 型号库批量导入 Design Spec

**Goal:** 从品类数据库 Excel（如耳机数据库.xlsx）中提取品牌型号、URL 映射、型号属性，清洗后批量写入 `models`、`model_specs`、`item_url_mappings` 三张表。

**Background:** 产品运营持有各品类的竞品数据库 Excel，格式为：平台、宝贝名称、宝贝链接、销量、销售额、品牌、型号 + N 个属性列。需要将其中有效数据提取为平台的型号库，供后续月报匹配使用。操作为一次性导入，在阿里云服务器上运行脚本完成。

---

## 变更范围

### 1. 新增脚本 `scripts/import_model_db.py`

命令行脚本，接受 Excel 文件路径和品类 code，完成清洗 + 入库。不涉及任何 FastAPI 路由或前端改动。

### 2. 不在本次范围

- 平台 UI 页面
- 对其他品类 Excel 格式的适配（本次只处理耳机数据库格式）
- 对 `historical_mappings` 表的任何改动

---

## 脚本接口

```bash
# 只预览，不写库（dry-run）
python scripts/import_model_db.py 耳机数据库.xlsx --category headphone --dry-run

# 正式入库
python scripts/import_model_db.py 耳机数据库.xlsx --category headphone
```

**参数：**
- 位置参数：Excel 文件路径（相对或绝对）
- `--category`：品类 code，必填，必须已存在于 `categories` 表
- `--dry-run`：仅统计和预览，不执行任何写库操作

---

## 数据清洗规则

### 跳过整行的条件（满足任一即跳过）

| 字段 | 规则 |
|---|---|
| 型号 | 为空 / 纯数字 / 长度 ≤ 2 / 以 `id:` 或 `id=` 开头（不区分大小写） |
| 品牌 | 为空 / 长度 ≤ 2 / 中文字符数 > 8（判定为店铺名而非品牌） |
| 宝贝链接 | 为空 |
| 属性列（第 8 列起） | 全部为空或全部为字符串 `"NULL"`（无实质属性） |

### 品牌标准化

- strip 首尾空格
- 原样使用 Excel 中的品牌字段作为 `brand_code`（如 `EDIFIER/漫步者`）

### 平台标准化

| Excel 值 | 标准化结果 |
|---|---|
| `JD` / `jd` | `jd` |
| `淘宝` / `taobao` | `taobao` |
| `天猫` / `tmall` | `tmall` |
| 其他 | 原样小写 |

### item_id 从链接提取

- **京东**：`https://item.jd.com/{item_id}.html` → 正则提取数字段
- **淘宝/天猫**：`?id={item_id}` → 提取 query param `id`
- 提取失败：该行跳过 URL 映射写入，但 model 仍正常入库；在报告中计数

---

## 入库逻辑

### 去重策略

按 `(品牌, 型号)` 分组处理。同一型号的多行（不同 SKU/颜色）：
- **属性**：取该组第一条属性非空的行
- **URL 映射**：每条有有效链接的行都写一条

### 写入顺序与幂等性

```
1. models          — INSERT IGNORE（brand_code+model_code 唯一约束天然幂等）
2. model_specs     — 先 DELETE WHERE model_id=?，再批量 INSERT（重跑安全）
3. item_url_mappings — INSERT ... ON DUPLICATE KEY UPDATE price=VALUES(price)
```

### 属性列映射（Excel 列名 → spec_name）

| Excel 列 | spec_name |
|---|---|
| 佩戴类型 | wearing_type |
| In-ear Type | inear_type |
| 开放式外观 | open_back |
| Power Type | power_type |
| Bluetooth Version | bluetooth_version |
| Sport | sport |
| Gaming | gaming |
| HIFI | hifi |
| ANC | anc |
| ENC | enc |
| Fast Charging | fast_charging |
| IP Marking | ip_marking |
| Health Monitoring | health_monitoring |
| Touch Screen Monitor | touch_screen |
| 骨传导 | bone_conduction |
| AI | ai |
| AI+功能 | ai_features |

值为 `None`、空字符串、`"NULL"` 的属性列跳过，不写入 `model_specs`。

---

## 输出报告格式

```
=== 型号库导入报告 [dry-run] ===
文件:              耳机数据库.xlsx
品类:              headphone
读取总行数:        938922

─── 过滤（跳过） ───
  型号脏数据:       xxxxxx 行
  品牌脏数据:         xxxx 行
  无链接:             xxxx 行
  无属性:             xxxx 行
有效行:              xxxxx 行
去重后唯一型号:       xxxx 条

─── 入库结果 ───
  models 新增:        xxxx 条
  models 已存在:      xxxx 条
  model_specs 写入:   xxxx 条
  url_mappings 新增:  xxxx 条
  url 提取失败跳过:    xxx 条
```

---

## 依赖

- Python 3.12
- `openpyxl`（项目已有）
- `sqlalchemy`（项目已有，直接复用 `backend/app/models/` 的 ORM 和 DB 连接）
- `python-dotenv`（读取 `backend/.env` 中的 DATABASE_URL）
