"""백업-키 분리 회귀 (M1 수정사항 4) — "백업이 암호문이라 안전"의 전제 검증.

보장 대상:
1. DB 어디에도 KEK 재료(평문 bytes/base64/hex)가 저장되지 않는다.
2. pg_dump 산출물에 KEK 재료가 없다 → 백업 유출 시에도 복호화 불가.
3. (보너스) PII 평문도 덤프에 없다 — 암호화 우회 저장 경로가 없음을 확인.

CI에서는 REQUIRE_PG_DUMP=1로 pg_dump 테스트를 강제(스킵 불가).
"""

import binascii
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from app.core.models import Base
from app.domain.pii import store_pii
from tests.conftest import TEST_DATABASE_URL, TEST_KEK, TEST_KEK_B64

PCCC_PLAINTEXT = "P123456789012"
FUTURE = datetime.now(UTC) + timedelta(days=30)


def _kek_representations() -> list[bytes]:
    """덤프에서 탐지할 KEK 표현형: base64 문자열, hex(소문자/대문자)."""
    hex_lower = binascii.hexlify(TEST_KEK)
    return [TEST_KEK_B64.encode(), hex_lower, hex_lower.upper()]


def test_db_rows_contain_no_kek_material(session: Session, engine: Engine) -> None:
    store_pii(session, store_id=1, pii_type="pccc", plaintext=PCCC_PLAINTEXT, retain_until=FUTURE)
    session.commit()

    dump_parts: list[str] = []
    for table in Base.metadata.sorted_tables:
        for row in session.execute(select(table)).all():
            dump_parts.append(repr(row))
    serialized = "\n".join(dump_parts)

    assert TEST_KEK_B64 not in serialized
    assert binascii.hexlify(TEST_KEK).decode() not in serialized.lower()


def test_pg_dump_excludes_kek_and_plaintext(session: Session) -> None:
    store_pii(session, store_id=1, pii_type="pccc", plaintext=PCCC_PLAINTEXT, retain_until=FUTURE)
    session.commit()

    require = os.environ.get("REQUIRE_PG_DUMP") == "1"
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        if require:
            pytest.fail("REQUIRE_PG_DUMP=1 but pg_dump not found")
        pytest.skip("pg_dump not available locally (CI enforces with REQUIRE_PG_DUMP=1)")

    url = make_url(TEST_DATABASE_URL)
    proc = subprocess.run(
        [
            pg_dump,
            "-h",
            url.host or "localhost",
            "-p",
            str(url.port or 5432),
            "-U",
            url.username or "insighta",
            "--no-password",
            url.database or "insighta_test",
        ],
        env={**os.environ, "PGPASSWORD": url.password or ""},
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        message = f"pg_dump failed: {proc.stderr.decode(errors='replace')[:300]}"
        if require:
            pytest.fail(message)
        pytest.skip(message)

    dump = proc.stdout
    assert len(dump) > 0
    for representation in _kek_representations():
        assert representation not in dump, "KEK 재료가 pg_dump 산출물에 포함됨"

    # PII 평문도 덤프에 없어야 함 (bytea hex 인코딩 포함 양쪽 확인)
    assert PCCC_PLAINTEXT.encode() not in dump
    plaintext_hex = binascii.hexlify(PCCC_PLAINTEXT.encode())
    assert plaintext_hex not in dump.lower()
