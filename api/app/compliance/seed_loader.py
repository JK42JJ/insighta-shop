"""시드 로더 — 운영자 제공 룰셋/코퍼스가 Source of Truth (CC가 패턴 임의 생성 금지).

- 파싱은 yaml.safe_load 고정 (yaml.load 사용 금지 — 임의 객체 역직렬화 차단).
- 동기화는 파일 → DB 단방향, rule_key 기준 멱등 upsert.
- 파일에서 제거된 rule_key는 DB에서 enabled=False 처리 (삭제 아님 — 감사 추적 보존).

실행: `python -m app.compliance.seed_loader` 또는 `make seed-compliance`
(모듈명이 seed_loader인 이유: 시드 데이터 디렉터리 `seed/`와의 모듈 경로 충돌 회피)
"""

import argparse
import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.compliance.models import ComplianceRule
from app.core.db import get_session_factory

DEFAULT_SEED_DIR = Path(__file__).parent / "seed"
RULES_FILE = "rules.yaml"
CORPUS_DIR = "corpus"
MUST_BLOCK_FILE = "must_block.yaml"
MUST_NOT_BLOCK_FILE = "must_not_block.yaml"


class SeedRule(BaseModel):
    rule_key: str = Field(min_length=1, max_length=64)
    scope: Literal["listing", "cs", "both"]
    pattern: str = Field(min_length=1)
    action: Literal["block", "warn"]
    note: str | None = None

    @field_validator("pattern")
    @classmethod
    def _pattern_compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return v


class CorpusCase(BaseModel):
    id: str = Field(min_length=1)
    scope: Literal["listing", "cs"]
    text: str = Field(min_length=1)
    expect_rule: str | None = None
    note: str | None = None


def _load_yaml_list(path: Path) -> list[dict[str, object]]:
    """yaml.safe_load 고정. 파일 부재/빈 파일 → 빈 리스트."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{path}: top-level must be a YAML list")
    return data


def load_rules(seed_dir: Path = DEFAULT_SEED_DIR) -> list[SeedRule]:
    return [SeedRule.model_validate(item) for item in _load_yaml_list(seed_dir / RULES_FILE)]


def load_corpus(filename: str, seed_dir: Path = DEFAULT_SEED_DIR) -> list[CorpusCase]:
    path = seed_dir / CORPUS_DIR / filename
    return [CorpusCase.model_validate(item) for item in _load_yaml_list(path)]


def apply_seed(session: Session, rules: list[SeedRule]) -> dict[str, int]:
    """rule_key 기준 멱등 upsert + 파일에 없는 룰 비활성화."""
    seed_keys = {r.rule_key for r in rules}
    if len(seed_keys) != len(rules):
        raise ValueError("duplicate rule_key in seed file")

    existing = {
        row.rule_key: row for row in session.execute(select(ComplianceRule)).scalars().all()
    }
    inserted = updated = 0
    for rule in rules:
        row = existing.get(rule.rule_key)
        if row is None:
            session.add(
                ComplianceRule(
                    rule_key=rule.rule_key,
                    scope=rule.scope,
                    pattern=rule.pattern,
                    action=rule.action,
                    note=rule.note,
                    enabled=True,
                )
            )
            inserted += 1
        else:
            row.scope = rule.scope
            row.pattern = rule.pattern
            row.action = rule.action
            row.note = rule.note
            row.enabled = True
            updated += 1

    stale_keys = set(existing) - seed_keys
    # rowcount 의존 금지 (M0에서 신뢰성 문제 확인) — 대상 키를 먼저 확정
    to_disable = [k for k in stale_keys if existing[k].enabled]
    if to_disable:
        session.execute(
            update(ComplianceRule)
            .where(ComplianceRule.rule_key.in_(to_disable))
            .values(enabled=False)
        )
    disabled = len(to_disable)
    session.flush()
    return {"inserted": inserted, "updated": updated, "disabled": disabled}


def main() -> None:
    parser = argparse.ArgumentParser(description="compliance 시드 → DB 동기화")
    parser.add_argument("--dir", type=Path, default=DEFAULT_SEED_DIR)
    args = parser.parse_args()

    rules = load_rules(args.dir)
    factory = get_session_factory()
    with factory() as session:
        summary = apply_seed(session, rules)
        session.commit()
    print(json.dumps({"rules_in_file": len(rules), **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
