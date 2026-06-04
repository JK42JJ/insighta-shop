"""컴플라이언스 게이트 — 결정적 룰셋 1차, LLM 보조 (F2.6/F5.4/F6.1).

단방향 규칙 (절대 변경 금지, CLAUDE.md §7-1):
- block 히트 → passed=False 즉시 확정. LLM을 호출하지 않으며, LLM이 뒤집을 수 없다.
- warn 히트(회색지대) → passed=True + escalate=True. LLM 의견은 사유 첨부용일 뿐,
  escalate를 내리거나 통과로 바꿀 수 없다.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.llm_assist import FakeLlmAssist, LlmAssist
from app.compliance.models import ACTION_BLOCK, ACTION_WARN, SCOPE_BOTH, ComplianceRule
from app.compliance.normalize import views
from app.core.logging import mask_pii

_EXCERPT_PAD = 15


@dataclass(frozen=True)
class Violation:
    rule_key: str
    action: str
    excerpt: str


@dataclass(frozen=True)
class GateResult:
    passed: bool
    violations: tuple[Violation, ...]
    escalate: bool
    llm_reason: str = ""


@lru_cache(maxsize=512)
def _compiled(pattern: str) -> re.Pattern[str]:
    """컴파일 캐시는 힌트 — 룰 정합성은 DB가 진실."""
    return re.compile(pattern)


def _excerpt(source: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - _EXCERPT_PAD)
    end = min(len(source), match.end() + _EXCERPT_PAD)
    return mask_pii(source[start:end])


def check(session: Session, scope: str, text: str, llm: LlmAssist | None = None) -> GateResult:
    """모든 리스팅 발행·CS 발송은 이 게이트를 통과해야 한다."""
    llm = llm or FakeLlmAssist()
    rules = (
        session.execute(
            select(ComplianceRule).where(
                ComplianceRule.enabled.is_(True),
                ComplianceRule.scope.in_((scope, SCOPE_BOTH)),
            )
        )
        .scalars()
        .all()
    )

    normalized, compact = views(text)
    violations: list[Violation] = []
    for rule in rules:
        rx = _compiled(rule.pattern)
        m = rx.search(normalized)
        source = normalized
        if m is None:
            m = rx.search(compact)
            source = compact
        if m is not None:
            violations.append(Violation(rule.rule_key, rule.action, _excerpt(source, m)))

    if any(v.action == ACTION_BLOCK for v in violations):
        # 하드 블록 — LLM 미호출, 번복 불가
        return GateResult(passed=False, violations=tuple(violations), escalate=False)

    warn_keys = tuple(v.rule_key for v in violations if v.action == ACTION_WARN)
    if warn_keys:
        review = llm.review(scope, text, warn_keys)
        # 단방향: LLM이 escalate=False라 해도 warn 히트는 항상 에스컬레이션
        return GateResult(
            passed=True,
            violations=tuple(violations),
            escalate=True,
            llm_reason=review.reason,
        )

    return GateResult(passed=True, violations=(), escalate=False)
