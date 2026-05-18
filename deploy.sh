#!/bin/bash
set -e

cd "$(dirname "$0")"

SERVER="root@47.94.230.225"
SERVER_DIR="/root/luotu/ltdata"

echo ">>> 推送代码到远端..."
git push origin main

echo ">>> 本地构建前端静态文件..."
cd frontend
npm install
npm run build
cd ..

echo ">>> 上传 dist 到服务器..."
ssh "$SERVER" "rm -rf $SERVER_DIR/frontend/dist"
scp -r frontend/dist "$SERVER:$SERVER_DIR/frontend/"

echo ">>> 服务器拉取代码并重启服务..."
ssh "$SERVER" "cd $SERVER_DIR && git pull && bash deploy-server.sh"

echo ">>> 部署完成！"
