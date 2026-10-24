import pytest
import requests
import requests_mock
from urllib.parse import parse_qs, urlsplit
from app.services.elexon_client import ElexonClient, ElexonAPIError


class TestElexonClient:
    @pytest.fixture
    def client(self):
        return ElexonClient(base_url="https://test.api", timeout=5, max_retries=0)

    def test_get_fuelhh_success(self, client):
        with requests_mock.Mocker() as m:
            m.get("https://test.api/datasets/FUELHH/stream", json={
                "data": [
                    {"dataset": "FUELHH", "settlementDate": "2026-01-15", "settlementPeriod": 1,
                     "startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-14T10:00:00Z",
                     "fuelType": "WIND", "generation": 1000}
                ]
            })
            result = client.get_fuelhh(settlement_date="2026-01-15")
            assert len(result) == 1
            assert result[0]["fuelType"] == "WIND"
            assert result[0]["generation"] == 1000

    def test_get_fuelhh_wind_only_filters(self, client):
        with requests_mock.Mocker() as m:
            m.get("https://test.api/datasets/FUELHH/stream", json={
                "data": [
                    {"dataset": "FUELHH", "settlementDate": "2026-01-15", "settlementPeriod": 1,
                     "startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-14T10:00:00Z",
                     "fuelType": "WIND", "generation": 1000},
                    {"dataset": "FUELHH", "settlementDate": "2026-01-15", "settlementPeriod": 1,
                     "startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-14T10:00:00Z",
                     "fuelType": "CCGT", "generation": 500},
                ]
            })
            result = client.get_fuelhh_wind_only(settlement_date="2026-01-15")
            assert len(result) == 1
            assert result[0]["fuelType"] == "WIND"

    def test_get_windfor_success(self, client):
        with requests_mock.Mocker() as m:
            m.get("https://test.api/datasets/WINDFOR/stream", json={
                "data": [
                    {"dataset": "WINDFOR", "settlementDate": "2026-01-15", "settlementPeriod": 1,
                     "startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-14T10:00:00Z",
                     "generation": 1000}
                ]
            })
            result = client.get_windfor(settlement_date="2026-01-15")
            assert len(result) == 1
            assert result[0]["generation"] == 1000

    def test_query_uses_publication_time_parameters(self, client):
        with requests_mock.Mocker() as m:
            m.get("https://test.api/datasets/WINDFOR/stream", json=[])
            client.get_windfor(
                start_time="2026-01-01T00:00:00Z",
                end_time="2026-01-01T12:00:00Z",
            )
            request = m.last_request
            query = parse_qs(urlsplit(request.url).query)
            assert query.get("publishDateTimeFrom") == ["2026-01-01T00:00:00Z"], request.url
            assert query.get("publishDateTimeTo") == ["2026-01-01T12:00:00Z"], request.url
            assert "startTime" not in query, request.url
            assert "endTime" not in query, request.url

    def test_http_error_raises(self, client):
        with requests_mock.Mocker() as m:
            m.get("https://test.api/datasets/FUELHH/stream", status_code=500)
            with pytest.raises(ElexonAPIError):
                client.get_fuelhh()

    def test_timeout_raises(self, client):
        with requests_mock.Mocker() as m:
            m.get("https://test.api/datasets/FUELHH/stream", exc=requests.Timeout)
            with pytest.raises(ElexonAPIError):
                client.get_fuelhh()

    def test_invalid_json_raises(self, client):
        with requests_mock.Mocker() as m:
            m.get("https://test.api/datasets/FUELHH/stream", text="not json")
            with pytest.raises(ElexonAPIError):
                client.get_fuelhh()

    def test_context_manager(self):
        with ElexonClient(base_url="https://test.api") as client:
            assert client.session is not None