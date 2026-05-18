#!/bin/bash
set -e

cd "$(dirname "$0")"

echo ">>> 重新构建并启动服务（迁移由容器 entrypoint 自动执行）..."
docker compose -f docker-compose.prod.yml up -d --build

echo ">>> 清理旧镜像..."
docker image prune -f

echo ">>> 部署完成！当前容器状态："
docker compose -f docker-compose.prod.yml ps
