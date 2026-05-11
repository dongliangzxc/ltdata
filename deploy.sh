#!/bin/bash
set -e

cd "$(dirname "$0")"

echo ">>> 拉取最新代码..."
git pull

echo ">>> 构建前端静态文件（在宿主机执行，避免容器内存不足）..."
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run build
cd ..

echo ">>> 重新构建并启动服务（迁移由容器 entrypoint 自动执行）..."
docker compose -f docker-compose.prod.yml up -d --build

echo ">>> 清理旧镜像..."
docker image prune -f

echo ">>> 部署完成！当前容器状态："
docker compose -f docker-compose.prod.yml ps
