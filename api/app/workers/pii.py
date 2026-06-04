"""PII 파기 배치 — 스케줄러는 직접 삭제하지 않고 멱등키 잡만 적재한다.

스케줄러 단일 인스턴스 전제(core/scheduler.py 규약). 만에 하나 중복 트리거돼도
idempotency_key(pii_purge:{날짜})의 DB unique 제약이 정합성을 보장한다 — 캐시·스케줄러는 힌트.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.db import get_session_factory
from app.core.jobs import Job, enqueue
from app.domain.pii import purge_expired

logger = logging.getLogger(__name__)

PII_PURGE_JOB_TYPE = "pii_purge"
PII_PURGE_ENQUEUE_HOUR_UTC = 17  # 02:00 KST


def enqueue_pii_purge_job() -> None:
    """APScheduler 일일 트리거 — pii_purge 잡 적재 (일 1회, 멱등)."""
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    factory = get_session_factory()
    with factory() as session:
        inserted = enqueue(
            session,
            type_=PII_PURGE_JOB_TYPE,
            payload={"day": day},
            idempotency_key=f"{PII_PURGE_JOB_TYPE}:{day}",
        )
        session.commit()
    logger.info("pii purge job enqueued", extra={"ctx": {"day": day, "inserted": inserted}})


def handle_pii_purge(session: Session, job: Job) -> None:
    deleted = purge_expired(session)
    logger.info("pii purge done", extra={"ctx": {"job_id": job.id, "deleted": deleted}})
