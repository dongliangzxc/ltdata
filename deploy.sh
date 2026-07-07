#!/bin/bash
set -e

cd "$(dirname "$0")"

SERVER="root@39.107.251.184"
SERVER_DIR="/root/luotu/ltdata"

echo ">>> 推送代码到远端..."
CODE_PUSHED=0
if git push origin main; then
  CODE_PUSHED=1
else
  echo ">>> GitHub 推送失败，跳过服务器 git pull，继续部署本地构建产物..."
fi

echo ">>> 本地构建前端静态文件..."
cd frontend
npm install
npm run build
cd ..

echo ">>> 上传 dist 到服务器..."
ssh "$SERVER" "rm -rf $SERVER_DIR/frontend/dist"
scp -r frontend/dist "$SERVER:$SERVER_DIR/frontend/"

if [ "$CODE_PUSHED" -eq 1 ]; then
  echo ">>> 服务器拉取代码并重启服务..."
  ssh "$SERVER" "cd $SERVER_DIR && git pull && bash deploy-server.sh"
else
  echo ">>> 使用服务器现有代码重启服务..."
  ssh "$SERVER" "cd $SERVER_DIR && bash deploy-server.sh"
fi

echo ">>> 部署完成！"
