import duckdb
import pandas as pd
import pytest

from fpl.context import load_context
from fpl.projections import minutes as minutes_model
from fpl.projections.minutes import flag_category, news_kind


def test_flag_categories():
    assert flag_category("a", None) == "none"
    assert flag_category("d", 75) == "d75"
    assert flag_category("i", 0) == "out"


def test_news_kind_reads_the_return_date():
    deadline = pd.Timestamp("2026-10-10 10:00", tz="UTC")
    assert news_kind("Hamstring injury - Expected back 10 Oct",
                     deadline) == "back_by_deadline"
    assert news_kind("Knee injury - Expected back 7 Nov",
                     deadline) == "back_later"
    assert news_kind("Knee injury - Unknown return date",
                     deadline) == "unknown_return"
    assert news_kind("", deadline) == "none"


@pytest.fixture
def training_db():
    with duckdb.connect(":memory:") as con:
        con.execute(
            "create table events "
            "(season varchar, gw integer, deadline timestamptz)"
        )
        con.execute(
            "create table state "
            "(season varchar, gw integer, element integer, status varchar, "
            "chance double, news varchar, position varchar)"
        )
        con.execute(
            "create table player_gw "
            "(season varchar, gw integer, element integer, "
            "starts integer, minutes double)"
        )
        con.execute("create table fixtures (season varchar, gw integer)")
        con.execute("create table teams (season varchar, team_id integer)")
        yield con


def add_training_week(con, season, gw):
    con.execute(
        "insert into events values (?, ?, '2026-10-01T10:00:00+00:00')",
        [season, gw],
    )
    con.executemany(
        "insert into state values (?, ?, ?, 'a', null, '', ?)",
        [(season, gw, 1, "GKP"), (season, gw, 2, "DEF"),
         (season, gw, 3, "MID")],
    )
    con.executemany(
        "insert into player_gw values (?, ?, ?, ?, ?)",
        [(season, gw, 1, 1, 90), (season, gw, 2, 0, 30),
         (season, gw, 3, 0, 0)],
    )


def test_gw9_training_skips_missing_gw8_state(training_db, caplog):
    for gw in range(1, 10):
        add_training_week(training_db, "2026-27", gw)
    training_db.execute("delete from state where gw = 8")

    gws = minutes_model.training_gws(training_db, "2026-27", 9, None)

    assert gws == [("2026-27", gw) for gw in range(2, 8)]
    assert "2026-27 GW8" in caplog.text
    # Use real features and regressions, not a mocked training implementation.
    model = minutes_model.train(training_db, gws)
    ctx = load_context(training_db, "2026-27", 9)
    predictions = model.predict(minutes_model.features(ctx))
    assert len(predictions) == 3
    assert predictions.e_minutes.between(0, 90).all()
    # Skipping a training example must not discard actual GW8 history.
    assert 8 in ctx.history.gw.to_list()
    assert training_db.execute(
        "select count(*) from state where gw = 8"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("remove_input", [
    "delete from state where gw = 3",
    "delete from player_gw where gw = 3",
    "delete from events where gw = 3",
    "update events set deadline = null where gw = 3",
    "update player_gw set element = element + 100 where gw = 3",
])
def test_training_requires_matching_state_results_and_deadline(
    training_db, caplog, remove_input,
):
    for gw in range(1, 7):
        add_training_week(training_db, "2026-27", gw)
    training_db.execute(remove_input)

    gws = minutes_model.training_gws(training_db, "2026-27", 5, None)

    assert gws == [("2026-27", 2), ("2026-27", 4)]
    assert "2026-27 GW3" in caplog.text


def test_training_preserves_previous_season_and_current_gw_cutoff(
    training_db, caplog,
):
    for season in ("2024-25", "2025-26", "2026-27"):
        for gw in (1, 2, 3, 4):
            add_training_week(training_db, season, gw)
    training_db.execute(
        "delete from player_gw where season = '2025-26' and gw = 3"
    )

    gws = minutes_model.training_gws(
        training_db, "2026-27", 4, "2025-26",
    )

    assert gws == [
        ("2025-26", 2), ("2025-26", 4),
        ("2026-27", 2), ("2026-27", 3),
    ]
    assert "2025-26 GW3" in caplog.text


def test_training_can_use_previous_season_without_current_snapshots(
    training_db, caplog,
):
    add_training_week(training_db, "2025-26", 2)

    assert minutes_model.training_gws(
        training_db, "2026-27", 3, "2025-26",
    ) == [("2025-26", 2)]
    assert "2026-27 GW2" in caplog.text


def test_training_reports_when_no_usable_gameweeks_exist(training_db):
    add_training_week(training_db, "2026-27", 2)
    training_db.execute("delete from state")

    with pytest.raises(LookupError, match="No usable minutes-model training"):
        minutes_model.training_gws(training_db, "2026-27", 3, None)


def test_training_keeps_all_eligible_weeks_without_warning(training_db, caplog):
    for gw in range(1, 6):
        add_training_week(training_db, "2026-27", gw)

    assert minutes_model.training_gws(
        training_db, "2026-27", 4, None,
    ) == [("2026-27", 2), ("2026-27", 3)]
    assert not caplog.records
