# 数据处理平台 任务计划

- [ ] Task 1: 项目初始化与基础设施搭建
    - 1.1: 创建后端项目结构（backend/），初始化 pyproject.toml，安装 fastapi、uvicorn、sqlalchemy、psycopg2-binary、pandas、openpyxl、python-multipart 依赖
    - 1.2: 创建前端项目结构（frontend/），使用 Vite + React + TypeScript 初始化，安装 antd、axios、ahooks
    - 1.3: 编写 docker-compose.yml，包含 PostgreSQL 15 服务、backend 服务、frontend 服务
    - 1.4: 创建 backend/app/core/config.py，管理数据库 URL、上传目录、CORS 等配置项

- [ ] Task 2: 数据库模型与迁移
    - 2.1: 创建 backend/app/models/database.py，配置 SQLAlchemy engine、SessionLocal、Base
    - 2.2: 创建 backend/app/models/schemas.py，定义 UploadFile、RawData、CleanJob、CleanedData 四张表的 ORM 模型
    - 2.3: 配置 Alembic，生成初始迁移脚本并执行，创建所有表
    - 2.4: 定义 Pydantic 响应模型（RawDataOut、UploadFileOut、CleanJobOut 等）

- [ ] Task 3: 后端 - 文件上传与解析接口
    - 3.1: 创建 backend/app/services/excel_parser.py，实现 parse_raw_excel() 函数，自动识别京东/天猫/淘宝列名差异，统一映射到标准字段
    - 3.2: 创建 backend/app/api/upload.py，实现 POST /api/upload 接口：接收文件、调用解析器、批量写入 raw_data 表，返回文件ID和预览数据
    - 3.3: 实现 GET /api/upload/files 接口，返回上传历史列表（文件名、平台、数据量、状态、时间）
    - 3.4: 实现 DELETE /api/upload/files/{file_id} 接口，级联删除对应原始数据

- [ ] Task 4: 后端 - 原始数据查询接口
    - 4.1: 创建 backend/app/api/rawdata.py，实现 GET /api/rawdata 接口，支持 file_id / platform / month / brand_std / page / page_size 过滤分页
    - 4.2: 实现聚合统计接口 GET /api/rawdata/stats，返回总销量、总销售额、品牌数、型号数
    - 4.3: 实现筛选项枚举接口 GET /api/rawdata/filters，返回可用平台、月份、品牌列表（用于前端下拉选项）

- [ ] Task 5: 后端 - 数据清洗接口
    - 5.1: 创建 backend/app/services/data_cleaner.py，实现核心清洗逻辑：品牌标准化补全、按白名单过滤、去重（同 item_id 同月份保留销量最大记录）
    - 5.2: 创建 backend/app/api/clean.py，实现 POST /api/clean/run 接口：接收 file_ids + rules，创建 CleanJob 记录，执行清洗，写入 cleaned_data 表
    - 5.3: 实现 GET /api/clean/jobs 接口，返回清洗任务历史（输入行数、输出行数、规则、状态）
    - 5.4: 实现 GET /api/clean/jobs/{job_id}/preview 接口，返回清洗结果预览数据（前100行）

- [ ] Task 6: 后端 - 数据导出接口
    - 6.1: 创建 backend/app/services/exporter.py，实现 export_to_excel() 函数：从 cleaned_data 查询数据，按平台分组，用 openpyxl 生成列顺序与"已处理"格式完全一致的 xlsx 文件
    - 6.2: 创建 backend/app/api/export.py，实现 POST /api/export 接口：触发生成文件，返回下载 token
    - 6.3: 实现 GET /api/export/download/{token} 接口，流式返回 xlsx 文件（FileResponse），支持中文文件名

- [ ] Task 7: 后端主入口与路由注册
    - 7.1: 创建 backend/app/main.py，配置 FastAPI 实例、CORS 中间件、注册所有路由（upload / rawdata / clean / export）
    - 7.2: 添加全局异常处理器，统一返回 {"code": xxx, "message": "...", "data": null} 格式
    - 7.3: 创建 uploads/ 目录和 exports/ 目录，确保服务启动时自动创建

- [ ] Task 8: 前端 - 基础布局与路由
    - 8.1: 创建 frontend/src/App.tsx，配置 React Router，定义 /upload、/rawdata、/clean、/export 四个路由
    - 8.2: 创建 frontend/src/components/Layout/index.tsx，实现左侧导航栏（Ant Design Layout + Menu）+ 右侧内容区布局
    - 8.3: 创建 frontend/src/services/api.ts，封装 axios 实例，统一配置 baseURL 和错误拦截

- [ ] Task 9: 前端 - 数据上传页面
    - 9.1: 创建 frontend/src/pages/Upload/index.tsx，实现拖拽上传区域（Upload.Dragger），限制文件类型为 .xlsx/.xls
    - 9.2: 上传成功后展示解析预览表格（前50行，Ant Design Table，支持横向滚动）
    - 9.3: 实现上传历史列表，展示文件名、平台、行数、状态、上传时间，支持删除操作

- [ ] Task 10: 前端 - 原始数据列表页面
    - 10.1: 创建 frontend/src/pages/DataList/index.tsx，顶部展示 KPI 卡片（总销量、总销售额、品牌数、型号数）
    - 10.2: 实现左侧筛选栏（文件选择、平台多选、月份选择、品牌搜索），筛选条件变更时自动刷新表格
    - 10.3: 实现右侧数据表格，支持分页（20条/页）、列排序，固定宝贝名称和品牌列

- [ ] Task 11: 前端 - 数据清洗页面
    - 11.1: 创建 frontend/src/pages/Clean/index.tsx，实现文件多选器（已上传文件列表 Checkbox 选择）
    - 11.2: 实现清洗规则配置表单：品牌白名单（Tag 输入）、去重开关
    - 11.3: 点击"开始清洗"后展示执行结果（输入行数 → 输出行数 对比卡片）+ 清洗任务历史列表
    - 11.4: 实现清洗预览弹窗，展示清洗后数据的前100行

- [ ] Task 12: 前端 - 数据导出页面
    - 12.1: 创建 frontend/src/pages/Export/index.tsx，实现清洗任务选择器（下拉列表，展示任务ID、文件名、输出行数）
    - 12.2: 实现导出配置表单：文件名前缀输入、是否按平台拆分为多文件（Switch）
    - 12.3: 点击"导出"后触发文件下载，展示下载进度和文件列表

- [ ] Task 13: 联调测试与收尾
    - 13.1: 使用 Soundbar 7-9月原始数据（京东/天猫/淘宝）三个文件进行完整流程测试
    - 13.2: 验证导出文件与"Soundbar 7-8月已处理"格式对齐（列顺序、字段名称）
    - 13.3: 完善 README.md，记录本地启动步骤（docker-compose up）
