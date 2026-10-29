# 2026-10-29 19:00 数据库迁移 Runbook

> 窗口：**今晚 19:00–20:00**
> 方式：停服 `mysqldump` 迁移到阿里云 RDS
> 预计：30–60 分钟
> 回滚：本地 MySQL 数据保留 7 天，可随时切回

---

## 0. 目标与原则

- 把 `luotu`（15.37G）和 `luotu_analytics`（0.11G）迁到 RDS。
- 迁移期间停服，保证数据一致。
- 本地 `/data/luotu/mysql` 不删除，作为回滚备份。
- 所有代码/配置改动走 Git，不在服务器直接改业务代码。

---

## 1. 迁移前（18:00 前完成）

### 1.1 RDS 参数（控制台 → 参数设置）

| 参数 | 值 | 是否必须 |
|---|---|---|
| `time_zone` | `+00:00` | 必须（也可由连接串兜底，见 1.3） |
| `transaction_isolation` | `REPEATABLE-READ` | 建议 |
| `character_set_server` | `utf8mb4` | 建议 |
| `collation_server` | `utf8mb4_0900_ai_ci` | 建议 |
| `binlog_expire_logs_seconds` | `604800` | 建议 |

> 部分参数保存后需要重启实例。

### 1.2 确认 RDS 存储

- 控制台确认存储空间 **≥100G**，并已开启**自动扩容**。
- 本次导入约 15.5G，留足余量。

### 1.3 服务器 `.env`（不提交 Git）

`/root/luotu/ltdata/.env` 追加：

```dotenv
DATABASE_URL=mysql+pymysql://luotu:<RDS_PASSWORD>@rm-2ze5mav2awbjyzw3u.mysql.rds.aliyuncs.com:3306/luotu?charset=utf8mb4
ANALYTICS_DATABASE_URL=mysql+pymysql://luotu:<RDS_PASSWORD>@rm-2ze5mav2awbjyzw3u.mysql.rds.aliyuncs.com:3306/luotu_analytics?charset=utf8mb4
```

> RDS 全局 `time_zone` 已设为 `+00:00`，连接串不需要再加 `init_command`。
> 注意：不要用 `&init_command=SET%20time_zone...`，URL 里的 `%` 会让 alembic 的 configparser 报 `invalid interpolation syntax`。

### 1.4 代码/配置

- [ ] `docker-compose.rds.yml` 已提交并推送
- [ ] `.gitignore` 已加入 `.env`
- [ ] 服务器 `cd /root/luotu/ltdata && git pull`
- [ ] 确认镜像存在：`docker images | grep ltdata`
- [ ] 确认 RDS 连通：从 backend 容器能登录（已测试通过）

### 1.5 通知用户

已发维护通知：今晚 19:00–20:00 停服。

---

## 2. 19:00 开始迁移

### 2.1 停服

```bash
cd /root/luotu/ltdata
docker compose -f docker-compose.prod.yml stop backend frontend
```

> 只停 backend/frontend，**不要停 mysql，也不要 down -v**。

### 2.2 导出并直接导入 RDS（不落本地文件，节省磁盘）

```bash
RP=$(docker exec ltdata-mysql-1 printenv MYSQL_ROOT_PASSWORD)
RDS=rm-2ze5mav2awbjyzw3u.mysql.rds.aliyuncs.com
RDS_PW='<RDS_PASSWORD>'

docker exec ltdata-mysql-1 mysqldump -uroot -p"$RP" \
  --single-transaction --quick --routines --triggers \
  --set-gtid-purged=OFF --default-character-set=utf8mb4 --hex-blob \
  --no-create-db --databases luotu luotu_analytics \
  | docker exec -i -e MYSQL_PWD="$RDS_PW" ltdata-mysql-1 mysql -h "$RDS" -u luotu
```

> 预计 20–40 分钟。命令返回 0 且无报错即成功。

### 2.3 校验数据

```bash
for t in raw_data dispatch_items match_results models clean_jobs; do
  echo -n "$t  source="; docker exec ltdata-mysql-1 mysql -uroot -p"$RP" -N -e "select count(*) from luotu.$t;" 2>/dev/null
  echo -n "$t  rds=";    docker exec -e MYSQL_PWD="$RDS_PW" ltdata-mysql-1 mysql -h "$RDS" -u luotu -N -e "select count(*) from luotu.$t;" 2>/dev/null
done

# alembic 版本
docker exec ltdata-mysql-1 mysql -uroot -p"$RP" -N -e "select * from luotu.alembic_version;" 2>/dev/null
docker exec -e MYSQL_PWD="$RDS_PW" ltdata-mysql-1 mysql -h "$RDS" -u luotu -N -e "select * from luotu.alembic_version;" 2>/dev/null
```

两边行数和 alembic 版本一致才继续。

### 2.4 启动新栈（连 RDS）

```bash
docker compose -f docker-compose.rds.yml up -d
docker compose -f docker-compose.rds.yml logs --tail=100 backend
```

### 2.5 验证

```bash
# 1) alembic 到 head
docker compose -f docker-compose.rds.yml exec -T backend alembic current

# 2) 前端可访问
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/

# 3) API 可用（401/422 都算正常，说明服务活着）
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8080/api/auth \
  -H 'Content-Type: application/json' -d '{"username":"x","password":"x"}'

# 4) 时区确认（应为 UTC）
docker compose -f docker-compose.rds.yml exec -T backend python -c \
"from app.models.database import engine; from sqlalchemy import text; print(engine.connect().execute(text('select now(), @@session.time_zone')).fetchall())"
```

再人工冒烟：登录、数据列表、匹配复核、导出、上传各点一遍。

### 2.6 恢复通知

验证通过后群里通知恢复。

---

## 3. 回滚（7 天内随时可回）

```bash
cd /root/luotu/ltdata
docker compose -f docker-compose.rds.yml down
docker compose -f docker-compose.prod.yml up -d
```

> `docker-compose.rds.yml down` 只删 backend/frontend，不会动本地 mysql 容器和数据。
> 回滚会丢失切换后写入 RDS 的新数据，所以切换窗口尽量短。

---

## 4. 迁移后

### 今晚

- [ ] 观察 backend 日志、错误率、慢查询
- [ ] 确认时间字段没有 8 小时偏移
- [ ] 确认 RDS 自动备份已生效

### 7 天后（确认稳定）

```bash
# 删除本地 MySQL 数据（释放约 41G）
rm -rf /data/luotu/mysql

# 清理 Docker 构建缓存（释放约 4.7G）
docker builder prune -f
```

- [ ] 配置 Docker 日志轮转（`/etc/docker/daemon.json`，max-size 100m / max-file 3）
- [ ] 清理 `/data/luotu/uploads` 旧 CSV（约 5.2G，先归档 OSS）
- [ ] 配置 ECS 磁盘 80%/90% 告警

---

## 5. 关键路径速查

| 时间 | 动作 |
|---|---|
| 18:00 | RDS 参数改好、`.env` 配好、代码已推送拉取 |
| 19:00 | 停 backend/frontend，发“开始维护” |
| 19:05 | 开始 dump + import |
| 19:45 | 校验行数 |
| 19:50 | 启动新栈、冒烟 |
| 20:00 | 恢复通知 |
| 20:30 | 观察无异常，收工 |
