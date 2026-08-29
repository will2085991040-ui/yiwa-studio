"""测试配置：内存 SQLite + TestClient，全离线可跑。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import os

# 测试套件强制离线：LLM 走 mock（真实生产默认已是 tokenhub openai_compat，这里不改它）
os.environ.setdefault("LLM_PROVIDER", "mock")

from app.db.base import Base, get_session
from app.main import app
from app.models import (  # noqa: F401
    AgentRun,
    AgentSpec,
    AgentVersion,
    Artifact,
    Project,
    PromptDefinition,
    PromptVersion,
)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture()
def client(session_factory):
    def _override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
