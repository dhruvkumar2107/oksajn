import logging
import time
from datetime import datetime, timezone
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import config

logger = logging.getLogger(__name__)


class ElexonAPIError(Exception):
    pass


class ElexonClient:
    def __init__(self, base_url: str = None, timeout: int = None, max_retries: int = None):
        self.base_url = base_url or config.ELEXON_BASE_URL
        self.timeout = timeout or config.ELEXON_TIMEOUT
        self.max_retries = max_retries or config.ELEXON_MAX_RETRIES
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=config.ELEXON_RETRY_BACKOFF,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD, GET, OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _make_request(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logger.error(f"Request timeout for {url}")
            raise ElexonAPIError(f"Request timeout for {url}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error for {url}: {e}")
            raise ElexonAPIError(f"HTTP error: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            raise ElexonAPIError(f"Request failed: {e}")
        except ValueError as e:
            logger.error(f"Invalid JSON response from {url}: {e}")
            raise ElexonAPIError(f"Invalid JSON response: {e}")

    def get_fuelhh(self, start_time: str = None, end_time: str = None, 
                   settlement_date: str = None, settlement_period: int = None) -> list:
        params = {}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        if settlement_date:
            params["settlementDate"] = settlement_date
        if settlement_period:
            params["settlementPeriod"] = settlement_period

        data = self._make_request("/datasets/FUELHH", params)
        return data.get("data", [])

    def get_windfor(self, start_time: str = None, end_time: str = None,
                    settlement_date: str = None, settlement_period: int = None) -> list:
        params = {}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        if settlement_date:
            params["settlementDate"] = settlement_date
        if settlement_period:
            params["settlementPeriod"] = settlement_period

        data = self._make_request("/datasets/WINDFOR", params)
        return data.get("data", [])

    def get_fuelhh_wind_only(self, start_time: str = None, end_time: str = None,
                             settlement_date: str = None, settlement_period: int = None) -> list:
        records = self.get_fuelhh(start_time, end_time, settlement_date, settlement_period)
        return [r for r in records if r.get("fuelType") == "WIND"]

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()