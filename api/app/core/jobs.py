"""Postgres 잡 큐 — SQS 대체 (Design Doc §0, §4 `job` 테이블).

- 적재: `idempotency_key` unique 제약으로 중복 차단 (ON CONFLICT DO NOTHING)
- 컨슘: `SELECT ... FOR UPDATE SKIP LOCKED` — 트랜잭션 유지 중 처리, 크래시 시 자동 pending 복귀
- 실패: 지수 백오프 재시도, `max_attempts` 초과 시 `dead` (DLQ 대체)
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings
from app.core.models import Base, PkMixin, StoreScopedMixin, TimestampMixin

logger = logging.getLogger(__name__)

# job.status 상태 머신: pending -> running -> done | pending(재시도) | dead
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"  # 미사용 예약 (수동 개입용)
STATUS_DEAD = "dead"


class Job(Base, PkMixin, StoreScopedMixin, TimestampMixin):
    __tablename__ = "job"

    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_PENDING)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (Index("ix_job_claim", "status", "run_after"),)


def enqueue(
    session: Session,
    *,
    type_: str,
    payload: dict[str, Any],
    idempotency_key: str,
    store_id: int | None = None,
    run_after: datetime | None = None,
    max_attempts: int | None = None,
) -> bool:
    """잡 적재. 동일 idempotency_key가 이미 있으면 적재하지 않고 False."""
    settings = get_settings()
    stmt = (
        insert(Job)
        .values(
            type=type_,
            payload_json=payload,
            status=STATUS_PENDING,
            run_after=run_after or datetime.now(UTC),
            attempts=0,
            max_attempts=max_attempts or settings.JOB_MAX_ATTEMPTS_DEFAULT,
            idempotency_key=idempotency_key,
            store_id=store_id,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        # rowcount는 ORM 세션 경유 시 -1 → RETURNING으로 삽입 여부 판별
        .returning(Job.id)
    )
    inserted_id = session.execute(stmt).scalar_one_or_none()
    return inserted_id is not None


def claim_next(session: Session, worker_id: str) -> Job | None:
    """실행 가능한 잡 1건을 SKIP LOCKED로 점유. 트랜잭션이 열려 있는 동안 락 유지."""
    job = session.execute(
        select(Job)
        .where(Job.status == STATUS_PENDING, Job.run_after <= func.now())
        .order_by(Job.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = STATUS_RUNNING
    job.locked_at = datetime.now(UTC)
    job.locked_by = worker_id
    session.flush()
    return job


def mark_done(session: Session, job: Job) -> None:
    job.status = STATUS_DONE
    job.locked_at = None
    job.locked_by = None
    session.flush()


def mark_failed(session: Session, job: Job, error: str) -> None:
    """실패 처리: 지수 백오프 재시도, max_attempts 도달 시 dead."""
    settings = get_settings()
    job.attempts += 1
    job.last_error = error[:2000]
    job.locked_at = None
    job.locked_by = None
    if job.attempts >= job.max_attempts:
        job.status = STATUS_DEAD
        logger.error("job dead", extra={"ctx": {"job_id": job.id, "type": job.type}})
    else:
        backoff = settings.JOB_RETRY_BASE_SECONDS * (2 ** (job.attempts - 1))
        job.status = STATUS_PENDING
        job.run_after = datetime.now(UTC) + timedelta(seconds=backoff)
    session.flush()


JobHandler = Callable[[Session, Job], None]


class JobRunner:
    """타입별 핸들러 디스패처. 워커 프로세스가 run_forever로 구동."""

    def __init__(self, session_factory: sessionmaker[Session], worker_id: str) -> None:
        self._session_factory = session_factory
        self._worker_id = worker_id
        self._handlers: dict[str, JobHandler] = {}

    def register(self, type_: str, handler: JobHandler) -> None:
        if type_ in self._handlers:
            raise ValueError(f"duplicate job handler: {type_}")
        self._handlers[type_] = handler

    def run_once(self) -> bool:
        """잡 1건 처리. 처리한 잡이 있으면 True. 클레임~완료가 단일 트랜잭션."""
        with self._session_factory() as session:
            job = claim_next(session, self._worker_id)
            if job is None:
                session.rollback()
                return False
            handler = self._handlers.get(job.type)
            try:
                if handler is None:
                    raise LookupError(f"no handler for job type: {job.type}")
                handler(session, job)
                mark_done(session, job)
            except Exception as exc:
                logger.exception("job failed", extra={"ctx": {"job_id": job.id, "type": job.type}})
                mark_failed(session, job, repr(exc))
            session.commit()
            return True

    def run_forever(self, stop: Callable[[], bool] | None = None) -> None:
        poll = get_settings().JOB_POLL_INTERVAL_SECONDS
        while not (stop and stop()):
            processed = self.run_once()
            if not processed:
                time.sleep(poll)
