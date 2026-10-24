import os
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo


@dataclass
class Config:
    ELEXON_BASE_URL: str = "https://data.elexon.co.uk/bmrs/api/v1"
    ELEXON_TIMEOUT: int = 30
    ELEXON_MAX_RETRIES: int = 3
    ELEXON_RETRY_BACKOFF: float = 1.0

    DB_PATH: str = os.getenv("DB_PATH", "/data/windsight.db")

    DECISION_CUTOFF_HOUR: int = 11
    DECISION_CUTOFF_MINUTE: int = 0
    DECISION_CUTOFF_TIMEZONE: str = "Europe/London"

    MAPE_EXCLUSION_THRESHOLD: float = 1.0

    CORS_ORIGINS: list = None

    def __post_init__(self):
        if self.CORS_ORIGINS is None:
            self.CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]

    @property
    def decision_cutoff_time(self) -> time:
        return time(self.DECISION_CUTOFF_HOUR, self.DECISION_CUTOFF_MINUTE)

    @property
    def decision_cutoff_tz(self) -> ZoneInfo:
        return ZoneInfo(self.DECISION_CUTOFF_TIMEZONE)


config = Config()