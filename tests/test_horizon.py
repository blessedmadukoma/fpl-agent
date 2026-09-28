"""Tests for expanding projections across a gameweek horizon."""

from types import SimpleNamespace

import pandas as pd

from fpl.projections.horizon import horizon_table


def test_horizon_table_repeats_projection_for_requested_gws():
    ctx = SimpleNamespace(
        fixtures=pd.DataFrame(
            {
                "gw": [6, 7],
                "team_h": [1, 2],
                "team_a": [2, 1],
            }
        ),
        state=pd.DataFrame(
            {
                "element": [10, 20],
                "team": [1, 2],
            }
        ),
    )

    def projector(_ctx):
        return pd.Series({10: 5.0, 20: 3.0})

    result = horizon_table(ctx, projector, [6, 7])

    expected = pd.DataFrame({6: [5.0, 3.0], 7: [5.0, 3.0]}, index=[10, 20])
    expected.index.name = "element"
    pd.testing.assert_frame_equal(result, expected, check_names=False)
