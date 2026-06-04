"""구조화 JSON 로그 (stdout) — Design Doc §8.4.

PII 마스킹: 직렬화된 최종 출력 문자열에 패턴 마스킹 적용 (msg/ctx/traceback 전부 커버).
설계상 평문은 어댑터 경계 밖으로 나오지 않지만(app/domain/pii.py), 이 필터는 2중 방어선.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

# 개인통관고유부호: P + 12자리
_PCCC_RE = re.compile(r"\b[Pp]\d{12}\b")
# 한국 휴대전화 (구분자 -, ., 공백 허용)
_PHONE_RE = re.compile(r"\b01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}\b")


def _mask_pccc(m: re.Match[str]) -> str:
    g = m.group()
    return g[0] + "*" * (len(g) - 3) + g[-2:]


def _mask_phone(m: re.Match[str]) -> str:
    g = m.group()
    return "*" * (len(g) - 4) + g[-4:]


def mask_pii(text: str) -> str:
    """PII 패턴 마스킹. 로그 외 출력(게이트 excerpt 등)에서도 재사용."""
    text = _PCCC_RE.sub(_mask_pccc, text)
    text = _PHONE_RE.sub(_mask_phone, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extra = getattr(record, "ctx", None)
        if extra:
            payload["ctx"] = extra
        # 최종 직렬화 결과에 마스킹 — msg/ctx/exc 어디에 평문이 섞여도 차단
        return mask_pii(json.dumps(payload, ensure_ascii=False, default=str))


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
