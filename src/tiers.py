from __future__ import annotations

import math
from typing import Dict

import pandas as pd


def assign_tiers(df: pd.DataFrame, score_col: str, config: Dict[str, float], tier_col: str = "tier") -> pd.DataFrame:
    frame = df.sort_values(score_col, ascending=False).reset_index(drop=True).copy()
    std = frame[score_col].std(ddof=0)
    threshold = max(
        float(config["score_gap_factor"]) * (std if not math.isnan(std) else 0.0),
        float(config.get("min_score_gap", 0.25)),
    )
    max_players_per_tier = int(config.get("max_players_per_tier", 999999))

    tiers = []
    current_tier = 1
    previous_score = None
    players_in_tier = 0
    for score in frame[score_col]:
        if previous_score is not None and (
            (previous_score - score) > threshold
            or players_in_tier >= max_players_per_tier
        ):
            current_tier += 1
            players_in_tier = 0
        tiers.append(current_tier)
        previous_score = score
        players_in_tier += 1

    frame[tier_col] = tiers
    return frame


def add_score_dropoffs(
    df: pd.DataFrame,
    score_col: str,
    rank_col: str,
    output_col: str = "dropoff_to_next",
) -> pd.DataFrame:
    frame = df.sort_values(rank_col).reset_index(drop=True).copy()
    frame[output_col] = frame[score_col] - frame[score_col].shift(-1)
    return frame
