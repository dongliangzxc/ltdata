# 洛图数据处理平台 - 项目记忆
> 最后更新：2026-06-04（更新生产服务器迁移目标）

## 协作偏好
- [部署必须经过本地 main](feedback_deploy_from_local_main.md) — 不要从 worktree 直接推远端 main，避免用户本地 deploy.sh non-fast-forward。

## 项目概览
- **类型**: 数据处理平台 (FastAPI + React + MySQL + Docker)
- **路径**: /Users/dongliang04/workspace/gitProject/luotu
- **启动**: docker compose up（开发模式，volume 挂载热重载）

## 生产部署（阿里云服务器）
- **服务器 IP**: 39.107.251.184
- **SSH**: root@39.107.251.184（密码：Runto@20260606）
- **旧服务器 / 迁移来源**: root@47.94.230.225（密钥认证，无法用密码直接 SSH）
- **项目目录**: /root/luotu/ltdata
- **容器名**: ltdata-backend-1 / ltdata-mysql-1 / ltdata-frontend-1
- **平台 URL**: http://39.107.251.184
- **平台账号**: admin / luotu123
- **MySQL 用户**: luotu / luotu123；root 密码: luotu123
- 服务器无 Docker Desktop，内存有限，**不能在容器内跑 npm build**（SIGKILL）
- 方案：宿主机先 `npm run build`，Dockerfile.prod 只做 `COPY dist/ → nginx`
- 部署命令：`bash deploy.sh`（自动 git pull → npm build → docker compose build）
- 服务器需要安装 Node 20（用 fnm：`fnm install 20 && fnm use 20`）
- API 调用方式：先 POST /api/auth/login 获取 token，再带 Authorization: Bearer {token}

## 架构
- [历史库与 URL 映射库职责](project_historical_url_mapping_roles.md) — 历史库进分析库；URL 映射库是长期沉淀的纯匹配库。
- **luotu** DB（处理库）：上传/清洗/匹配/发布任务记录 + 规则配置表
- **luotu_analytics** DB（分析库）：published_items + published_item_specs（EAV）
- 同一 MySQL 实例，两个 database

## 关键文件路径
| 层 | 文件 | 说明 |
|---|---|---|
| SQL | sql/init.sql | 全量建表（两个库） |
| 后端 | backend/app/core/config.py | DATABASE_URL + ANALYTICS_DATABASE_URL |
| 后端 | backend/app/models/schemas.py | 所有 luotu ORM（含规则引擎6张表 + HistoricalMapping + ColumnTemplate）+ Pydantic |
| 后端 | backend/app/api/upload_templates_api.py | 列模板 CRUD（GET/POST/PUT/DELETE /api/upload/templates） |
| 后端 | backend/app/api/upload.py | 含两阶段上传：POST /upload/headers + /upload/confirm |
| 后端 | backend/app/services/excel_parser.py | 含 parse_with_mapping()（P9新增，mapping驱动） |
| 后端 | backend/app/models/analytics_db.py | luotu_analytics 引擎/Session + ORM |
| 后端 | backend/app/services/data_cleaner.py | 清洗服务：去重 + 干扰词过滤 + 品牌写法标准化 |
| 后端 | backend/app/services/matcher.py | 匹配引擎：S0(URL) → S0.2(历史库) → S0.5(显式规则) → S1-S4(算法) |
| 后端 | backend/app/services/publisher.py | 发布服务（luotu → luotu_analytics） |
| 后端 | backend/app/services/exporter.py | Excel 导出（按品类分 Sheet，动态规格列） |
| 后端 | backend/app/api/rules_api.py | 规则管理 CRUD（噪声词/品牌别名/匹配规则/过滤存档/属性规则） |
| 后端 | backend/app/api/match_api.py | 匹配 CRUD API（含 brand_identified 过滤、attr_count、missing-attrs） |
| 后端 | backend/app/api/historical_api.py | 历史库 CRUD（import/batches/mappings，挂载 /api/historical） |
| 后端 | backend/app/services/attribute_matcher.py | 属性关键词匹配服务（型号确认后触发） |
| 前端 | frontend/src/services/api.ts | 所有 API 函数 |
| 前端 | frontend/src/pages/Rules/index.tsx | 规则管理页（5 Tab：干扰词/品牌写法/匹配规则/过滤存档/属性规则） |
| 前端 | frontend/src/pages/Match/index.tsx | 匹配确认页（含「未识别品牌」「未补属性」Tab，来源列） |
| 前端 | frontend/src/pages/Historical/index.tsx | 历史库页（Tab1: 导入对照表 / Tab2: 映射管理） |

## 规则引擎表（Phase 1+2 新增，luotu DB）
- `noise_words`：干扰词库
- `filtered_items`：干扰项存档（可恢复）
- `brand_aliases`：品牌写法→标准码映射
- `match_rules`：S0.5 显式匹配规则（keyword → model_id，按 priority 执行）
- `attr_rules`：属性关键词规则（keyword → attr_name/attr_value，支持全局/品类）
- `match_result_attrs`：属性标注结果（match_result_id → attr_name/attr_value）

## 列模板上传（P9，已完成）
- `column_templates` 表：name, mapping(JSON), ignore_columns(JSON), col_fingerprint(MD5), is_builtin，UNIQUE(name)
- `upload_files.template_id`：记录本次使用的模板
- `raw_data.extra_data`：未映射列存入 JSON 字段（P9 起正式填充）
- Alembic: p9a1b2c3d4e5（down_revision = p8a1b2c3d4e5）
- 两阶段流程：POST /upload/headers → 前端确认映射 → POST /upload/confirm
- 模板匹配：精确 col_fingerprint 优先，否则 Jaccard 相似度
- 内置模板：京东月报（jd）、天猫/淘宝月报（tmall），is_builtin=1 不可删


- `historical_mappings`：历史对照表（platform+item_id → model_id），UNIQUE(platform,item_id)，import_batch 支持批量删除
- Alembic: f6a7b8c9d0e1（down_revision = e5f6a7b8c9d0）

## match_source 枚举值
`s0` / `s0.2` / `s0.5` / `historical` / `s1` / `s2` / `s3` / `s4` / `manual`

## match_status 生命周期
pending → matched(auto/s0/s0.2/s0.5) / confirmed(manual) / excluded(manual)

## Docker MySQL 用户
- user: luotu / pass: luotu123 / root pass: luotu123

## 规则引擎三期路线图
- **第一期（已完成）**：数据清洗 规则1-3（干扰词库、品牌写法库、S0.5显式匹配规则）
- **第二期（已完成）**：数据清洗 规则4（属性关键词匹配）+ 结果5（未匹配汇总页面）
  - 新增：`attr_rules` 表 + `match_result_attrs` 表（Alembic: e5f6a7b8c9d0）
  - 新增：`attribute_matcher.py` 服务（含8个单测）
  - 新增：`/rules` 页面 Tab5「属性规则」+ `/match` 页面「未补属性」Tab
  - publisher 合并 match_result_attrs 作为条目级属性来源
- **第三期（进行中）**：
  - **历史库匹配（已完成）**：historical_mappings 表 + S0.2 阶段 + 历史库页面 + 匹配来源标签
  - **待实现**：标记/取标/标记转移、量价审核（4月滑动窗口+建议价）、数据调整（系数+改前改后对比）、抖快数据支持+系数配置