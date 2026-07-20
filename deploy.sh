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
  echo ">>> GitHub 推送失败，跳过服务器 git pull，继续在远端直接部署..."
fi

if [ "$CODE_PUSHED" -eq 1 ]; then
  echo ">>> 服务器拉取代码并重启服务..."
  ssh "$SERVER" "cd $SERVER_DIR && git pull && bash deploy-server.sh"
else
  echo ">>> 远端直接重启服务..."
  ssh "$SERVER" "cd $SERVER_DIR && bash deploy-server.sh"
fi

echo ">>> 部署完成！"
