#!/bin/bash

echo ">>> 执行数据库迁移..."

# alembic upgrade 可能因 alembic_version 表已存在但记录缺失而失败（常见于
# create_all 初始化后的首次迁移）。出错时自动 stamp head 再重试一次。
if ! alembic upgrade head 2>&1; then
    echo ">>> 迁移失败，尝试 stamp head 后重试..."
    alembic stamp head
    alembic upgrade head
fi

echo ">>> 启动应用..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
