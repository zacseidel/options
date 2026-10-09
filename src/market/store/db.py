"""DuckDB connection and schema bootstrap.

One file (`paths.db`), one writer (the daily run). Readers in the same process share the
connection; tests pass an explicit path (or ':memory:').
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import duckdb
import pandas as pd

from market.config import path

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(db_path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    target = str(db_path) if db_path is not None else str(path("db"))
    con = duckdb.connect(target)
    con.execute(SCHEMA.read_text())
    return con


@contextmanager
def transaction(con: duckdb.DuckDBPyConnection) -> Iterator[duckdb.DuckDBPyConnection]:
    con.execute("BEGIN TRANSACTION")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def replace_rows(con: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame, where: str, params: list) -> int:
    """Delete rows matching `where`, then insert `frame` (columns by name) — in one transaction."""
    with transaction(con):
        con.execute(f"DELETE FROM {table} WHERE {where}", params)
        if not frame.empty:
            con.register("_incoming", frame)
            columns = ", ".join(frame.columns)
            con.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM _incoming")
            con.unregister("_incoming")
    return len(frame)


def log_fetch(con: duckdb.DuckDBPyConnection, source: str, key: str, rows: int | None, immutable: bool) -> None:
    con.execute(
        "INSERT OR REPLACE INTO fetch_log VALUES (?, ?, ?, ?, ?)",
        [source, key, datetime.now(), rows, immutable],
    )


def already_fetched(con: duckdb.DuckDBPyConnection, source: str, key: str) -> bool:
    """True when an immutable fetch is recorded — the no-refetch rule (PLAN §3)."""
    row = con.execute(
        "SELECT immutable FROM fetch_log WHERE source = ? AND key = ?", [source, key]
    ).fetchone()
    return bool(row and row[0])
