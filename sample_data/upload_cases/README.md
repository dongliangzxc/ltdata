# 数据上传测试文件与能力检查

检查日期：2026-11-23。本次检查基于前后端代码、真实解析器和隔离数据库中的接口测试，未连接生产数据库，也未向运行中的系统写入测试数据。初次检查新增了样例和自动化测试，后续已修复同名上传覆盖原件的问题，并增加可确认继续的数据质量提示。

所有商品均为合成数据。除一条专门测试前导零的长数字文本 ID 和一条刻意留空的 ID 外，ID 均以 `UPLOAD-TEST-` 开头。共 24 个可选上传文件，含刻意损坏和不合法的数据。请先选正常样例，再单独验证异常文件，不要一次性把整个目录批量入库。

## 当前能力

- 支持拖拽/选择多个文件，逐文件识别表头和国家，统一或单独设置国家及模板。
- 提供列映射、内置/自定义模板、扩展字段和忽略列，支持下载示例。
- 支持 CSV 的 UTF-8 BOM、GBK，以及 XLSX；页面也声明支持 XLS，但项目依赖未包含 `xlrd`，当前本地环境也未安装，不能视为可用。
- 文件名可识别年月、Amazon/Shopee 及别名、已启用的国家、已登记的品类。国内 `jd/tmall/taobao` 暂不在文件名平台识别列表中，仍需映射平台列。
- 后台分块解析，提供进度、任务列表、取消入口、入库结果和最多 50 行预览。
- 按国家 + 商品 ID + 月份 + 平台去重，支持文件内、跨分块和与数据库已有记录去重。正常路径及解析中途失败的回滚已验证。
- 支持历史文件下载、批次打包和删除。提示功能已用生产构建和隔离 API 替身验证浏览器交互；未验证多进程部署、任务取消竞争及 MySQL 并发行为。

## 已复现的问题

初次检查复现了下列 11 项问题。原件覆盖已修复，空值、非法数字和非法月份已按用户要求增加软提示，不做数据质量硬拦截。剩余 7 项保留 `strict=True` 的预期失败测试。修复后测试会报 XPASS，提示去掉对应的 `xfail` 标记。代码行号记录的是初次检查时的位置。

| 优先级 | 问题与影响 | 复现方法 | 代码位置 |
|---|---|---|---|
| 已修复 | 同名上传覆盖历史原件，历史记录下载到后一次的文件 | 依次上传 `same_name/a/data.csv`、`same_name/b/data.csv`，修复后两条记录应分别下载到 A、B | `backend/app/api/upload.py` |
| P1 | 必填映射来源列不存在仍能提交，造成必填数据丢失 | API 中将 `nonexistent` 映射为 `item_name`，删除真实标题列映射，仍返回 202 | `backend/app/api/upload.py:1124` |
| P1 | 忽略的列仍被算作完成必填映射 | 已映射 `item_name` 后再加入 `ignore_columns`，仍返回 202，标题不会导入 | `backend/app/api/upload.py:1124` |
| 已处理（软提示） | 每行必填值为空时缺少提示 | 上传 `invalid/missing_values.csv`，确认入库前展示 3 处空值，用户可返回检查或仍然上传 | `backend/app/services/upload_validation.py` |
| 已处理（软提示） | 非法数字静默变成 NULL | 上传 `invalid/bad_numbers.csv`，先展示原始数值和问题；确认后无法保存的数字以空值入库 | `backend/app/services/upload_validation.py` |
| 已处理（软提示） | 不校验 YYYYMM 的月份范围 | 上传 `invalid/invalid_month.csv`，先提示 `202613`、`202600` 月份无效，仍允许确认入库 | `backend/app/services/upload_validation.py` |
| P1 | 文件名覆盖表内月份和平台，无冲突提示 | 上传 `filename_conflict/202611_amazon_US_conflict.csv`，表内 `202610/shopee` 被写成 `202611/amazon` | `backend/app/api/upload.py:785` |
| P2 | 只有表头的空表显示处理成功 | 上传 `invalid/empty.xlsx`，任务 done、0 行 | `backend/app/api/upload.py:851` |
| P2 | 两列映射同一标准字段未提前拒绝 | `invalid/duplicate_target.csv` 中 `sales_qty` 和 `second_qty` 都映射销量，提交返回 202，后台解析才失败 | `backend/app/api/upload.py:1124` |
| P2 | 大写扩展名被拒绝 | `invalid/uppercase.CSV` 是有效 CSV，表头接口却返回 400 | `backend/app/api/upload.py:1031` |
| P2 | 上传历史年份与真实数据月份可能不一致 | 上传 2026 文件、请求传 `data_year=2025`，历史年份为 2025，数据月份仍为 202610；页面默认年份总会随请求传入，跨年导入容易遇到 | `backend/app/api/upload.py:1113` |

另有代码检查发现的限制，未计入初次检查的 11 项自动化复现：

- XLS 所需的 `xlrd` 既未列入 `backend/pyproject.toml`，也未安装在本地后端虚拟环境。
- XLSX 表头使用第一张表（`import_helper.py:38`），实际数据使用活动表（`excel_parser.py:182`）。首表和活动表不一致时，表头映射可能与实际导入的数据不符。多张工作表不会被全部导入，页面也没有选表入口。
- `MAX_UPLOAD_SIZE_MB` 配置未用于上传接口校验，表头阶段会先把文件完整写到磁盘。
- 原始数据先提交，再移动原件（`upload.py:851`、`:868`）。移动失败可能造成任务显示失败但数据已经入库，需要补偿处理。
- 前端把表头读取阶段的后端详细错误统一显示为“表头读取失败”（`frontend/src/pages/Upload/index.tsx:1109`），不利于判断坏文件、编码或依赖问题。

原件存储隔离和逐行数据质量提示已完成。建议接下来优先处理有效映射校验、文件名冲突提示，再处理格式兼容。

## 本轮修复：同名原件隔离

新上传原件保存到 `UPLOAD_DIR/originals/<唯一存储名>`，上传记录通过新增的 `stored_filename` 字段关联原件。页面显示和下载附件继续使用原文件名。同步上传和两阶段异步上传均已修改，直接下载、后台下载、批次打包均按上传记录读取原件。

旧记录的 `stored_filename` 保持空值，继续读取原来的文件路径。新原件丢失时返回 404，不会误取旧版同名文件。历史上已经被覆盖的原件需要从备份恢复，这次修改无法还原丢失的内容。

部署时需要先执行 `cd backend && alembic upgrade head`（生产容器入口已有此步骤），将数据库升级至 `p79a1b2c3d4e5`。本次未对运行中的数据库执行迁移。

## 本轮增加：可确认继续的数据质量提示

单文件、批量确认入库都会先按当前列映射检查全部数据。发现问题时弹出提示，显示受影响的行数、问题总数，以及行号、原始列、原始值和原因。每份文件最多展示前 50 处问题，统计覆盖全部数据。批量上传会在任何文件入库之前集中展示所有文件的警告。

- 点击“返回检查”：不创建入库任务，保留待处理文件及映射，用户可修改后重试。
- 点击“仍然上传”：按现有入库流程继续，不因这些数据质量问题硬拦截。
- 没有发现问题：不显示警告弹窗，直接提交入库。

缺失内容仍为空值。无法保存的数字（如“十件”“￥99”、小数销量、非有限数字、超出字段范围的金额）以空值入库，不会猜测、截断或自动补成 0。`202613` 这类能保存的整数月份继续按原值保存，但会明确提示月份无效。原文件会单独保留以供核对。

文件名已补齐月份或平台时，不会误报相应字段为空。CSV 行号将带换行的引号字段视为一条记录，Excel 行号保留原工作表的空行位置。

新增只读接口 `POST /api/upload/validate` 接收临时文件 ID、映射和忽略列，返回警告统计及示例。它不会写入商品数据或创建入库任务，也没有新增必须通过校验才能入库的后端限制。本次软提示功能本身不需要额外数据库迁移。

## 如何使用样例

1. 打开“数据管理 → 数据上传”，先上传 `normal/jd.xlsx`。
2. 为该文件选择中国；按下表或 `manifest.json` 完成映射。没有匹配模板时需要手动映射，可保存为测试模板。
3. 检查入库数、跳过数和预览，再到原始数据中搜索 `UPLOAD-TEST-` 核对。
4. 海外文件需要系统已启用美国 US 或新加坡 SG；国家决定金额币种，样例金额按所选国家原币理解。
5. 重复与交叉文件要按指定顺序上传；重复执行整套测试前应清理这些测试上传记录，或使用独立测试库，否则插入/跳过计数会变化。

默认标准列映射为同名字段：`platform`、`month`、`item_id`、`item_name`、`sales_qty`、`sales_amount`、`price`。

| 文件 | 数据行数 | 首次测试的预期结果/观察点 |
|---|---:|---|
| `normal/jd.xlsx` | 3 | 中国，插入 3；含合法零销量/零金额/零价格 |
| `normal/tmall_utf8.csv` | 2 | 中国，插入 2；UTF-8 BOM；“天猫”与 `tmall` 统一 |
| `normal/taobao_gbk.csv` | 2 | 中国，插入 2；GBK 中文；“淘宝”与 `taobao` 统一 |
| `normal/202610_amazon_US_filename.xlsx` | 2 | 美国，插入 2；文件内没有月份/平台列，应从文件名补齐 |
| `normal/shopee.csv` | 2 | 新加坡，插入 2；“虾皮”与 `shopee` 统一 |
| `normal/custom_columns.csv` | 2 | 中国，插入 2；颜色进入扩展字段，内部备注被忽略 |
| `normal/quoted_multiline.csv` | 2 | 插入 2；保留逗号、引号、标题换行、长文本 ID `000001234567890123456789` 和合法零值 |
| `dedup/in_file.csv` | 4 | 插入 3，跳过 1；同 ID 不同月份保留 |
| `dedup/cross_chunk_5002.csv` | 5002 | 插入 5001，跳过 1；第 5001 条重复第 1 条，跨过 5000 行分块边界 |
| `dedup/reimport_a.csv` | 2 | 先上传，插入 2；再次上传插入 0、跳过 2 |
| `dedup/reimport_b.csv` | 2 | A 后上传，插入 1、跳过 1 |
| `same_name/a/data.csv` | 1 | 先上传，插入 1；保留以便之后核对下载内容 |
| `same_name/b/data.csv` | 1 | 后上传，插入 1；修复后 A、B 的下载内容应各自保持正确 |
| `invalid/missing_price.csv` | 1 | 缺少价格列，应在映射/提交阶段阻止，API 返回 422 |
| `invalid/missing_values.csv` | 3 | 提示 3 处空值；“返回检查”不入库，“仍然上传”可插入 3 行 |
| `invalid/bad_numbers.csv` | 2 | 提示 3 处数字异常并展示原值；确认后插入 2 行，非法数字留空 |
| `invalid/fractional_qty.csv` | 1 | 提示销量应为整数；确认后插入 1 行，销量留空 |
| `invalid/invalid_month.csv` | 2 | 提示 2 处月份无效；确认后允许插入 2 行 |
| `invalid/empty.xlsx` | 0 | 理想应提示无数据；当前显示成功、0 行 |
| `invalid/duplicate_target.csv` | 1 | 将 `second_qty` 也映射为销量；理想应提交前拦截，当前后台才失败 |
| `invalid/corrupt.xlsx` | — | 故意损坏的文件，表头阶段返回 422，临时文件应清理 |
| `invalid/uppercase.CSV` | 1 | 内容正确但扩展名大写；当前返回 400 |
| `filename_conflict/202611_amazon_US_conflict.csv` | 1 | 美国；观察表内月份/平台被文件名覆盖 |
| `invalid/multiple_sheets.xlsx` | 每表 1 | 两张数据表，当前只导入第一张；不是完整多表导入样例 |

中文样例映射：

| 原始列 | 标准字段 |
|---|---|
| 平台 / 渠道 | platform |
| 月 / 统计月份 | month |
| 宝贝ID / ASIN / 商品编号 | item_id |
| 宝贝名称 / 产品名称 / 商品标题 | item_name |
| 销量 / 售出件数 | sales_qty |
| 销售额 / 销额 / 成交金额 | sales_amount |
| 价格 / 成交单价 | price |
| 颜色 | 扩展字段（`__ext__`） |
| 内部备注 | 忽略 |

## 自动化验证

在项目根目录运行：

```bash
cd backend
.venv/bin/python -m pytest tests/test_upload_cases.py -q -rx --disable-warnings
```

增加提示后，样例测试结果为 **31 passed，7 xfailed**。预期失败表示已确认且尚未修复的问题，不代表验收通过。去掉预期失败机制可观察原始断言失败：

```bash
.venv/bin/python -m pytest tests/test_upload_cases.py --runxfail -q --disable-warnings
```

本轮还验证了数据质量提示、数据库迁移、原有上传下载功能及清洗补充上传。合跑结果为 **141 passed、7 xfailed、2 xpassed、4 deselected**。`test_upload_storage_migration.py` 覆盖旧记录升级、存储引用保留和降级保护，`test_upload_validation.py` 覆盖数字与月份边界、跨 5000 行分块、50 条示例上限、原始行号和文件名补齐。

```bash
.venv/bin/python -m pytest tests/test_upload_validation.py tests/test_upload_cases.py tests/test_upload_storage_migration.py tests/test_excel_parser.py tests/test_upload_templates.py tests/test_upload_dimension_fields.py tests/test_upload_batch.py tests/test_upload_download.py tests/test_upload_download_jobs.py tests/test_filename_metadata.py tests/test_async_jobs.py tests/test_clean_supplement.py tests/test_auth_downloads.py -k 'not wb_export and not dispatch_export_download_skips_auth_like_other_downloads' -q --disable-warnings
```

排除的 4 项为 3 项工作台导出测试，以及 1 项原有分发导出免登录下载测试。后者当前返回 401，其接口已声明 `Depends(get_current_user)`，旧测试仍预期免登录，未在本次同名文件修复中修改鉴权行为。

前端 TypeScript 检查、生产构建和原有上传下载测试通过。浏览器中验证了单文件返回检查、单文件仍然上传、批量返回检查、批量仍然上传，以及正常文件不弹警告的 5 个流程。浏览器使用实际页面和后端检查服务生成的警告报告，API 请求由隔离替身响应，未向在线系统写入数据。

测试调用真实表头接口、确认接口、解析器、去重和入库逻辑。数据库为临时 SQLite，上传目录为临时目录，后台线程被改为测试中顺序执行；独立进度事务被替换，以避免 SQLite 写锁影响业务验证。因此这里没有验证 MySQL 独立进度事务与真实线程竞争。

已有相关测试初跑结果为 66 passed、2 xpassed、2 failed；两项失败属于 `test_async_jobs.py` 的工作台导出用例，均因收到 401 而失败，与本次新增文件无关。修复前排除 `wb_export` 用例后合跑结果为 82 passed、11 xfailed、2 xpassed、3 deselected。已有的 2 个 xpassed 是年份/区域筛选已经实现但旧测试还保留了预期失败标记。前端上传页现有下载测试也通过（1 passed）。

`manifest.json` 记录每份样例的映射、国家及预期结果。`generate.mjs` 使用 `@oai/artifact-tool` 生成 XLSX，CSV 由合成值生成；GBK 编码使用 Python 标准库。重新生成需要将 `node_modules` 指向已安装的 Artifact Tool 运行时后执行 `node generate.mjs`。
