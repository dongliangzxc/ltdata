# 落土数据处理平台

电商数据采集、清洗与报告产出平台，面向咨询公司日常数据分析工作流。

## 功能

- **数据上传**：拖拽上传原始 Excel（京东/天猫/淘宝），自动解析入库并预览
- **原始数据**：分页展示、多维筛选（平台/月份/品牌）、KPI 汇总
- **数据清洗**：品牌白名单过滤、去重、清洗结果预览
- **数据导出**：按"已处理"格式导出 Excel，支持按平台拆分文件

## 本地启动

### 前置要求

- Docker + Docker Compose

### 一键启动

```bash
docker-compose up -d
```

服务启动后访问：
- 前端：http://localhost:5173
- 后端 API：http://localhost:8000
- API 文档：http://localhost:8000/docs

### 不使用 Docker（开发模式）

**后端**
```bash
cd backend
# 确保 PostgreSQL 已启动并建库
pip install -e .
uvicorn app.main:app --reload --port 8000
```

**前端**
```bash
cd frontend
npm install
npm run dev
```

## 数据格式

### 支持上传的原始数据格式

- `Soundbar 7-9月原始数据 京东.xlsx`
- `Soundbar 7-9月原始数据 天猫.xlsx`
- `Soundbar 7-9月原始数据 淘宝.xlsx`

### 导出格式

与 `Soundbar 7-8月已处理` 格式完全一致，列顺序：
`平台 / 月 / Lv1~Lv5类目 / 宝贝ID / 宝贝链接 / 宝贝名称 / 宝贝图片 / 参考价格 / 宝贝品牌 / 宝贝店铺名称 / 销量 / 销售额 / 价格 / 品牌 / 机型`

## 项目结构

```
luotu/
├── backend/         # FastAPI + SQLAlchemy + pandas
├── frontend/        # React + TypeScript + Ant Design
└── docker-compose.yml
```
