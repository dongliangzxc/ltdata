#!/bin/bash

echo ">>> 执行数据库迁移..."
alembic upgrade head

echo ">>> 启动应用..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
