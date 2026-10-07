import math

import duckdb

from fpl.agent.schemas import (
    ChipGwValues,
    ChipValuesInput,
    ChipValuesResult,
    ComparedPlayer,
    ComparePlayersInput,
    ComparePlayersResult,
    FixtureOutlookInput,
    FixtureOutlookResult,
    FixtureProjection,
    HistoricalLeader,
    HistoricalLeadersInput,
    HistoricalLeadersResult,
    MyTeamSchema,
    PlayerDetails,
    PlayerGwResult,
    PlayerProjection,
    PlayerSummaryInput,
    PlayerSummaryResult,
    RecommendationInput,
    RecommendationResult,
    SelectedGwPlan,
    SquadPlayerSchema,
)
from fpl.context import load_context
from fpl.optimise.chips import chip_values
from fpl.optimise.solver import SolverSettings
from fpl.projections import registry
from fpl.projections.horizon import horizon_table
from fpl.projections.teams import fixture_rates, team_view
from fpl.recommend import recommend_from_projections
from fpl.team_state import TeamState


def get_my_team(snapshot_context, con: duckdb.DuckDBPyConnection) -> MyTeamSchema:
    """Return the frozen squad with player and club details.

    Combine the loaded TeamState with state and teams rows from the snapshot
    database. Preserve squad order and keep prices in tenths of a million pounds.

    Args:
        snapshot_context: Validated snapshot metadata, manifest, team payload
            and reconstructed TeamState.
        con: Open, read-only connection to the frozen database.

    Returns:
        MyTeamSchema containing snapshot metadata, squad details, bank,
        free transfers and chips.

    Raises:
        Exception: A squad player or their club is missing from the database.
    """

    snapshot = snapshot_context["snapshot"]
    manifest = snapshot_context["manifest"]
    payload = snapshot_context["payload"]
    team: TeamState = snapshot_context["team"]

    # build the player list
    squad_players = []

    for player_row in team.squad:
        player_output = con.execute('select element, web_name, position, team, now_cost, status, news from state where season = ? and gw = ? and element = ?', [
            snapshot["season"], snapshot["gw"], player_row.element]).fetchone()

        if player_output is None:
            raise Exception(
                f"Player {player_row.element} not found in state table")

        club_row = con.execute(
            'select team_id, name from teams where season = ? and team_id = ?', [snapshot["season"], player_output[3]]).fetchone()

        if club_row is None:
            raise Exception(
                f"Club with team ID {player_output[3]} not found in teams table")

        player_output = SquadPlayerSchema(
            element_id=player_row.element,
            player_name=player_output[1],
            position=player_output[2],
            club=club_row[1],
            purchase_price=player_row.purchase_price,
            current_price=player_output[4],
            selling_price=player_row.selling_price,
            status=player_output[5],
            news=player_output[6]
        )

        squad_players.append(player_output)

    my_team = MyTeamSchema(
        snapshot_id=snapshot["snapshot_id"],
        snapshot_created_at=manifest["created_at"],
        season=snapshot["season"],
        target_gw=snapshot["gw"],
        deadline=manifest["deadline"],
        team_name=team.team_name,
        based_on_gw=team.based_on_gw,
        bank_in_tenths=payload["bank"],
        free_transfers=team.free_transfers,
        available_chips=[chip for chip in team.chips_available],
        used_chips=[chip for chip in team.chips_used],
        squad_players=squad_players
    )

    return my_team


def _metadata(snapshot_context) -> dict:
    manifest = snapshot_context["manifest"]
    return {
        "snapshot_id": manifest["snapshot_id"],
        "as_of": manifest["created_at"],
        "season": manifest["season"],
        "target_gw": manifest["gw"],
    }


def _club_name(con, season: str, team_id: int) -> str:
    row = con.execute(
        "select name from teams where season = ? and team_id = ?",
        [season, team_id],
    ).fetchone()
    if row is None:
        raise LookupError(f"Club {team_id} is missing in {season}")
    return row[0]


def _player_details(con, manifest: dict, element_id: int) -> PlayerDetails:
    row = con.execute(
        """
        select web_name, position, team, now_cost, status, news
        from state where season = ? and gw = ? and element = ?
        """,
        [manifest["season"], manifest["gw"], element_id],
    ).fetchone()
    if row is None:
        raise LookupError(
            f"Player {element_id} is missing in {manifest['season']} GW{manifest['gw']}"
        )
    return PlayerDetails(
        element_id=element_id, player_name=row[0], position=row[1],
        club=_club_name(con, manifest["season"], row[2]),
        current_price=row[3], status=row[4], news=row[5],
    )


def _context(snapshot_context, con):
    manifest = snapshot_context["manifest"]
    return load_context(con, manifest["season"], manifest["gw"])


def _horizon_gws(ctx, horizon: int) -> list[int]:
    """Limit the requested horizon to the remaining GWs of this season."""
    return list(range(ctx.gw, min(ctx.gw + horizon, 39)))


def _project_horizon(con, ctx, model: str, gws: list[int]):
    projector = registry.build(model, con, ctx.season, first_gw=ctx.gw)
    projected = horizon_table(ctx, projector, gws)
    if not all(math.isfinite(float(value)) for value in projected.to_numpy().flat):
        raise ValueError(
            "Projection model returned non-finite expected points")
    return projected


def get_player_summary(
    snapshot_context, con: duckdb.DuckDBPyConnection, request: PlayerSummaryInput
) -> PlayerSummaryResult:
    """Return recent observed GW results and a next-GW projection for one player."""
    request = PlayerSummaryInput.model_validate(request)
    manifest = snapshot_context["manifest"]
    player = _player_details(con, manifest, request.element_id)
    ctx = _context(snapshot_context, con)
    history_rows = con.execute(
        """
        select gw, minutes, total_points, goals_scored, assists, clean_sheets
        from player_gw
        where season = ? and element = ? and gw < ? and gw >= ?
        order by gw
        """,
        [ctx.season, request.element_id, ctx.gw,
            max(1, ctx.gw - request.history_gws)],
    ).fetchall()
    projections = _project_horizon(con, ctx, request.model, [ctx.gw])
    return PlayerSummaryResult(
        **_metadata(snapshot_context), player=player,
        history=[PlayerGwResult(
            gw=row[0], minutes=row[1], total_points=row[2], goals_scored=row[3],
            assists=row[4], clean_sheets=row[5],
        ) for row in history_rows],
        projection=PlayerProjection(
            gw=ctx.gw, expected_points=float(
                projections.at[request.element_id, ctx.gw])
        ),
        model=request.model,
    )


def compare_players(
    snapshot_context, con: duckdb.DuckDBPyConnection, request: ComparePlayersInput
) -> ComparePlayersResult:
    """Compare two to five players using the same model and frozen GW horizon."""
    request = ComparePlayersInput.model_validate(request)
    details = [
        _player_details(con, snapshot_context["manifest"], element)
        for element in request.element_ids
    ]
    ctx = _context(snapshot_context, con)
    gws = _horizon_gws(ctx, request.horizon)
    projected = _project_horizon(con, ctx, request.model, gws)
    players = [
        ComparedPlayer(
            player=player,
            projections=[PlayerProjection(
                gw=gw, expected_points=float(
                    projected.at[player.element_id, gw])
            ) for gw in gws],
            total_expected_points=float(
                projected.loc[player.element_id, gws].sum()),
        ) for player in details
    ]
    maximum = max(player.total_expected_points for player in players)
    return ComparePlayersResult(
        **_metadata(snapshot_context), gws=gws, model=request.model, players=players,
        best_element_ids=[
            player.player.element_id for player in players
            if player.total_expected_points == maximum
        ],
    )


def get_fixture_outlook(
    snapshot_context, con: duckdb.DuckDBPyConnection, request: FixtureOutlookInput
) -> FixtureOutlookResult:
    """Return each scheduled fixture's attack and clean-sheet estimates for a club."""
    request = FixtureOutlookInput.model_validate(request)
    manifest = snapshot_context["manifest"]
    club = _club_name(con, manifest["season"], request.team_id)
    ctx = _context(snapshot_context, con)
    gws = _horizon_gws(ctx, request.horizon)
    rates = team_view(fixture_rates(con, ctx, gws))
    selected = rates[rates.team == request.team_id].sort_values(
        ["gw", "fixture_id"])
    fixtures = [
        FixtureProjection(
            fixture_id=int(row.fixture_id), gw=int(row.gw),
            opponent_id=int(row.opponent),
            opponent=_club_name(con, ctx.season, int(row.opponent)),
            home=bool(row.home), expected_goals_for=float(row.lambda_for),
            expected_goals_against=float(row.lambda_against),
            clean_sheet_probability=float(row.p_clean_sheet), source=row.source,
        ) for row in selected.itertuples(index=False)
    ]
    return FixtureOutlookResult(
        **_metadata(snapshot_context), team_id=request.team_id, club=club,
        gws=gws, fixtures=fixtures,
    )


def get_chip_values(
    snapshot_context, con: duckdb.DuckDBPyConnection, request: ChipValuesInput
) -> ChipValuesResult:
    """Estimate chip gains for the frozen squad over a bounded horizon.

    This is the example for get_recommendation: load the frozen context,
    build a projector, create the player-by-GW EP table, then call the optimiser
    through an existing library function. No live team reconstruction is needed.
    """
    request = ChipValuesInput.model_validate(request)

    # 1. Use the frozen season/GW and the TeamState already loaded by the service.
    ctx = _context(snapshot_context, con)
    team = snapshot_context["team"]
    gws = _horizon_gws(ctx, request.horizon)

    # 2. Build the expected-points table with the existing projection library.
    projected = _project_horizon(con, ctx, request.model, gws)

    # 3. The chip library calls optimise for the owned squad and the Free Hit squad.
    values = chip_values(projected, ctx.state, team)
    rows = [ChipGwValues(**row) for row in values.to_dict(orient="records")]

    # 4. Return typed data with explicit assumptions.
    best_gws = {
        chip: int(values.loc[values[chip].idxmax(), "gw"])
        for chip in ("triple_captain", "bench_boost", "free_hit")
    }
    return ChipValuesResult(
        **_metadata(snapshot_context), model=request.model, values=rows,
        best_gws=best_gws, available_chips=list(team.chips_available),
        assumptions=[
            "Uses the current frozen squad in every GW; future transfers are not planned.",
            "Values are hypothetical gains even for chips that are no longer available.",
            "The existing optimiser includes its default bench weight in squad selection.",
            "For equal chip values, best_gws selects the earliest GW.",
        ],
    )


def get_historical_leaders(
    snapshot_context, con: duckdb.DuckDBPyConnection, request: HistoricalLeadersInput
) -> HistoricalLeadersResult:
    """Rank observed player-GW statistics for a finished GW in the frozen season."""
    request = HistoricalLeadersInput.model_validate(request)
    manifest = snapshot_context["manifest"]
    event = con.execute(
        "select finished from events where season = ? and gw = ?",
        [manifest["season"], request.gw],
    ).fetchone()
    if request.gw >= manifest["gw"] or event is None or not event[0]:
        raise ValueError(
            "Choose a finished GW before the snapshot's target GW")

    # statistic is a Literal allow-list, never arbitrary model-generated SQL.
    conditions = "season = ? and gw = ?"
    parameters = [manifest["season"], request.gw]
    if request.position is not None:
        conditions += " and position = ?"
        parameters.append(request.position)
    parameters.append(request.limit)
    rows = con.execute(
        f"select element, position, team, {request.statistic} from player_gw "
        f"where {conditions} order by {request.statistic} desc, element asc limit ?",
        parameters,
    ).fetchall()
    if not rows:
        raise LookupError(
            f"No matching player results for {manifest['season']} GW{request.gw}")

    leaders = []
    for rank, (element, position, club_id, value) in enumerate(rows, start=1):
        identity = con.execute(
            "select web_name from state where season = ? and element = ? and gw <= ? "
            "order by gw desc limit 1",
            [manifest["season"], element, manifest["gw"]],
        ).fetchone()
        if identity is None:
            raise LookupError(f"No frozen player name for element {element}")
        leaders.append(HistoricalLeader(
            rank=rank, element_id=element, player_name=identity[0], position=position,
            club=_club_name(con, manifest["season"], club_id), value=float(value),
        ))
    return HistoricalLeadersResult(
        **_metadata(snapshot_context), gw=request.gw, statistic=request.statistic,
        position=request.position, leaders=leaders,
    )


def get_recommendation(snapshot_context, con: duckdb.DuckDBPyConnection, request: RecommendationInput) -> RecommendationResult:
    """Recommend transfers, a starting XI, captain and bench from a frozen snapshot.

    Compare the best transfer plan with a plan that makes no transfers in the
    first GW. Recommend transfers only when their gain meets the threshold.

    Args:
        snapshot_context: Validated snapshot metadata and frozen TeamState.
        con: Open, read-only connection to the frozen database.
        request: Projection model, horizon, transfer threshold and allowed hits.

    Returns:
        RecommendationResult containing the comparison, verdict and selected plan.
    """

    request = RecommendationInput.model_validate(request)

    # Load the frozen GwContext and team.
    ctx = _context(snapshot_context, con)
    team = snapshot_context["team"]
    gws = _horizon_gws(ctx, request.horizon)

    # Build the expected-points table.
    projected = _project_horizon(con, ctx, request.model, gws)

    # Call the existing optimisation library.
    settings = SolverSettings(max_hits_per_gw=request.max_hits)
    recommendation = recommend_from_projections(
        ctx, team, projected, settings, request.threshold)

    # Construct a typed result.
    selected_gw_plans = [
        SelectedGwPlan(
            gw=gw_plan.gw,
            buys=gw_plan.buy,
            sells=gw_plan.sell,
            team_xi=gw_plan.xi,
            ordered_bench=gw_plan.bench,
            captain=gw_plan.captain,
            vice_captain=gw_plan.vice,
            hits=gw_plan.hits,
            expected_points=gw_plan.expected_points,
        )
        for gw_plan in recommendation.chosen.gws
    ]
    return RecommendationResult(
        **_metadata(snapshot_context),
        model=request.model,
        actual_gws=gws,
        threshold=request.threshold,
        allowed_hits=request.max_hits,
        plan_objective=recommendation.plan.objective,
        hold_objective=recommendation.hold.objective,
        gain=recommendation.gain,
        make_transfers=recommendation.make_transfers,
        selected_gw_plans=selected_gw_plans,
        assumptions=[
            "Uses frozen prices, squad and projections; no transfer is executed.",
            "The hold plan forbids transfers in the first GW only.",
            "Objectives include GW discounting, bench weighting and hit penalties.",
            "Later GW transfers are provisional plans, not actions to take now.",
        ],
    )
