# RDS MySQL 迁移方案（洛图数据平台）

> 日期：2026-10-29
> 触发原因：2026-10-28 17:00 起 ECS 系统盘被写满，22:59 机器卡死，10-29 11:22 重启后释放约 35G 临时数据。
> 目标：把 MySQL 从 ECS 自建容器迁到阿里云 RDS，消除「临时表/binlog 撑爆系统盘」的风险，并顺带解决备份、HA、监控缺失问题。

---

## 1. 现状盘点

| 项 | 当前值 |
|---|---|
| ECS 实例 | `i-2ze064n82hdriwkznxku`，地域 `cn-beijing`，可用区 `cn-beijing-f` |
| ECS 规格 | 4 vCPU / 7.3G 内存 / 100G ESSD 系统盘 |
| ECS 私网 IP | `172.29.83.181` |
| VPC / vSwitch | `vpc-2zekiu08eoizzj368jxe1` / `vsw-2ze0hh6zvm0z68glc1k1s` |
| MySQL | 8.0.27，Docker 容器 `ltdata-mysql-1`，单节点无 HA |
| 数据目录 | `/data/luotu/mysql`（41G，其中 binlog 22G） |
| 数据库 | `luotu` 15.37G / 49 张表；`luotu_analytics` 0.11G / 2 张表 |
| 存储引擎 | 全部 InnoDB |
| 字符集 | `utf8mb4` / `utf8mb4_0900_ai_ci` |
| 时区 | `SYSTEM` = **UTC**（`now()` 返回 UTC） |
| buffer pool | 仅 **128M**（偏小，是慢查询原因之一） |
| `max_allowed_packet` | 实际 **64M**（启动参数写的是 512M，但未生效，迁移时需核对） |
| binlog | `ROW`，保留 30 天，单文件最大 1G（但单个大事务不切分，出现过 11G 文件） |
| 触发器 / 存储过程 / 事件 | 无 |
| 外键 | 有（约 20+ 个） |
| 无主键表 | 5 张，均为 `*_bak_*_20261013` 备份表（合计约 11MB） |
| 备份 | 无自动备份 |
| 监控 | 无数据库层监控 |

---

## 2. 目标架构

```
用户 → 宿主机 nginx → frontend 容器 → backend 容器 ──内网──→ RDS MySQL 8.0（主备高可用）
                                          │
                                          └─ /data/luotu/uploads、/data/luotu/exports（继续留在 ECS）
```

- RDS 与 ECS **同地域、同 VPC**，backend 通过 RDS 内网地址访问。
- ECS 上不再运行 MySQL 容器；`/data/luotu/mysql` 保留 7 天后删除（释放 41G）。
- `uploads`（5.2G）和 `exports`（0.5G）短期仍放 ECS，后续可迁 OSS。

---

## 3. 规格选型与成本估算

### 3.1 推荐规格

| 项目 | 推荐值 | 说明 |
|---|---|---|
| 版本 | MySQL **8.0** | 与现网 8.0.27 同大版本 |
| 系列 | **高可用系列（主备）** | 生产必须，自动故障切换 |
| 产品类型 | 标准版（或倚天版，性价比更高） | 倚天版更便宜，需确认可用区支持 |
| 规格 | **4核8G**（预算紧可用 2核4G） | 现网 ECS 为 4C，4C8G 可把 buffer pool 提到约 5–6G，明显改善 `raw_data` 聚合查询 |
| 存储 | **100G ESSD PL1**，开启自动扩容 | 当前逻辑数据 15.5G，预留增长 + binlog |
| 网络 | 专有网络，同 VPC | 内网低延迟、免公网流量费 |
| 备份 | 自动备份 7 天 + binlog 备份 | RDS 自带 |

### 3.2 费用估算（以控制台实时价格为准）

| 方案 | 规格 | 存储 | 参考年费 | 折合月费 |
|---|---|---|---|---|
| 经济型 | 高可用 2核4G | 100G ESSD | 约 ¥4,000–6,000 | 约 ¥350–500 |
| **推荐** | 高可用 4核8G | 100G ESSD | 约 ¥9,000–12,000 | 约 ¥750–1,000 |
| 省钱版 | 基础系列 2核4G（单节点，不推荐生产） | 100G | 约 ¥3,800 | 约 ¥320 |

> - 新用户/活动价可低至 3–6 折（例如高可用 100G 首年新人价约 ¥7,992）。
> - DTS 迁移任务按量计费，本次数据量约 15.5G，费用通常在几十元以内；也可用 `mysqldump` 免费迁移。
> - 迁移完成后可释放 ECS 上 MySQL 占用的 41G，但 **ECS 本身不降配**（uploads/docker 仍需空间）。

---

## 4. 迁移前准备

### 4.1 创建 RDS 实例

在阿里云控制台创建 RDS MySQL 8.0：
- 地域：`cn-beijing`，可用区建议 `cn-beijing-f`（与 ECS 同可用区，延迟最低）
- 网络：专有网络，选择 `vpc-2zekiu08eoizzj368jxe1`，交换机 `vsw-2ze0hh6zvm0z68glc1k1s`
- 系列：高可用系列；规格：4核8G；存储：100G ESSD，开启自动扩容
- 购买后记录 **内网地址**（形如 `rm-xxxx.mysql.rds.aliyuncs.com`）和端口 `3306`

### 4.2 参数组配置（关键，必须与现网一致）

创建自定义参数组并设置：

| 参数 | 目标值 | 原因 |
|---|---|---|
| `time_zone` | `+00:00` | 现网 MySQL 为 UTC；不改会导致 `created_at` 等时间整体偏移 8 小时 |
| `character_set_server` | `utf8mb4` | 与现网一致 |
| `collation_server` | `utf8mb4_0900_ai_ci` | 与现网一致 |
| `sql_mode` | `ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION` | 与现网一致 |
| `lower_case_table_names` | `0` | 与现网一致（RDS 创建后不可改，务必创建时确认） |
| `max_allowed_packet` | `134217728`（128M）或 `536870912`（512M） | 现网实际 64M，批量写入可能不够；建议 128M 起 |
| `binlog_expire_logs_seconds` | `604800`（7 天） | 避免 binlog 无限增长；现网 30 天占 22G |
| `event_scheduler` | `OFF` | 现网无自定义事件 |
| `innodb_buffer_pool_size` | 由 RDS 自动管理 | 无需手动设置 |

> `lower_case_table_names` 只能在创建实例时指定，事后不可修改；现网为 `0`，创建时务必选对。

### 4.3 白名单与账号

1. 白名单加入 ECS 私网 IP：`172.29.83.181/32`（或 VPC 网段 `172.29.0.0/16`）。
2. 创建数据库：
   - `luotu`（utf8mb4 / utf8mb4_0900_ai_ci）
   - `luotu_analytics`（同上）
3. 创建高权限账号 `luotu`，授权 `luotu.*` 和 `luotu_analytics.*` 的 **ALL PRIVILEGES**（backend 启动时会执行 `alembic upgrade head`，需要 DDL 权限）。
4. 密码使用强密码，写入服务器 `/root/luotu/ltdata/.env`（不要提交 Git）。

### 4.4 网络连通性（当前有个坑）

`docker-compose.prod.yml` 里 MySQL **没有映射端口到宿主机**，DTS 无法直接连到容器内的 3306。三选一：

- **方案 A（推荐，改动最小）**：迁移期间临时给 mysql 容器加端口映射
  ```yaml
  ports:
    - "172.29.83.181:3306:3306"
  ```
  安全组入方向 3306 只放行 DTS 提供的 IP 段（DTS 控制台会给出），迁移完成后立即删除该映射并收回安全组规则。
- **方案 B**：DTS 使用 SSH 隧道，通过 ECS 的 22 端口连接（需 DTS 能访问 ECS 公网/内网 SSH）。
- **方案 C（最省事，但要停机）**：停机窗口内用 `mysqldump` 从容器导出，直接管道导入 RDS，不暴露端口。15.5G 预计导出 + 导入 1–2 小时。

### 4.5 DTS 预检查注意事项

- 源库 `binlog_format=ROW`、`log_bin=ON` 已满足。
- DTS **增量迁移要求表有主键/唯一键**。5 张 `*_bak_*_20261013` 备份表无主键：
  - 建议先与业务确认后 **删除**（它们是 10-13 的临时备份），或
  - 在 DTS 中排除这 5 张表，单独做全量。
- 外键较多：DTS 迁移时会处理，切换后需抽查。
- 无触发器/存储过程/事件，迁移风险低。

---

## 5. 迁移步骤（推荐 DTS 全量 + 增量）

### 5.1 创建 DTS 任务

1. 源库：ECS 上自建 MySQL（`172.29.83.181:3306`），账号 `root` 或具备 `REPLICATION SLAVE`、`REPLICATION CLIENT` 的账号。
2. 目标库：RDS 实例，账号 `luotu`。
3. 迁移对象：`luotu`、`luotu_analytics`（排除 5 张无主键备份表）。
4. 迁移类型：**全量 + 增量**。
5. 启动后等待全量完成，观察增量延迟（应接近 0）。

### 5.2 停机切换（建议安排在低峰，预计 10–30 分钟）

1. 通知停服，执行：
   ```bash
   cd /root/luotu/ltdata
   docker compose -f docker-compose.prod.yml stop backend
   ```
2. 等待 DTS 增量延迟归零，确认无新写入。
3. 校验数据：
   ```sql
   -- 在 RDS 上执行，与源库对比
   SELECT COUNT(*) FROM raw_data;
   SELECT COUNT(*) FROM dispatch_items;
   SELECT COUNT(*) FROM match_results;
   SELECT * FROM alembic_version;
   ```
4. 切换连接串（见第 6 节），重新部署/启动 backend。
5. 冒烟测试：登录、列表、匹配页、导出、上传各跑一遍。
6. 观察 30 分钟无异常后恢复对外。

### 5.3 回滚方案

- 切换前：直接停止 DTS，放弃迁移即可，现网无影响。
- 切换后 7 天内：`/data/luotu/mysql` 数据目录**不要删**。若 RDS 异常：
  1. 停 backend；
  2. 把 `.env` 的 `DATABASE_URL` 改回 `mysql` 容器地址；
  3. `git revert` 本次 compose 改动（或恢复备份的 compose 文件）；
  4. `docker compose -f docker-compose.prod.yml up -d`。
- 注意：切换后写入 RDS 的新数据不会自动回流本地库，回滚会丢失这段数据，因此切换窗口要短、验证要快。

---

## 6. 代码与配置改动（遵守「本地改 → Git → 服务器拉取」）

> 按 `CLAUDE.md` 规范：不得直接在服务器改业务代码。以下改动在本地完成、提交推送后，服务器 `git pull` 再部署。

### 6.1 `docker-compose.prod.yml`

- 删除 `mysql` 服务（或保留但不再启动，建议删除以免误启动）。
- backend 的 `depends_on: mysql` 删除。
- `DATABASE_URL` / `ANALYTICS_DATABASE_URL` 改为从环境变量读取，例如：

```yaml
  backend:
    environment:
      DATABASE_URL: ${DATABASE_URL:?DATABASE_URL is required}
      ANALYTICS_DATABASE_URL: ${ANALYTICS_DATABASE_URL:?ANALYTICS_DATABASE_URL is required}
      # 其余不变
```

### 6.2 服务器 `/root/luotu/ltdata/.env`（不提交 Git）

```dotenv
DATABASE_URL=mysql+pymysql://luotu:<强密码>@rm-xxxx.mysql.rds.aliyuncs.com:3306/luotu
ANALYTICS_DATABASE_URL=mysql+pymysql://luotu:<强密码>@rm-xxxx.mysql.rds.aliyuncs.com:3306/luotu_analytics
```

> 需确认 `.env` 在 `.gitignore` 中；不要用 `git add -f`。

### 6.3 部署

```bash
cd /root/luotu/ltdata
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec -T backend alembic current
```

---

## 7. 迁移后清理（释放约 46G）

1. 观察 7 天，确认 RDS 稳定。
2. 停止并删除本地 MySQL 容器：
   ```bash
   docker compose -f docker-compose.prod.yml rm -sf mysql
   ```
3. 删除本地数据目录（**确认备份/回滚期已过**）：
   ```bash
   rm -rf /data/luotu/mysql   # 释放约 41G
   ```
4. 清理 Docker 构建缓存：
   ```bash
   docker builder prune -f    # 释放约 4.7G
   ```
5. 清理旧上传文件（需业务确认）：`/data/luotu/uploads` 中 9–10 月的 CSV 约 5.2G，可归档到 OSS 后删除。
6. 配置 Docker 日志轮转，避免单个 json 日志无限增长（当前 mysql 日志已 521M）：
   `/etc/docker/daemon.json`
   ```json
   {
     "log-driver": "json-file",
     "log-opts": { "max-size": "100m", "max-file": "3" }
   }
   ```
   修改后 `systemctl restart docker`（需安排窗口）。
7. 确认 nginx 日志已配置 logrotate（`/var/log/nginx` 当前约 301M）。

---

## 8. 风险清单

| 风险 | 影响 | 应对 |
|---|---|---|
| `time_zone` 不一致 | 时间字段整体偏移 8 小时 | 参数组强制 `+00:00`，切换后抽查 `created_at` |
| `lower_case_table_names` 不一致 | 表名大小写问题，且不可修改 | 创建实例时选 `0` |
| `max_allowed_packet` 过小 | 批量写入报错 | 设为 128M/512M，压测一次大导入 |
| DTS 增量不支持无主键表 | 增量同步失败 | 迁移前删除/排除 5 张备份表 |
| 迁移期间暴露 3306 | 安全风险 | 安全组只放行 DTS IP 段，迁移后立即收回 |
| RDS 存储/binlog 再次写满 | 数据库不可用 | 开自动扩容 + binlog 保留 7 天 + 存储告警 |
| 切换后回滚丢数据 | 短窗口内新数据丢失 | 停机窗口尽量短，先验证再放量 |
| backend 启动执行 alembic | 权限不足导致启动失败 | RDS 账号授予 DDL 权限，切换前 `alembic current` 确认到 head |

---

## 9. 验收清单

- [ ] RDS 实例创建完成，同 VPC 内网可连通
- [ ] 参数组：`time_zone=+00:00`、字符集/collation/sql_mode/lower_case_table_names 与现网一致
- [ ] `luotu`、`luotu_analytics` 两个库数据完整，关键表行数一致
- [ ] `alembic_version` 与迁移前一致
- [ ] backend 能正常启动，`alembic current` 显示 head
- [ ] 登录、匹配复核、批量确认、导出、上传功能冒烟通过
- [ ] 时间字段无 8 小时偏移
- [ ] RDS 自动备份、binlog 保留、存储自动扩容、监控告警已开启
- [ ] 本地 MySQL 容器已停用，`/data/luotu/mysql` 已按计划清理
- [ ] ECS 磁盘使用率回落到 30% 以下，并配置 80%/90% 告警
