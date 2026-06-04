# BUILD_PLAN.md — MVP 빌드 계획

> 기준 문서: `PRD.md`(§5 기능, §8 단계), `DESIGN_DOC.md`(§0 경량화 결정, §4 데이터모델, §7 시퀀스).
> 원칙: **운영 백본(주문→발주→송장)** 과 **컴플라이언스 기반**을 먼저 세우고, 콘텐츠·리서치를 그 위에 얹는다.
> 각 작업은 PRD 요구사항 ID를 참조. 마일스톤 끝마다 Acceptance(완료조건)를 통과해야 다음으로 넘어간다.

## 의존 관계 (요약)

```
M0 스캐폴딩 (+ job 큐/스케줄러 골격)
 └─ M1 컴플라이언스+PII 기반 ── (게이트를 M4·M5가 사용)
      └─ M2 채널 연동(스마트스토어) ── (주문·송장의 입출구)
           └─ M3 주문/발주/송장        ← 운영자 최대 페인, 핵심 가치(G3)
                └─ M4 에르메스 CS
                     └─ M5 리스팅 스튜디오
                          └─ M6 소싱/리서치
콘솔(Next.js)은 M2부터 화면을 점진적으로 붙인다.
```

> 참고: M1(컴플라이언스/PII)은 라이브러리 성격이라 먼저 만들고, M3·M5에서 게이트로 끼워 넣는다.

---

## M0 — 스캐폴딩 & 기반

**목표:** 빈 레포 → 실행·테스트·마이그레이션이 도는 골격. **로컬 의존성은 postgres 컨테이너 하나.**

- 레포 구조 생성(CLAUDE.md §4), `pyproject.toml`, ruff/mypy, pytest 설정.
- `docker-compose.yml`: **postgres 단일** (LocalStack/Redis 없음 — Design Doc §0).
- `.env.example`(CLAUDE.md §6), `core/`의 config/db/logging(JSON 구조화 로그).
- Alembic 초기화 + 베이스 모델 믹스인(`id`, `store_id`, `created_at`, `updated_at`).
- `store`, `audit_log`, **`job`** 테이블(Design Doc §4) 마이그레이션.
- **잡 큐 골격**: `job` 적재/컨슘(`FOR UPDATE SKIP LOCKED`), 백오프 재시도, `dead` 전이. 워커 엔트리포인트 + APScheduler 부트스트랩.
- Makefile(`dev`/`migrate`/`test`/`lint`) + README 실행법.
- GitHub Actions: lint + test 스켈레톤.

**Acceptance:** `docker compose up` → `make migrate` → `make test`/`make lint` 전부 통과. 빈 FastAPI `/health` 200. 더미 잡 적재 → 워커가 컨슘 → 실패 시 재시도 → `max_attempts` 초과 시 `dead` (테스트로 검증).

## M1 — 컴플라이언스 & PII 기반 (F6.1~F6.3)

**목표:** 이후 모든 발행·발송이 통과할 안전 계층.

- `compliance/`: `compliance_rule` 테이블 + 결정적 룰엔진. 룰셋 시드(반품불가/청약철회 7일 축소·배제/효능·원산지 허위 등) — `scope=listing|cs`, `action=block|warn`.
- 게이트 API: `check(scope, text) -> {passed, violations[]}`. 회색지대만 `claude-haiku-4-5` 보조(룰 우선).
- `customer_pii`: **앱 레벨 봉투암호화 래퍼**(`cryptography` AES-256-GCM, `encrypt/decrypt`, `key_version`), 본문 분리, `retain_until`. 인터페이스는 V1 KMS 전환을 가정해 키 공급자를 추상화.
- PII 마스킹 로깅 미들웨어(평문 차단).
- 파기 배치: APScheduler 일일 잡으로 구현(`retain_until` 경과분 삭제).

**Acceptance:** 위법 문구 코퍼스 회귀 테스트에서 금지 패턴 **0 통과**. PII가 로그·예외·응답에 평문으로 노출되지 않음(테스트로 검증). 암호화 라운드트립 + 파기 배치 테스트 통과.

## M2 — 채널 연동 / 스마트스토어 (F3.1~F3.4)

**목표:** 상품 등록·주문 수집·송장 전송의 입출구.

- `adapters/smartstore`: OAuth(env 자격증명 ref), 상품 등록/수정, 주문 조회, 배송정보 전송. **fixture 모킹 우선**, 실호출은 운영자 앱 발급 후.
- `modules/channel`: 가격·재고 동기화(F3.2), 공급사 품절 시 자동 판매중지.
- 주문 수집: **APScheduler 5분 폴링**(웹훅 미보장 가정), 멱등 upsert.
- `modules/listing`의 상품/리스팅 엔티티(Design Doc §4) 마이그레이션.

**Acceptance:** 모킹된 스마트스토어로 상품 upsert·주문 폴링·송장 전송이 계약 테스트 통과. 동일 주문 2회 폴링 시 1건만 저장(멱등).

## M3 — 주문 / 발주 / 송장 (F4.1~F4.3) — 핵심

**목표:** Design Doc §7.1 시퀀스 완성. 운영자 수기 입력 제거(G3).

- `workers/order`: 폴링 트리거 → `orders` upsert(`idempotency_key`) → `order_dispatch` 잡 적재 → `surcharge_risk_flag` 체크(해외·동일자 다건, F4.5는 플래그만).
- `adapters/domeggook`: `api|tool|manual` 전략 분기(`DOMEGGOOK_MODE`). 미확정 시 `manual` 기본 + 인터페이스 추상화.
- 발주 생성 → `supplier_order_no`/`tracking_no` 표준 스키마 정규화(`fulfillment`).
- 송장 수신 → 캐리어 코드 매핑 → M2 통해 채널 배송정보 전송.
- 모든 발주/발송 `audit_log` 기록.

**Acceptance:** 모킹 환경에서 주문 1건 → 발주 → 송장 → 채널 반영 전 사이클 통과. 재시도 시 발주 중복 없음(잡 `idempotency_key` unique). 실패 시 백오프 재시도 → `dead` 시 운영자 통지.

## M4 — 에르메스 CS (F5.1~F5.4)

**목표:** Design Doc §7.2 시퀀스. 정형 1차 응대 자동화 + 안전한 에스컬레이션.

- `workers/hermes`: 인입 문의 → 의도 분류(`claude-haiku-4-5`, structured enum: 배송조회/교환·반품/관부가세/재고/기타).
- 정형 & 고신뢰 → 템플릿 답변 초안(+ 주문 컨텍스트 F5.5) → **M1 게이트 검증** → 통과분만 `adapters/ses` 발송 → `cs_ticket(handling=auto)`.
- 검증 실패/저신뢰/비정형/클레임 → 운영자 에스컬레이션(컨텍스트 첨부).
- 에르메스 입력 계약(`order_context/intent/draft_body`)은 §10-2 확정 후 고정.

**Acceptance:** 정형 문의 자동발송이 게이트 통과분만 나감. 청약철회 등 법적 문구 누락·오안내 케이스는 발송 0, 전량 에스컬레이션.

## M5 — 리스팅 스튜디오 (F2.1, F2.2, F2.4, F2.6)

**목표:** 등록 리드타임 단축(G2, 목표 ≤15분).

- `modules/listing`: 상품 정보 → 상세 카피 생성(`claude-sonnet-4-6`, 후킹→문제→해결→스펙→시나리오→신뢰요소→CTA).
- 시나리오/모델 이미지: Insighta `scenario-illustrator` / (홍보용)`x-post-creator` 스킬 호출 파이프라인.
- 생성 자산 → `insighta-assets` S3 업로드 → 버전드 키(`/<product>/<hash>.webp`) → CloudFront(`shop.insighta.one`) URL을 `asset.cdn_url`에.
- 발행 전 **M1 게이트(F2.6)** 통과 필수. 원본/백업은 `insighta-raw`.
- 주의: 스마트스토어 상세는 에디터 직접 업로드 기본, S3/CDN은 자사 랜딩·원본관리·백업.

**Acceptance:** 상품 1건 입력 → 카피+이미지 초안 생성 → S3/CDN 서빙 → 게이트 통과 → 리스팅 draft 완성까지 한 흐름. 금지 문구 포함 시 발행 차단.

## M6 — 소싱 / 리서치 (F1.1~F1.3, F1.6)

**목표:** 등록 의사결정을 한 화면에서(G1).

- `adapters/datalab`: 키워드 검색량 추이·성/연령 분포(F1.1).
- 경쟁 강도 지표: 검색량 대비 등록 상품 수(F1.2).
- 마진 계산기(F1.3): 판매가 − 공급가 − 채널수수료 − (해외)관부가세 − 예상반품손실.
- 워치리스트 저장/태깅(F1.6).

**Acceptance:** 키워드 입력 → 트렌드·경쟁·마진이 한 응답/화면에. 마진 계산 단위 테스트 통과.

---

## V1 이후 (이번 MVP 비범위)

- 완전 자동화 고도화, 공급사 신뢰도 스코어(F1.5), 계절성 알림(F1.4), 손익/정산 대시보드(F6.4), CS 리포트(F5.6), 감사로그 뷰(F6.5).
- 인프라 승격 (Design Doc §0 트리거 충족 시에만): RDS 분리, Redis, KMS, Secrets Manager, CloudWatch, SQS/Fargate.
- V2: 멀티 스토어/채널(쿠팡), 해외구매대행 통관·합산과세 풀 지원.

## 마일스톤 점검 체크리스트(공통)

- [ ] 새 코드에 테스트 동반, `make test`/`make lint` 통과
- [ ] 외부 호출은 어댑터 뒤 + 계약 테스트(실호출 없음)
- [ ] 발행·발송 경로에 컴플라이언스 게이트 연결
- [ ] PII 평문 미노출, 외부 발송 `audit_log` 기록
- [ ] 커밋 메시지에 PRD 요구사항 ID 참조
- [ ] 인프라 컴포넌트 추가 제안 시 Design Doc §0 트리거 근거 명시 (측정 없는 선제 도입 금지)
