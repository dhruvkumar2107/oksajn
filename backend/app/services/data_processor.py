import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Optional, Tuple
import pandas as pd
import numpy as np

from ..config import config
from ..models import (
    insert_actual_generation,
    insert_forecast_generation,
    insert_evaluation_results,
    get_actual_generation,
    get_forecast_generation,
)

logger = logging.getLogger(__name__)

UK_TZ = ZoneInfo("Europe/London")


def parse_utc_timestamp(ts: str) -> pd.Timestamp:
    if pd.isna(ts) or ts is None:
        return pd.NaT
    try:
        return pd.Timestamp(ts, tz="UTC")
    except Exception:
        return pd.NaT


def utc_to_uk(ts: pd.Timestamp) -> pd.Timestamp:
    if pd.isna(ts):
        return pd.NaT
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(UK_TZ)


def uk_to_utc(ts: pd.Timestamp) -> pd.Timestamp:
    if pd.isna(ts):
        return pd.NaT
    if ts.tz is None:
        ts = ts.tz_localize(UK_TZ)
    return ts.tz_convert("UTC")


def get_decision_cutoff_for_delivery(delivery_start_utc: pd.Timestamp) -> pd.Timestamp:
    delivery_uk = utc_to_uk(delivery_start_utc)
    delivery_date = delivery_uk.date()
    cutoff_uk = pd.Timestamp.combine(delivery_date, config.decision_cutoff_time).tz_localize(UK_TZ)
    cutoff_uk = cutoff_uk - pd.Timedelta(days=1)
    return cutoff_uk.tz_convert("UTC")


def normalize_actual_generation(raw_records: list) -> pd.DataFrame:
    if not raw_records:
        return pd.DataFrame()

    df = pd.DataFrame(raw_records)
    required_cols = ["settlementDate", "settlementPeriod", "startTime", "publishTime", "generation"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        logger.warning(f"Missing columns in actual generation data: {missing}")
        return pd.DataFrame()

    df = df.copy()
    df["start_time_utc"] = df["startTime"].apply(parse_utc_timestamp)
    df["publish_time_utc"] = df["publishTime"].apply(parse_utc_timestamp)
    df["generation_mw"] = pd.to_numeric(df["generation"], errors="coerce")
    df["settlement_date"] = df["settlementDate"].astype(str)
    df["settlement_period"] = pd.to_numeric(df["settlementPeriod"], errors="coerce").astype("Int64")

    df = df.dropna(subset=["start_time_utc", "publish_time_utc", "generation_mw", "settlement_period"])
    df = df[["settlement_date", "settlement_period", "start_time_utc", "publish_time_utc", "generation_mw"]]
    df = df.drop_duplicates(subset=["settlement_date", "settlement_period", "publish_time_utc"])

    return df


def normalize_forecast_generation(raw_records: list) -> pd.DataFrame:
    if not raw_records:
        return pd.DataFrame()

    df = pd.DataFrame(raw_records)
    required_cols = ["settlementDate", "settlementPeriod", "startTime", "publishTime", "generation"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        logger.warning(f"Missing columns in forecast generation data: {missing}")
        return pd.DataFrame()

    df = df.copy()
    df["start_time_utc"] = df["startTime"].apply(parse_utc_timestamp)
    df["publish_time_utc"] = df["publishTime"].apply(parse_utc_timestamp)
    df["generation_mw"] = pd.to_numeric(df["generation"], errors="coerce")
    df["settlement_date"] = df["settlementDate"].astype(str)
    df["settlement_period"] = pd.to_numeric(df["settlementPeriod"], errors="coerce").astype("Int64")

    df = df.dropna(subset=["start_time_utc", "publish_time_utc", "generation_mw", "settlement_period"])
    df = df[["settlement_date", "settlement_period", "start_time_utc", "publish_time_utc", "generation_mw"]]
    df = df.drop_duplicates(subset=["settlement_date", "settlement_period", "publish_time_utc"])

    return df


def select_eligible_forecasts(forecasts: pd.DataFrame) -> pd.DataFrame:
    if forecasts.empty:
        return pd.DataFrame()

    forecasts = forecasts.copy()
    forecasts["decision_cutoff_utc"] = forecasts["start_time_utc"].apply(get_decision_cutoff_for_delivery)
    forecasts["is_eligible"] = forecasts["publish_time_utc"] <= forecasts["decision_cutoff_utc"]

    eligible = forecasts[forecasts["is_eligible"]].copy()
    if eligible.empty:
        return pd.DataFrame(columns=forecasts.columns.tolist() + ["decision_cutoff_utc", "is_eligible"])

    eligible = eligible.sort_values(["settlement_date", "settlement_period", "publish_time_utc"])
    selected = eligible.drop_duplicates(subset=["settlement_date", "settlement_period"], keep="last")

    return selected


def evaluate_forecasts(actuals: pd.DataFrame, forecasts: pd.DataFrame, 
                       mape_threshold: float = 1.0) -> pd.DataFrame:
    if actuals.empty and forecasts.empty:
        return pd.DataFrame()

    actuals = actuals.copy()
    forecasts = forecasts.copy()

    if actuals.empty:
        actuals = pd.DataFrame(columns=["settlement_date", "settlement_period", "start_time_utc", "actual_generation_mw", "has_actual"])
    if forecasts.empty:
        forecasts = pd.DataFrame(columns=["settlement_date", "settlement_period", "start_time_utc", "selected_forecast_generation_mw", "selected_forecast_publish_time_utc", "has_forecast"])

    if "has_actual" not in actuals.columns:
        actuals["has_actual"] = 1
    if "has_forecast" not in forecasts.columns:
        forecasts["has_forecast"] = 1

    actuals_cols = ["settlement_date", "settlement_period", "start_time_utc", "has_actual"]
    actuals_gen_col = None
    if "actual_generation_mw" in actuals.columns:
        actuals_gen_col = "actual_generation_mw"
    elif "generation_mw" in actuals.columns:
        actuals_gen_col = "generation_mw"
    if actuals_gen_col:
        actuals_cols.append(actuals_gen_col)
    
    forecasts_cols = ["settlement_date", "settlement_period", "start_time_utc", "has_forecast"]
    forecast_gen_col = None
    if "selected_forecast_generation_mw" in forecasts.columns:
        forecast_gen_col = "selected_forecast_generation_mw"
    elif "generation_mw" in forecasts.columns:
        forecast_gen_col = "generation_mw"
    if forecast_gen_col:
        forecasts_cols.append(forecast_gen_col)
    if "publish_time_utc" in forecasts.columns:
        forecasts_cols.append("publish_time_utc")
    elif "selected_forecast_publish_time_utc" in forecasts.columns:
        forecasts_cols.append("selected_forecast_publish_time_utc")

    actuals_key = actuals[actuals_cols].copy()
    if actuals_gen_col and actuals_gen_col != "actual_generation_mw":
        actuals_key = actuals_key.rename(columns={actuals_gen_col: "actual_generation_mw"})

    forecasts_key = forecasts[forecasts_cols].copy()
    if forecast_gen_col and forecast_gen_col != "selected_forecast_generation_mw":
        forecasts_key = forecasts_key.rename(columns={forecast_gen_col: "selected_forecast_generation_mw"})
    if "publish_time_utc" in forecasts_key.columns:
        forecasts_key = forecasts_key.rename(columns={"publish_time_utc": "selected_forecast_publish_time_utc"})

    merged = pd.merge(actuals_key, forecasts_key, on=["settlement_date", "settlement_period", "start_time_utc"], how="outer")

    merged["has_actual"] = merged["has_actual"].fillna(0).astype(int)
    merged["has_eligible_forecast"] = merged["has_forecast"].fillna(0).astype(int)

    merged["error_mw"] = np.where(
        (merged["has_actual"] == 1) & (merged["has_eligible_forecast"] == 1),
        merged["selected_forecast_generation_mw"] - merged["actual_generation_mw"],
        np.nan
    )
    merged["absolute_error_mw"] = merged["error_mw"].abs()

    merged["is_overestimation"] = np.where(
        merged["error_mw"] > 0, 1, 0
    )
    merged["is_underestimation"] = np.where(
        merged["error_mw"] < 0, 1, 0
    )

    merged["evaluation_status"] = np.where(
        (merged["has_actual"] == 1) & (merged["has_eligible_forecast"] == 1), "evaluated",
        np.where(merged["has_actual"] == 0, "missing_actual",
        np.where(merged["has_eligible_forecast"] == 0, "missing_forecast", "unknown"))
    )

    merged["created_at"] = pd.Timestamp.utcnow().isoformat()

    return merged


def calculate_mape(actual: pd.Series, forecast: pd.Series, threshold: float = 1.0) -> Tuple[Optional[float], int]:
    mask = (actual.notna()) & (forecast.notna()) & (actual.abs() > threshold)
    if not mask.any():
        return None, 0
    valid_actual = actual[mask]
    valid_forecast = forecast[mask]
    mape = np.mean(np.abs(valid_forecast - valid_actual) / np.abs(valid_actual)) * 100
    return float(mape), int(mask.sum())


def ingest_and_evaluate_period(start_date: str, end_date: str) -> dict:
    from ..services.elexon_client import ElexonClient

    stats = {
        "actual_records": 0,
        "forecast_records": 0,
        "eligible_forecasts": 0,
        "matched_intervals": 0,
        "unmatched_intervals": 0,
        "errors": []
    }

    try:
        with ElexonClient() as client:
            logger.info(f"Fetching actual generation for {start_date} to {end_date}")
            actual_raw = client.get_fuelhh_wind_only(start_time=f"{start_date}T00:00:00Z", end_time=f"{end_date}T00:00:00Z")
            logger.info(f"Fetched {len(actual_raw)} actual records")

            logger.info(f"Fetching forecast generation for {start_date} to {end_date}")
            forecast_raw = client.get_windfor(start_time=f"{start_date}T00:00:00Z", end_time=f"{end_date}T00:00:00Z")
            logger.info(f"Fetched {len(forecast_raw)} forecast records")

    except Exception as e:
        logger.error(f"API fetch failed: {e}")
        stats["errors"].append(str(e))
        return stats

    actuals_df = normalize_actual_generation(actual_raw)
    forecasts_df = normalize_forecast_generation(forecast_raw)

    stats["actual_records"] = len(actuals_df)
    stats["forecast_records"] = len(forecasts_df)

    if not actuals_df.empty:
        inserted = insert_actual_generation(actuals_df)
        logger.info(f"Inserted {inserted} actual records")

    if not forecasts_df.empty:
        inserted = insert_forecast_generation(forecasts_df)
        logger.info(f"Inserted {inserted} forecast records")

    selected_forecasts = select_eligible_forecasts(forecasts_df)
    stats["eligible_forecasts"] = len(selected_forecasts)

    evaluation_df = evaluate_forecasts(actuals_df, selected_forecasts, config.MAPE_EXCLUSION_THRESHOLD)
    
    matched = evaluation_df[(evaluation_df["has_actual"] == 1) & (evaluation_df["has_eligible_forecast"] == 1)]
    stats["matched_intervals"] = len(matched)
    stats["unmatched_intervals"] = len(evaluation_df) - len(matched)

    if not evaluation_df.empty:
        inserted = insert_evaluation_results(evaluation_df)
        logger.info(f"Inserted/updated {inserted} evaluation records")

    return stats


def import_from_json(actual_json: list, forecast_json: list, start_date: str, end_date: str) -> dict:
    stats = {
        "actual_records": 0,
        "forecast_records": 0,
        "eligible_forecasts": 0,
        "matched_intervals": 0,
        "unmatched_intervals": 0,
        "errors": []
    }

    actuals_df = normalize_actual_generation(actual_json)
    forecasts_df = normalize_forecast_generation(forecast_json)

    stats["actual_records"] = len(actuals_df)
    stats["forecast_records"] = len(forecasts_df)

    if not actuals_df.empty:
        insert_actual_generation(actuals_df)

    if not forecasts_df.empty:
        insert_forecast_generation(forecasts_df)

    selected_forecasts = select_eligible_forecasts(forecasts_df)
    stats["eligible_forecasts"] = len(selected_forecasts)

    evaluation_df = evaluate_forecasts(actuals_df, selected_forecasts, config.MAPE_EXCLUSION_THRESHOLD)
    
    matched = evaluation_df[(evaluation_df["has_actual"] == 1) & (evaluation_df["has_eligible_forecast"] == 1)]
    stats["matched_intervals"] = len(matched)
    stats["unmatched_intervals"] = len(evaluation_df) - len(matched)

    if not evaluation_df.empty:
        insert_evaluation_results(evaluation_df)

    return stats