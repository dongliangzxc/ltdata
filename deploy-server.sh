#!/bin/bash
set -e

cd "$(dirname "$0")"

echo ">>> 构建前端静态文件..."
cd frontend
npm install
npm run build
cd ..

echo ">>> 重新构建前端镜像（--no-cache 避免 dist 层缓存）..."
docker compose -f docker-compose.prod.yml build --no-cache frontend

echo ">>> 启动所有服务（backend 容器启动时自动执行 alembic upgrade head 迁移）..."
docker compose -f docker-compose.prod.yml up -d --build

echo ">>> 确认数据库迁移已到最新版本..."
for i in $(seq 1 60); do
  VERSION=$(docker compose -f docker-compose.prod.yml exec -T backend alembic current 2>/dev/null | grep -oE '[a-z0-9]+\s+\(head\)' || true)
  if [ -n "$VERSION" ]; then
    echo ">>> 迁移版本: $VERSION"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo ">>> 警告: 未能在 120 秒内确认迁移完成，请检查 backend 容器日志" >&2
  fi
  sleep 2
done

echo ">>> 清理旧镜像..."
docker image prune -f

echo ">>> 部署完成！当前容器状态："
docker compose -f docker-compose.prod.yml ps
