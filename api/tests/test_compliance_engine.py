"""게이트 엔진 단위 테스트 (F6.1) — 합성 픽스처 사용.

주의: 여기서 쓰는 패턴("테스트차단문구" 등)은 엔진 검증용 합성 픽스처다.
실제 법적 룰셋은 운영자 시드(seed/)가 SSOT — 테스트가 임의 생성하지 않는다.
"""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.compliance.engine import check
from app.compliance.llm_assist import LlmReview
from app.compliance.models import ComplianceRule


def _add_rule(
    session: Session,
    key: str,
    pattern: str,
    action: str = "block",
    scope: str = "cs",
    enabled: bool = True,
) -> None:
    session.add(
        ComplianceRule(rule_key=key, scope=scope, pattern=pattern, action=action, enabled=enabled)
    )
    session.flush()


class PermissiveLlm:
    """escalate를 내리려 시도하는 LLM — 엔진이 무시해야 함 (단방향 검증용)."""

    calls: int = 0

    def review(self, scope: str, text: str, warn_rule_keys: Sequence[str]) -> LlmReview:
        self.calls += 1
        return LlmReview(escalate=False, reason="looks fine to me")


def test_block_hit_fails_gate(session: Session) -> None:
    _add_rule(session, "t-block-1", "테스트차단문구")
    result = check(session, "cs", "안내: 테스트차단문구 입니다")
    assert result.passed is False
    assert result.violations[0].rule_key == "t-block-1"
    assert result.escalate is False


def test_spacing_evasion_caught_by_compact_view(session: Session) -> None:
    _add_rule(session, "t-block-1", "테스트차단문구")
    result = check(session, "cs", "테 스 트 차 단 문 구")
    assert result.passed is False


def test_zero_width_evasion_caught(session: Session) -> None:
    _add_rule(session, "t-block-1", "테스트차단문구")
    result = check(session, "cs", "테스트​차단‍문구")
    assert result.passed is False


def test_block_does_not_consult_llm(session: Session) -> None:
    """하드 블록 — LLM 호출 자체가 없어야 함."""
    _add_rule(session, "t-block-1", "테스트차단문구")
    llm = PermissiveLlm()
    result = check(session, "cs", "테스트차단문구", llm=llm)
    assert result.passed is False
    assert llm.calls == 0


def test_warn_passes_but_escalates_with_fake_llm(session: Session) -> None:
    """회색지대(warn 히트)는 pass로 흘리지 않고 escalate=True — Fake LLM 경유 검증."""
    _add_rule(session, "t-warn-1", "테스트주의문구", action="warn")
    result = check(session, "cs", "테스트주의문구 포함")  # 기본 FakeLlmAssist
    assert result.passed is True
    assert result.escalate is True
    assert result.llm_reason == "llm-not-wired (M1 fake)"


def test_llm_cannot_lower_escalation(session: Session) -> None:
    """단방향: LLM이 escalate=False라 해도 warn 히트는 에스컬레이션 유지."""
    _add_rule(session, "t-warn-1", "테스트주의문구", action="warn")
    llm = PermissiveLlm()
    result = check(session, "cs", "테스트주의문구 포함", llm=llm)
    assert llm.calls == 1
    assert result.escalate is True  # LLM 의견 무시


def test_clean_text_passes_without_llm(session: Session) -> None:
    _add_rule(session, "t-warn-1", "테스트주의문구", action="warn")
    llm = PermissiveLlm()
    result = check(session, "cs", "아무 문제 없는 안내문", llm=llm)
    assert result.passed is True
    assert result.escalate is False
    assert result.violations == ()
    assert llm.calls == 0


def test_scope_filtering(session: Session) -> None:
    _add_rule(session, "t-listing-only", "테스트차단문구", scope="listing")
    _add_rule(session, "t-both", "공용차단문구", scope="both")
    assert check(session, "cs", "테스트차단문구").passed is True  # listing 룰은 cs 미적용
    assert check(session, "cs", "공용차단문구").passed is False  # both는 적용


def test_disabled_rule_ignored(session: Session) -> None:
    _add_rule(session, "t-off", "테스트차단문구", enabled=False)
    assert check(session, "cs", "테스트차단문구").passed is True
