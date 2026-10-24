import sqlite3

from app import create_app
from app.config import config
from app.models import init_db


def test_summary_endpoint_returns_json_for_empty_database(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "summary-test.db"))
    app = create_app()
    app.config.update(TESTING=True)

    response = app.test_client().get("/api/summary?month=2026-01")

    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["period"] == {"start": "2026-01-01", "end": "2026-02-01"}
    assert payload["metrics"]["mae_mw"] is None
    assert payload["coverage"]["total_intervals"] == 0
    assert isinstance(payload["data_quality"]["warnings"], list)


def test_init_db_migrates_older_evaluation_table_without_deleting_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_path))

    # Simulate a persistent SQLite file created by an older application version.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE evaluation_results (id INTEGER PRIMARY KEY, settlement_date TEXT)"
        )
        conn.execute(
            "INSERT INTO evaluation_results (settlement_date) VALUES (?)",
            ("2026-01-15",),
        )
        conn.commit()

    init_db()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT settlement_date, has_actual, has_eligible_forecast "
            "FROM evaluation_results WHERE settlement_date = ?",
            ("2026-01-15",),
        ).fetchone()

    assert row == ("2026-01-15", 0, 0)



def test_summary_and_accuracy_calculate_metrics_from_matched_intervals(tmp_path, monkeypatch):
    db_path = tmp_path / "metrics-test.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_path))
    app = create_app()
    app.config.update(TESTING=True)

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO evaluation_results
              (settlement_date, settlement_period, start_time_utc,
               actual_generation_mw, selected_forecast_generation_mw,
               selected_forecast_publish_time_utc, error_mw, absolute_error_mw,
               is_overestimation, is_underestimation, has_eligible_forecast,
               has_actual, evaluation_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-01-15", 1, "2026-01-15T00:00:00+00:00",
                 1000.0, 1100.0, "2026-01-14T10:30:00+00:00",
                 100.0, 100.0, 1, 0, 1, 1, "evaluated", "2026-01-15T00:00:00Z"),
                ("2026-01-15", 2, "2026-01-15T00:30:00+00:00",
                 1200.0, 1100.0, "2026-01-14T10:30:00+00:00",
                 -100.0, 100.0, 0, 1, 1, 1, "evaluated", "2026-01-15T00:30:00Z"),
            ],
        )
        conn.commit()

    client = app.test_client()
    summary_response = client.get("/api/summary?month=2026-01")
    accuracy_response = client.get("/api/accuracy?month=2026-01")

    assert summary_response.status_code == 200
    summary = summary_response.get_json()
    assert summary["metrics"]["mae_mw"] == 100.0
    assert summary["metrics"]["rmse_mw"] == 100.0
    assert summary["metrics"]["bias_mw"] == 0.0
    assert summary["coverage"]["matched_intervals"] == 2
    assert summary["coverage"]["coverage_percent"] == 100.0
    assert summary["data_quality"]["latest_eligible_forecast_publish_time"] == "2026-01-14T10:30:00+00:00"

    assert accuracy_response.status_code == 200
    accuracy = accuracy_response.get_json()
    assert accuracy["metrics"]["mae_mw"]["value"] == 100.0
    assert accuracy["metrics"]["rmse_mw"]["value"] == 100.0
    assert accuracy["metrics"]["bias_mw"]["value"] == 0.0
    assert accuracy["metrics"]["mape_percent"]["sample_count"] == 2



def test_refresh_completes_a_bounded_date_range_synchronously(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "sync-refresh-test.db"))
    app = create_app()
    app.config.update(TESTING=True)
    expected_stats = {
        "actual_records": 240,
        "forecast_records": 2200,
        "eligible_forecasts": 168,
        "matched_intervals": 168,
        "unmatched_intervals": 72,
        "errors": [],
    }
    calls = []

    def fake_ingest(start_date, end_date):
        calls.append((start_date, end_date))
        return expected_stats

    monkeypatch.setattr("app.routes.api.ingest_and_evaluate_period", fake_ingest)
    client = app.test_client()
    response = client.post(
        "/api/refresh",
        json={"start_date": "2026-01-01", "end_date": "2026-01-08"},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["status"] == "success"
    assert payload["stats"] == expected_stats
    assert calls == [("2026-01-01", "2026-01-08")]
