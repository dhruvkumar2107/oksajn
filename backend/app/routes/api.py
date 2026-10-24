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


@api_bp.route("/summary", methods=["GET"])
def summary():
    month = request.args.get("month", "2026-01")
    try:
        start_date = f"{month}-01"
        end_date = f"{int(month[:4]) + (int(month[5:]) // 12)}-{(int(month[5:]) % 12) + 1:02d}-01"
        if end_date.endswith("-01"):
            year = int(month[:4])
            mon = int(month[5:]) + 1
            if mon > 12:
                mon = 1
                year += 1
            end_date = f"{year}-{mon:02d}-01"
    except Exception:
        return jsonify({"error": "Invalid month format. Use YYYY-MM"}), 400

    metrics = get_summary_metrics(start_date, end_date)
    mape_result = get_mape(start_date, end_date, config.MAPE_EXCLUSION_THRESHOLD)
    refresh = get_latest_refresh()

    total_intervals = metrics.get("total_intervals", 0) or 0
    matched = metrics.get("matched_intervals", 0) or 0
    coverage = (matched / total_intervals * 100) if total_intervals > 0 else 0

    return jsonify({
        "period": {"start": start_date, "end": end_date},
        "metrics": {
            "mae_mw": round(metrics.get("mae_mw") or metrics.get("mae", 0), 2) if metrics.get("mae_mw") or metrics.get("mae") else None,
            "rmse_mw": round(metrics.get("rmse_mw") or metrics.get("rmse", 0), 2) if metrics.get("rmse_mw") or metrics.get("rmse") else None,
            "bias_mw": round(metrics.get("bias_mw") or metrics.get("bias", 0), 2) if metrics.get("bias_mw") or metrics.get("bias") else None,
            "mape_percent": round(mape_result.get("mape"), 2) if mape_result.get("mape") else None,
            "mape_observations": mape_result.get("valid_observations", 0),
            "mape_exclusion_threshold_mw": config.MAPE_EXCLUSION_THRESHOLD,
        },
        "coverage": {
            "total_intervals": int(total_intervals),
            "intervals_with_actual": int(metrics.get("intervals_with_actual", 0) or 0),
            "intervals_with_forecast": int(metrics.get("intervals_with_forecast", 0) or 0),
            "matched_intervals": int(matched),
            "coverage_percent": round(coverage, 2),
        },
        "data_quality": {
            "period_start": metrics.get("period_start"),
            "period_end": metrics.get("period_end"),
            "last_refresh": refresh,
            "warnings": _generate_warnings(metrics, mape_result),
        }
    })


def _generate_warnings(metrics: dict, mape_result: dict) -> list:
    warnings = []
    total = metrics.get("total_intervals", 0) or 0
    matched = metrics.get("matched_intervals", 0) or 0
    with_actual = metrics.get("intervals_with_actual", 0) or 0
    with_forecast = metrics.get("intervals_with_forecast", 0) or 0

    if total == 0:
        warnings.append("No evaluation data available for this period. Import historical data using POST /api/import")
    elif matched == 0:
        warnings.append("No matched intervals - cannot calculate accuracy metrics")
    elif matched < total * 0.5:
        warnings.append(f"Low evaluation coverage: only {matched}/{total} intervals have both actual and eligible forecast")

    if with_actual == 0:
        warnings.append("No actual generation data available")
    if with_forecast == 0:
        warnings.append("No eligible forecast data available")

    if mape_result.get("valid_observations", 0) == 0:
        warnings.append("MAPE unavailable: no valid observations above exclusion threshold")

    return warnings


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
        start_date = f"{month}-01"
        year = int(month[:4])
        mon = int(month[5:]) + 1
        if mon > 12:
            mon = 1
            year += 1
        end_date = f"{year}-{mon:02d}-01"
    except Exception:
        return jsonify({"error": "Invalid month format. Use YYYY-MM"}), 400

    metrics = get_summary_metrics(start_date, end_date)
    mape_result = get_mape(start_date, end_date, config.MAPE_EXCLUSION_THRESHOLD)

    matched = metrics.get("matched_intervals", 0) or 0

    return jsonify({
        "period": {"start": start_date, "end": end_date},
        "metrics": {
            "mae_mw": {
                "value": round(metrics.get("mae_mw") or metrics.get("mae", 0), 2) if metrics.get("mae_mw") or metrics.get("mae") else None,
                "description": "Mean Absolute Error - average absolute forecast error in MW",
                "sample_count": int(matched),
            },
            "rmse_mw": {
                "value": round(metrics.get("rmse_mw") or metrics.get("rmse", 0), 2) if metrics.get("rmse_mw") or metrics.get("rmse") else None,
                "description": "Root Mean Squared Error - penalizes larger errors more heavily",
                "sample_count": int(matched),
            },
            "bias_mw": {
                "value": round(metrics.get("bias_mw") or metrics.get("bias", 0), 2) if metrics.get("bias_mw") or metrics.get("bias") else None,
                "description": "Mean Error (Bias) - positive means systematic overestimation, negative means underestimation",
                "sample_count": int(matched),
            },
            "mape_percent": {
                "value": round(mape_result.get("mape"), 2) if mape_result.get("mape") else None,
                "description": f"Mean Absolute Percentage Error - calculated only for actuals > {config.MAPE_EXCLUSION_THRESHOLD} MW",
                "sample_count": int(mape_result.get("valid_observations", 0)),
                "exclusion_threshold_mw": config.MAPE_EXCLUSION_THRESHOLD,
            },
            "coverage": {
                "matched_intervals": int(matched),
                "total_intervals": int(metrics.get("total_intervals", 0) or 0),
                "description": "Proportion of delivery intervals with both actual and eligible forecast",
            }
        },
        "interpretation": {
            "mae": "Lower is better. Represents typical absolute forecast error magnitude.",
            "rmse": "Lower is better. More sensitive to large errors than MAE.",
            "bias": "Close to zero is better. Positive = forecasts tend to overestimate wind. Negative = forecasts tend to underestimate wind.",
            "mape": "Lower is better. Percentage error relative to actual generation. Excludes near-zero actuals.",
            "coverage": "Higher is better. Indicates data completeness for evaluation.",
            "caveat": "These metrics evaluate wind forecast accuracy only. They do not determine optimal procurement quantities, which depend on demand, other generation, interconnector flows, balancing costs, and operational constraints."
        }
    })


@api_bp.route("/intervals", methods=["GET"])
def intervals():
    start = request.args.get("start")
    end = request.args.get("end")
    page = int(request.args.get("page", 1))
    page_size = min(int(request.args.get("page_size", 50)), 200)

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
    data = request.get_json() or {}
    start_date = data.get("start_date", "2026-01-01")
    end_date = data.get("end_date", "2026-02-01")

    log_refresh("api_refresh", "started")
    try:
        stats = ingest_and_evaluate_period(start_date, end_date)
        log_refresh("api_refresh", "completed", 
                   records_processed=stats["actual_records"] + stats["forecast_records"],
                   records_inserted=stats["matched_intervals"])
        return jsonify({"status": "success", "stats": stats})
    except Exception as e:
        logger.exception("Refresh failed")
        log_refresh("api_refresh", "failed", error_message=str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route("/import", methods=["POST"])
def import_data():
    if "actual_file" not in request.files or "forecast_file" not in request.files:
        return jsonify({"error": "Both actual_file and forecast_file required"}), 400

    actual_file = request.files["actual_file"]
    forecast_file = request.files["forecast_file"]

    if actual_file.filename == "" or forecast_file.filename == "":
        return jsonify({"error": "No files selected"}), 400

    start_date = request.form.get("start_date", "2026-01-01")
    end_date = request.form.get("end_date", "2026-02-01")

    try:
        import json
        actual_json = json.load(actual_file)
        forecast_json = json.load(forecast_file)

        if not isinstance(actual_json, list):
            actual_json = actual_json.get("data", [])
        if not isinstance(forecast_json, list):
            forecast_json = forecast_json.get("data", [])

    except json.JSONDecodeError as e:
        return jsonify({"error": f"Invalid JSON: {e}"}), 400
    except Exception as e:
        return jsonify({"error": f"File read error: {e}"}), 400

    log_refresh("file_import", "started")
    try:
        stats = import_from_json(actual_json, forecast_json, start_date, end_date)
        log_refresh("file_import", "completed",
                   records_processed=stats["actual_records"] + stats["forecast_records"],
                   records_inserted=stats["matched_intervals"])
        return jsonify({"status": "success", "stats": stats})
    except Exception as e:
        logger.exception("Import failed")
        log_refresh("file_import", "failed", error_message=str(e))
        return jsonify({"status": "error", "message": str(e)}), 500