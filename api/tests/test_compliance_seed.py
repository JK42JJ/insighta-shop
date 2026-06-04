"""시드 로더 (F6.1) — safe_load 고정, 멱등 upsert, 스키마 검증."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.models import ComplianceRule
from app.compliance.seed_loader import SeedRule, _load_yaml_list, apply_seed, load_rules


def _write_rules(tmp_path: Path, content: str) -> Path:
    (tmp_path / "rules.yaml").write_text(content, encoding="utf-8")
    return tmp_path


RULE_YAML = """
- rule_key: t-rule-1
  scope: cs
  pattern: "합성테스트패턴"
  action: block
  note: "테스트"
"""


def test_load_and_apply_idempotent(tmp_path: Path, session: Session) -> None:
    rules = load_rules(_write_rules(tmp_path, RULE_YAML))
    assert len(rules) == 1

    first = apply_seed(session, rules)
    assert first == {"inserted": 1, "updated": 0, "disabled": 0}
    second = apply_seed(session, rules)
    assert second == {"inserted": 0, "updated": 1, "disabled": 0}

    row = session.execute(select(ComplianceRule)).scalar_one()
    assert row.rule_key == "t-rule-1"
    assert row.enabled is True


def test_removed_rule_disabled_not_deleted(tmp_path: Path, session: Session) -> None:
    apply_seed(session, load_rules(_write_rules(tmp_path, RULE_YAML)))
    summary = apply_seed(session, [])  # 파일에서 룰 제거됨
    assert summary["disabled"] == 1
    row = session.execute(select(ComplianceRule)).scalar_one()
    assert row.enabled is False  # 삭제 아님 — 감사 추적 보존


def test_invalid_regex_rejected() -> None:
    with pytest.raises(ValidationError):
        SeedRule.model_validate(
            {"rule_key": "bad", "scope": "cs", "pattern": "(", "action": "block"}
        )


def test_invalid_scope_action_rejected() -> None:
    with pytest.raises(ValidationError):
        SeedRule.model_validate(
            {"rule_key": "bad", "scope": "email", "pattern": "x", "action": "block"}
        )
    with pytest.raises(ValidationError):
        SeedRule.model_validate(
            {"rule_key": "bad", "scope": "cs", "pattern": "x", "action": "delete"}
        )


def test_duplicate_rule_key_rejected(session: Session) -> None:
    rule = SeedRule(rule_key="dup", scope="cs", pattern="x", action="block")
    with pytest.raises(ValueError, match="duplicate"):
        apply_seed(session, [rule, rule])


def test_safe_load_blocks_python_object_injection(tmp_path: Path) -> None:
    """yaml.load 금지 규약 — 임의 객체 태그는 safe_load가 거부해야 한다."""
    path = tmp_path / "rules.yaml"
    path.write_text('- !!python/object/apply:os.system ["echo pwned"]\n', encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        _load_yaml_list(path)


def test_missing_or_empty_file_returns_empty(tmp_path: Path) -> None:
    assert _load_yaml_list(tmp_path / "nope.yaml") == []
    empty = tmp_path / "empty.yaml"
    empty.write_text("# 주석뿐\n", encoding="utf-8")
    assert _load_yaml_list(empty) == []
