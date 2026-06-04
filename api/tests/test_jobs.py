"""잡 큐 Acceptance (BUILD_PLAN M0): 적재 멱등 / 컨슘 / 백오프 재시도 / dead 전이 / SKIP LOCKED."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.jobs import (
    STATUS_DEAD,
    STATUS_DONE,
    STATUS_PENDING,
    Job,
    JobRunner,
    claim_next,
    enqueue,
    mark_failed,
)


def _enqueue(session: Session, key: str = "k1", max_attempts: int = 3) -> bool:
    return enqueue(
        session,
        type_="dummy",
        payload={"n": 1},
        idempotency_key=key,
        max_attempts=max_attempts,
    )


def test_enqueue_is_idempotent(session: Session) -> None:
    assert _enqueue(session) is True
    assert _enqueue(session) is False  # 동일 키 재적재 차단
    session.commit()
    jobs = session.execute(select(Job)).scalars().all()
    assert len(jobs) == 1


def test_runner_processes_job_to_done(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        _enqueue(s)
        s.commit()

    handled: list[int] = []
    runner = JobRunner(session_factory, worker_id="t1")
    runner.register("dummy", lambda sess, job: handled.append(job.id))

    assert runner.run_once() is True
    assert runner.run_once() is False  # 더 처리할 잡 없음
    assert len(handled) == 1

    with session_factory() as s:
        job = s.execute(select(Job)).scalar_one()
        assert job.status == STATUS_DONE


def test_failure_backs_off_then_dead(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        _enqueue(s, max_attempts=2)
        s.commit()

    def boom(sess: Session, job: Job) -> None:
        raise RuntimeError("boom")

    runner = JobRunner(session_factory, worker_id="t1")
    runner.register("dummy", boom)

    # 1차 실패 → pending + 백오프 (미래 run_after)
    assert runner.run_once() is True
    with session_factory() as s:
        job = s.execute(select(Job)).scalar_one()
        assert job.status == STATUS_PENDING
        assert job.attempts == 1
        assert job.run_after > datetime.now(UTC)
        assert "boom" in (job.last_error or "")
        # 백오프 중이므로 클레임 불가
        assert claim_next(s, "t2") is None
        # 재시도 시점 도래 시뮬레이션
        job.run_after = datetime.now(UTC)
        s.commit()

    # 2차 실패 → max_attempts 도달 → dead
    assert runner.run_once() is True
    with session_factory() as s:
        job = s.execute(select(Job)).scalar_one()
        assert job.status == STATUS_DEAD
    assert runner.run_once() is False  # dead는 컨슘 대상 아님


def test_unregistered_type_fails_not_crashes(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        enqueue(s, type_="unknown", payload={}, idempotency_key="u1", max_attempts=1)
        s.commit()

    runner = JobRunner(session_factory, worker_id="t1")
    assert runner.run_once() is True
    with session_factory() as s:
        job = s.execute(select(Job)).scalar_one()
        assert job.status == STATUS_DEAD
        assert "no handler" in (job.last_error or "")


def test_skip_locked_prevents_double_claim(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        _enqueue(s)
        s.commit()

    s1 = session_factory()
    s2 = session_factory()
    try:
        job1 = claim_next(s1, "w1")  # s1 트랜잭션이 락 보유
        assert job1 is not None
        assert claim_next(s2, "w2") is None  # SKIP LOCKED → 즉시 None
    finally:
        s1.rollback()
        s2.rollback()
        s1.close()
        s2.close()


def test_failed_attempts_isolated_per_job(session_factory: sessionmaker[Session]) -> None:
    """실패한 잡의 백오프가 다른 잡 처리를 막지 않는다."""
    with session_factory() as s:
        _enqueue(s, key="a", max_attempts=3)
        _enqueue(s, key="b", max_attempts=3)
        job_a = s.execute(select(Job).where(Job.idempotency_key == "a")).scalar_one()
        claimed = claim_next(s, "w1")
        assert claimed is not None and claimed.id == job_a.id
        mark_failed(s, job_a, "err")
        s.commit()

    with session_factory() as s:
        job_b = claim_next(s, "w2")
        assert job_b is not None
        assert job_b.idempotency_key == "b"
        s.rollback()
