# Insighta Commerce OS (insighta-shop)

스마트스토어 + 도매꾹 위탁판매를 1인 운영자가 굴리기 위한 운영 자동화 시스템.
설계 문서: [`docs/PRD.md`](docs/PRD.md) · [`docs/DESIGN_DOC.md`](docs/DESIGN_DOC.md) · [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md)

## Quickstart

요구사항: Docker, [uv](https://docs.astral.sh/uv/) (Python 3.12는 uv가 자동 설치)

```bash
cp .env.example .env          # 로컬 기본값으로 그대로 동작
docker compose up -d          # postgres (localhost:5433 — 5432는 insighta 본 프로젝트가 점유)
make install                  # cd api && uv sync
make migrate                  # alembic upgrade head
make test                     # pytest (insighta_test DB 사용, 외부 호출 없음)
make lint                     # ruff + mypy
make dev                      # API(:8000) + 워커 동시 실행
```

확인: `curl http://localhost:8000/health` → `{"status":"ok","env":"local"}`

## 구조

```
api/app/
├── core/         # config, db, logging, jobs(Postgres 잡 큐), scheduler(APScheduler)
├── domain/       # 순수 도메인 엔티티 (store, audit_log, ...)
├── adapters/     # smartstore / domeggook / ses / claude / datalab / s3 (M2+)
├── compliance/   # 결정적 룰엔진 + 게이트 (M1)
├── modules/      # sourcing, listing, channel, order, hermes, admin (M2+)
└── workers/      # 워커 엔트리포인트 + 잡 컨슈머
```

인프라는 의도적으로 **Postgres 하나**로 시작한다 (큐/락/멱등 포함).
무엇을 왜 뺐고 언제 다시 넣는지는 `docs/DESIGN_DOC.md` §0 참조.

## 명령

| 명령 | 동작 |
|---|---|
| `make dev` | API + 워커 로컬 실행 |
| `make migrate` | `alembic upgrade head` |
| `make revision m="msg"` | 새 마이그레이션 생성 |
| `make test` | pytest (요구: `docker compose up -d`) |
| `make lint` / `make fmt` | ruff + mypy / 자동 포맷 |
