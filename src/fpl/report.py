"""Everything that prints. Library code returns data; this module turns it into text."""

from __future__ import annotations

import pandas as pd

POSITION_ORDER = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}


def table(df: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    """Format a DataFrame for the terminal with consistent number formatting."""
    formatters = {
        c: floatfmt.format for c in df.columns if pd.api.types.is_float_dtype(df[c])}
    return df.to_string(index=False, formatters=formatters)


def money(tenths: float) -> str:
    return f"£{tenths / 10:.1f}m"
