"""APScheduler 부트스트랩 — EventBridge 대체 (Design Doc §0).

## 단일 인스턴스 규약 (절대 규칙)

스케줄러가 도는 워커 프로세스는 **항상 1개**를 전제한다 (M1 PII 파기, M2 폴링 동일).
- 스케줄 잡은 작업을 직접 실행하지 않고 **멱등키 단 job enqueue만** 한다.
- 따라서 중복 트리거가 나도 정합성은 job.idempotency_key unique 제약이 보장 (스케줄러는 힌트).
- 워커 다중화가 필요해지면 Design Doc §0 트리거 표에 따라 분산 스케줄러로 승격.

주기 잡 등록은 컴포지션 루트(app/workers/main.py)에서 한다.
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
