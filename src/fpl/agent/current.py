"""Prepare fresh data before passing an immutable snapshot to the agent."""

from fpl.config import Settings
from fpl.evals.snapshot import create_snapshot
from fpl.fplapi import FplClient
from fpl.ingest.current import update_current
from fpl.ingest.history import ensure_history
from fpl.ingest.odds import load_odds
from fpl.storage import connect
from fpl.team_state import current_team


def prepare_current_snapshot(settings: Settings, name: str = "ask-current") -> dict:
    """Refresh current inputs, fill missing history, then freeze the closed DB."""
    if not settings.entry_id:
        raise ValueError("Set FPL_ENTRY_ID before preparing a team snapshot.")

    client = FplClient(settings)
    with connect(settings) as con:
        summary = update_current(client, con)
        ensure_history(settings, con, summary["finished_gws"])
        load_odds(settings, con, settings.current_season)
        ctx, team = current_team(con, client, settings.entry_id)

    return create_snapshot(
        ctx, settings, name=name, team=team,
        update_summary=summary, raw_paths=client.saved_raw_paths,
    )
