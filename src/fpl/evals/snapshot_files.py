from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path

from fpl.config import PROJECT_ROOT, Settings
from fpl.context import GwContext
from fpl.evals.snapshot_database import as_utc_timestamp
from fpl.team_state import SquadPlayer, TeamState


def write_team_json(
    target: Path,
    snapshot_id: str,
    team: TeamState,
    player_names: Mapping[int, str],
) -> None:
    missing_names = sorted(set(team.elements) - set(player_names))
    if missing_names:
        raise ValueError(
            "Player names are missing for squad elements: "
            + ", ".join(map(str, missing_names))
        )

    payload = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "entry_id": team.entry_id,
        "team_name": team.team_name,
        "based_on_gw": team.based_on_gw,
        "bank": team.bank,
        "free_transfers": team.free_transfers,
        "chips_available": list(team.chips_available),
        "chips_used": list(team.chips_used),
        "squad": [
            {
                "element": player.element,
                "name": str(player_names[player.element]),
                "purchase_price": player.purchase_price,
                "selling_price": player.selling_price,
            }
            for player in team.squad
        ],
    }
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_team_json(source: Path) -> tuple[dict, TeamState]:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid team JSON: {source}") from exc

    try:
        if payload["schema_version"] != 1:
            raise ValueError(
                f"Unsupported team schema version: {payload['schema_version']}"
            )
        team = TeamState(
            entry_id=int(payload["entry_id"]),
            team_name=str(payload["team_name"]),
            based_on_gw=int(payload["based_on_gw"]),
            squad=tuple(
                SquadPlayer(
                    element=int(player["element"]),
                    purchase_price=int(player["purchase_price"]),
                    selling_price=int(player["selling_price"]),
                )
                for player in payload["squad"]
            ),
            bank=int(payload["bank"]),
            free_transfers=int(payload["free_transfers"]),
            chips_available=tuple(map(str, payload["chips_available"])),
            chips_used=tuple(map(str, payload["chips_used"])),
        )
        str(payload["snapshot_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid team schema: {source}") from exc

    return payload, team


def write_manifest_json(
    target: Path,
    *,
    snapshot_id: str,
    name: str,
    created_at: datetime,
    ctx: GwContext,
    git: dict,
    database_file: dict,
    team_file: dict,
    raw_files: list[dict],
    database_inspection: dict,
    settings: Settings,
    update_summary: dict,
) -> None:
    payload = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "name": name,
        "created_at": created_at.isoformat(),
        "season": ctx.season,
        "gw": int(ctx.gw),
        "deadline": as_utc_timestamp(ctx.deadline).isoformat(),
        "git": git,
        "files": {
            "database": database_file,
            "team": team_file,
            "raw": raw_files,
        },
        "database": database_inspection,
        "configuration": {
            "current_season": settings.current_season,
            "history_season": settings.history_season,
            "fpl_base_url": settings.fpl_base_url,
        },
        "refresh": {
            "operation": "update_current",
            "season": update_summary["season"],
            "players": int(update_summary["players"]),
            "finished_gws": [int(gw) for gw in update_summary["finished_gws"]],
            "player_gw_rows": int(update_summary["player_gw_rows"]),
            "next_gw": int(update_summary["next_gw"]),
            "next_deadline": as_utc_timestamp(
                update_summary["next_deadline"]
            ).isoformat(),
        },
        "raw_response_scope": {
            "description": (
                "Responses written by one FplClient during update_current and "
                "current_team for this freeze"
            ),
            "includes": [
                "bootstrap-static",
                "fixtures",
                "finished-GW live data",
                "entry",
                "entry history",
                "entry transfers",
                "entry picks",
                "element summaries when required",
            ],
            "excludes": [
                "historical fplcache and vaastav inputs",
                "odds downloaded before this freeze",
                "raw inputs from earlier database loads",
            ],
        },
    }
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def git_metadata() -> dict:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        return {"commit": commit, "dirty": dirty}
    except (FileNotFoundError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def calculate_file_sha256(file_path: Path, chunk_size: int = 65536) -> str:
    sha256_context = hashlib.sha256()
    with file_path.open("rb") as file:
        while chunk := file.read(chunk_size):
            sha256_context.update(chunk)
    return sha256_context.hexdigest()


def file_metadata(file_path: Path) -> dict:
    return {
        "filename": file_path.name,
        "size_bytes": file_path.stat().st_size,
        "sha256": calculate_file_sha256(file_path),
    }


def copy_raw_responses(
    raw_paths: Iterable[Path], source_root: Path, destination_root: Path
) -> list[dict]:
    source_root = source_root.resolve()
    destination_root.mkdir()
    copied_files = []

    sources = sorted({Path(path).resolve() for path in raw_paths})
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(f"Raw response not found: {source}")
        try:
            relative_path = source.relative_to(source_root)
        except ValueError as exc:
            raise ValueError(
                f"Raw response is outside the configured raw directory: {source}"
            ) from exc

        destination = destination_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

        metadata = file_metadata(destination)
        metadata["path"] = str(Path("raw") / relative_path)
        copied_files.append(metadata)

    return copied_files


def read_manifest(snapshot_dir: Path) -> dict:
    manifest_path = snapshot_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Snapshot is missing manifest.json: {snapshot_dir}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid manifest JSON: {manifest_path}") from exc

    if manifest.get("schema_version") != 1:
        raise ValueError(
            f"Unsupported manifest schema version: {manifest.get('schema_version')}"
        )
    return manifest
