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
