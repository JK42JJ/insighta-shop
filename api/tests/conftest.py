"""테스트 픽스처 — insighta_test DB 사용 (외부 API 호출 없음, CLAUDE.md §8)."""

import os
from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# get_settings()가 .env보다 테스트 DSN을 우선하도록 import 전에 주입
TEST_DATABASE_URL = os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://insighta:insighta@localhost:5433/insighta_test",
)

from app.core.jobs import Job  # noqa: E402, F401  (메타데이터 등록)
from app.core.models import Base  # noqa: E402
from app.domain.models import AuditLog, Store  # noqa: E402, F401


@pytest.fixture(scope="session")
def engine() -> Generator[Engine, None, None]:
    eng = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine: Engine) -> Generator[sessionmaker[Session], None, None]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    # 테스트 간 격리: 전체 테이블 비움
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))


@pytest.fixture()
def session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    s = session_factory()
    yield s
    s.close()
