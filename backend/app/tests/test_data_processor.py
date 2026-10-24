import pytest
from datetime import datetime, time
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

from app.services.data_processor import (
    parse_utc_timestamp,
    utc_to_uk,
    uk_to_utc,
    get_decision_cutoff_for_delivery,
    normalize_actual_generation,
    normalize_forecast_generation,
    select_eligible_forecasts,
    evaluate_forecasts,
    calculate_mape,
)
from app.config import config


UK_TZ = ZoneInfo("Europe/London")


class TestTimestampParsing:
    def test_parse_utc_timestamp_valid(self):
        ts = parse_utc_timestamp("2026-01-15T10:30:00Z")
        assert ts == pd.Timestamp("2026-01-15T10:30:00Z", tz="UTC")

    def test_parse_utc_timestamp_none(self):
        ts = parse_utc_timestamp(None)
        assert pd.isna(ts)

    def test_parse_utc_timestamp_invalid(self):
        ts = parse_utc_timestamp("invalid")
        assert pd.isna(ts)


class TestTimezoneConversion:
    def test_utc_to_uk_winter(self):
        utc = pd.Timestamp("2026-01-15T10:30:00Z", tz="UTC")
        uk = utc_to_uk(utc)
        assert uk.tz == UK_TZ
        assert uk.hour == 10

    def test_utc_to_uk_summer(self):
        utc = pd.Timestamp("2026-07-15T10:30:00Z", tz="UTC")
        uk = utc_to_uk(utc)
        assert uk.tz == UK_TZ
        assert uk.hour == 11

    def test_uk_to_utc_winter(self):
        uk = pd.Timestamp("2026-01-15T10:30:00", tz=UK_TZ)
        utc = uk_to_utc(uk)
        assert str(utc.tz) == "UTC"
        assert utc.hour == 10


class TestDecisionCutoff:
    def test_cutoff_winter_delivery(self):
        delivery = pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC")
        cutoff = get_decision_cutoff_for_delivery(delivery)
        expected = pd.Timestamp("2026-01-14T11:00:00Z", tz="UTC")
        assert cutoff == expected

    def test_cutoff_summer_delivery(self):
        delivery = pd.Timestamp("2026-07-15T00:00:00Z", tz="UTC")
        cutoff = get_decision_cutoff_for_delivery(delivery)
        expected = pd.Timestamp("2026-07-14T10:00:00Z", tz="UTC")
        assert cutoff == expected


class TestActualGenerationNormalization:
    def test_normalize_wind_only(self):
        raw = [
            {"settlementDate": "2026-01-15", "settlementPeriod": 1, "startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-14T10:00:00Z", "generation": 1000, "fuelType": "WIND"},
            {"settlementDate": "2026-01-15", "settlementPeriod": 1, "startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-14T10:00:00Z", "generation": 500, "fuelType": "CCGT"},
        ]
        df = normalize_actual_generation(raw)
        assert len(df) == 1
        assert df.iloc[0]["generation_mw"] == 1000

    def test_normalize_handles_missing_fields(self):
        raw = [{"settlementDate": "2026-01-15", "settlementPeriod": 1}]
        df = normalize_actual_generation(raw)
        assert len(df) == 0

    def test_normalize_removes_duplicates(self):
        raw = [
            {"settlementDate": "2026-01-15", "settlementPeriod": 1, "startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-14T10:00:00Z", "generation": 1000, "fuelType": "WIND"},
            {"settlementDate": "2026-01-15", "settlementPeriod": 1, "startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-14T10:00:00Z", "generation": 1000, "fuelType": "WIND"},
        ]
        df = normalize_actual_generation(raw)
        assert len(df) == 1

    def test_actual_revision_keeps_latest_publication_for_delivery_interval(self):
        raw = [
            {"settlementDate": "2026-01-15", "settlementPeriod": 1,
             "startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-15T00:45:00Z",
             "generation": 1000, "fuelType": "WIND"},
            {"settlementDate": "2026-01-15", "settlementPeriod": 1,
             "startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-15T01:00:00Z",
             "generation": 1050, "fuelType": "WIND"},
        ]
        df = normalize_actual_generation(raw)
        assert len(df) == 1
        assert df.iloc[0]["generation_mw"] == 1050
        assert df.iloc[0]["publish_time_utc"] == pd.Timestamp("2026-01-15T01:00:00Z", tz="UTC")


class TestForecastGenerationNormalization:
    def test_normalize_basic(self):
        raw = [
            {"settlementDate": "2026-01-15", "settlementPeriod": 1, "startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-14T10:00:00Z", "generation": 1000},
        ]
        df = normalize_forecast_generation(raw)
        assert len(df) == 1
        assert df.iloc[0]["generation_mw"] == 1000


class TestForecastVintageSelection:
    def test_select_latest_eligible_before_cutoff(self):
        forecasts = pd.DataFrame({
            "settlement_date": ["2026-01-15", "2026-01-15", "2026-01-15"],
            "settlement_period": [1, 1, 1],
            "start_time_utc": [pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC")] * 3,
            "publish_time_utc": [
                pd.Timestamp("2026-01-14T09:00:00Z", tz="UTC"),
                pd.Timestamp("2026-01-14T10:30:00Z", tz="UTC"),
                pd.Timestamp("2026-01-14T11:30:00Z", tz="UTC"),
            ],
            "generation_mw": [1000, 1100, 1200],
        })
        selected = select_eligible_forecasts(forecasts)
        assert len(selected) == 1
        assert selected.iloc[0]["generation_mw"] == 1100
        assert selected.iloc[0]["publish_time_utc"] == pd.Timestamp("2026-01-14T10:30:00Z", tz="UTC")

    def test_exclude_forecasts_after_cutoff(self):
        forecasts = pd.DataFrame({
            "settlement_date": ["2026-01-15"],
            "settlement_period": [1],
            "start_time_utc": [pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC")],
            "publish_time_utc": [pd.Timestamp("2026-01-14T11:30:00Z", tz="UTC")],
            "generation_mw": [1200],
        })
        selected = select_eligible_forecasts(forecasts)
        assert len(selected) == 0

    def test_multiple_delivery_intervals(self):
        forecasts = pd.DataFrame({
            "settlement_date": ["2026-01-15", "2026-01-15", "2026-01-15", "2026-01-15"],
            "settlement_period": [1, 1, 2, 2],
            "start_time_utc": [
                pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC"),
                pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC"),
                pd.Timestamp("2026-01-15T00:30:00Z", tz="UTC"),
                pd.Timestamp("2026-01-15T00:30:00Z", tz="UTC"),
            ],
            "publish_time_utc": [
                pd.Timestamp("2026-01-14T10:00:00Z", tz="UTC"),
                pd.Timestamp("2026-01-14T10:30:00Z", tz="UTC"),
                pd.Timestamp("2026-01-14T10:00:00Z", tz="UTC"),
                pd.Timestamp("2026-01-14T10:30:00Z", tz="UTC"),
            ],
            "generation_mw": [1000, 1100, 900, 950],
        })
        selected = select_eligible_forecasts(forecasts)
        assert len(selected) == 2
        assert set(selected["generation_mw"].tolist()) == {1100, 950}

    def test_deterministic_with_duplicate_publish_times(self):
        forecasts = pd.DataFrame({
            "settlement_date": ["2026-01-15", "2026-01-15"],
            "settlement_period": [1, 1],
            "start_time_utc": [pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC")] * 2,
            "publish_time_utc": [pd.Timestamp("2026-01-14T10:30:00Z", tz="UTC")] * 2,
            "generation_mw": [1000, 1100],
        })
        selected = select_eligible_forecasts(forecasts)
        assert len(selected) == 1


class TestForecastEvaluation:
    def test_error_sign_convention(self):
        actuals = pd.DataFrame({
            "settlement_date": ["2026-01-15"],
            "settlement_period": [1],
            "start_time_utc": [pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC")],
            "actual_generation_mw": [1000],
            "has_actual": [1],
        })
        forecasts = pd.DataFrame({
            "settlement_date": ["2026-01-15"],
            "settlement_period": [1],
            "start_time_utc": [pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC")],
            "selected_forecast_generation_mw": [1100],
            "selected_forecast_publish_time_utc": [pd.Timestamp("2026-01-14T10:30:00Z", tz="UTC")],
            "has_forecast": [1],
        })
        result = evaluate_forecasts(actuals, forecasts)
        assert result.iloc[0]["error_mw"] == 100
        assert result.iloc[0]["is_overestimation"] == 1
        assert result.iloc[0]["is_underestimation"] == 0

    def test_underestimation_negative_error(self):
        actuals = pd.DataFrame({
            "settlement_date": ["2026-01-15"],
            "settlement_period": [1],
            "start_time_utc": [pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC")],
            "actual_generation_mw": [1100],
            "has_actual": [1],
        })
        forecasts = pd.DataFrame({
            "settlement_date": ["2026-01-15"],
            "settlement_period": [1],
            "start_time_utc": [pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC")],
            "selected_forecast_generation_mw": [1000],
            "selected_forecast_publish_time_utc": [pd.Timestamp("2026-01-14T10:30:00Z", tz="UTC")],
            "has_forecast": [1],
        })
        result = evaluate_forecasts(actuals, forecasts)
        assert result.iloc[0]["error_mw"] == -100
        assert result.iloc[0]["is_overestimation"] == 0
        assert result.iloc[0]["is_underestimation"] == 1

    def test_matches_by_start_time_even_if_settlement_labels_differ(self):
        delivery = pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC")
        actuals = pd.DataFrame({
            "settlement_date": ["2026-01-15"],
            "settlement_period": [1],
            "start_time_utc": [delivery],
            "actual_generation_mw": [1000],
            "has_actual": [1],
        })
        forecasts = pd.DataFrame({
            "settlement_date": ["2026-01-16"],
            "settlement_period": [3],
            "start_time_utc": [delivery],
            "selected_forecast_generation_mw": [1100],
            "selected_forecast_publish_time_utc": [pd.Timestamp("2026-01-14T10:30:00Z", tz="UTC")],
            "has_forecast": [1],
        })
        result = evaluate_forecasts(actuals, forecasts)
        assert len(result) == 1
        assert result.iloc[0]["has_actual"] == 1
        assert result.iloc[0]["has_eligible_forecast"] == 1
        assert result.iloc[0]["error_mw"] == 100

    def test_missing_actual_flagged(self):
        actuals = pd.DataFrame()
        forecasts = pd.DataFrame({
            "settlement_date": ["2026-01-15"],
            "settlement_period": [1],
            "start_time_utc": [pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC")],
            "selected_forecast_generation_mw": [1000],
            "selected_forecast_publish_time_utc": [pd.Timestamp("2026-01-14T10:30:00Z", tz="UTC")],
            "has_forecast": [1],
        })
        result = evaluate_forecasts(actuals, forecasts)
        assert result.iloc[0]["has_actual"] == 0
        assert result.iloc[0]["evaluation_status"] == "missing_actual"

    def test_missing_forecast_flagged(self):
        actuals = pd.DataFrame({
            "settlement_date": ["2026-01-15"],
            "settlement_period": [1],
            "start_time_utc": [pd.Timestamp("2026-01-15T00:00:00Z", tz="UTC")],
            "actual_generation_mw": [1000],
            "has_actual": [1],
        })
        forecasts = pd.DataFrame()
        result = evaluate_forecasts(actuals, forecasts)
        assert result.iloc[0]["has_eligible_forecast"] == 0
        assert result.iloc[0]["evaluation_status"] == "missing_forecast"


class TestMetricsCalculation:
    def test_mae(self):
        actual = pd.Series([1000, 1100, 1200])
        forecast = pd.Series([1100, 1100, 1100])
        errors = forecast - actual
        mae = np.mean(np.abs(errors))
        assert round(mae, 2) == 66.67

    def test_rmse(self):
        actual = pd.Series([1000, 1100, 1200])
        forecast = pd.Series([1100, 1100, 1100])
        errors = forecast - actual
        rmse = np.sqrt(np.mean(errors ** 2))
        assert round(rmse, 2) == 81.65

    def test_bias(self):
        actual = pd.Series([1000, 1100, 1200])
        forecast = pd.Series([1100, 1100, 1100])
        bias = np.mean(forecast - actual)
        assert bias == 0

    def test_mape_with_threshold(self):
        actual = pd.Series([1000, 0.5, 1200])
        forecast = pd.Series([1100, 100, 1100])
        mape, count = calculate_mape(actual, forecast, threshold=1.0)
        assert count == 2
        expected = (abs(1100-1000)/1000 + abs(1100-1200)/1200) / 2 * 100
        assert round(mape, 2) == round(expected, 2)

    def test_mape_all_below_threshold(self):
        actual = pd.Series([0.5, 0.3])
        forecast = pd.Series([100, 200])
        mape, count = calculate_mape(actual, forecast, threshold=1.0)
        assert mape is None
        assert count == 0

    def test_empty_dataset(self):
        actual = pd.Series(dtype=float)
        forecast = pd.Series(dtype=float)
        mape, count = calculate_mape(actual, forecast)
        assert mape is None
        assert count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])