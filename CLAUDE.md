# CLAUDE.md — Insighta Commerce OS (Hermes Ecosystem)

> 이 파일은 Claude Code가 세션마다 읽는 프로젝트 컨텍스트다.
> **코딩 전에 반드시 `docs/PRD.md`와 `docs/DESIGN_DOC.md`를 먼저 읽는다.**

## 1. 프로젝트 한 줄 요약

스마트스토어 + 도매꾹 **위탁판매/구매대행**을 1인 운영자가 굴리기 위한 운영 자동화 시스템.
소싱·리스팅·채널연동·발주/송장·CS(에르메스)·컴플라이언스 6개 모듈. 직접 배송은 하지 않으며 송장만 동기화한다.

## 2. 현재 상태

- **그린필드.** 설계(PRD/Design Doc v0.2) 완료, 코드 0줄. 이 레포에서 MVP를 처음부터 만든다.
- insighta 본 프로젝트(`~/cursor/insighta`)에서 운영 원칙을 상속하되, 인프라는 1인 MVP에 맞게 **Postgres 중심으로 경량화**했다 (Design Doc §0).
- 빌드 순서·범위는 `docs/BUILD_PLAN.md`를 따른다. 임의로 모듈을 앞당기거나 건너뛰지 않는다.

## 3. 기술 스택 (Design Doc §3 기준, 임의 변경 금지)

- **API/워커:** Python 3.12 + FastAPI + Pydantic v2. 워커는 동일 코드베이스 + APScheduler + `job` 테이블 컨슈머.
- **DB/큐/락/멱등:** PostgreSQL 16 단일 (SQLAlchemy + Alembic). 큐=`job` 테이블(`SKIP LOCKED`), 락=advisory lock, 멱등=unique 제약. **Redis/SQS/EventBridge/LocalStack 없음.**
- **콘솔:** Next.js (App Router) — `console/`, 도메인 `admin.insighta.one`.
- **자산:** S3 + CloudFront(OAC), 도메인 `shop.insighta.one`, 리전 `us-west-2`.
- **AI:** Claude API — 분류 `claude-haiku-4-5`, 생성 `claude-sonnet-4-6` (Design Doc §6 라우팅 준수).
- **PII 암호화:** `cryptography` AES-256-GCM 봉투암호화, 마스터키 env (V1에 KMS 전환).
- **배포:** 단일 EC2 + docker-compose + GitHub Actions.
- 인프라 컴포넌트 추가(Redis, SQS 등)는 **측정된 병목 + Design Doc §0 트리거 근거 + 운영자 승인** 없이 금지. 스택 변경이 필요하다고 판단되면 **코드 작성 전에 운영자에게 물어본다.**

## 4. 레포 구조 (이 구조로 스캐폴딩한다)

```
.
├── CLAUDE.md
├── README.md
├── docker-compose.yml          # postgres 단일
├── .env.example                # 아래 §6 키 전부 포함
├── docs/
│   ├── PRD.md
│   ├── DESIGN_DOC.md
│   └── BUILD_PLAN.md
├── api/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/               # config, db, jobs(큐), scheduler, logging, security
│   │   ├── domain/             # 엔티티·서비스 (채널 비의존, 순수 도메인)
│   │   ├── adapters/           # smartstore / domeggook / ses / claude / datalab / s3
│   │   ├── compliance/         # 결정적 룰엔진 + 게이트 (모든 발행·발송의 관문)
│   │   ├── modules/            # sourcing, listing, channel, order, hermes, admin
│   │   └── workers/            # order, sync, hermes, listing 잡 컨슈머
│   └── tests/                  # 단위 + 계약 테스트(외부 API는 fixture 모킹)
└── console/                    # Next.js 운영 콘솔
```

## 5. 빌드/실행 명령 (스캐폴딩 시 Makefile + compose로 구성)

- `docker compose up -d` — postgres 기동
- `make dev` — API + 워커 로컬 실행
- `make migrate` — `alembic upgrade head`
- `make test` — `pytest` (외부 호출 없이 통과해야 함)
- `make lint` — ruff + mypy
- `cd console && npm run dev` — 콘솔
> 위 명령이 아직 없으면, 첫 마일스톤에서 **명령부터 만들고** README에 적는다.

## 6. 환경변수 (.env.example에 키만, 값은 비움)

```
APP_ENV=local
DATABASE_URL=postgresql+psycopg://...
AWS_REGION=us-west-2
S3_ASSETS_BUCKET=insighta-assets
S3_RAW_BUCKET=insighta-raw
CLOUDFRONT_DOMAIN=shop.insighta.one
PII_MASTER_KEY=                  # base64 32B, 고객 PII 봉투암호화 마스터키
ANTHROPIC_API_KEY=
NAVER_COMMERCE_CLIENT_ID=
NAVER_COMMERCE_CLIENT_SECRET=
NAVER_DATALAB_CLIENT_ID=
NAVER_DATALAB_CLIENT_SECRET=
DOMEGGOOK_MODE=manual            # api | tool | manual (오픈이슈, 운영자 확인)
DOMEGGOOK_API_KEY=
SES_FROM_ADDR=
```
- 로컬은 `.env`, 운영은 EC2 배포 시 env 주입. 평문 비밀을 코드/로그/커밋에 절대 넣지 않는다.
- **`.env` 파일을 수정/교체/삭제하지 않는다.** 다른 환경값이 필요하면 CLI 인라인 주입(`DATABASE_URL=... make dev`)으로만.
- **Secret vs Config 2-question test:** (1) 값을 로그에 찍어도 되는가, (2) 오픈소스 PR에 포함해도 되는가 — 둘 다 yes면 시크릿이 아니다. 튜닝 노브(가중치·임계값·TTL·플래그)는 코드 default / compose env / DB config로, 시크릿 저장소에 두지 않는다.

## 7. 절대 규칙 (NON-NEGOTIABLE GUARDRAILS)

이 프로젝트의 가치는 안전장치에 있다. 아래는 성능·편의보다 우선한다.

1. **컴플라이언스 게이트는 결정적 룰셋이 1차, LLM은 보조.**
   - 모든 리스팅 발행(F2.6)과 CS 발송(F5.4)은 `app/compliance` 게이트를 **반드시 통과**해야 한다.
   - 위법 패턴(예: "반품 불가", 청약철회 7일 축소·배제, 효능·원산지 허위)은 **하드 블록**. LLM이 괜찮다고 해도 통과시키지 않는다.
2. **PII(개인통관고유부호 등)는 봉투암호화.** `customer_pii`는 본문 테이블과 분리. **평문을 로그·예외·응답·테스트 픽스처에 절대 남기지 않는다.** 마스킹 미들웨어 적용, `retain_until` 경과분은 파기 배치.
3. **주문 파이프라인은 멱등·재시도 가능.** `idempotency_key`(unique 제약)로 동일 주문 중복 수집/발주 차단 — 같은 주문 2번 수집돼도 발주는 1건. 주문 누락 0건이 목표.
4. **모든 외부 발송(메일·발주·상품등록)은 `audit_log` 기록.** 누가/언제/무엇을.
5. **CS 자동발송은 법적 검증 통과분만.** 검증 실패·저신뢰·비정형·클레임은 **사람에게 에스컬레이션**, 자동발송 금지.
6. **모든 엔티티에 `store_id`.** 1일차부터. 멀티 스토어를 막는 단일 스토어 가정 금지.
7. **AI 생성 이미지에 실인물·유명인 금지.** 생성/사용허락 자산만(`asset.license_ok`).

## 8. 외부 연동 원칙

- 스마트스토어/도매꾹/SES/데이터랩/S3 호출은 **전부 `app/adapters` 뒤로 격리.** 도메인 코드가 외부 SDK를 직접 import하지 않는다.
- **인프라(큐/락/암호화/스토리지)도 인터페이스 뒤에.** Postgres 큐 → SQS, env 마스터키 → KMS 교체가 어댑터 구현 교체로 끝나야 한다 (Design Doc §0).
- 테스트는 **계약 테스트 + fixture 모킹.** 테스트에서 실제 외부 API를 호출하지 않는다.
- 도매꾹 발주는 `DOMEGGOOK_MODE`로 `api|tool|manual` 분기. 경로 미확정이면 `manual`(주문서 생성 후 운영자 확인) 구현을 기본으로 두고 인터페이스만 추상화.

## 9. AI 사용 규칙 (비용·품질)

- 분류·라우팅은 `claude-haiku-4-5`, 콘텐츠 생성은 `claude-sonnet-4-6`. 더 비싼 모델은 운영자 승인 후.
- 분류는 structured output(enum)로 토큰 최소화. 시스템 프롬프트·템플릿·few-shot은 **프롬프트 캐싱** 적용.
- 야간 대량 상세 생성 등 비실시간 작업은 **배치 API**.
- **Claude API 호출은 `app/adapters/claude` 경유만.** 개발 중 일회성 스크립트·테스트·데이터셋 생성에서 실제 LLM API를 호출하지 않는다(테스트는 fixture 모킹). insighta 본 프로젝트의 재정 손실 사고에서 상속한 규칙.

## 10. 작업 원칙 (insighta에서 증류)

1. **추측 전 소스 읽기.** 진단·수정·스크립트 작성 전에 관련 파일의 실제 소스를 읽는다. 에러 메시지·문서·기억·패턴만으로 코드를 쓰지 않는다. 설정 키·enum·호스트명은 grep으로 실제 값을 확인한다.
2. **계획 → 승인 → 실행.** side-effect 작업(Write/Edit/git/배포/외부 발송) 전에 계획(파일 경로 + diff 요지 + 롤백 방법)을 제시하고 명시적 승인 후 실행. 제안·질문형 답변은 실행 트리거가 아니다.
3. **하드코딩 + 단편 조치 금지.** 매직 넘버는 named constant, env 읽기는 `core/config`(Pydantic Settings) 경유. 수정 전 동일 패턴을 전수 검색해 **같은 PR에서 일괄 정리** — 단일 파일 부분 조치 금지.
4. **Done = 실제 동작 검증.** 빌드/테스트 통과 ≠ 완료. 로컬에서 실제 플로우가 도는지 확인한 후 "완료"라 말한다. 운영 배포 건은 운영 환경 동작 확인까지.
5. **테스트 의무.** 새 함수/모듈/API → 단위 테스트 최소 1개, 버그 수정 → regression 테스트 1개. 기존 테스트 삭제/skip 금지 — 실패하면 코드를 고친다.
6. **DB 작업 순서: 로컬 → 운영.** 스키마 변경은 Alembic 마이그레이션으로만(수동 DDL 금지). 운영 DB에 테스트/시드 데이터 직접 INSERT 금지. 마이그레이션 적용 후 실제 스키마를 검증한다(성공 리턴을 맹신하지 않는다).
7. **새 컬럼/필드 추가 시 write path 전수 검토.** 해당 테이블에 쓰는 모든 경로를 grep으로 찾고, path별 write/preserve/no-op 결정을 PR 설명에 기록.
8. **수치 튜닝(timeout·retry·TTL 등)은 측정 근거와 함께.** "느리니까 한계 늘리기" 전에 로그/EXPLAIN 등 측정 1개 확보, root cause를 PR에 명시.

## 11. 운영자에게 먼저 물어볼 오픈 이슈 (추측 금지)

해당 모듈을 구현하기 직전에 확인한다. 그 외 영역은 합리적 가정을 명시하고 진행한다.

1. **도매꾹 발주 경로** — API / 연동툴(스피드고·플레이오토) / 수동? → M3 어댑터 분기.
2. **에르메스 입력·발송 계약** — `{ order_context, intent, draft_body }` 규격 확정? → M4/Design Doc §5.4.
3. **스마트스토어 커머스 API** — 앱 발급/호출 IP 등록 완료 상태? → M2.
4. **1차 집중 카테고리** — (예: 1인 캠핑)? → M5 상세 템플릿 + M1 규제 룰셋 시드에 직접 영향.
5. **콘솔 인증 방식** — 자체 세션 vs 소셜 OAuth? → 콘솔.

## 12. 작업 방식 (Working Agreement)

- 마일스톤 단위로 작업하고, **작고 리뷰 가능한 커밋**을 남긴다. 각 커밋은 PRD 요구사항 ID(F3.3 등)를 참조.
- 새 코드에는 테스트를 함께 작성. `make test`/`make lint` 통과 후 마무리.
- 파괴적 작업(스키마 드롭, 대량 삭제, 외부로 실제 발송/등록)은 **실행 전 운영자 확인.**
- 막히면 추측으로 진행하지 말고 §11 절차대로 질문.
- 시크릿·PII·컴플라이언스 게이트를 약화시키는 변경은 하지 않는다(§7).
