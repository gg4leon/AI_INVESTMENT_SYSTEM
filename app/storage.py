"""Historial privado, local, persistente en SQLite. No hay conexión a la nube."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "ais_history.sqlite3"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS simulation_runs (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            source TEXT NOT NULL,
            period TEXT NOT NULL,
            total_return_pct REAL NOT NULL,
            snapshot_json TEXT NOT NULL
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_simulation_created "
        "ON simulation_runs (created_at DESC)"
    )
    connection.commit()
    return connection


def save_run(snapshot: dict, db_path: str | Path = DEFAULT_DB) -> str:
    """Inserta un snapshot de backtest, nunca una operación real."""
    if snapshot.get("schema_version") != 1:
        raise ValueError("Versión de snapshot no compatible")
    required = ("symbol", "source", "period", "backtest")
    if any(key not in snapshot for key in required):
        raise ValueError("Snapshot incompleto")
    encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
    run_id = uuid4().hex
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = _connect(Path(db_path))
    try:
        with connection:
            connection.execute(
                "INSERT INTO simulation_runs "
                "(id, created_at, symbol, source, period, total_return_pct, snapshot_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, created, snapshot["symbol"], snapshot["source"],
                 snapshot["period"], float(snapshot["backtest"]["total_return_pct"]),
                 encoded),
            )
    finally:
        connection.close()
    return run_id


def list_runs(limit: int = 50, db_path: str | Path = DEFAULT_DB) -> list[dict]:
    """Metadatos únicamente; evita cargar grandes series para cada fila."""
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit debe estar entre 1 y 500")
    connection = _connect(Path(db_path))
    try:
        rows = connection.execute(
            "SELECT id, created_at, symbol, source, period, total_return_pct "
            "FROM simulation_runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def get_run(run_id: str, db_path: str | Path = DEFAULT_DB) -> dict | None:
    connection = _connect(Path(db_path))
    try:
        row = connection.execute(
            "SELECT snapshot_json FROM simulation_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return json.loads(row["snapshot_json"]) if row else None
    finally:
        connection.close()
