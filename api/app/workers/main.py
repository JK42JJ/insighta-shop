"""워커 엔트리포인트 — APScheduler(주기 잡) + JobRunner(job 테이블 컨슘).

잡 핸들러 등록 지점: M3 order_dispatch / M4 hermes_reply / M5 listing_gen.
"""

import logging
import os
import signal
import socket
from types import FrameType

from app.core.db import get_session_factory
from app.core.jobs import JobRunner
from app.core.logging import setup_logging
from app.core.scheduler import build_scheduler
from app.workers.pii import (
    PII_PURGE_ENQUEUE_HOUR_UTC,
    PII_PURGE_JOB_TYPE,
    enqueue_pii_purge_job,
    handle_pii_purge,
)

logger = logging.getLogger(__name__)

_shutdown = False


def _handle_signal(signum: int, frame: FrameType | None) -> None:
    global _shutdown
    logger.info("shutdown signal received", extra={"ctx": {"signal": signum}})
    _shutdown = True


def build_runner() -> JobRunner:
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    runner = JobRunner(get_session_factory(), worker_id)
    runner.register(PII_PURGE_JOB_TYPE, handle_pii_purge)
    # M3+: runner.register("order_dispatch", handle_order_dispatch) 등
    return runner


def main() -> None:
    setup_logging()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    scheduler = build_scheduler()
    scheduler.add_job(
        enqueue_pii_purge_job,
        "cron",
        hour=PII_PURGE_ENQUEUE_HOUR_UTC,
        minute=0,
        id="pii_purge_enqueue",
    )
    scheduler.start()
    logger.info("worker started")
    try:
        build_runner().run_forever(stop=lambda: _shutdown)
    finally:
        scheduler.shutdown(wait=False)
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
