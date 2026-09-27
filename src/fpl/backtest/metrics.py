"""Scores for projections. See 01-reference.md §B for why these and not MAE."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def rmse(predicted: pd.Series, actual: pd.Series) -> float:
    return float(np.sqrt(((predicted - actual) ** 2).mean()))


def bias(predicted: pd.Series, actual: pd.Series) -> float:
    return float((predicted - actual).mean())


def mean_rank_correlation(frame: pd.DataFrame, predicted: str, actual: str, by: str = "gw") -> float:
    """Spearman correlation within each GW, averaged over GWs (the solver ranks within a GW)."""
    values = [
        spearmanr(group[predicted], group[actual]).statistic
        for _, group in frame.groupby(by)
        if group[predicted].nunique() > 1
    ]
    return float(np.nanmean(values))


def top_k(frame: pd.DataFrame, predicted: str, actual: str, k: int = 15, by: str = "gw") -> tuple[float, float]:
    """Mean projected and mean realised points of the k highest projections per GW."""
    ranks = frame.groupby(by)[predicted].rank(ascending=False, method="first")
    top = frame[ranks <= k]
    return float(top[predicted].mean()), float(top[actual].mean())


def log_loss(probability: pd.Series, outcome: pd.Series, eps: float = 1e-4) -> float:
    p = probability.clip(eps, 1 - eps)
    return float(-(outcome * np.log(p) + (1 - outcome) * np.log(1 - p)).mean())


def brier(probability: pd.Series, outcome: pd.Series) -> float:
    return float(((probability - outcome) ** 2).mean())
