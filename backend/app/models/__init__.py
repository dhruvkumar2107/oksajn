import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
import pandas as pd

from ..config import config


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS actual_generation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_date TEXT NOT NULL,
    settlement_period INTEGER NOT NULL,
    start_time_utc TEXT NOT NULL,
    publish_time_utc TEXT NOT NULL,
    generation_mw REAL NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(settlement_date, settlement_period, publish_time_utc)
);

CREATE TABLE IF NOT EXISTS forecast_generation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_date TEXT NOT NULL,
    settlement_period INTEGER NOT NULL,
    start_time_utc TEXT NOT NULL,
    publish_time_utc TEXT NOT NULL,
    generation_mw REAL NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(settlement_date, settlement_period, publish_time_utc)
);

CREATE TABLE IF NOT EXISTS evaluation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_date TEXT NOT NULL,
    settlement_period INTEGER NOT NULL,
    start_time_utc TEXT NOT NULL,
    actual_generation_mw REAL,
    selected_forecast_generation_mw REAL,
    selected_forecast_publish_time_utc TEXT,
    error_mw REAL,
    absolute_error_mw REAL,
    is_overestimation INTEGER,
    is_underestimation INTEGER,
    has_eligible_forecast INTEGER DEFAULT 0,
    has_actual INTEGER DEFAULT 0,
    evaluation_status TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(settlement_date, settlement_period)
);

CREATE TABLE IF NOT EXISTS data_refresh_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_type TEXT NOT NULL,
    status TEXT NOT NULL,
    records_processed INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(refresh_type, started_at)
);

CREATE INDEX IF NOT EXISTS idx_actual_date_period ON actual_generation(settlement_date, settlement_period);
CREATE INDEX IF NOT EXISTS idx_forecast_date_period ON forecast_generation(settlement_date, settlement_period);
CREATE INDEX IF NOT EXISTS idx_evaluation_date_period ON evaluation_results(settlement_date, settlement_period);
CREATE INDEX IF NOT EXISTS idx_forecast_publish_time ON forecast_generation(publish_time_utc);
"""


def get_db_connection() -> sqlite3.Connection:
    db_path = Path(config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_transaction():
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables and migrate older persistent SQLite databases in place.

    CREATE TABLE IF NOT EXISTS does not add columns to an existing table. Since
    Render may retain a SQLite file across deployments, keep the expected
    evaluation columns forward-compatible without deleting any user data.
    """
    with db_transaction() as conn:
        conn.executescript(SCHEMA_SQL)

        # SQLite-compatible additive migrations only. Existing rows and tables
        # are preserved. Columns added here are nullable because old rows cannot
        # always be reconstructed from the old schema.
        migrations = {
            "actual_generation": {
                "settlement_date": "TEXT",
                "settlement_period": "INTEGER",
                "start_time_utc": "TEXT",
                "publish_time_utc": "TEXT",
                "generation_mw": "REAL",
                "created_at": "TEXT",
            },
            "forecast_generation": {
                "settlement_date": "TEXT",
                "settlement_period": "INTEGER",
                "start_time_utc": "TEXT",
                "publish_time_utc": "TEXT",
                "generation_mw": "REAL",
                "created_at": "TEXT",
            },
            "evaluation_results": {
                "settlement_date": "TEXT",
                "settlement_period": "INTEGER",
                "start_time_utc": "TEXT",
                "actual_generation_mw": "REAL",
                "selected_forecast_generation_mw": "REAL",
                "selected_forecast_publish_time_utc": "TEXT",
                "error_mw": "REAL",
                "absolute_error_mw": "REAL",
                "is_overestimation": "INTEGER DEFAULT 0",
                "is_underestimation": "INTEGER DEFAULT 0",
                "has_eligible_forecast": "INTEGER DEFAULT 0",
                "has_actual": "INTEGER DEFAULT 0",
                "evaluation_status": "TEXT",
                "created_at": "TEXT",
            },
            "data_refresh_log": {
                "refresh_type": "TEXT",
                "status": "TEXT",
                "records_processed": "INTEGER DEFAULT 0",
                "records_inserted": "INTEGER DEFAULT 0",
                "records_failed": "INTEGER DEFAULT 0",
                "error_message": "TEXT",
                "started_at": "TEXT",
                "completed_at": "TEXT",
            },
        }

        for table_name, expected_columns in migrations.items():
            existing_columns = {
                row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
            for column_name, column_type in expected_columns.items():
                if column_name not in existing_columns:
                    conn.execute(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {column_type}'
                    )

        # Additive column migrations can introduce columns referenced by new
        # queries, so create/recreate indexes after the migration pass.
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_actual_date_period
                ON actual_generation(settlement_date, settlement_period);
            CREATE INDEX IF NOT EXISTS idx_forecast_date_period
                ON forecast_generation(settlement_date, settlement_period);
            CREATE INDEX IF NOT EXISTS idx_evaluation_date_period
                ON evaluation_results(settlement_date, settlement_period);
            CREATE INDEX IF NOT EXISTS idx_forecast_publish_time
                ON forecast_generation(publish_time_utc);
        """)


def insert_actual_generation(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    with db_transaction() as conn:
        data = df.to_dict("records")
        placeholders = ", ".join(["?"] * 6)
        sql = f"""
            INSERT OR IGNORE INTO actual_generation 
            (settlement_date, settlement_period, start_time_utc, publish_time_utc, generation_mw, created_at)
            VALUES ({placeholders})
        """
        params = [
            (
                r["settlement_date"],
                r["settlement_period"],
                r["start_time_utc"].isoformat() if hasattr(r["start_time_utc"], 'isoformat') else str(r["start_time_utc"]),
                r["publish_time_utc"].isoformat() if hasattr(r["publish_time_utc"], 'isoformat') else str(r["publish_time_utc"]),
                r["generation_mw"],
                r.get("created_at", pd.Timestamp.utcnow().isoformat()),
            )
            for r in data
        ]
        cursor = conn.executemany(sql, params)
        return cursor.rowcount


def insert_forecast_generation(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    with db_transaction() as conn:
        data = df.to_dict("records")
        placeholders = ", ".join(["?"] * 6)
        sql = f"""
            INSERT OR IGNORE INTO forecast_generation 
            (settlement_date, settlement_period, start_time_utc, publish_time_utc, generation_mw, created_at)
            VALUES ({placeholders})
        """
        params = [
            (
                r["settlement_date"],
                r["settlement_period"],
                r["start_time_utc"].isoformat() if hasattr(r["start_time_utc"], 'isoformat') else str(r["start_time_utc"]),
                r["publish_time_utc"].isoformat() if hasattr(r["publish_time_utc"], 'isoformat') else str(r["publish_time_utc"]),
                r["generation_mw"],
                r.get("created_at", pd.Timestamp.utcnow().isoformat()),
            )
            for r in data
        ]
        cursor = conn.executemany(sql, params)
        return cursor.rowcount


def get_actual_generation(start_date: str, end_date: str) -> pd.DataFrame:
    with get_db_connection() as conn:
        sql = """
            SELECT * FROM actual_generation
            WHERE settlement_date >= ? AND settlement_date < ?
            ORDER BY settlement_date, settlement_period
        """
        return pd.read_sql_query(sql, conn, params=(start_date, end_date))


def get_forecast_generation(start_date: str, end_date: str) -> pd.DataFrame:
    with get_db_connection() as conn:
        sql = """
            SELECT * FROM forecast_generation
            WHERE settlement_date >= ? AND settlement_date < ?
            ORDER BY settlement_date, settlement_period, publish_time_utc
        """
        return pd.read_sql_query(sql, conn, params=(start_date, end_date))


def insert_evaluation_results(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    with db_transaction() as conn:
        data = df.to_dict("records")
        placeholders = ", ".join(["?"] * 14)
        sql = f"""
            INSERT OR REPLACE INTO evaluation_results 
            (settlement_date, settlement_period, start_time_utc, actual_generation_mw,
             selected_forecast_generation_mw, selected_forecast_publish_time_utc,
             error_mw, absolute_error_mw, is_overestimation, is_underestimation,
             has_eligible_forecast, has_actual, evaluation_status, created_at)
            VALUES ({placeholders})
        """
        def fmt_ts(ts):
            if ts is None or (isinstance(ts, float) and pd.isna(ts)):
                return None
            return ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
        
        params = [
            (
                r["settlement_date"],
                r["settlement_period"],
                fmt_ts(r["start_time_utc"]),
                r.get("actual_generation_mw"),
                r.get("selected_forecast_generation_mw"),
                fmt_ts(r.get("selected_forecast_publish_time_utc")),
                r.get("error_mw"),
                r.get("absolute_error_mw"),
                r.get("is_overestimation", 0),
                r.get("is_underestimation", 0),
                r.get("has_eligible_forecast", 0),
                r.get("has_actual", 0),
                r.get("evaluation_status", "evaluated"),
                r.get("created_at", pd.Timestamp.utcnow().isoformat()),
            )
            for r in data
        ]
        cursor = conn.executemany(sql, params)
        return cursor.rowcount


def get_evaluation_results(start_date: str, end_date: str, limit: int = 1000, offset: int = 0) -> pd.DataFrame:
    with get_db_connection() as conn:
        sql = """
            SELECT * FROM evaluation_results
            WHERE settlement_date >= ? AND settlement_date < ?
            ORDER BY settlement_date, settlement_period
            LIMIT ? OFFSET ?
        """
        return pd.read_sql_query(sql, conn, params=(start_date, end_date, limit, offset))


def get_evaluation_count(start_date: str, end_date: str) -> int:
    with get_db_connection() as conn:
        sql = """
            SELECT COUNT(*) as cnt FROM evaluation_results
            WHERE settlement_date >= ? AND settlement_date < ?
        """
        cursor = conn.execute(sql, (start_date, end_date))
        return cursor.fetchone()["cnt"]


def get_summary_metrics(start_date: str, end_date: str) -> dict:
    """Return aggregate forecast metrics without requiring SQLite's optional SQRT()."""
    import math

    with get_db_connection() as conn:
        sql = """
            SELECT
                COUNT(*) AS total_intervals,
                COALESCE(SUM(has_actual), 0) AS intervals_with_actual,
                COALESCE(SUM(has_eligible_forecast), 0) AS intervals_with_forecast,
                COALESCE(SUM(CASE WHEN has_actual = 1 AND has_eligible_forecast = 1
                                  THEN 1 ELSE 0 END), 0) AS matched_intervals,
                AVG(CASE WHEN has_actual = 1 AND has_eligible_forecast = 1
                         THEN absolute_error_mw END) AS mae,
                AVG(CASE WHEN has_actual = 1 AND has_eligible_forecast = 1
                         THEN error_mw * error_mw END) AS mse,
                AVG(CASE WHEN has_actual = 1 AND has_eligible_forecast = 1
                         THEN error_mw END) AS bias,
                MIN(start_time_utc) AS period_start,
                MAX(start_time_utc) AS period_end
            FROM evaluation_results
            WHERE settlement_date >= ? AND settlement_date < ?
        """
        row = conn.execute(sql, (start_date, end_date)).fetchone()
        result = dict(row) if row else {}
        mse = result.pop("mse", None)
        result["rmse"] = math.sqrt(float(mse)) if mse is not None else None
        return result


def get_mape(start_date: str, end_date: str, threshold: float = 1.0) -> dict:
    with get_db_connection() as conn:
        sql = """
            SELECT 
                AVG(ABS(error_mw) / ABS(actual_generation_mw)) * 100 as mape,
                COUNT(*) as valid_observations
            FROM evaluation_results
            WHERE settlement_date >= ? AND settlement_date < ?
              AND has_actual = 1 AND has_eligible_forecast = 1
              AND ABS(actual_generation_mw) > ?
        """
        cursor = conn.execute(sql, (start_date, end_date, threshold))
        row = cursor.fetchone()
        return dict(row) if row else {"mape": None, "valid_observations": 0}


def log_refresh(refresh_type: str, status: str, records_processed: int = 0, 
                records_inserted: int = 0, records_failed: int = 0, error_message: str = None):
    with db_transaction() as conn:
        sql = """
            INSERT INTO data_refresh_log 
            (refresh_type, status, records_processed, records_inserted, records_failed, error_message, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        now = pd.Timestamp.utcnow().isoformat()
        conn.execute(sql, (refresh_type, status, records_processed, records_inserted, records_failed, error_message, now, now))


def get_latest_refresh() -> Optional[dict]:
    with get_db_connection() as conn:
        sql = "SELECT * FROM data_refresh_log ORDER BY started_at DESC LIMIT 1"
        cursor = conn.execute(sql)
        row = cursor.fetchone()
        return dict(row) if row else None