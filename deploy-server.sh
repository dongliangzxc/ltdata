#!/bin/bash
set -e

cd "$(dirname "$0")"

echo ">>> 重新构建前端镜像（--no-cache 避免 dist 层缓存）..."
docker compose -f docker-compose.prod.yml build --no-cache frontend

echo ">>> 启动所有服务..."
docker compose -f docker-compose.prod.yml up -d --build

echo ">>> 清理旧镜像..."
docker image prune -f

echo ">>> 部署完成！当前容器状态："
docker compose -f docker-compose.prod.yml ps
