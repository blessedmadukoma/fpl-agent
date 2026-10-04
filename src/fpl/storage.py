"""DuckDB helpers. The whole database is one file: data/fpl.duckdb.

Tables that hold several seasons have a `season` column. A loader replaces only the rows it owns (for example one season, or one season and GW), so every loader can be re-run.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from fpl.config import Settings


def connect(settings: Settings) -> duckdb.DuckDBPyConnection:
    return connect_path(settings.db_path)


def connect_path(path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=read_only)


def table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    sql = "select count(*) from information_schema.tables where table_name = ?"
    return con.execute(sql, [table]).fetchone()[0] > 0


def replace_rows(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame, **keys) -> None:
    """Delete the rows of `table` that match `keys`, then insert `df`. The only way data enters the db.

    Example: replace_rows(con, "player_gw", df, season="2026-27")
    Creates the table from `df` if it does not exist yet.
    """

    con.register("_incoming", df)
    try:
        if not table_exists(con, table):
            con.execute(f"create table {table} as select * from _incoming")
            return

        if keys:
            where = " and ".join(f"{column} = ?" for column in keys)
            con.execute(
                f"delete from {table} where {where}", list(keys.values()))

        con.execute(f"insert into {table} by name select * from _incoming")
    finally:
        con.unregister("_incoming")


def query(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    return con.execute(sql, params or []).df()
