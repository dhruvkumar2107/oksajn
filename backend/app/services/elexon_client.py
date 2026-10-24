import logging
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import config

logger = logging.getLogger(__name__)


class ElexonAPIError(RuntimeError):
    """Raised when the Elexon API cannot return a valid dataset response."""


class ElexonClient:
    """Small, testable client for the official Elexon BMRS API."""

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None,
                 max_retries: Optional[int] = None):
        self.base_url = (base_url or config.ELEXON_BASE_URL).rstrip("/")
        self.timeout = timeout or config.ELEXON_TIMEOUT
        self.max_retries = config.ELEXON_MAX_RETRIES if max_retries is None else max_retries
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=self.max_retries,
            connect=self.max_retries,
            read=self.max_retries,
            status=self.max_retries,
            backoff_factor=config.ELEXON_RETRY_BACKOFF,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _make_request(self, endpoint: str, params: Optional[dict] = None):
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            logger.info("Elexon GET %s status=%s params=%s", url, response.status_code, params)
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.Timeout as exc:
            logger.error("Elexon request timed out: %s", url)
            raise ElexonAPIError(f"Elexon request timed out: {endpoint}") from exc
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            body = ""
            if exc.response is not None:
                body = (exc.response.text or "")[:300]
            logger.error("Elexon HTTP error status=%s url=%s body=%s", status, url, body)
            raise ElexonAPIError(f"Elexon HTTP {status} for {endpoint}: {body}") from exc
        except requests.exceptions.RequestException as exc:
            logger.error("Elexon network error for %s: %s", url, exc)
            raise ElexonAPIError(f"Elexon request failed for {endpoint}") from exc
        except ValueError as exc:
            logger.error("Invalid JSON response from Elexon: %s", url)
            raise ElexonAPIError(f"Elexon returned invalid JSON for {endpoint}") from exc

        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return data
            # Some dataset responses may themselves be a single record, but do not
            # misinterpret metadata/error objects as an empty successful dataset.
            if not payload:
                return []
        raise ElexonAPIError(f"Unexpected response schema from Elexon endpoint {endpoint}")

    @staticmethod
    def _published_window(start_time: Optional[str], end_time: Optional[str]) -> dict:
        """Build the documented published-time filters used by dataset endpoints."""
        params = {}
        if start_time:
            params["publishDateTimeFrom"] = start_time
        if end_time:
            params["publishDateTimeTo"] = end_time
        return params

    def get_fuelhh(self, start_time: Optional[str] = None, end_time: Optional[str] = None,
                   settlement_date: Optional[str] = None,
                   settlement_period: Optional[int] = None) -> list:
        # FUELHH stream is queried by published time. Do not pass unsupported
        # startTime/endTime parameters and mistake an ignored filter for history.
        params = self._published_window(start_time, end_time)
        if settlement_date:
            params["settlementDate"] = settlement_date
        if settlement_period is not None:
            params["settlementPeriod"] = settlement_period
        return self._make_request("/datasets/FUELHH/stream", params)

    def get_windfor(self, start_time: Optional[str] = None, end_time: Optional[str] = None,
                    settlement_date: Optional[str] = None,
                    settlement_period: Optional[int] = None) -> list:
        # Preserve publication time filters to retrieve historical forecast vintages.
        params = self._published_window(start_time, end_time)
        if settlement_date:
            params["settlementDate"] = settlement_date
        if settlement_period is not None:
            params["settlementPeriod"] = settlement_period
        return self._make_request("/datasets/WINDFOR/stream", params)

    def get_fuelhh_wind_only(self, start_time: Optional[str] = None, end_time: Optional[str] = None,
                             settlement_date: Optional[str] = None,
                             settlement_period: Optional[int] = None) -> list:
        records = self.get_fuelhh(start_time, end_time, settlement_date, settlement_period)
        return [record for record in records if record.get("fuelType") == "WIND"]

    def get_windfor_history(self, publish_time: str) -> list:
        """Fetch historical WINDFOR values for a publication timestamp when needed."""
        return self._make_request(
            "/forecast/generation/wind/history",
            {"publishTime": publish_time},
        )

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
