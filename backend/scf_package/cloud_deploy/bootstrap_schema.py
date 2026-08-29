"""云侧建库引导：幂等地在 CloudBase MySQL 上建表并提升管理员。

用法（部署到云函数后，手动执行一次，或在首个请求前由 CLOUD_DEPLOY.md 指引触发）：
    python -c "from cloud_bootstrap import run; run()"
云端数据库连接来自环境变量 DATABASE_URL（pymysql://...），密钥只读环境变量。
"""
from app.core.config import settings  # noqa: F401 （读取环境变量，确保 URL 生效）


def run() -> dict:
    from app.db.base import SessionLocal, ensure_schema
    from app.services.auth import promote_admins

    ensure_schema()
    db = SessionLocal()
    try:
        promoted = promote_admins(db)
        db.commit()
    finally:
        db.close()
    return {"ok": True, "promoted": promoted}


if __name__ == "__main__":
    print(run())
