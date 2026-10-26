# 海外商品名称翻译实现方案

> 日期：2026-10-23
> 状态：已确认，开发中（Azure）
> 关联：`问题记录.md` →「海外商品名称翻译」

## 1. 背景

清洗任务详情 `/match?job_id=248` 中，海外商品名称是德语、日语、西班牙语等原文，业务人员看不懂，影响型号判断。

目标：

1. 在清洗任务详情列表和右侧详情中展示中文翻译。
2. 原文始终保留，翻译只作为辅助信息，不覆盖 `item_name`。
3. 不影响现有匹配、搜索、去重、导出。
4. 控制翻译成本和响应时间，避免每打开一次页面就重复调用翻译服务。

## 2. 总体方案

```text
前端展示中文翻译
  → 调用后端 /api/translation/translate
  → 后端先查 translation_cache
  → 未命中再调用翻译服务
  → 翻译结果写回缓存
  → 返回前端展示
```

核心原则：

- **按需翻译**：只翻译当前页面可见的 20 条，不批量翻译整个任务。
- **缓存优先**：相同商品名称只调用一次翻译服务。
- **原文不覆盖**：数据库里的 `item_name` 不变，翻译只新增缓存表。
- **失败降级**：翻译服务超时/报错时，只显示原文，不阻塞页面。

## 3. 翻译服务选型

后端封装统一的 `TranslationProvider`，通过环境变量切换，避免代码绑定某一家。

可选：

| 方案 | 优点 | 注意 |
|---|---|---|
| Google Cloud Translation | 语种覆盖广，Amazon/Shopee 多语言场景稳定 | 需要 API Key 和费用 |
| Azure Translator | 国内访问相对稳定，支持自动识别语言 | 需要订阅 Key |
| DeepL | 欧洲语言质量好 | 东南亚语种覆盖不如 Google/Azure |
| LLM（如 DeepSeek/OpenAI） | 可结合品牌、型号上下文，翻译更自然 | 速度较慢、成本较高、需要控制并发 |
| 免费公开接口 | 无需 Key | 不稳定、可能被封禁，**不建议生产使用** |

推荐：**Azure Translator 或 Google Cloud Translation**，后端代理调用，Key 只放服务器环境变量。

## 4. 数据结构

新增表 `translation_cache`：

```sql
CREATE TABLE translation_cache (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    source_hash     CHAR(64)    NOT NULL COMMENT '原文 SHA-256',
    source_text     TEXT        NULL COMMENT '原文，便于排查',
    source_lang     VARCHAR(16) NOT NULL DEFAULT 'auto',
    target_lang     VARCHAR(16) NOT NULL DEFAULT 'zh-CN',
    provider        VARCHAR(32) NOT NULL,
    translated_text TEXT        NOT NULL,
    created_at      DATETIME    DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_translation_cache (source_hash, target_lang, provider),
    KEY idx_translation_cache_hash (source_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品名称翻译缓存';
```

说明：

- `source_hash = sha256(规范化后的原文)`，避免长文本做唯一索引。
- 规范化只做首尾空格、连续空白合并，不改变语义。
- `provider` 参与唯一键，切换翻译服务后可以重新缓存。
- 原文过长（例如超过 2000 字符）时，翻译前截断并记录警告，但缓存仍按完整原文 hash。

## 5. 后端接口

### 5.1 批量翻译

```http
POST /api/translation/translate
```

请求：

```json
{
  "texts": ["Cosori TurboBlaze Smart Air Fryer 6 Qt...", "Levoit Air Purifiers..."],
  "source_lang": "auto",
  "target_lang": "zh-CN"
}
```

响应：

```json
{
  "provider": "azure",
  "translations": [
    {
      "source_hash": "...",
      "source_text": "Cosori TurboBlaze Smart Air Fryer 6 Qt...",
      "translated_text": "Cosori TurboBlaze 智能空气炸锅 6 夸脱..."
    }
  ]
}
```

规则：

- 单次最多 50 条，单条最长 2000 字符。
- 相同文本去重后查询缓存。
- 缓存未命中的文本一次性批量调用翻译服务。
- 翻译服务失败时返回已缓存结果；未命中的返回空字符串，前端只显示原文。
- 接口失败不影响清洗业务。

### 5.2 权限

- 需要登录。
- 建议归入「处理工作台」权限（`processing_workbench`），与 `/api/match` 一致。
- 可在 `API_PERMISSION_PREFIXES` 增加 `/api/translation`。

### 5.3 限流与成本控制

- 单次最多 50 条。
- 同一用户每秒最多 2 次请求（可选）。
- `TRANSLATION_ENABLED=false` 时接口直接返回空翻译，前端隐藏翻译开关。
- 记录每日调用量，便于观察成本。

## 6. 前端设计

### 6.1 位置

第一期：

- `/match` 清洗任务详情左侧复核队列
- 右侧详情「商品名称」
- 干扰项过滤列表

第二期再评估：

- `/match-results` 匹配结果
- 数据调整
- 查询工作台

### 6.2 展示方式

在清洗任务详情顶部增加开关：

```text
显示中文翻译  [开/关]
```

默认关闭，用户打开后记住到 `localStorage`。

展示：

```text
商品名称：
Cosori TurboBlaze Smart Air Fryer 6 Qt, Shake Reminders, 9-in-1, Cream
【中文】Cosori TurboBlaze 智能空气炸锅 6 夸脱，摇匀提醒，9 合 1，奶油色
```

- 原文加粗显示。
- 中文翻译用次要颜色显示，带「中文」标签。
- 原文不替换、不截断。
- 国内商品（`country_code=CN`）不需要翻译。

### 6.3 请求策略

- 打开开关时，收集当前页可见商品名称（最多 20 条），调用批量翻译接口。
- 翻页时只翻译新页面的名称。
- 右侧详情如果未命中当前页缓存，单独请求该条名称。
- 前端维护 `Map<原文, 译文>`，同一页面不重复请求。
- 翻译中显示 `翻译中…`；失败显示原文，不弹错误。

### 6.4 搜索与匹配

- 搜索仍使用原文 `item_name`，不使用译文。
- 匹配、导出、去重逻辑完全不变。
- 不新增 `raw_data.item_name_zh` 字段，避免大表写入。

## 7. 后端实现结构

```text
backend/app/services/translation/
  __init__.py
  base.py          # TranslationProvider 接口
  azure.py         # Azure Translator
  google.py        # Google Cloud Translation
  cache.py         # 缓存读写
  service.py       # 统一入口：缓存 → provider → 回写缓存
backend/app/api/translation_api.py
```

环境变量：

```env
TRANSLATION_ENABLED=true
TRANSLATION_PROVIDER=azure
TRANSLATION_TARGET_LANG=zh-CN
AZURE_TRANSLATOR_KEY=...
AZURE_TRANSLATOR_REGION=...
AZURE_TRANSLATOR_ENDPOINT=https://api.cognitive.microsofttranslator.com
```

部署时在服务器项目根目录 `.env` 增加以上变量，并确保 `TRANSLATION_ENABLED=true`。未配置 Key 时翻译开关不会显示。

或：

```env
TRANSLATION_PROVIDER=google
GOOGLE_TRANSLATE_API_KEY=...
```

## 8. 异常与降级

| 场景 | 行为 |
|---|---|
| 未配置翻译服务 | 开关隐藏或不可用，页面正常显示原文 |
| 翻译接口超时 | 返回已缓存结果，未命中返回空，前端显示原文 |
| 文本超长 | 截断后翻译，前端可提示「原文过长，翻译可能不完整」 |
| 翻译服务限流 | 返回空翻译，不阻塞页面 |
| 缓存写入失败 | 只返回本次翻译结果，不影响页面 |

## 9. 测试

后端：

- 缓存命中：相同文本第二次请求不调用 provider。
- 批量去重：同一请求里重复文本只翻译一次。
- provider 失败：返回空翻译，不抛 500。
- 超长文本截断。
- 权限校验。

前端：

- 开关关闭时不发起翻译请求。
- 打开后只翻译当前页。
- 翻页后翻译新页。
- 翻译失败仍显示原文。
- 国内商品不发翻译请求。

## 10. 上线步骤

1. 确认翻译服务商和 API Key。
2. 新增 `translation_cache` 迁移。
3. 实现 provider + 缓存 + 批量接口。
4. 前端加开关和译文展示。
5. 配置环境变量并部署。
6. 用 `/match?job_id=248` 验证德语/日语/西班牙语商品名称。

## 11. 待确认

| # | 问题 | 默认方案 | 状态 |
|---|---|---|---|
| 1 | 使用哪家翻译服务？ | Azure Translator 或 Google Cloud Translation | ⏳ |
| 2 | 是否允许把商品名称发送给第三方翻译服务？ | 需要业务确认数据合规 | ⏳ |
| 3 | 默认是否打开「显示中文翻译」？ | 默认关闭，用户手动打开并记住 | ⏳ |
| 4 | 第一期范围只做清洗任务详情吗？ | 是，匹配结果/看板后续再做 | ⏳ |
| 5 | 是否只翻译海外商品？ | 是，`country_code=CN` 不翻译 | ⏳ |
| 6 | 译文是否需要人工纠错/编辑？ | 第一期不做，只展示 | ⏳ |
| 7 | 单次批量上限 50 条、单条 2000 字符是否合适？ | 是 | ⏳ |
