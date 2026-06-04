"""테스트 픽스처 — insighta_test DB 사용 (외부 API 호출 없음, CLAUDE.md §8)."""

import base64
import os
from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# get_settings()가 .env보다 테스트 DSN/키를 우선하도록 import 전에 주입
# (실제 env var > .env 파일 — pydantic-settings 우선순위)
TEST_DATABASE_URL = os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://insighta:insighta@localhost:5433/insighta_test",
)
# 테스트 전용 KEK — 결정적 더미값. 운영 키와 무관.
# (env에 이미 설정돼 있으면 그 값을 따름 — TEST_KEK는 항상 실제 사용 키와 일치)
TEST_KEK_B64 = os.environ.setdefault("PII_MASTER_KEY", base64.b64encode(bytes(range(32))).decode())
TEST_KEK = base64.b64decode(TEST_KEK_B64)

from app.compliance.models import ComplianceRule  # noqa: E402, F401  (메타데이터 등록)
from app.core.jobs import Job  # noqa: E402, F401
from app.core.models import Base  # noqa: E402
from app.domain.models import AuditLog, Store  # noqa: E402, F401
from app.domain.pii import CustomerPii  # noqa: E402, F401


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
