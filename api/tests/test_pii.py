"""customer_pii 저장/복호화/에러 경로/파기 (F6.3) — M1 에러 정책 검증 포함."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.jobs import STATUS_DONE, Job, JobRunner
from app.core.security import PiiDecryptError
from app.domain.models import AuditLog
from app.domain.pii import CustomerPii, purge_expired, read_pii, store_pii
from app.workers.pii import PII_PURGE_JOB_TYPE, enqueue_pii_purge_job, handle_pii_purge

FUTURE = datetime.now(UTC) + timedelta(days=30)
PAST = datetime.now(UTC) - timedelta(days=1)
PCCC = "P123456789012"


def test_store_and_read_roundtrip(session: Session) -> None:
    row = store_pii(session, store_id=1, pii_type="pccc", plaintext=PCCC, retain_until=FUTURE)
    session.commit()
    assert row.key_version == 1
    assert PCCC.encode() not in bytes(row.ciphertext)  # 평문이 그대로 박혀있지 않음
    assert read_pii(row) == PCCC


def test_unknown_type_rejected(session: Session) -> None:
    with pytest.raises(ValueError):
        store_pii(session, store_id=1, pii_type="email", plaintext="x", retain_until=FUTURE)


def test_decrypt_failure_raises_and_audits(
    session: Session, session_factory: sessionmaker[Session]
) -> None:
    """에러 경로 정책: 조용한 빈 값 금지 — 예외 + audit_log, 평문·키 누출 없음."""
    row = store_pii(session, store_id=1, pii_type="pccc", plaintext=PCCC, retain_until=FUTURE)
    session.commit()
    row.ciphertext = bytes(row.ciphertext[:-1]) + bytes([row.ciphertext[-1] ^ 0xFF])

    with pytest.raises(PiiDecryptError) as exc_info:
        read_pii(row)
    assert PCCC not in str(exc_info.value)

    # 별도 세션에서 즉시 커밋된 감사 기록 확인
    with session_factory() as s:
        audit = s.execute(
            select(AuditLog).where(AuditLog.action == "pii_decrypt_failed")
        ).scalar_one()
        assert audit.target_id == str(row.id)
        assert audit.payload_ref == "PiiDecryptError"  # 타입명만 — 평문/키 조각 없음


def test_purge_deletes_only_expired(session: Session) -> None:
    store_pii(session, store_id=1, pii_type="pccc", plaintext=PCCC, retain_until=PAST)
    keep = store_pii(
        session, store_id=1, pii_type="phone", plaintext="01012345678", retain_until=FUTURE
    )
    session.commit()

    deleted = purge_expired(session)
    session.commit()
    assert deleted == 1
    remaining = session.execute(select(CustomerPii)).scalars().all()
    assert [r.id for r in remaining] == [keep.id]
    audit = session.execute(select(AuditLog).where(AuditLog.action == "pii_purge")).scalar_one()
    assert audit.payload_ref == "deleted=1"


def test_purge_enqueue_is_idempotent_per_day(
    session_factory: sessionmaker[Session],
) -> None:
    """스케줄러 중복 트리거 대비 — 정합성은 idempotency_key unique 제약."""
    enqueue_pii_purge_job()
    enqueue_pii_purge_job()
    with session_factory() as s:
        jobs = s.execute(select(Job).where(Job.type == PII_PURGE_JOB_TYPE)).scalars().all()
        assert len(jobs) == 1


def test_purge_via_job_runner_end_to_end(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        store_pii(s, store_id=1, pii_type="pccc", plaintext=PCCC, retain_until=PAST)
        s.commit()
    enqueue_pii_purge_job()

    runner = JobRunner(session_factory, worker_id="t1")
    runner.register(PII_PURGE_JOB_TYPE, handle_pii_purge)
    assert runner.run_once() is True

    with session_factory() as s:
        assert s.execute(select(CustomerPii)).scalars().all() == []
        job = s.execute(select(Job)).scalar_one()
        assert job.status == STATUS_DONE
