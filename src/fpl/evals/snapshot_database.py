from __future__ import annotations

from pathlib import Path

import pandas as pd

from fpl.storage import connect_path
from fpl.team_state import TeamState

REQUIRED_TABLES = {
    "events",
    "fixtures",
    "odds",
    "player_gw",
    "rules",
    "state",
    "teams",
}


def as_utc_timestamp(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def inspect_database(
    database_path: Path,
    *,
    season: str,
    gw: int,
    deadline,
    team: TeamState,
) -> dict:
    with connect_path(database_path, read_only=True) as con:
        tables = [
            row[0]
            for row in con.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema = 'main' and table_type = 'BASE TABLE'
                order by table_name
                """
            ).fetchall()
        ]
        missing_tables = sorted(REQUIRED_TABLES - set(tables))
        if missing_tables:
            raise ValueError(
                f"Snapshot database is missing required tables: {', '.join(missing_tables)}"
            )

        columns_by_table: dict[str, set[str]] = {table: set() for table in tables}
        for table, column in con.execute(
            """
            select table_name, column_name
            from information_schema.columns
            where table_schema = 'main'
            order by table_name, ordinal_position
            """
        ).fetchall():
            columns_by_table[table].add(column)

        table_statistics = {}
        for table in tables:
            quoted_table = _quoted_identifier(table)
            statistics = {
                "row_count": int(
                    con.execute(f"select count(*) from {quoted_table}").fetchone()[0]
                )
            }
            if "season" in columns_by_table[table]:
                statistics["seasons"] = [
                    row[0]
                    for row in con.execute(
                        f"select distinct season from {quoted_table} order by season"
                    ).fetchall()
                ]
            if "gw" in columns_by_table[table]:
                maximum_gw = con.execute(
                    f"select max(gw) from {quoted_table}"
                ).fetchone()[0]
                statistics["max_gw"] = (
                    int(maximum_gw) if maximum_gw is not None else None
                )
            table_statistics[table] = statistics

        event = con.execute(
            "select cast(deadline as varchar) from events where season = ? and gw = ?",
            [season, gw],
        ).fetchone()
        if event is None:
            raise ValueError(f"Snapshot database has no event for {season} GW{gw}")

        database_deadline = as_utc_timestamp(event[0])
        context_deadline = as_utc_timestamp(deadline)
        if database_deadline != context_deadline:
            raise ValueError(
                "Snapshot database deadline does not match the frozen context: "
                f"{database_deadline.isoformat()} != {context_deadline.isoformat()}"
            )

        state_elements = {
            int(row[0])
            for row in con.execute(
                "select element from state where season = ? and gw = ?",
                [season, gw],
            ).fetchall()
        }
        if not state_elements:
            raise ValueError(f"Snapshot database has no state rows for {season} GW{gw}")

        missing_elements = sorted(set(team.elements) - state_elements)
        if missing_elements:
            raise ValueError(
                "Snapshot database state is missing squad elements: "
                + ", ".join(map(str, missing_elements))
            )

    return {
        "season": season,
        "gw": int(gw),
        "deadline": database_deadline.isoformat(),
        "state_row_count": len(state_elements),
        "squad_element_count": len(team.elements),
        "tables": table_statistics,
    }
