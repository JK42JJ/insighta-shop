"""APScheduler 부트스트랩 — EventBridge 대체 (Design Doc §0).

주기 잡 등록 지점. M1: PII 파기 배치 / M2: 주문 폴링·재고 동기화가 여기에 추가된다.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 60


def _heartbeat() -> None:
    logger.info("worker heartbeat")


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _heartbeat,
        "interval",
        seconds=HEARTBEAT_INTERVAL_SECONDS,
        id="heartbeat",
    )
    return scheduler
