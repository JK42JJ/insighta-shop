"""텍스트 정규화 — 우회 표기("반 품 불 가", zero-width 삽입) 차단.

매칭 계약 (SEED_FORMAT.md와 동일하게 유지):
  1) NFKC 정규화 + zero-width 문자 제거
  2) 두 가지 뷰 생성:
     - normalized: 공백을 단일 스페이스로 축약
     - compact:    공백 전부 제거 (띄어쓰기 우회 차단)
  패턴은 두 뷰 중 하나라도 매치되면 히트.
"""

import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))
_WS_RE = re.compile(r"\s+")


def views(text: str) -> tuple[str, str]:
    """반환: (normalized, compact)."""
    base = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    normalized = _WS_RE.sub(" ", base).strip()
    compact = _WS_RE.sub("", base)
    return normalized, compact
