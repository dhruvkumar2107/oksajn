import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import config

logger = logging.getLogger(__name__)


class ElexonAPIError(RuntimeError):
    """Raised when Elexon returns an unusable response or request failure."""


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ElexonClient:
    """HTTP client for Elexon's public BMRS API.

    Dataset stream endpoints filter by *publication time* via
    publishDateTimeFrom/publishDateTimeTo. These are not delivery startTime
    filters. Requests are split into <=24-hour windows to avoid very large
    queries and to make date coverage easier to diagnose.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None,
                 max_retries: Optional[int] = None):
        self._custom_base_url = base_url is not None
        self.base_url = (base_url or config.ELEXON_BASE_URL).rstrip("/")
        self.timeout = timeout or config.ELEXON_TIMEOUT
        self.max_retries = config.ELEXON_MAX_RETRIES if max_retries is None else max_retries
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=self.max_retries,
            connect=self.max_retries,
            read=self.max_retries,
            status=self.max_retries,
            backoff_factor=config.ELEXON_RETRY_BACKOFF,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(("GET", "HEAD", "OPTIONS")),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> list:
        url = endpoint if endpoint.startswith(("https://", "http://")) else f"{self.base_url}{endpoint}"
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
            body = (exc.response.text or "")[:300] if exc.response is not None else ""
            logger.error("Elexon HTTP error status=%s url=%s body=%s", status, url, body)
            raise ElexonAPIError(f"Elexon HTTP {status} for {endpoint}: {body}") from exc
        except requests.exceptions.RequestException as exc:
            logger.error("Elexon request failed: %s", url)
            raise ElexonAPIError(f"Elexon request failed for {endpoint}") from exc
        except ValueError as exc:
            logger.error("Elexon returned invalid JSON: %s", url)
            raise ElexonAPIError(f"Elexon returned invalid JSON for {endpoint}") from exc

        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return payload["data"]
        raise ElexonAPIError(f"Unexpected response schema from Elexon endpoint {endpoint}")

    @staticmethod
    def _published_window(start_time: Optional[str], end_time: Optional[str]) -> dict:
        params = {}
        if start_time:
            params["publishDateTimeFrom"] = start_time
        if end_time:
            params["publishDateTimeTo"] = end_time
        return params

    def _get_dataset(self, dataset: str, start_time: Optional[str] = None,
                     end_time: Optional[str] = None,
                     settlement_date: Optional[str] = None,
                     settlement_period: Optional[int] = None) -> list:
        endpoint = f"/datasets/{dataset}/stream"
        if not self._custom_base_url:
            endpoint = (
                config.ELEXON_FUELHH_STREAM_URL
                if dataset == "FUELHH"
                else config.ELEXON_WINDFOR_STREAM_URL
            )
        extra = {}
        # Keep optional filters for compatibility, but historical range filtering
        # is always done using the documented publication-time fields.
        if settlement_date:
            extra["settlementDate"] = settlement_date
        if settlement_period is not None:
            extra["settlementPeriod"] = settlement_period

        if not start_time or not end_time:
            return self._make_request(endpoint, {**extra, **self._published_window(start_time, end_time)})

        try:
            cursor = _parse_datetime(start_time)
            end = _parse_datetime(end_time)
        except (TypeError, ValueError) as exc:
            raise ValueError("start_time and end_time must be ISO 8601 timestamps") from exc
        if end <= cursor:
            raise ValueError("end_time must be later than start_time")

        # Each dataset stream accepts publication-time windows of up to one day.
        # Fetch the windows concurrently so a month-backfill does not spend a
        # separate network round-trip on every day (Render request timeouts can
        # otherwise abort the refresh before any rows are persisted).
        windows = []
        while cursor < end:
            chunk_end = min(cursor + timedelta(hours=24), end)
            windows.append({
                **extra,
                "publishDateTimeFrom": _iso_z(cursor),
                "publishDateTimeTo": _iso_z(chunk_end),
            })
            cursor = chunk_end

        max_workers = max(1, min(int(config.ELEXON_MAX_CONCURRENCY), len(windows)))
        if max_workers == 1:
            records = []
            for params in windows:
                records.extend(self._make_request(endpoint, params))
        else:
            # pool.map preserves window order; each task is a read-only GET.
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                batches = list(pool.map(
                    lambda params: self._make_request(endpoint, params),
                    windows,
                ))
            records = [record for batch in batches for record in batch]

        # A boundary record can appear in adjacent windows; preserve unique
        # source records while keeping distinct forecast publication vintages.
        unique = {}
        for index, record in enumerate(records):
            key = (
                record.get("settlementDate"),
                record.get("settlementPeriod"),
                record.get("startTime"),
                record.get("publishTime"),
                record.get("fuelType"),
                record.get("generation"),
                record.get("dataset"),
            )
            unique.setdefault(key, record)
        return list(unique.values())

    def get_fuelhh(self, start_time: Optional[str] = None, end_time: Optional[str] = None,
                   settlement_date: Optional[str] = None,
                   settlement_period: Optional[int] = None) -> list:
        return self._get_dataset("FUELHH", start_time, end_time, settlement_date, settlement_period)

    def get_windfor(self, start_time: Optional[str] = None, end_time: Optional[str] = None,
                    settlement_date: Optional[str] = None,
                    settlement_period: Optional[int] = None) -> list:
        return self._get_dataset("WINDFOR", start_time, end_time, settlement_date, settlement_period)

    def get_fuelhh_wind_only(self, start_time: Optional[str] = None, end_time: Optional[str] = None,
                             settlement_date: Optional[str] = None,
                             settlement_period: Optional[int] = None) -> list:
        records = self.get_fuelhh(start_time, end_time, settlement_date, settlement_period)
        return [record for record in records if record.get("fuelType") == "WIND"]

    def get_windfor_history(self, publish_time: str) -> list:
        """Return the historical WINDFOR vintage for a documented publishTime."""
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
