"""양방향 코퍼스 회귀 (M1 Acceptance 본체) — 운영자 시드가 SSOT.

시드 투입 전에는 skip, 파일이 채워지면 자동 활성화 (M1 설계 합의).
- must_block:     전 항목 passed=False (+expect_rule 히트 검증)
- must_not_block: 전 항목 passed=True + violations=[] (과차단 0)
"""

import pytest
from sqlalchemy.orm import Session

from app.compliance.engine import check
from app.compliance.seed_loader import (
    MUST_BLOCK_FILE,
    MUST_NOT_BLOCK_FILE,
    apply_seed,
    load_corpus,
    load_rules,
)


@pytest.fixture()
def seeded_session(session: Session) -> Session:
    rules = load_rules()
    if not rules:
        pytest.skip("awaiting operator seed (rules.yaml empty)")
    apply_seed(session, rules)
    return session


def test_must_block_corpus(seeded_session: Session) -> None:
    cases = load_corpus(MUST_BLOCK_FILE)
    if not cases:
        pytest.skip("awaiting operator seed (must_block.yaml empty)")
    failures: list[str] = []
    for case in cases:
        result = check(seeded_session, case.scope, case.text)
        if result.passed:
            failures.append(f"{case.id}: NOT blocked")
        elif case.expect_rule and case.expect_rule not in {v.rule_key for v in result.violations}:
            failures.append(f"{case.id}: blocked but not by {case.expect_rule}")
    assert not failures, "위법 코퍼스 통과 발생:\n" + "\n".join(failures)


def test_must_not_block_corpus(seeded_session: Session) -> None:
    cases = load_corpus(MUST_NOT_BLOCK_FILE)
    if not cases:
        pytest.skip("awaiting operator seed (must_not_block.yaml empty)")
    failures: list[str] = []
    for case in cases:
        result = check(seeded_session, case.scope, case.text)
        if not result.passed or result.violations:
            keys = [v.rule_key for v in result.violations]
            failures.append(f"{case.id}: overblocked by {keys}")
    assert not failures, "정상 코퍼스 과차단 발생:\n" + "\n".join(failures)
