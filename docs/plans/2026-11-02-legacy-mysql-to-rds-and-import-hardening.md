# 旧系统 MySQL 迁 RDS + 导入稳定性改造方案

> 日期：2026-11-02
> 背景：2026-11-02 10:32 旧系统（`api.runtotech.com`）导入「儿童智能手表」14 万行 Excel 时，PHPExcel 打满 512MB 内存并连续重试，ECS 云盘读 BPS 冲到 126.71MB/s 上限后整机卡死，11:03 强制重启。
> 目标：把旧系统 MySQL 从 ECS 本地容器迁到阿里云 RDS，并把大文件导入改造成流式、有上限、不可重入，消除同类卡死。
> 非目标：本次不改旧系统业务功能，不重写旧系统页面。

---

## 1. 现状

| 项 | 旧系统（legacy） | 新平台（ltdata） |
|---|---|---|
| 入口 | `api.runtotech.com`（nginx 8081） | `data.runtotech.com`（nginx 8080） |
| 应用 | PHP 7.2.34 + ThinkPHP，`/root/luotu/legacy` | FastAPI + React，`/root/luotu/ltdata` |
| 数据库 | 本机 Docker `luotu-legacy-mysql`（MySQL 5.7.36） | 阿里云 RDS MySQL 8.0.36 |
| 数据位置 | Docker volume `legacy_legacy_mysql_data`，系统盘 | `rm-2ze5mav2awbjyzw3u.mysql.rds.aliyuncs.com` |
| 库名 | `luotu` | `luotu`、`luotu_analytics` |
| 数据量 | 约 108MB（30 张表） | RDS 上，已迁移 |
| 引擎 | 17 张 MyISAM（约 101.6MB）+ 13 张 InnoDB | InnoDB |
| 字符集 | `utf8_general_ci` / `utf8mb4_general_ci` | `utf8mb4` / `utf8mb4_0900_ai_ci` |
| sql_mode | `NO_ENGINE_SUBSTITUTION` | 严格模式（`STRICT_TRANS_TABLES` 等） |
| 时区 | MySQL `SYSTEM`=+08:00；PHP `Asia/Shanghai` | RDS `+00:00` |
| 代码版本 | **未纳入 Git** | 已在 Git |

结论：

1. 旧库体量很小，迁 RDS 成本低、风险可控。
2. 旧库不能导入现有 `luotu` 库（与新平台撞名），必须新建独立 schema，例如 `luotu_legacy`。
3. 只迁库不能根治卡死：PHPExcel 全量读 14 万行仍然发生在 ECS 的 PHP 容器里，必须同步改造导入逻辑。
4. 本地 `luotu-legacy-mysql` 数据保留 7 天作为回滚兜底；新平台遗留的 `ltdata-mysql-1` 也可停掉但保留数据目录。

---

## 2. 目标架构

```
旧系统用户 → api.runtotech.com → legacy-nginx → legacy-php-fpm ──内网──→ RDS luotu_legacy
                                                      │
                                                      └─ 导入文件仍落 ECS /root/luotu/legacy/app/Uploads

新平台用户 → data.runtotech.com → frontend → backend ──内网──→ RDS luotu / luotu_analytics
```

- ECS 上不再承担旧库的 MySQL 内存和磁盘 IO。
- 旧库走 RDS 独立 schema，与 `luotu`、`luotu_analytics` 隔离。
- 旧系统 `uploads` 继续留 ECS，后续再评估 OSS。

---

## 3. 方案要点

### 3.1 数据库迁移

- **目标库**：RDS 新建 `luotu_legacy`（`utf8mb4` / `utf8mb4_general_ci`）。
- **专用账号**：`luotu_legacy`，只授权 `luotu_legacy.*`，不复用新平台的 `luotu` 账号。
- **认证插件**：旧 PHP 7.2 对 MySQL 8 默认 `caching_sha2_password` 支持不确定，账号优先用：
  ```sql
  CREATE USER 'luotu_legacy'@'%' IDENTIFIED WITH mysql_native_password BY '<强密码>';
  GRANT ALL PRIVILEGES ON luotu_legacy.* TO 'luotu_legacy'@'%';
  ```
  若 RDS 已禁用 `mysql_native_password`，再评估 TLS + `caching_sha2_password`。
- **引擎**：导入后把 17 张 MyISAM 表统一转 InnoDB，获得事务、行锁和 RDS 备份一致性。
- **sql_mode**：RDS 为严格模式，旧库为宽松模式。先 dry-run 导入并跑旧系统主要功能；如出现空字符串写数值列等报错，再选择：
  - A. 旧系统连接后执行 `SET SESSION sql_mode='NO_ENGINE_SUBSTITUTION'`（需代码改动）；
  - B. 旧系统单独使用一个小 RDS 实例，参数组按旧库配置（隔离性最好，成本更高）。
- **时区**：旧代码未使用 `NOW()` / `CURDATE()` / `FROM_UNIXTIME()`，主要用 PHP `time()`，时区风险低；切换后仍要抽查时间字段。
- **网络**：使用 RDS 内网地址；白名单已包含 ECS 私网 IP（新平台已在用），需从 legacy 容器实测连通。

### 3.2 导入改造（解决卡死根因）

- **流式读取**：替换 `DataExcelReader::read()` 的 PHPExcel 全量加载。推荐用 PHP 自带 `ZipArchive + XMLReader` 实现 `XlsxStreamReader`，逐行回调，不依赖 Composer；也可引入 OpenSpout/PhpSpreadsheet ReadFilter。
- **只保留必要数据**：流式读取后只保留归一化后的记录，不再保留 110 万个 PHPExcel Cell 对象。
- **按块查重**：`loadExisting()` 不再 `SELECT *` 全量加载，只查 `id + 唯一键 + 期间字段`，并按 key 分块查询。
- **批量写入**：每 500–1000 行一个事务/多值 INSERT，避免 14 万次单条 `add()`。
- **硬上限**：单文件 ≤ 20MB、单次 ≤ 20 万行（可配置）；超限直接返回明确错误。
- **防重入**：用 MySQL `GET_LOCK('legacy_import:<product>:<type2>', 0)` 或文件锁，同一品类同一时间只允许一个导入；前端处理中禁用按钮。
- **可观测**：导入开始/结束记录行数、耗时、`memory_get_peak_usage()`，方便下次定位。
- **可选**：改为异步导入任务 + 进度轮询（新平台已有类似能力），彻底避免 HTTP 超时。

### 3.3 资源与监控

- PHP-FPM：`pm.max_children` 5 → 3，`pm.max_requests = 200`，限制单机 PHP 内存上限。
- 评估增加 4GB swap 作为防卡死缓冲（不能替代内存治理），或直接升配 ECS 到 16GB。
- RDS 开启慢查询日志（`long_query_time=2`）和存储/连接数告警。
- ECS 开启 CloudMonitor 告警：内存 >80%、云盘读 BPS >80% 规格上限、磁盘使用率 >80%、load 持续偏高。
- Docker 日志轮转：`max-size=100m`、`max-file=3`（当前 mysql 日志已 500MB+）。

---

## 4. 分阶段执行计划

### Phase 0：准备（不停服，可先做）

1. 确认维护窗口和业务通知。
2. 记录旧库基线：每张表 `COUNT(*)`、关键表 `CHECKSUM TABLE`、`lt_import_batch` 最新记录。
3. 备份：
   - `mysqldump` 全库到 `/root/legacy_luotu_YYYYMMDD.sql`；
   - 对 ECS 系统盘/Docker volume 做一次快照（或至少保留 volume 不删）。
4. RDS 侧：
   - 新建 `luotu_legacy` schema；
   - 新建专用账号（`mysql_native_password`）；
   - 确认白名单包含 `172.29.83.181`；
   - 从 legacy 容器测试 `mysql -h <rds> -u luotu_legacy -p` 连通。
5. 兼容性预检：
   - 旧 PHP 7.2 连接 RDS 8.0 认证是否通过；
   - 严格模式下旧数据写入是否报错；
   - 表名大小写、字符集、时区。
6. 旧系统纳入 Git（或明确配置变更的合规方式）。

### Phase 1：Dry-run（RDS 临时 schema）

1. 从 legacy 容器导出：
   ```bash
   docker exec luotu-legacy-mysql sh -c \
     'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --lock-tables --routines --triggers \
      --set-gtid-purged=OFF --default-character-set=utf8mb4 --hex-blob \
      --no-create-db luotu' > /root/legacy_luotu_dryrun.sql
   ```
2. 导入 `luotu_legacy_dryrun`。
3. 生成并执行 MyISAM → InnoDB：
   ```sql
   SELECT CONCAT('ALTER TABLE `', table_name, '` ENGINE=InnoDB;')
   FROM information_schema.tables
   WHERE table_schema='luotu_legacy_dryrun' AND engine='MyISAM';
   ```
4. 校验：表数量、每表行数、关键表 `CHECKSUM TABLE`、最新导入批次。
5. 用旧系统测试副本或临时改配置的测试容器，验证：
   - 登录、数据列表、新闻/设置页；
   - 小文件导入；
   - 14 万行大文件导入（需先完成 Phase 2）；
   - 数据导出。
6. 记录 dry-run 问题并修正。

### Phase 2：导入改造（本地开发 → Git → 部署）

1. 实现 `XlsxStreamReader`（ZipArchive + XMLReader，逐行读取）。
2. 改造 `DataImportService::parse()`：流式读取、分块查重、批量写入。
3. 增加行数/文件大小上限、单飞锁、前端防重复提交。
4. 增加导入日志（行数、耗时、峰值内存）。
5. 本地用 14 万行文件压测：峰值内存 < 400MB、无 500、耗时可控。
6. 代码提交推送，服务器按规范 `git pull` 部署；旧系统若未入 Git，先完成纳入。

### Phase 3：正式切换（低峰窗口，预计 10–30 分钟）

1. 通知停服，旧系统切维护页或停 `legacy-php-fpm`，冻结写入。
2. 最终导出（`--lock-tables`）并导入 `luotu_legacy`。
3. 执行 MyISAM → InnoDB，校验行数/checksum。
4. 切换旧系统数据库配置到 RDS（`DB_HOST` / `DB_NAME` / `DB_USER` / `DB_PWD`）。
5. 重启 `legacy-php-fpm`，冒烟测试：登录、列表、小文件导入、大文件导入、导出。
6. 观察 30–60 分钟：PHP 错误日志、RDS 连接数/慢查询、ECS 内存/磁盘。
7. 无异常后恢复对外。

### Phase 4：观察与下线（7 天）

1. 观察 7 天，确认 RDS 稳定、旧系统无报错。
2. 停 `luotu-legacy-mysql`（保留 volume），确认不再被使用后再清理。
3. 停 `ltdata-mysql-1`（新平台本地回滚库，保留 `/data/luotu/mysql`）。
4. 清理磁盘、开启慢查询/监控告警、Docker 日志轮转。
5. 更新 `问题记录.md` 和运维文档。

---

## 5. 回滚方案

### 5.1 切换前

直接放弃 dry-run，线上无影响。

### 5.2 切换后 7 天内

1. 停 `legacy-php-fpm`。
2. 把旧系统配置改回 `DB_HOST=legacy-mysql`、`DB_NAME=luotu`。
3. 重启 `legacy-php-fpm`。
4. 验证旧系统恢复。

注意：切换后写入 RDS 的新数据不会自动回流本地库，回滚会丢失这段数据，因此窗口要短、验证要快。

---

## 6. 验收清单

- [ ] RDS `luotu_legacy` 表数量与旧库一致
- [ ] 每张表 `COUNT(*)` 一致，关键表 `CHECKSUM TABLE` 一致
- [ ] MyISAM 表已全部转 InnoDB
- [ ] 旧 PHP 7.2 能正常连接 RDS（认证插件/字符集无报错）
- [ ] 登录、列表、导入、导出冒烟通过
- [ ] 14 万行 Excel 导入成功，峰值内存 < 400MB，无 500
- [ ] 导入期间 ECS 云盘读 BPS 明显低于上限，无卡顿
- [ ] 时间字段无 8 小时偏移
- [ ] 重复点击导入只执行一次（单飞锁生效）
- [ ] 7 天后本地旧库停用且数据保留
- [ ] 监控告警、慢查询、日志轮转已配置

---

## 7. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| PHP 7.2 不支持 RDS 8.0 默认认证 | 旧系统连不上库 | 账号用 `mysql_native_password`；不行再评估 TLS |
| RDS 严格 sql_mode | 旧数据/写入报错 | dry-run 全流程测试；必要时会话级放宽或独立实例 |
| MyISAM 转 InnoDB 后行为变化 | 锁/自增/性能差异 | dry-run 压测；保留原表备份 |
| 时区不一致 | 时间字段偏移 | 切换后抽查；必要时连接初始化设置时区 |
| 回滚丢数据 | 切换后新数据丢失 | 窗口短、验证快、提前通知 |
| RDS 与新平台共用实例 | 资源互相影响 | 先独立 schema；压力大时拆独立 RDS |
| 旧系统未入 Git | 配置变更不合规、不可追溯 | 先纳入 Git 或明确合规变更方式 |
| 大文件导入再次打满内存 | 再次卡死 | 流式读取 + 行数上限 + 单飞锁 + 监控 |
| ECS 仍无 swap/内存偏小 | 其他操作也可能触发卡死 | 加 swap 或升配，停掉不用的本地 MySQL |

---

## 8. TODO

### Phase 0：准备
- [ ] 确认维护窗口和业务通知
- [ ] 记录旧库每表行数、关键表 checksum、最新导入批次
- [ ] 全库 `mysqldump` 备份并异地保存
- [ ] ECS/数据卷快照
- [ ] RDS 新建 `luotu_legacy` + 专用账号
- [ ] 白名单和 legacy 容器连通性验证
- [ ] PHP 7.2 认证/严格模式/字符集/时区预检
- [ ] 旧系统纳入 Git 或确认配置变更方式

### Phase 1：Dry-run
- [ ] 导出旧库到 `luotu_legacy_dryrun`
- [ ] MyISAM 转 InnoDB
- [ ] 行数/checksum 校验
- [ ] 旧系统测试副本连 dry-run 库
- [ ] 登录/列表/导入/导出冒烟
- [ ] 记录并修复 dry-run 问题

### Phase 2：导入改造
- [ ] 实现 `XlsxStreamReader` 流式读取
- [ ] 改造 `DataImportService::parse()` 分块查重 + 批量写入
- [ ] 增加 20MB / 20 万行上限
- [ ] 增加 MySQL `GET_LOCK` 单飞锁
- [ ] 前端处理中禁用导入按钮
- [ ] 增加导入耗时/峰值内存日志
- [ ] 14 万行文件压测通过
- [ ] 代码提交推送并按规范部署

### Phase 3：切换
- [ ] 低峰停写并切维护页
- [ ] 最终导出/导入/校验
- [ ] 切换旧系统 DB 配置到 RDS
- [ ] 重启并冒烟测试
- [ ] 观察 60 分钟
- [ ] 恢复对外

### Phase 4：观察与下线
- [ ] 观察 7 天
- [ ] 停 `luotu-legacy-mysql`（保留 volume）
- [ ] 停 `ltdata-mysql-1`（保留 `/data/luotu/mysql`）
- [ ] 配置 RDS 慢查询、CloudMonitor 告警
- [ ] 配置 Docker 日志轮转
- [ ] 更新问题记录和运维文档

---

## 9. 待确认

| # | 问题 | 默认假设 | 状态 |
|---|------|----------|------|
| 1 | 维护窗口定在什么时间？ | 低峰夜间，10–30 分钟 | ⏳ |
| 2 | 旧库迁到现有 RDS 的独立 schema，还是新开独立 RDS？ | 先用现有 RDS + `luotu_legacy`，出兼容问题再拆独立实例 | ⏳ |
| 3 | 旧系统代码如何纳入 Git？ | 新增独立仓库或纳入当前仓库子目录，不含 Uploads/Runtime | ⏳ |
| 4 | 单次导入行数/文件大小上限？ | 20 万行 / 20MB | ⏳ |
| 5 | 是否允许旧系统继续保留大文件导入？ | 保留，但必须走流式 + 上限 | ⏳ |
| 6 | 是否给 ECS 加 swap 或升配？ | 先加 4GB swap + 停用闲置 MySQL，观察后再决定升配 | ⏳ |

---

## 10. 执行记录（2026-11-02）

### 已完成

- [x] 旧库基线：30 张表行数 + checksum，保存至 `/root/legacy_backup/baseline_20261102_132856.txt`
- [x] 全库备份：`/root/legacy_backup/luotu_20261102_132910.sql.gz`（17MB，gzip 校验通过）
- [x] 本地 MySQL 8.0 dry-run：导入、MyISAM→InnoDB、行数/checksum 全一致
- [x] PHP 7.2 + MySQL 8.0 + `mysql_native_password` 连接验证
- [x] RDS 创建 `luotu_legacy` schema + 专用账号（`mysql_native_password`）
- [x] RDS 导入：30 张表全部 InnoDB，行数/checksum 与源库一致
- [x] 旧系统导入流式改造并部署：
  - 14 万行文件：峰值 123.6MB / 3.3s（原 512MB OOM）
  - 8.9 万行文件：峰值 86.5MB / 2.2s，0 错误
  - commit 18,238 条：3.46s（事务分批前 54.9s）
  - 并发导入单飞锁验证通过
- [x] 旧系统切 RDS：`config.php` 读 `.env.legacy`，php-fpm 已重建，配置/中文/登录页验证通过
- [x] 临时测试控制器、dry-run schema、RDS admin 临时文件已清理

### 待执行

- [ ] 观察 7 天，确认 RDS 稳定后停 `luotu-legacy-mysql`（保留 volume）
- [ ] 确认新平台稳定后停 `ltdata-mysql-1`（保留 `/data/luotu/mysql`）
- [ ] RDS 慢查询、备份、CloudMonitor 告警配置
- [ ] Docker 日志轮转
- [ ] 轮换 RDS 高权限账号密码（本次已在对话中明文出现）
- [ ] 把旧系统代码纳入 Git，避免后续继续直接改服务器

### 关键备份位置

| 内容 | 路径 |
|---|---|
| 旧库 SQL 备份 | `/root/legacy_backup/luotu_20261102_132910.sql.gz` |
| 旧库行数/checksum 基线 | `/root/legacy_backup/baseline_20261102_132856.txt` |
| 切换前配置备份 | `/root/legacy_backup/cutover_20261102_134711/` |
| 导入代码备份 | `/root/legacy_backup/code_20261102_133633/` |
| 新导入代码 | `/root/legacy_backup/new_code/` |
