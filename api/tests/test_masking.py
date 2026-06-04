"""PII 마스킹 로깅 필터 (F6.3) — msg/ctx/traceback 어디서도 평문 미노출."""

import io
import logging
from collections.abc import Callable

from app.core.logging import JsonFormatter, mask_pii

PCCC = "P123456789012"
PHONE = "010-1234-5678"


def _log_and_capture(fn: Callable[[logging.Logger], None]) -> str:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.masking")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    fn(logger)
    return stream.getvalue()


def test_mask_pii_function() -> None:
    assert mask_pii(PCCC) == "P**********12"
    assert mask_pii(PHONE) == "*********5678"
    assert mask_pii("일반 텍스트") == "일반 텍스트"


def test_msg_masked() -> None:
    out = _log_and_capture(lambda lg: lg.info("customer pccc=%s phone=%s", PCCC, PHONE))
    assert PCCC not in out
    assert PHONE not in out
    assert "P**********12" in out


def test_ctx_masked() -> None:
    out = _log_and_capture(lambda lg: lg.info("x", extra={"ctx": {"pccc": PCCC}}))
    assert PCCC not in out


def test_traceback_masked() -> None:
    def fn(lg: logging.Logger) -> None:
        try:
            raise ValueError(f"bad pccc: {PCCC}")
        except ValueError:
            lg.exception("failed")

    out = _log_and_capture(fn)
    assert PCCC not in out
    assert "P**********12" in out
