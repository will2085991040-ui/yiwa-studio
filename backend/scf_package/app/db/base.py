"""SQLAlchemy 基础设施：Base 与会话工厂。"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
# SQLite 需要 check_same_thread=False；并设 busy timeout(秒) + WAL，避免并发写的“database is locked”
connect_args = (
    {"check_same_thread": False, "timeout": 30} if _is_sqlite else {}
)
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)

if _is_sqlite:
    # 每个新连接启用 WAL + 30s busy 处理：读不阻塞写，短暂写冲突会等待而非立刻抛
    # “database is locked”，大幅降低多实例/并发生成时的写锁崩坏。
    @event.listens_for(engine, "connect")
    def _sqlite_on_connect(dbapi_connection, connection_record):  # noqa: ANN001
        try:
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
        except Exception:  # noqa: BLE001 - 对非 SQLite/只读场景保持宽容
            pass

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session():
    """FastAPI 依赖：请求级会话。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def _table_columns(conn, table_name: str) -> set[str]:
    """跨 SQLite/PostgreSQL 返回表内已存在列名，用于幂等迁移判断。"""
    if _is_sqlite:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").all()
        return {r[1] for r in rows}
    rows = conn.exec_driver_sql(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_name = '{table_name}'"
    ).all()
    return {r[0] for r in rows}


def ensure_schema() -> None:
    """启动时幂等：建缺失表 + 迁移最小增量字段（如 users.role）。纯增量、可重复调用。"""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        cols = _table_columns(conn, "users")
        if not cols:  # users 表都还没建（异常空库），交给 create_all 即可
            return
        if "role" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user' NOT NULL")
