# URL精确匹配系统 设计文档

## 背景

当前系统仅通过文本子串匹配（S1-S4）来识别商品型号，存在以下问题：

1. **短型号码碰撞**：2-4字符的型号码（如 `V1`、`K2`）会误匹配到标题中的无关子串（如 `AV108` 中的 `V1`）
2. **缩写不统一**：商品标题使用缩写形式（`019KW-K`），而型号库用全称（`HD-019KW-K`），导致文本匹配失败
3. **兼容性描述干扰**：配件标题会列出兼容型号，被误认为是商品本身的型号
4. **无品类过滤**：麦克风、功放等非Soundbar产品因品牌码命中被错误归入Soundbar

数据分析师线下维护了一张 `Soundbar数据模板.xlsx` 的 rawdata sheet（37,078行），包含每个商品URL到品牌+型号的精确映射。这是最权威的真值来源，需要导入系统并用于匹配。

---

## 目标

1. 新建 `item_url_mappings` 参考表，存储 URL→型号 的精确映射
2. 提供一次性从 Excel rawdata sheet 批量导入的功能
3. 提供平台 CRUD 管理界面（增删改查）
4. 匹配引擎增加 S0 步骤（URL精确匹配，优先级最高）
5. 新增 `text_only` 匹配状态（文本命中但URL不在映射表）
6. 前端 Match 页新增 `text_only` 审核 Tab

---

## 数据库设计

### 新表：`item_url_mappings`

```sql
CREATE TABLE item_url_mappings (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    platform    VARCHAR(20)  NOT NULL COMMENT '平台：jd/tmall/taobao/suning',
    item_id     VARCHAR(50)  NOT NULL COMMENT '从URL提取的商品ID',
    model_id    INT          NOT NULL COMMENT 'FK → models.id',
    price       DECIMAL(10,2) DEFAULT NULL COMMENT '单价（来自rawdata单价列）',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY  uq_platform_item (platform, item_id),
    KEY         idx_model_id (model_id)
) COMMENT='商品URL → 型号精确映射表';
```

**URL解析规则：**

| 平台 | URL格式 | item_id提取 |
|---|---|---|
| JD | `https://item.jd.com/{item_id}.html` | 去掉路径前缀和`.html`后缀 |
| TMALL | `https://detail.tmall.com/item.htm?id={item_id}` | 取`id=`参数值 |
| TAOBAO | `https://item.taobao.com/item.htm?id={item_id}` | 取`id=`参数值 |
| SUNING | `https://product.suning.com/{shop_id}/{item_id}.html` | 取最后一段路径 |

### `match_results` 新增 match_status 枚举值

现有枚举：`pending / matched / confirmed / excluded`

新增两个值：

| 值 | 含义 | 发布行为 |
|---|---|---|
| `url_matched` | S0 URL精确命中，最高可信度 | **自动发布** |
| `text_only` | 文本匹配成功但URL不在映射表（或URL冲突） | **待确认**，可独立筛选 |

**match_status 完整生命周期：**

```
初始匹配阶段:
  url_matched   ← S0 命中（直接结束，不跑文本匹配）
  matched       ← S1-S4 文本命中，且 item_id 也在映射表（双重确认）
  text_only     ← S1-S4 文本命中，但 item_id 不在映射表 OR URL映射到不同model
  pending       ← 文本和URL均未命中

人工操作阶段（对 pending / text_only）:
  confirmed     ← 人工选型号确认
  excluded      ← 人工排除
```

**发布条件（更新后）：**
```sql
match_status IN ('url_matched', 'matched', 'confirmed') AND is_disabled = 0
```

---

## 后端设计

### ORM（schemas.py）

新增 `ItemUrlMapping` ORM 类：

```python
class ItemUrlMapping(Base):
    __tablename__ = "item_url_mappings"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    platform   = Column(String(20), nullable=False)
    item_id    = Column(String(50), nullable=False)
    model_id   = Column(Integer, ForeignKey("models.id"), nullable=False)
    price      = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("platform", "item_id"),)
    model = relationship("ModelRecord", lazy="joined")
```

`MatchSummary` 新增字段：
```python
text_only: int = 0
```

### URL 提取工具函数（url_utils.py）

```python
def extract_item_id(url: str) -> tuple[str, str] | None:
    """返回 (platform, item_id) 或 None"""
    # JD: https://item.jd.com/12345.html
    # TMALL: https://detail.tmall.com/item.htm?id=12345
    # TAOBAO: https://item.taobao.com/item.htm?id=12345
    # SUNING: https://product.suning.com/0000000000/12345.html
```

### 匹配引擎变化（matcher.py）

在现有 S1-S4 之前插入 S0：

```python
# S0: URL精确匹配
item_url = row.item_url  # RawDataRecord 新增 item_url 字段（来自宝贝链接）
url_info = extract_item_id(item_url) if item_url else None
if url_info:
    platform, item_id = url_info
    url_mapping = url_map.get((platform, item_id))  # 预加载的内存字典
    if url_mapping:
        # S0 命中，直接使用 URL 映射的 model_id
        results.append(MatchResult(
            ..., model_id=url_mapping.model_id,
            match_status="url_matched", match_source="s0"
        ))
        continue  # 跳过 S1-S4

# S1-S4（现有逻辑不变）
... 文本匹配 ...
if best_model:
    # 检查 item_id 是否在映射表（无论是否冲突）
    has_url_entry = url_info and url_info in url_map
    status = "matched" if has_url_entry else "text_only"
    results.append(MatchResult(..., match_status=status, match_source=match_source))
else:
    results.append(MatchResult(..., match_status="pending"))
```

**性能优化**：匹配开始前将 `item_url_mappings` 全量加载为 `dict[(platform, item_id) → ItemUrlMapping]`，避免逐行查库。

### 发布服务变化（publisher.py）

```python
# 更新发布条件
WHERE mr.clean_job_id = :clean_job_id
  AND mr.match_status IN ('url_matched', 'matched', 'confirmed')
  AND mr.is_disabled = 0
```

### API 端点

新增路由文件 `backend/app/api/url_mapping_api.py`：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/url-mappings/import` | 批量导入 Excel rawdata sheet（multipart/form-data） |
| GET | `/api/url-mappings` | 分页查询（platform/item_id/brand/model_code 关键词搜索） |
| POST | `/api/url-mappings` | 单条新增 |
| PUT | `/api/url-mappings/{id}` | 编辑（model_id / price） |
| DELETE | `/api/url-mappings/{id}` | 删除 |

**导入逻辑**（`/import` 端点）：
1. 解析 Excel rawdata sheet，识别列：`渠道/网址/型号码/品牌码/单价`
2. 逐行提取 `(platform, item_id)`，根据 `品牌码 + 型号码` 查找 `model_id`
3. `INSERT ... ON DUPLICATE KEY UPDATE`（upsert，允许重复导入覆盖）
4. 返回：`{imported: N, skipped: M, errors: [...]}`

---

## 前端设计

### 新增"URL映射管理"页面（`/url-mappings`）

- 搜索栏：按 platform / item_id / 型号码关键词
- 表格列：platform、item_id、品牌码、型号码、价格、操作（编辑/删除）
- 顶部按钮：「导入 Excel」（上传 rawdata sheet）、「新增」

### Match 页面变化

**统计卡片新增"URL待审"：**
```
总条数 | 自动匹配(url) | 自动匹配(文本) | URL待审 | 待确认 | 已确认 | 已排除 | 已禁用 | 匹配率
```

**待确认列表新增 Tab 筛选：**
- Tab 1：`text_only`（URL缺失/冲突，需补录）——默认展示，数量角标
- Tab 2：`pending`（文本也未命中）——原有逻辑不变

`text_only` 行在表格里额外显示一列"URL状态"（`缺失` / `冲突`），便于分析师判断是去补录 URL 映射还是驳回文本匹配结果。

---

## 数据迁移

- 新表 `item_url_mappings`：通过 Alembic 新增
- `RawDataRecord`：确认是否已存储 `宝贝链接` 字段（即 `item_url`）；若无，需通过 Alembic 新增列并在清洗阶段写入
- 现有 `match_results`：不迁移（历史数据保持现有状态，重跑匹配后自动产出新状态）

---

## 不在本次范围内

- TMALL/TAOBAO/SUNING 平台的URL解析（优先实现JD，其他平台预留接口）
- URL映射的批量导出
- 操作日志（谁改了哪条映射）
- 自动发现"URL存在但映射表无记录"的批量提醒
