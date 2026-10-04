"""Create and validate immutable evaluation snapshots."""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from fpl.config import Settings
from fpl.context import GwContext
from fpl.evals.snapshot_database import as_utc_timestamp, inspect_database
from fpl.evals.snapshot_files import (
    calculate_file_sha256,
    copy_raw_responses,
    file_metadata,
    git_metadata,
    read_manifest,
    read_team_json,
    write_manifest_json,
    write_team_json,
)
from fpl.team_state import TeamState


def _snapshot_member(snapshot_dir: Path, relative_path: str) -> Path:
    root = snapshot_dir.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Snapshot manifest path escapes its directory: {relative_path}"
        ) from exc
    return candidate


def _validate_file(path: Path, expected: dict) -> None:
    if not path.is_file():
        raise ValueError(f"Snapshot file is missing: {path}")
    actual = file_metadata(path)
    if actual["size_bytes"] != expected.get("size_bytes"):
        raise ValueError(f"Snapshot file size does not match manifest: {path}")
    if actual["sha256"] != expected.get("sha256"):
        raise ValueError(f"Snapshot file hash does not match manifest: {path}")


def validate_snapshot(snapshot_dir: Path) -> dict:
    snapshot_dir = snapshot_dir.resolve()
    database_path = snapshot_dir / "fpl.duckdb"
    team_path = snapshot_dir / "team.json"
    manifest_path = snapshot_dir / "manifest.json"

    for required_path in (database_path, team_path, manifest_path):
        if not required_path.is_file():
            raise ValueError(f"Snapshot file is missing: {required_path}")

    manifest = read_manifest(snapshot_dir)
    try:
        files = manifest["files"]
        database_expected = files["database"]
        team_expected = files["team"]
        raw_expected = files["raw"]
        snapshot_id = str(manifest["snapshot_id"])
        season = str(manifest["season"])
        gw = int(manifest["gw"])
        deadline = manifest["deadline"]
        refresh = manifest["refresh"]
        refresh_season = str(refresh["season"])
        refresh_gw = int(refresh["next_gw"])
        refresh_deadline = refresh["next_deadline"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid manifest schema: {manifest_path}") from exc

    if refresh_season != season:
        raise ValueError("Refresh season does not match manifest season")
    if refresh_gw != gw:
        raise ValueError("Refresh next GW does not match manifest GW")
    if as_utc_timestamp(refresh_deadline) != as_utc_timestamp(deadline):
        raise ValueError("Refresh deadline does not match manifest deadline")

    if database_expected.get("filename") != "fpl.duckdb":
        raise ValueError("Manifest database filename must be fpl.duckdb")
    if team_expected.get("filename") != "team.json":
        raise ValueError("Manifest team filename must be team.json")

    _validate_file(database_path, database_expected)
    _validate_file(team_path, team_expected)

    checked_raw_paths = []
    for expected in raw_expected:
        try:
            relative_path = str(expected["path"])
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Invalid raw-file manifest entry: {expected}") from exc
        raw_path = _snapshot_member(snapshot_dir, relative_path)
        _validate_file(raw_path, expected)
        checked_raw_paths.append(relative_path)

    team_payload, team = read_team_json(team_path)
    if str(team_payload["snapshot_id"]) != snapshot_id:
        raise ValueError("team.json snapshot ID does not match manifest")

    database_inspection = inspect_database(
        database_path,
        season=season,
        gw=gw,
        deadline=deadline,
        team=team,
    )
    if database_inspection != manifest.get("database"):
        raise ValueError("Database inspection does not match manifest")

    return {
        "status": "valid",
        "snapshot_id": snapshot_id,
        "season": season,
        "gw": gw,
        "checked_file_count": 2 + len(checked_raw_paths),
        "raw_file_count": len(checked_raw_paths),
    }


def _player_names(ctx: GwContext) -> dict[int, str]:
    required_columns = {"element", "web_name"}
    missing_columns = required_columns - set(ctx.state.columns)
    if missing_columns:
        raise ValueError(
            "Frozen state is missing player-name columns: "
            + ", ".join(sorted(missing_columns))
        )
    return {
        int(element): str(name)
        for element, name in zip(ctx.state.element, ctx.state.web_name)
    }


def create_snapshot(
    ctx: GwContext,
    settings: Settings,
    name: str,
    team: TeamState,
    update_summary: dict,
    raw_paths: Iterable[Path] = (),
) -> dict:
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("Snapshot name must be one non-empty path segment")

    created_at = datetime.now(UTC)
    timestamp = created_at.strftime("%Y%m%d_%H%M%S")
    git = git_metadata()
    git_label = git["commit"][:8] if git["commit"] else "no-git"
    if git["dirty"]:
        git_label += "-dirty"
    snapshot_id = f"{timestamp}_{name}_{git_label}"

    base_dir = settings.data_dir / "evals" / "snapshots"
    temp_dir = base_dir / f"tmp_{snapshot_id}"
    final_dir = base_dir / snapshot_id

    if final_dir.exists():
        raise FileExistsError(f"Snapshot already exists: {final_dir}")
    temp_dir.mkdir(parents=True, exist_ok=False)

    try:
        dest_db = temp_dir / "fpl.duckdb"
        if not settings.db_path.is_file():
            raise FileNotFoundError(f"Database not found: {settings.db_path}")
        shutil.copy2(settings.db_path, dest_db)

        team_path = temp_dir / "team.json"
        write_team_json(team_path, snapshot_id, team, _player_names(ctx))

        raw_files = copy_raw_responses(
            raw_paths,
            source_root=settings.raw_dir,
            destination_root=temp_dir / "raw",
        )

        database_inspection = inspect_database(
            dest_db,
            season=ctx.season,
            gw=ctx.gw,
            deadline=ctx.deadline,
            team=team,
        )
        database_file = file_metadata(dest_db)
        team_file = file_metadata(team_path)

        manifest_path = temp_dir / "manifest.json"
        write_manifest_json(
            manifest_path,
            snapshot_id=snapshot_id,
            name=name,
            created_at=created_at,
            ctx=ctx,
            git=git,
            database_file=database_file,
            team_file=team_file,
            raw_files=raw_files,
            database_inspection=database_inspection,
            settings=settings,
            update_summary=update_summary,
        )
        manifest_file = file_metadata(manifest_path)
        validation = validate_snapshot(temp_dir)

        if final_dir.exists():
            raise FileExistsError(f"Snapshot already exists: {final_dir}")
        temp_dir.rename(final_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return {
        "snapshot_id": snapshot_id,
        "final_path": str(final_dir),
        "season": ctx.season,
        "gw": int(ctx.gw),
        "git": git,
        "database_file": database_file,
        "database_inspection": database_inspection,
        "team_file": team_file,
        "manifest_file": manifest_file,
        "raw_files": raw_files,
        "raw_file_count": len(raw_files),
        "validation_result": validation,
    }
