"""Check conditional history loading with an in-memory database."""

from types import SimpleNamespace

import duckdb
import pytest

from fpl.config import Settings
from fpl.ingest import history


@pytest.fixture
def historical_data(tmp_path, monkeypatch):
    settings = Settings(entry_id=123, data_dir=tmp_path)
    with duckdb.connect(":memory:") as con:
        tables = ("events", "teams", "rules", "state", "fixtures", "player_gw")
        for table in tables:
            con.execute(f"create table {table} (season varchar, gw integer)")

        def fill(table, season, gws):
            for gw in gws:
                con.execute(
                    f"insert into {table} select ?, ? where not exists "
                    f"(select 1 from {table} where season = ? and gw = ?)",
                    [season, gw, season, gw],
                )

        for table in tables:
            fill(table, settings.history_season, [1, 2, 3])
            fill(table, settings.current_season, [1, 2])
        runtime = SimpleNamespace(
            settings=settings, con=con, calls=[], archive_available=True,
        )

        def states(supplied_settings, connection, season, with_metadata=True):
            assert supplied_settings is settings and connection is con
            runtime.calls.append(("states", season, with_metadata))
            if not runtime.archive_available:
                return
            gws = [1, 2, 3] if season == settings.history_season else [1, 2]
            fill("state", season, gws)
            if with_metadata:
                for table in ("events", "teams", "rules"):
                    fill(table, season, gws)

        def results(supplied_settings, connection, season):
            assert supplied_settings is settings and connection is con
            runtime.calls.append(("results", season))
            for table in ("fixtures", "player_gw"):
                fill(table, season, [1, 2, 3])

        monkeypatch.setattr(history, "load_states_from_fplcache", states)
        monkeypatch.setattr(history, "load_vaastav_season", results)
        yield runtime


def test_complete_history_does_not_download_again(historical_data):
    runtime = historical_data

    history.ensure_history(runtime.settings, runtime.con, [1, 2])

    assert runtime.calls == []


def test_missing_current_snapshot_loads_only_current_states(historical_data):
    runtime = historical_data
    runtime.con.execute(
        "delete from state where season = '2026-27' and gw = 2"
    )

    history.ensure_history(runtime.settings, runtime.con, [1, 2])
    history.ensure_history(runtime.settings, runtime.con, [1, 2])

    assert runtime.calls == [("states", "2026-27", False)]
    assert runtime.con.execute(
        "select count(*) from state where season = '2026-27' and gw = 2"
    ).fetchone()[0] == 1


@pytest.mark.parametrize("table", ["events", "teams", "rules", "state"])
def test_missing_previous_inputs_load_only_previous_states(
    historical_data, table,
):
    runtime = historical_data
    runtime.con.execute(f"delete from {table} where season = '2025-26'")

    history.ensure_history(runtime.settings, runtime.con, [1, 2])

    assert runtime.calls == [("states", "2025-26", True)]


@pytest.mark.parametrize("table", ["fixtures", "player_gw"])
def test_missing_previous_results_load_only_previous_results(
    historical_data, table,
):
    runtime = historical_data
    runtime.con.execute(f"delete from {table} where season = '2025-26'")

    history.ensure_history(runtime.settings, runtime.con, [1, 2])

    assert runtime.calls == [("results", "2025-26")]


def test_missing_one_previous_result_week_is_detected(historical_data):
    runtime = historical_data
    runtime.con.execute(
        "delete from player_gw where season = '2025-26' and gw = 2"
    )

    history.ensure_history(runtime.settings, runtime.con, [1, 2])

    assert runtime.calls == [("results", "2025-26")]


def test_first_run_loads_previous_metadata_before_results(historical_data):
    runtime = historical_data
    for table in ("events", "teams", "rules", "state", "fixtures", "player_gw"):
        runtime.con.execute(f"delete from {table} where season = '2025-26'")

    history.ensure_history(runtime.settings, runtime.con, [1, 2])

    assert runtime.calls == [
        ("states", "2025-26", True), ("results", "2025-26"),
    ]


def test_unavailable_archive_warns_without_inventing_state(
    historical_data, caplog,
):
    runtime = historical_data
    runtime.archive_available = False
    runtime.con.execute(
        "delete from state where season = '2026-27' and gw = 2"
    )

    history.ensure_history(runtime.settings, runtime.con, [1, 2])

    assert runtime.calls == [("states", "2026-27", False)]
    assert "Archive did not supply snapshots for 2026-27 GWs [2]" in caplog.text
    assert runtime.con.execute(
        "select count(*) from state where season = '2026-27' and gw = 2"
    ).fetchone()[0] == 0
