# 컴플라이언스 시드 포맷

> **이 디렉터리의 룰셋·코퍼스는 운영자가 제공하는 Source of Truth다.**
> Claude Code는 여기에 법적 패턴을 임의 생성·추가하지 않는다 (M1 설계 합의).
> 시드 투입 전까지 코퍼스 회귀 테스트는 skip되며, 파일이 채워지면 자동 활성화된다.

## 파일 구성

```
seed/
├── rules.yaml               # 룰셋 (전자상거래법 계열 등)
└── corpus/
    ├── must_block.yaml      # 위법 — 반드시 차단돼야 하는 텍스트
    └── must_not_block.yaml  # 정상 — 과차단되면 안 되는 텍스트
```

- 파싱은 `yaml.safe_load` 고정. 커스텀 태그(`!!python/...`) 사용 불가.
- 동기화: `make seed-compliance` (파일 → DB 단방향, `rule_key` 기준 멱등 upsert).
- 파일에서 제거된 룰은 DB에서 `enabled=False` 처리 (행 삭제 아님).

## rules.yaml 스키마

```yaml
- rule_key: ecl-return-ban-001        # unique. upsert 키 (변경 시 새 룰로 취급됨)
  scope: listing                      # listing | cs | both
  pattern: "반품\\s*불가"              # Python regex (아래 매칭 계약 참조)
  action: block                       # block(하드 블록) | warn(통과+에스컬레이션)
  note: "전자상거래법 §17 청약철회 배제 금지"   # 선택
```

## corpus/*.yaml 스키마

```yaml
- id: mb-001                          # unique (파일 내)
  scope: cs                           # listing | cs
  text: "단순변심 반품 불가 상품입니다"
  expect_rule: ecl-return-ban-001     # 선택 — 이 룰이 잡아야 함을 명시 (must_block 전용)
  note: "설명"                         # 선택
```

- `must_block.yaml`: 모든 항목이 `passed=False`여야 회귀 통과. `expect_rule` 지정 시 해당 룰 히트까지 검증.
- `must_not_block.yaml`: 모든 항목이 `passed=True` + `violations=[]`여야 회귀 통과 (과차단 0).

## 매칭 계약 (패턴 작성 시 전제)

입력 텍스트는 매칭 전에 다음 처리를 거친다 (`app/compliance/normalize.py`):

1. **NFKC 정규화** + **zero-width 문자 제거** (`​` 등 — "반품​불가" 우회 차단)
2. 두 가지 뷰 생성, **둘 중 하나라도 매치되면 히트**:
   - `normalized`: 연속 공백 → 단일 스페이스
   - `compact`: 공백 전부 제거 → `"반 품 불 가"`도 패턴 `반품불가`에 히트

따라서:
- 띄어쓰기 우회는 compact 뷰가 잡으므로 패턴에 `\s*`를 일일이 넣을 필요 없음.
- 단, compact 뷰는 단어 경계가 사라지므로 과차단 위험이 있는 짧은 패턴은
  `must_not_block.yaml`에 반례를 함께 넣어 검증할 것.
- 대소문자 구분이 필요 없으면 패턴에 `(?i)` 인라인 플래그 사용.

## 게이트 동작 (참고)

- `block` 히트 → `passed=False` 확정. LLM 호출 없음, 번복 불가.
- `warn` 히트 → `passed=True` + `escalate=True` (운영자 검토로 라우팅). LLM은 사유 첨부만.
- 히트 없음 → `passed=True`, `escalate=False`.
