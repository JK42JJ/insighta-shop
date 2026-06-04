"""중앙 설정 — env 읽기는 반드시 이 모듈 경유 (CLAUDE.md §10-3 하드코딩 금지)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 레포 루트의 .env (cwd 무관). 실제 env var가 .env보다 우선한다 (pydantic-settings 기본).
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "local"
    DATABASE_URL: str = "postgresql+psycopg://insighta:insighta@localhost:5433/insighta"

    # AWS / 자산 (M5에서 사용)
    AWS_REGION: str = "us-west-2"
    S3_ASSETS_BUCKET: str = "insighta-assets"
    S3_RAW_BUCKET: str = "insighta-raw"
    CLOUDFRONT_DOMAIN: str = "shop.insighta.one"

    # PII 봉투암호화 마스터키 (M1에서 사용, base64 32B)
    PII_MASTER_KEY: str = ""

    # 외부 연동 (M2+)
    ANTHROPIC_API_KEY: str = ""
    NAVER_COMMERCE_CLIENT_ID: str = ""
    NAVER_COMMERCE_CLIENT_SECRET: str = ""
    NAVER_DATALAB_CLIENT_ID: str = ""
    NAVER_DATALAB_CLIENT_SECRET: str = ""
    DOMEGGOOK_MODE: str = "manual"  # api | tool | manual
    DOMEGGOOK_API_KEY: str = ""
    SES_FROM_ADDR: str = ""

    # 잡 큐 튜닝 노브 (시크릿 아님 — Secret vs Config 2-question test)
    JOB_MAX_ATTEMPTS_DEFAULT: int = 5
    JOB_RETRY_BASE_SECONDS: int = 30
    JOB_POLL_INTERVAL_SECONDS: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
