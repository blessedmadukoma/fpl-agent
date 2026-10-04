import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from fpl import report
from fpl.config import Settings
from fpl.evals import snapshot
from fpl.evals import snapshot_files
from fpl.evals.snapshot import (
    calculate_file_sha256,
    create_snapshot,
    file_metadata,
    git_metadata,
    validate_snapshot,
    write_team_json,
)
from fpl.team_state import SquadPlayer, TeamState


def create_test_database(path):
    with duckdb.connect(str(path)) as con:
        con.execute("create table events (season varchar, gw integer, deadline timestamptz)")
        con.execute("create table fixtures (season varchar, gw integer)")
        con.execute("create table odds (season varchar, gw integer)")
        con.execute("create table player_gw (season varchar, gw integer)")
        con.execute("create table rules (season varchar)")
        con.execute("create table state (season varchar, gw integer, element integer)")
        con.execute("create table teams (season varchar)")
        con.execute(
            "insert into events values ('2026-27', 6, '2026-10-10 10:00:00+00')"
        )
        con.execute("insert into fixtures values ('2026-27', 6)")
        con.execute("insert into odds values ('2026-27', 6)")
        con.execute("insert into player_gw values ('2026-27', 5)")
        con.execute("insert into rules values ('2026-27')")
        con.execute("insert into state values ('2026-27', 6, 10)")
        con.execute("insert into teams values ('2026-27')")


def make_team():
    return TeamState(
        entry_id=123,
        team_name="Test Team",
        based_on_gw=5,
        squad=(SquadPlayer(element=10, purchase_price=50, selling_price=52),),
        bank=7,
        free_transfers=2,
        chips_available=(),
        chips_used=(),
    )


def make_context(season="2026-27", gw=6):
    return SimpleNamespace(
        season=season,
        gw=gw,
        deadline="2026-10-10T10:00:00+00:00",
        state=pd.DataFrame({"element": [10], "web_name": ["Player Ten"]}),
    )


def make_update_summary():
    return {
        "season": "2026-27",
        "players": 1,
        "finished_gws": [1, 2, 3, 4, 5],
        "player_gw_rows": 5,
        "next_gw": 6,
        "next_deadline": "2026-10-10T10:00:00+00:00",
    }


def create_valid_snapshot(tmp_path, monkeypatch, name="baseline"):
    settings = Settings(entry_id=123, data_dir=tmp_path)
    create_test_database(settings.db_path)
    raw_path = settings.raw_dir / "2026-10-04" / "120000_bootstrap_static.json.gz"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"raw response")
    monkeypatch.setattr(
        snapshot, "git_metadata", lambda: {"commit": "abc123def456", "dirty": False}
    )
    result = create_snapshot(
        make_context(),
        settings,
        name,
        make_team(),
        update_summary=make_update_summary(),
        raw_paths=[raw_path],
    )
    return settings, result, Path(result["final_path"])


def rewrite_manifest(snapshot_dir, change):
    path = snapshot_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_write_team_json_serialises_team_state(tmp_path):
    team = TeamState(
        entry_id=123,
        team_name="Test Team",
        based_on_gw=5,
        squad=(SquadPlayer(element=10, purchase_price=50, selling_price=52),),
        bank=7,
        free_transfers=2,
        chips_available=("wildcard (until GW19)",),
        chips_used=("freehit (GW3)",),
    )
    target = tmp_path / "team.json"

    write_team_json(target, "snapshot-1", team, {10: "Player Ten"})

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "snapshot_id": "snapshot-1",
        "entry_id": 123,
        "team_name": "Test Team",
        "based_on_gw": 5,
        "bank": 7,
        "free_transfers": 2,
        "chips_available": ["wildcard (until GW19)"],
        "chips_used": ["freehit (GW3)"],
        "squad": [
            {
                "element": 10,
                "name": "Player Ten",
                "purchase_price": 50,
                "selling_price": 52,
            }
        ],
    }
    assert target.read_bytes().endswith(b"\n")


def test_git_metadata_reports_commit_and_dirty_state(monkeypatch):
    outputs = iter(["abc123def456\n", " M src/fpl/config.py\n"])

    def fake_run(*args, **kwargs):
        return SimpleNamespace(stdout=next(outputs))

    monkeypatch.setattr(snapshot_files.subprocess, "run", fake_run)

    assert git_metadata() == {"commit": "abc123def456", "dirty": True}


def test_file_metadata_reports_size_and_sha256(tmp_path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"original")

    original = file_metadata(target)
    target.write_bytes(b"changed")

    assert original == {
        "filename": "sample.bin",
        "size_bytes": 8,
        "sha256": "0682c5f2076f099c34cfdd15a9e063849ed437a49677e6fcc5b4198c76575be5",
    }
    assert calculate_file_sha256(target) != original["sha256"]


def test_create_snapshot_writes_team_json(tmp_path, monkeypatch):
    settings = Settings(entry_id=123, data_dir=tmp_path)
    create_test_database(settings.db_path)
    team = TeamState(
        entry_id=123,
        team_name="Test Team",
        based_on_gw=5,
        squad=(SquadPlayer(element=10, purchase_price=50, selling_price=52),),
        bank=7,
        free_transfers=2,
        chips_available=(),
        chips_used=(),
    )
    monkeypatch.setattr(
        snapshot, "git_metadata", lambda: {"commit": "abc123def456", "dirty": False}
    )
    raw_path = settings.raw_dir / "2026-10-04" / "120000_bootstrap_static.json.gz"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"raw response")

    result = create_snapshot(
        make_context(),
        settings,
        "baseline",
        team,
        update_summary={
            "season": "2026-27",
            "players": 1,
            "finished_gws": [1, 2, 3, 4, 5],
            "player_gw_rows": 5,
            "next_gw": 6,
            "next_deadline": "2026-10-10T10:00:00+00:00",
        },
        raw_paths=[raw_path],
    )

    snapshot_dirs = list((tmp_path / "evals" / "snapshots").iterdir())
    assert len(snapshot_dirs) == 1
    assert (snapshot_dirs[0] / "fpl.duckdb").is_file()
    saved_team = json.loads(
        (snapshot_dirs[0] / "team.json").read_text(encoding="utf-8")
    )
    assert saved_team["snapshot_id"].endswith("_baseline_abc123de")
    assert saved_team["squad"][0]["element"] == 10
    assert saved_team["squad"][0]["name"] == "Player Ten"
    assert result["database_file"]["size_bytes"] > 0
    assert result["database_file"]["sha256"] == calculate_file_sha256(
        snapshot_dirs[0] / "fpl.duckdb"
    )
    assert result["team_file"]["sha256"] == calculate_file_sha256(
        snapshot_dirs[0] / "team.json"
    )
    copied_raw = snapshot_dirs[0] / "raw" / "2026-10-04" / raw_path.name
    assert copied_raw.read_bytes() == b"raw response"
    assert result["raw_file_count"] == 1
    assert result["raw_files"][0] == {
        "filename": raw_path.name,
        "path": f"raw/2026-10-04/{raw_path.name}",
        "size_bytes": 12,
        "sha256": calculate_file_sha256(copied_raw),
    }
    assert result["database_inspection"]["season"] == "2026-27"
    assert result["database_inspection"]["gw"] == 6
    assert result["database_inspection"]["state_row_count"] == 1
    assert result["database_inspection"]["squad_element_count"] == 1
    assert result["database_inspection"]["tables"]["events"] == {
        "row_count": 1,
        "seasons": ["2026-27"],
        "max_gw": 6,
    }
    manifest = json.loads(
        (snapshot_dirs[0] / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["snapshot_id"] == saved_team["snapshot_id"]
    assert manifest["name"] == "baseline"
    assert manifest["season"] == "2026-27"
    assert manifest["gw"] == 6
    assert manifest["git"] == {"commit": "abc123def456", "dirty": False}
    assert manifest["files"]["database"] == result["database_file"]
    assert manifest["files"]["team"] == result["team_file"]
    assert manifest["files"]["raw"] == result["raw_files"]
    assert manifest["database"] == result["database_inspection"]
    assert manifest["refresh"]["operation"] == "update_current"
    assert manifest["refresh"]["next_gw"] == 6
    assert "update_current" in manifest["raw_response_scope"]["description"]
    assert result["manifest_file"]["sha256"] == calculate_file_sha256(
        snapshot_dirs[0] / "manifest.json"
    )
    assert result["validation_result"]["status"] == "valid"
    assert Path(result["final_path"]) == snapshot_dirs[0]
    assert not snapshot_dirs[0].name.startswith("tmp_")


@pytest.mark.parametrize("name", ["", ".", "..", "../bad", "bad/name"])
def test_create_snapshot_rejects_invalid_names(tmp_path, name):
    settings = Settings(entry_id=123, data_dir=tmp_path)

    with pytest.raises(ValueError, match="Snapshot name"):
        create_snapshot(
            make_context(),
            settings,
            name,
            make_team(),
            update_summary=make_update_summary(),
        )


def test_missing_source_database_leaves_no_snapshot(tmp_path, monkeypatch):
    settings = Settings(entry_id=123, data_dir=tmp_path)
    monkeypatch.setattr(
        snapshot, "git_metadata", lambda: {"commit": "abc123def456", "dirty": False}
    )

    with pytest.raises(FileNotFoundError, match="Database not found"):
        create_snapshot(
            make_context(),
            settings,
            "missing-db",
            make_team(),
            update_summary=make_update_summary(),
        )

    snapshots_dir = tmp_path / "evals" / "snapshots"
    assert not snapshots_dir.exists() or list(snapshots_dir.iterdir()) == []


def test_existing_snapshot_id_is_rejected(tmp_path, monkeypatch):
    fixed_time = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)

    class FixedDatetime:
        @classmethod
        def now(cls, tz=None):
            return fixed_time

    monkeypatch.setattr(snapshot, "datetime", FixedDatetime)
    create_valid_snapshot(tmp_path, monkeypatch, name="duplicate")

    with pytest.raises(FileExistsError, match="Snapshot already exists"):
        create_snapshot(
            make_context(),
            Settings(entry_id=123, data_dir=tmp_path),
            "duplicate",
            make_team(),
            update_summary=make_update_summary(),
        )


def test_raw_file_outside_configured_directory_leaves_no_snapshot(tmp_path, monkeypatch):
    settings = Settings(entry_id=123, data_dir=tmp_path)
    create_test_database(settings.db_path)
    outside = tmp_path / "outside.json.gz"
    outside.write_bytes(b"raw")
    monkeypatch.setattr(
        snapshot, "git_metadata", lambda: {"commit": "abc123def456", "dirty": False}
    )

    with pytest.raises(ValueError, match="outside the configured raw directory"):
        create_snapshot(
            make_context(),
            settings,
            "outside-raw",
            make_team(),
            update_summary=make_update_summary(),
            raw_paths=[outside],
        )

    assert list((tmp_path / "evals" / "snapshots").iterdir()) == []


def test_missing_raw_file_leaves_no_snapshot(tmp_path, monkeypatch):
    settings = Settings(entry_id=123, data_dir=tmp_path)
    create_test_database(settings.db_path)
    missing = settings.raw_dir / "missing.json.gz"
    monkeypatch.setattr(
        snapshot, "git_metadata", lambda: {"commit": "abc123def456", "dirty": False}
    )

    with pytest.raises(FileNotFoundError, match="Raw response not found"):
        create_snapshot(
            make_context(),
            settings,
            "missing-raw",
            make_team(),
            update_summary=make_update_summary(),
            raw_paths=[missing],
        )

    assert list((tmp_path / "evals" / "snapshots").iterdir()) == []


def test_modified_database_fails_validation(tmp_path, monkeypatch):
    _, _, snapshot_dir = create_valid_snapshot(tmp_path, monkeypatch)
    with (snapshot_dir / "fpl.duckdb").open("ab") as database:
        database.write(b"changed")

    with pytest.raises(ValueError, match="file size"):
        validate_snapshot(snapshot_dir)


def test_modified_team_json_fails_validation(tmp_path, monkeypatch):
    _, _, snapshot_dir = create_valid_snapshot(tmp_path, monkeypatch)
    with (snapshot_dir / "team.json").open("a", encoding="utf-8") as team_file:
        team_file.write(" ")

    with pytest.raises(ValueError, match="file size"):
        validate_snapshot(snapshot_dir)


def test_modified_raw_response_fails_validation(tmp_path, monkeypatch):
    _, result, snapshot_dir = create_valid_snapshot(tmp_path, monkeypatch)
    raw_path = snapshot_dir / result["raw_files"][0]["path"]
    raw_path.write_bytes(b"changed raw")

    with pytest.raises(ValueError, match="file size"):
        validate_snapshot(snapshot_dir)


def test_malformed_team_json_fails_validation(tmp_path, monkeypatch):
    _, _, snapshot_dir = create_valid_snapshot(tmp_path, monkeypatch)
    team_path = snapshot_dir / "team.json"
    team_path.write_text("{not-json", encoding="utf-8")
    rewrite_manifest(
        snapshot_dir,
        lambda manifest: manifest["files"].update({"team": file_metadata(team_path)}),
    )

    with pytest.raises(ValueError, match="Invalid team JSON"):
        validate_snapshot(snapshot_dir)


def test_missing_required_database_table_fails_validation(tmp_path, monkeypatch):
    _, _, snapshot_dir = create_valid_snapshot(tmp_path, monkeypatch)
    database_path = snapshot_dir / "fpl.duckdb"
    with duckdb.connect(str(database_path)) as con:
        con.execute("drop table odds")
    rewrite_manifest(
        snapshot_dir,
        lambda manifest: manifest["files"].update(
            {"database": file_metadata(database_path)}
        ),
    )

    with pytest.raises(ValueError, match="missing required tables: odds"):
        validate_snapshot(snapshot_dir)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("season", "2099-00", "Refresh season"),
        ("gw", 99, "Refresh next GW"),
    ],
)
def test_wrong_manifest_context_fails_validation(
    tmp_path, monkeypatch, field, value, message
):
    _, _, snapshot_dir = create_valid_snapshot(tmp_path, monkeypatch)
    rewrite_manifest(
        snapshot_dir, lambda manifest: manifest.update({field: value})
    )

    with pytest.raises(ValueError, match=message):
        validate_snapshot(snapshot_dir)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("season", "2099-00", "Refresh season"),
        ("next_gw", 99, "Refresh next GW"),
        ("next_deadline", "2099-01-01T00:00:00+00:00", "Refresh deadline"),
    ],
)
def test_refresh_context_must_match_manifest(
    tmp_path, monkeypatch, field, value, message
):
    _, _, snapshot_dir = create_valid_snapshot(tmp_path, monkeypatch)
    rewrite_manifest(
        snapshot_dir,
        lambda manifest: manifest["refresh"].update({field: value}),
    )

    with pytest.raises(ValueError, match=message):
        validate_snapshot(snapshot_dir)


def test_failed_validation_does_not_create_final_directory(tmp_path, monkeypatch):
    settings = Settings(entry_id=123, data_dir=tmp_path)
    create_test_database(settings.db_path)
    monkeypatch.setattr(
        snapshot, "git_metadata", lambda: {"commit": "abc123def456", "dirty": False}
    )
    monkeypatch.setattr(
        snapshot,
        "validate_snapshot",
        lambda path: (_ for _ in ()).throw(ValueError("forced validation failure")),
    )

    with pytest.raises(ValueError, match="forced validation failure"):
        create_snapshot(
            make_context(),
            settings,
            "invalid",
            make_team(),
            update_summary=make_update_summary(),
        )

    assert list((tmp_path / "evals" / "snapshots").iterdir()) == []


def test_print_snapshot_reports_final_result(capsys):
    report.print_snapshot(
        {
            "snapshot_id": "snapshot-1",
            "final_path": "/tmp/snapshot-1",
            "season": "2026-27",
            "gw": 6,
            "git": {"commit": "abc123", "dirty": False},
            "database_file": {"sha256": "db-hash"},
            "team_file": {"sha256": "team-hash"},
            "raw_file_count": 4,
            "validation_result": {"status": "valid"},
        }
    )

    output = capsys.readouterr().out
    assert "Snapshot snapshot-1 (valid)" in output
    assert "Season / GW   2026-27 / GW6" in output
    assert "Git           abc123 (clean)" in output
