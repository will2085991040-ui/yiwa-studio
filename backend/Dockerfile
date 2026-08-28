FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# create_app() 启动时自动 execute ensure_schema()(建表+增量列) + 管理员 bootstrap；
# 不再依赖 alembic 迁移文件，全新/老库都能幂等收敛到最新 schema。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
