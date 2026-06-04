"""LLM 보조 인터페이스 — 회색지대 검토 (Design Doc §6).

M1은 Fake만 배선 (실 Claude 어댑터는 M4). CLAUDE.md §9: 개발·테스트에서 실 API 호출 금지.
역할 한계: LLM은 escalate를 올릴 수만 있고, block을 해제하거나 escalate를 내릴 수 없다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LlmReview:
    escalate: bool
    reason: str = ""


class LlmAssist(Protocol):
    def review(self, scope: str, text: str, warn_rule_keys: Sequence[str]) -> LlmReview: ...


class FakeLlmAssist:
    """실 LLM 미배선 동안의 보수적 기본값 — 회색지대는 무조건 에스컬레이션."""

    def review(self, scope: str, text: str, warn_rule_keys: Sequence[str]) -> LlmReview:
        return LlmReview(escalate=True, reason="llm-not-wired (M1 fake)")
