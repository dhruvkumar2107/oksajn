import logging
from datetime import datetime
from flask import Blueprint, jsonify, request, current_app
import pandas as pd

from ..models import (
    get_evaluation_results,
    get_evaluation_count,
    get_summary_metrics,
    get_mape,
    get_latest_refresh,
    log_refresh,
)
from ..services.data_processor import ingest_and_evaluate_period, import_from_json
from ..config import config

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.errorhandler(Exception)
def handle_unexpected_api_error(error):
    """Log the real exception server-side and keep HTML tracebacks out of API responses."""
    logger.exception("Unhandled API error: %s", error)
    return jsonify({
        "error": "internal_server_error",
        "message": "The API encountered an internal error. The server log contains the diagnostic details.",
    }), 500


def _safe_round(value, decimals=2):
    if value is None or pd.isna(value):
        return None
    try:
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return None


def _month_range(month: str) -> tuple[str, str]:
    """Validate YYYY-MM and return an inclusive start/exclusive end date."""
    parsed = datetime.strptime(month, "%Y-%m")
    start_date = parsed.replace(day=1).date()
    if parsed.month == 12:
        end_date = parsed.replace(year=parsed.year + 1, month=1, day=1).date()
    else:
        end_date = parsed.replace(month=parsed.month + 1, day=1).date()
    return start_date.isoformat(), end_date.isoformat()


@api_bp.route("/health", methods=["GET"])
def health():
    refresh = get_latest_refresh()
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "database": "connected",
        "last_refresh": refresh,
        "config": {
            "decision_cutoff": f"{config.decision_cutoff_time} {config.DECISION_CUTOFF_TIMEZONE}",
            "mape_threshold": config.MAPE_EXCLUSION_THRESHOLD,
        }
    })


def _generate_warnings(metrics: dict, mape_result: dict) -> list:
    """Explain missing or incomplete evaluation data without failing the summary API."""
    warnings = []
    total = int(metrics.get("total_intervals") or 0)
    matched = int(metrics.get("matched_intervals") or 0)
    with_actual = int(metrics.get("intervals_with_actual") or 0)
    with_forecast = int(metrics.get("intervals_with_forecast") or 0)
    valid_mape_observations = int(mape_result.get("valid_observations") or 0)

    if total == 0:
        warnings.append(
            "No evaluation data available for this period. Import genuine Elexon actuals and forecasts or refresh the source data."
        )
    elif matched == 0:
        warnings.append("No matched intervals; forecast accuracy metrics cannot be calculated.")
    elif with_actual and matched < with_actual * 0.5:
        warnings.append(
            f"Low evaluation coverage: {matched}/{with_actual} actual intervals have both actual and eligible forecast data."
        )

    if with_actual == 0:
        warnings.append("No actual wind generation data is available for this period.")
    if with_forecast == 0:
        warnings.append("No eligible forecast data is available for this period.")
    if valid_mape_observations == 0:
        warnings.append(
            f"MAPE is unavailable because no matched actual values exceed the {config.MAPE_EXCLUSION_THRESHOLD:g} MW exclusion threshold."
        )

    return warnings


@api_bp.route("/summary", methods=["GET"])
def summary():
    month = request.args.get("month", "2026-01")
    try:
        start_date, end_date = _month_range(month)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid month format. Use YYYY-MM"}), 400

    metrics = get_summary_metrics(start_date, end_date)
    mape_result = get_mape(start_date, end_date, config.MAPE_EXCLUSION_THRESHOLD)
    refresh = get_latest_refresh()

    total_intervals = int(metrics.get("total_intervals") or 0)
    with_actual = int(metrics.get("intervals_with_actual") or 0)
    with_forecast = int(metrics.get("intervals_with_forecast") or 0)
    matched = int(metrics.get("matched_intervals") or 0)
    # Evaluation coverage uses actual delivery intervals as the denominator,
    # as required by the assignment, not the union of actual/forecast rows.
    coverage = matched / with_actual * 100 if with_actual else 0.0

    return jsonify({
        "period": {"start": start_date, "end": end_date},
        "metrics": {
            "mae_mw": _safe_round(metrics.get("mae")),
            "rmse_mw": _safe_round(metrics.get("rmse")),
            "bias_mw": _safe_round(metrics.get("bias")),
            "mape_percent": _safe_round(mape_result.get("mape")),
            "mape_observations": int(mape_result.get("valid_observations") or 0),
            "mape_exclusion_threshold_mw": config.MAPE_EXCLUSION_THRESHOLD,
        },
        "coverage": {
            "total_intervals": total_intervals,
            "intervals_with_actual": with_actual,
            "intervals_with_forecast": with_forecast,
            "matched_intervals": matched,
            "coverage_denominator": with_actual,
            "coverage_percent": round(coverage, 2),
        },
        "data_quality": {
            "period_start": metrics.get("period_start"),
            "period_end": metrics.get("period_end"),
            "latest_eligible_forecast_publish_time": metrics.get("latest_forecast_publish_time"),
            "last_refresh": refresh,
            "warnings": _generate_warnings(metrics, mape_result),
        },
    })


@api_bp.route("/forecasts", methods=["GET"])
def forecasts():
    start = request.args.get("start")
    end = request.args.get("end")

    if not start or not end:
        return jsonify({"error": "start and end parameters required (ISO 8601)"}), 400

    try:
        start_dt = pd.Timestamp(start)
        end_dt = pd.Timestamp(end)
    except Exception:
        return jsonify({"error": "Invalid timestamp format"}), 400

    start_date = start_dt.date().isoformat()
    end_date = end_dt.date().isoformat()

    results = get_evaluation_results(start_date, end_date)
    
    if results.empty:
        return jsonify({"data": [], "count": 0, "message": "No data for requested period"})

    records = results.to_dict("records")
    for r in records:
        r["error_mw"] = round(r["error_mw"], 2) if pd.notna(r["error_mw"]) else None
        r["absolute_error_mw"] = round(r["absolute_error_mw"], 2) if pd.notna(r["absolute_error_mw"]) else None
        r["actual_generation_mw"] = round(r["actual_generation_mw"], 2) if pd.notna(r["actual_generation_mw"]) else None
        r["selected_forecast_generation_mw"] = round(r["selected_forecast_generation_mw"], 2) if pd.notna(r["selected_forecast_generation_mw"]) else None

    return jsonify({"data": records, "count": len(records)})


@api_bp.route("/accuracy", methods=["GET"])
def accuracy():
    month = request.args.get("month", "2026-01")
    try:
        start_date, end_date = _month_range(month)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid month format. Use YYYY-MM"}), 400

    metrics = get_summary_metrics(start_date, end_date)
    mape_result = get_mape(start_date, end_date, config.MAPE_EXCLUSION_THRESHOLD)
    matched = int(metrics.get("matched_intervals") or 0)
    actual_count = int(metrics.get("intervals_with_actual") or 0)
    total_intervals = int(metrics.get("total_intervals") or 0)
    coverage_percent = matched / actual_count * 100 if actual_count else 0.0

    return jsonify({
        "period": {"start": start_date, "end": end_date},
        "metrics": {
            "mae_mw": {
                "value": _safe_round(metrics.get("mae")),
                "description": "Mean Absolute Error — average absolute forecast error in MW",
                "sample_count": matched,
            },
            "rmse_mw": {
                "value": _safe_round(metrics.get("rmse")),
                "description": "Root Mean Squared Error — penalizes larger errors more heavily",
                "sample_count": matched,
            },
            "bias_mw": {
                "value": _safe_round(metrics.get("bias")),
                "description": "Mean Error (Bias) — positive means overestimation; negative means underestimation",
                "sample_count": matched,
            },
            "mape_percent": {
                "value": _safe_round(mape_result.get("mape")),
                "description": f"Mean Absolute Percentage Error — only actuals above {config.MAPE_EXCLUSION_THRESHOLD} MW",
                "sample_count": int(mape_result.get("valid_observations") or 0),
                "exclusion_threshold_mw": config.MAPE_EXCLUSION_THRESHOLD,
            },
            "coverage": {
                "matched_intervals": matched,
                "total_intervals": total_intervals,
                "intervals_with_actual": actual_count,
                "coverage_denominator": actual_count,
                "coverage_percent": round(coverage_percent, 2),
                "description": "Matched eligible forecast/actual intervals divided by actual intervals available for evaluation",
            },
        },
        "interpretation": {
            "mae": "Lower is better. Represents typical absolute forecast error magnitude.",
            "rmse": "Lower is better. More sensitive to large errors than MAE.",
            "bias": "Close to zero is better. Positive means forecasts tend to overestimate wind; negative means underestimation.",
            "mape": "Lower is better. Percentage error relative to actual generation; excludes near-zero actuals.",
            "coverage": "Higher is better. Indicates how much of the available actual series had a valid, eligible forecast.",
            "caveat": "These metrics evaluate wind forecast accuracy only. They do not determine optimal procurement quantities, which depend on demand, other generation, interconnector flows, balancing costs, and operational constraints.",
        },
    })


@api_bp.route("/intervals", methods=["GET"])
def intervals():
    start = request.args.get("start")
    end = request.args.get("end")
    try:
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 50))
    except (TypeError, ValueError):
        return jsonify({"error": "page and page_size must be integers"}), 400
    if page < 1 or page_size < 1:
        return jsonify({"error": "page and page_size must be positive integers"}), 400
    page_size = min(page_size, 200)

    if not start or not end:
        return jsonify({"error": "start and end parameters required (ISO 8601)"}), 400

    try:
        start_dt = pd.Timestamp(start)
        end_dt = pd.Timestamp(end)
    except Exception:
        return jsonify({"error": "Invalid timestamp format"}), 400

    start_date = start_dt.date().isoformat()
    end_date = end_dt.date().isoformat()

    total = get_evaluation_count(start_date, end_date)
    offset = (page - 1) * page_size
    results = get_evaluation_results(start_date, end_date, limit=page_size, offset=offset)

    records = results.to_dict("records")
    for r in records:
        r["error_mw"] = round(r["error_mw"], 2) if pd.notna(r["error_mw"]) else None
        r["absolute_error_mw"] = round(r["absolute_error_mw"], 2) if pd.notna(r["absolute_error_mw"]) else None
        r["actual_generation_mw"] = round(r["actual_generation_mw"], 2) if pd.notna(r["actual_generation_mw"]) else None
        r["selected_forecast_generation_mw"] = round(r["selected_forecast_generation_mw"], 2) if pd.notna(r["selected_forecast_generation_mw"]) else None

    return jsonify({
        "data": records,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": int(total),
            "total_pages": (int(total) + page_size - 1) // page_size,
        }
    })


@api_bp.route("/intervals/export", methods=["GET"])
def export_intervals():
    start = request.args.get("start")
    end = request.args.get("end")

    if not start or not end:
        return jsonify({"error": "start and end parameters required"}), 400

    try:
        start_dt = pd.Timestamp(start)
        end_dt = pd.Timestamp(end)
    except Exception:
        return jsonify({"error": "Invalid timestamp format"}), 400

    start_date = start_dt.date().isoformat()
    end_date = end_dt.date().isoformat()

    results = get_evaluation_results(start_date, end_date, limit=100000, offset=0)

    if results.empty:
        return jsonify({"error": "No data to export"}), 404

    csv_data = results.to_csv(index=False)
    from flask import Response
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=wind_forecast_evaluation_{start_date}_to_{end_date}.csv"}
    )


@api_bp.route("/refresh", methods=["POST"])
def refresh():
    data = request.get_json(silent=True) or {}
    start_date = data.get("start_date", "2026-01-01")
    end_date = data.get("end_date", "2026-02-01")

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        if end <= start:
            return jsonify({"status": "error", "message": "end_date must be after start_date"}), 400
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Dates must use YYYY-MM-DD"}), 400

    log_refresh("api_refresh", "started")
    try:
        stats = ingest_and_evaluate_period(start_date, end_date)
        if stats.get("errors"):
            message = "; ".join(stats["errors"])
            log_refresh(
                "api_refresh", "failed",
                records_processed=stats["actual_records"] + stats["forecast_records"],
                records_inserted=stats["matched_intervals"],
                error_message=message,
            )
            return jsonify({"status": "error", "message": message, "stats": stats}), 502

        log_refresh(
            "api_refresh", "completed",
            records_processed=stats["actual_records"] + stats["forecast_records"],
            records_inserted=stats["matched_intervals"],
        )
        return jsonify({"status": "success", "stats": stats})
    except Exception as exc:
        logger.exception("Refresh failed")
        log_refresh("api_refresh", "failed", error_message=str(exc))
        return jsonify({"status": "error", "message": "Refresh failed; inspect backend logs."}), 500


def _load_import_records(upload):
    """Read a bounded JSON or CSV upload and return source rows."""
    import csv
    import io
    import json
    from pathlib import Path

    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".json", ".csv"}:
        raise ValueError(f"Unsupported file type for {upload.filename!r}; use .json or .csv.")

    raw = upload.read()
    if not raw:
        raise ValueError(f"{upload.filename or 'Uploaded file'} is empty.")

    if suffix == ".json":
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{upload.filename}: invalid UTF-8 JSON file.") from exc
        if isinstance(payload, dict):
            payload = payload.get("data")
        if not isinstance(payload, list):
            raise ValueError(f"{upload.filename}: expected a JSON array or an object containing a data array.")
        return payload

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{upload.filename}: CSV must be UTF-8 encoded.") from exc
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError(f"{upload.filename}: CSV header row is missing.")
        rows = list(reader)
    except csv.Error as exc:
        raise ValueError(f"{upload.filename}: malformed CSV.") from exc
    if not rows:
        raise ValueError(f"{upload.filename}: CSV contains no records.")
    # DictReader returns strings. Empty values become None so the normalizers
    # can consistently reject incomplete rows.
    return [{k: (v if v != "" else None) for k, v in row.items() if k is not None} for row in rows]


@api_bp.route("/import", methods=["POST"])
def import_data():
    if "actual_file" not in request.files or "forecast_file" not in request.files:
        return jsonify({"status": "error", "message": "Both actual_file and forecast_file are required."}), 400

    actual_file = request.files["actual_file"]
    forecast_file = request.files["forecast_file"]
    if not actual_file.filename or not forecast_file.filename:
        return jsonify({"status": "error", "message": "Choose both the actuals and forecast files."}), 400

    start_date = request.form.get("start_date", "2026-01-01")
    end_date = request.form.get("end_date", "2026-02-01")
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        if end <= start:
            return jsonify({"status": "error", "message": "end_date must be after start_date."}), 400
        actual_records = _load_import_records(actual_file)
        forecast_records = _load_import_records(forecast_file)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    log_refresh("file_import", "started")
    try:
        stats = import_from_json(actual_records, forecast_records, start_date, end_date)
        warning = "; ".join(stats.get("errors", []))
        if stats["actual_records"] == 0 or stats["forecast_records"] == 0:
            log_refresh(
                "file_import", "failed",
                records_processed=stats["actual_records"] + stats["forecast_records"],
                records_inserted=stats["matched_intervals"],
                error_message=warning or "No valid records were imported.",
            )
            return jsonify({
                "status": "error",
                "message": warning or "No valid source records were imported.",
                "stats": stats,
            }), 422

        log_refresh(
            "file_import", "completed",
            records_processed=stats["actual_records"] + stats["forecast_records"],
            records_inserted=stats["matched_intervals"],
            records_failed=stats["unmatched_intervals"],
            error_message=warning or None,
        )
        return jsonify({"status": "success", "stats": stats, "message": warning or "Import completed."})
    except Exception:
        logger.exception("Historical data import failed")
        log_refresh("file_import", "failed", error_message="Import failed; inspect server logs.")
        return jsonify({"status": "error", "message": "Import failed. Check that both files contain valid Elexon records and inspect backend logs."}), 500
