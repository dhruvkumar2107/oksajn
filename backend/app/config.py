import os
from dotenv import load_dotenv
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

# Load a local .env for documented non-Docker development. In deployed
# environments, platform-provided environment variables take precedence.
load_dotenv(override=False)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    ELEXON_BASE_URL: str = os.getenv(
        "ELEXON_BASE_URL", "https://data.elexon.co.uk/bmrs/api/v1"
    ).rstrip("/")
    ELEXON_TIMEOUT: int = _int_env("ELEXON_TIMEOUT", 30)
    ELEXON_MAX_RETRIES: int = _int_env("ELEXON_MAX_RETRIES", 3)
    ELEXON_RETRY_BACKOFF: float = _float_env("ELEXON_RETRY_BACKOFF", 1.0)

    DB_PATH: str = os.getenv("DB_PATH", "/data/windsight.db")

    DECISION_CUTOFF_HOUR: int = _int_env("DECISION_CUTOFF_HOUR", 11)
    DECISION_CUTOFF_MINUTE: int = _int_env("DECISION_CUTOFF_MINUTE", 0)
    DECISION_CUTOFF_TIMEZONE: str = os.getenv("DECISION_CUTOFF_TIMEZONE", "Europe/London")

    MAPE_EXCLUSION_THRESHOLD: float = _float_env("MAPE_EXCLUSION_THRESHOLD", 1.0)

    CORS_ORIGINS: list = None

    def __post_init__(self):
        raw_origins = os.getenv("CORS_ORIGINS")
        if raw_origins:
            self.CORS_ORIGINS = [origin.strip().rstrip("/") for origin in raw_origins.split(",") if origin.strip()]
        elif self.CORS_ORIGINS is None:
            self.CORS_ORIGINS = [
                "http://localhost:5173",
                "http://localhost:3000",
                "http://localhost",
                "https://frontend-95b6.vercel.app",
            ]

        if not 0 <= self.DECISION_CUTOFF_HOUR <= 23:
            self.DECISION_CUTOFF_HOUR = 11
        if not 0 <= self.DECISION_CUTOFF_MINUTE <= 59:
            self.DECISION_CUTOFF_MINUTE = 0
        if self.ELEXON_TIMEOUT <= 0:
            self.ELEXON_TIMEOUT = 30
        if self.ELEXON_MAX_RETRIES < 0:
            self.ELEXON_MAX_RETRIES = 3
        if self.MAPE_EXCLUSION_THRESHOLD < 0:
            self.MAPE_EXCLUSION_THRESHOLD = 1.0

    @property
    def decision_cutoff_time(self) -> time:
        return time(self.DECISION_CUTOFF_HOUR, self.DECISION_CUTOFF_MINUTE)

    @property
    def decision_cutoff_tz(self) -> ZoneInfo:
        return ZoneInfo(self.DECISION_CUTOFF_TIMEZONE)


config = Config()
