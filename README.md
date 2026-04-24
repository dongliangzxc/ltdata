# 洛图数据处理平台

电商数据采集、清洗、型号匹配与报告产出平台，面向咨询公司日常数据分析工作流。

## 功能模块

| 模块 | 说明 |
|------|------|
| **数据上传** | 拖拽上传原始 Excel（京东/天猫/淘宝），自动解析入库并预览 |
| **原始数据** | 分页展示、多维筛选（平台/月份/品牌/关键词） |
| **元数据管理** | 维护商品规格字段定义，支持 Excel 导入预览确认 |
| **型号管理** | 维护品牌型号及规格参数库，支持 Excel 导入预览确认 |
| **数据清洗** | 去重、品牌标准化，清洗结果独立保存可反复执行 |
| **匹配确认** | 自动型号匹配 + 人工确认待匹配条目，实时进度展示，发布到分析库 |
| **查询工作台** | 对已发布数据多维查询并导出 |
| **数据导出** | 异步生成含规格参数的 Excel 报告（按品类分 Sheet），历史记录可重复下载 |

## 技术栈

- **后端**：FastAPI · SQLAlchemy · pandas · MySQL
- **前端**：React · TypeScript · Ant Design · Vite
- **部署**：Docker Compose

## 部署

### 生产环境

```bash
./deploy.sh
```

拉取最新代码、重新构建镜像、启动容器，一步完成。

### 本地开发

```bash
docker compose up -d
```

服务启动后访问：
- 前端：http://localhost:5173
- 后端 API：http://localhost:8000/docs

## 项目结构

```
luotu/
├── backend/          # FastAPI + SQLAlchemy + pandas
│   └── app/
│       ├── api/      # 各业务路由
│       ├── models/   # ORM 模型 + Pydantic Schema
│       ├── services/ # 清洗、匹配、导出核心逻辑
│       └── core/     # 配置、安全、JWT
├── frontend/         # React + TypeScript + Ant Design
│   └── src/
│       ├── pages/    # 各页面组件
│       ├── components/
│       └── services/ # API 调用封装
├── sql/              # 数据库初始化 SQL
├── docs/             # 使用手册
└── deploy.sh         # 一键部署脚本
```

## 默认账号

首次部署自动创建管理员账号：

- 用户名：`admin`
- 密码：`luotu123`
