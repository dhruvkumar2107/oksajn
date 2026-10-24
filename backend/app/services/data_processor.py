import logging
from datetime import datetime, time, timedelta
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
    """Parse an ISO timestamp as UTC without double-localizing aware values."""
    if ts is None or pd.isna(ts):
        return pd.NaT
    try:
        parsed = pd.to_datetime(ts, utc=True, errors="coerce")
        return pd.Timestamp(parsed) if not pd.isna(parsed) else pd.NaT
    except (TypeError, ValueError, OverflowError):
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
    """Return D-1 cutoff at the configured UK wall-clock time.

    Subtract the calendar day before localizing. Subtracting 24 hours from a
    timezone-aware timestamp would shift the local clock around DST changes.
    """
    delivery_uk = utc_to_uk(delivery_start_utc)
    cutoff_date = delivery_uk.date() - timedelta(days=1)
    naive_cutoff = pd.Timestamp(datetime.combine(cutoff_date, config.decision_cutoff_time))
    cutoff_uk = naive_cutoff.tz_localize(UK_TZ)
    return cutoff_uk.tz_convert("UTC")


def _add_settlement_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Use official keys when supplied; otherwise derive them from startTime."""
    local_times = df["start_time_utc"].dt.tz_convert(UK_TZ)
    if "settlementDate" in df.columns:
        dates = df["settlementDate"].astype("string")
        df["settlement_date"] = dates.where(dates.notna() & (dates != ""), local_times.dt.strftime("%Y-%m-%d"))
    else:
        df["settlement_date"] = local_times.dt.strftime("%Y-%m-%d")

    if "settlementPeriod" in df.columns:
        periods = pd.to_numeric(df["settlementPeriod"], errors="coerce")
        derived = (local_times.dt.hour * 2 + (local_times.dt.minute // 30) + 1).astype("Int64")
        df["settlement_period"] = periods.where(periods.notna(), derived).astype("Int64")
    else:
        df["settlement_period"] = (
            local_times.dt.hour * 2 + (local_times.dt.minute // 30) + 1
        ).astype("Int64")
    return df


def normalize_actual_generation(raw_records: list) -> pd.DataFrame:
    """Normalize FUELHH actuals and enforce the assignment's WIND-only scope."""
    if not raw_records:
        return pd.DataFrame()

    df = pd.DataFrame(raw_records).copy()
    required = ["startTime", "generation", "fuelType"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        logger.warning("Actual data missing required columns: %s", missing)
        return pd.DataFrame()

    # Do this before de-duplication: otherwise a non-WIND row appearing first
    # can win a duplicate key and contaminate the national wind series.
    df = df[df["fuelType"].astype(str).str.upper() == "WIND"].copy()
    if df.empty:
        return pd.DataFrame()

    df["start_time_utc"] = df["startTime"].apply(parse_utc_timestamp)
    df["generation_mw"] = pd.to_numeric(df["generation"], errors="coerce")
    df = _add_settlement_keys(df)

    # publishTime is not an input to the actual/forecast comparison. If a
    # source export omits it, use startTime only as a storage-key fallback.
    if "publishTime" in df.columns:
        df["publish_time_utc"] = df["publishTime"].apply(parse_utc_timestamp)
        df["publish_time_utc"] = df["publish_time_utc"].fillna(df["start_time_utc"])
    else:
        df["publish_time_utc"] = df["start_time_utc"]

    df = df.dropna(subset=[
        "start_time_utc", "generation_mw", "settlement_date", "settlement_period"
    ])
    df = df[[
        "settlement_date", "settlement_period", "start_time_utc",
        "publish_time_utc", "generation_mw"
    ]]
    # FUELHH can contain more than one published version of a delivery
    # interval. Evaluation should compare against one final/latest actual,
    # while preserving the source's publication timestamp when it exists.
    df = df.sort_values(["start_time_utc", "publish_time_utc"], kind="stable")
    df = df.drop_duplicates(subset=["start_time_utc"], keep="last")
    return df.reset_index(drop=True)


def normalize_forecast_generation(raw_records: list) -> pd.DataFrame:
    """Normalize WINDFOR while preserving the forecast publication vintage."""
    if not raw_records:
        return pd.DataFrame()

    df = pd.DataFrame(raw_records).copy()
    required = ["startTime", "publishTime", "generation"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        logger.warning("Forecast data missing required columns: %s", missing)
        return pd.DataFrame()

    df["start_time_utc"] = df["startTime"].apply(parse_utc_timestamp)
    df["publish_time_utc"] = df["publishTime"].apply(parse_utc_timestamp)
    df["generation_mw"] = pd.to_numeric(df["generation"], errors="coerce")
    df = _add_settlement_keys(df)
    df = df.dropna(subset=[
        "start_time_utc", "publish_time_utc", "generation_mw",
        "settlement_date", "settlement_period"
    ])
    df = df[[
        "settlement_date", "settlement_period", "start_time_utc",
        "publish_time_utc", "generation_mw"
    ]]
    df = df.drop_duplicates(
        subset=["settlement_date", "settlement_period", "start_time_utc", "publish_time_utc"],
        keep="last",
    )
    return df.reset_index(drop=True)


def filter_delivery_period(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """Keep delivery startTimes in [start_date, end_date), interpreted in UK time."""
    if df.empty:
        return df.copy()
    start_utc = pd.Timestamp(start_date).tz_localize(UK_TZ).tz_convert("UTC")
    end_utc = pd.Timestamp(end_date).tz_localize(UK_TZ).tz_convert("UTC")
    return df[
        (df["start_time_utc"] >= start_utc) &
        (df["start_time_utc"] < end_utc)
    ].copy().reset_index(drop=True)


def _uk_publication_window(start_date: str, end_date: str, pad_start_days: int = 0,
                           pad_end_days: int = 0) -> tuple[str, str]:
    start = (pd.Timestamp(start_date).tz_localize(UK_TZ) -
             pd.Timedelta(days=pad_start_days)).tz_convert("UTC")
    end = (pd.Timestamp(end_date).tz_localize(UK_TZ) +
           pd.Timedelta(days=pad_end_days)).tz_convert("UTC")
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def select_eligible_forecasts(forecasts: pd.DataFrame) -> pd.DataFrame:
    if forecasts.empty:
        return pd.DataFrame()

    forecasts = forecasts.copy()
    forecasts["decision_cutoff_utc"] = forecasts["start_time_utc"].apply(get_decision_cutoff_for_delivery)
    forecasts["is_eligible"] = forecasts["publish_time_utc"] <= forecasts["decision_cutoff_utc"]

    eligible = forecasts[forecasts["is_eligible"]].copy()
    if eligible.empty:
        return pd.DataFrame(columns=forecasts.columns.tolist() + ["decision_cutoff_utc", "is_eligible"])

    # startTime is the actual target delivery interval. Use it as the
    # primary selection key rather than relying only on settlement labels.
    eligible = eligible.sort_values(["start_time_utc", "publish_time_utc"], kind="stable")
    selected = eligible.drop_duplicates(subset=["start_time_utc"], keep="last")

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

    # startTime is the assignment's primary delivery-interval key. Settlement
    # labels are retained as metadata, but must not prevent a match when a source
    # export has missing or inconsistent settlement labels for the same interval.
    actuals_cols = ["start_time_utc", "settlement_date", "settlement_period", "has_actual"]
    actuals_gen_col = None
    if "actual_generation_mw" in actuals.columns:
        actuals_gen_col = "actual_generation_mw"
    elif "generation_mw" in actuals.columns:
        actuals_gen_col = "generation_mw"
    if actuals_gen_col:
        actuals_cols.append(actuals_gen_col)

    forecasts_cols = ["start_time_utc", "settlement_date", "settlement_period", "has_forecast"]
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

    merged = pd.merge(
        actuals_key, forecasts_key, on=["start_time_utc"], how="outer",
        suffixes=("_actual", "_forecast"),
        validate="one_to_one",
    )
    merged["settlement_date"] = merged["settlement_date_actual"].combine_first(
        merged["settlement_date_forecast"]
    )
    merged["settlement_period"] = merged["settlement_period_actual"].combine_first(
        merged["settlement_period_forecast"]
    ).astype("Int64")
    merged = merged.drop(
        columns=["settlement_date_actual", "settlement_date_forecast",
                 "settlement_period_actual", "settlement_period_forecast"]
    )

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
        "errors": [],
    }

    # Dataset stream filters are by publishTime, not the delivery startTime.
    # Retrieve a padded publication window, then explicitly filter by startTime.
    actual_from, actual_to = _uk_publication_window(
        start_date, end_date, pad_start_days=1, pad_end_days=1
    )
    # Include a seven-day publication lookback so an interval with no D-1
    # update can still use the latest earlier vintage that was available.
    # A source record is still eligible only if publishTime <= its cutoff.
    forecast_from, forecast_to = _uk_publication_window(
        start_date, end_date, pad_start_days=7, pad_end_days=0
    )

    try:
        with ElexonClient() as client:
            logger.info("Fetching FUELHH published %s to %s", actual_from, actual_to)
            actual_raw = client.get_fuelhh_wind_only(
                start_time=actual_from, end_time=actual_to
            )
            logger.info("Fetched %s FUELHH WIND source rows", len(actual_raw))

            logger.info("Fetching WINDFOR published %s to %s", forecast_from, forecast_to)
            forecast_raw = client.get_windfor(
                start_time=forecast_from, end_time=forecast_to
            )
            logger.info("Fetched %s WINDFOR source rows", len(forecast_raw))
    except Exception as exc:
        logger.exception("Elexon historical data fetch failed")
        stats["errors"].append(str(exc))
        return stats

    actuals_df = filter_delivery_period(
        normalize_actual_generation(actual_raw), start_date, end_date
    )
    forecasts_df = filter_delivery_period(
        normalize_forecast_generation(forecast_raw), start_date, end_date
    )

    stats["actual_records"] = int(len(actuals_df))
    stats["forecast_records"] = int(len(forecasts_df))

    if not actuals_df.empty:
        insert_actual_generation(actuals_df)
    if not forecasts_df.empty:
        insert_forecast_generation(forecasts_df)

    selected_forecasts = select_eligible_forecasts(forecasts_df)
    stats["eligible_forecasts"] = int(len(selected_forecasts))
    evaluation_df = evaluate_forecasts(
        actuals_df, selected_forecasts, config.MAPE_EXCLUSION_THRESHOLD
    )

    if not evaluation_df.empty:
        matched = evaluation_df[
            (evaluation_df["has_actual"] == 1) &
            (evaluation_df["has_eligible_forecast"] == 1)
        ]
        stats["matched_intervals"] = int(len(matched))
        stats["unmatched_intervals"] = int(len(evaluation_df) - len(matched))
        insert_evaluation_results(evaluation_df)

    if stats["actual_records"] == 0:
        stats["errors"].append(
            "No genuine FUELHH WIND records were returned for January delivery intervals. "
            "Verify historical endpoint access or import an official export."
        )
    if stats["forecast_records"] == 0:
        stats["errors"].append(
            "No genuine WINDFOR records with publication timestamps were returned for the "
            "requested delivery period. Do not report accuracy metrics without eligible vintages."
        )
    elif stats["eligible_forecasts"] == 0:
        stats["errors"].append(
            "WINDFOR records were returned, but none was published at or before the configured "
            "procurement cutoff for the requested delivery intervals. Verify cutoff settings "
            "and historical publication coverage."
        )
    elif stats["actual_records"] > 0 and stats["matched_intervals"] == 0:
        stats["errors"].append(
            "Actuals and eligible forecasts were found, but no delivery intervals matched on "
            "startTime. Inspect the source timestamps and imported file schemas."
        )
    return stats


def import_from_json(actual_json: list, forecast_json: list, start_date: str, end_date: str) -> dict:
    """Import genuine source records after strict schema and delivery-period checks."""
    stats = {
        "actual_records": 0,
        "forecast_records": 0,
        "eligible_forecasts": 0,
        "matched_intervals": 0,
        "unmatched_intervals": 0,
        "errors": [],
    }
    if not isinstance(actual_json, list) or not isinstance(forecast_json, list):
        raise ValueError("Both imported datasets must contain JSON arrays or an object with a data array.")
    if not actual_json or not forecast_json:
        raise ValueError("Both the actuals and forecast files must contain records.")

    actuals_df = filter_delivery_period(
        normalize_actual_generation(actual_json), start_date, end_date
    )
    forecasts_df = filter_delivery_period(
        normalize_forecast_generation(forecast_json), start_date, end_date
    )
    if actuals_df.empty:
        raise ValueError("No valid WIND actual records in the selected delivery period.")
    if forecasts_df.empty:
        raise ValueError("No valid WINDFOR records with publishTime in the selected delivery period.")

    stats["actual_records"] = int(len(actuals_df))
    stats["forecast_records"] = int(len(forecasts_df))

    insert_actual_generation(actuals_df)
    insert_forecast_generation(forecasts_df)

    selected_forecasts = select_eligible_forecasts(forecasts_df)
    stats["eligible_forecasts"] = int(len(selected_forecasts))
    evaluation_df = evaluate_forecasts(
        actuals_df, selected_forecasts, config.MAPE_EXCLUSION_THRESHOLD
    )
    if not evaluation_df.empty:
        matched = evaluation_df[
            (evaluation_df["has_actual"] == 1) &
            (evaluation_df["has_eligible_forecast"] == 1)
        ]
        stats["matched_intervals"] = int(len(matched))
        stats["unmatched_intervals"] = int(len(evaluation_df) - len(matched))
        insert_evaluation_results(evaluation_df)
    if stats["matched_intervals"] == 0:
        stats["errors"].append(
            "Import succeeded but no interval had both actuals and an eligible pre-cutoff forecast."
        )
    return stats
