from __future__ import annotations

from typing import Dict, Iterable, List

import numpy as np
import pandas as pd


def _safe_zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _volume_adjusted_ratio_z(series: pd.Series, volume: pd.Series, baseline: float) -> pd.Series:
    z = _safe_zscore(series.fillna(series.mean()))
    factor = np.sqrt(volume.fillna(0).clip(lower=0) / baseline)
    return z * factor.clip(lower=0.0, upper=1.0)


def _compute_adp_gap(df: pd.DataFrame, rank_col: str) -> pd.Series:
    return df["adp"].fillna(df[rank_col]) - df[rank_col]


def _rank_desc(df: pd.DataFrame, score_col: str, output_col: str) -> pd.DataFrame:
    ranked = df.sort_values(score_col, ascending=False).reset_index(drop=True).copy()
    ranked[output_col] = ranked.index + 1
    return ranked


def score_hitters(df: pd.DataFrame, config: Dict[str, float], min_pa: int) -> pd.DataFrame:
    frame = df.copy()
    frame["is_rankable"] = frame["PA"].fillna(0) >= min_pa

    for stat in ["R", "RBI", "HR", "SB"]:
        frame[f"{stat}_z"] = _safe_zscore(frame[stat].fillna(0.0))
    frame["AVG_z"] = _volume_adjusted_ratio_z(frame["AVG"], frame["PA"], 600.0)
    frame["OBP_z"] = _volume_adjusted_ratio_z(frame["OBP"], frame["PA"], 600.0)

    z_cols = ["R_z", "RBI_z", "HR_z", "SB_z", "AVG_z", "OBP_z"]
    frame["category_score"] = frame[z_cols].sum(axis=1)
    frame["upside_score"] = (
        0.45 * frame["HR_z"] + 0.45 * frame["SB_z"] + 0.10 * _safe_zscore(frame["Spd"].fillna(0.0))
    )

    pool = frame.loc[frame["is_rankable"]].copy()
    prelim = _rank_desc(pool, "category_score", "prelim_rank")
    prelim["adp_gap"] = _compute_adp_gap(prelim, "prelim_rank")
    adp_map = prelim.set_index("player_id")["adp_gap"]

    frame["adp_gap"] = frame["player_id"].map(adp_map).fillna(0.0)
    frame["adp_bonus"] = frame["adp_gap"] / 50.0 * float(config["adp_bonus_weight"])
    frame["final_score"] = (
        frame["category_score"] + frame["adp_bonus"] + frame["upside_score"] * float(config["upside_weight"])
    )

    ranked = _rank_desc(frame.loc[frame["is_rankable"]], "final_score", "final_rank")
    ranked["adp_gap"] = _compute_adp_gap(ranked, "final_rank")
    return ranked


def score_pitchers(df: pd.DataFrame, config: Dict[str, float], min_ip: int, min_svh: int) -> pd.DataFrame:
    frame = df.copy()
    frame["is_rankable"] = (frame["IP"].fillna(0) >= min_ip) | (frame["Saves_plus_Holds"].fillna(0) >= min_svh)

    frame["QS_z"] = _safe_zscore(frame["QS"].fillna(0.0))
    frame["K_z"] = _safe_zscore(frame["K"].fillna(0.0))
    frame["Saves_plus_Holds_z"] = _safe_zscore(frame["Saves_plus_Holds"].fillna(0.0))
    frame["ERA_z"] = -_volume_adjusted_ratio_z(frame["ERA"], frame["IP"], 180.0)
    frame["WHIP_z"] = -_volume_adjusted_ratio_z(frame["WHIP"], frame["IP"], 180.0)
    frame["category_score"] = frame[["QS_z", "K_z", "Saves_plus_Holds_z", "ERA_z", "WHIP_z"]].sum(axis=1)

    frame["role_bonus"] = np.where(
        (frame["inferred_role"] == "SP") & (frame["QS_z"] > 0),
        1.0,
        np.where((frame["inferred_role"] == "RP") & (frame["Saves_plus_Holds_z"] > 0), 1.0, 0.0),
    )

    prelim = _rank_desc(frame.loc[frame["is_rankable"]].copy(), "category_score", "prelim_rank")
    prelim["adp_gap"] = _compute_adp_gap(prelim, "prelim_rank")
    adp_map = prelim.set_index("player_id")["adp_gap"]

    frame["adp_gap"] = frame["player_id"].map(adp_map).fillna(0.0)
    frame["adp_bonus"] = frame["adp_gap"] / 50.0 * float(config["adp_bonus_weight"])
    frame["final_score"] = (
        frame["category_score"] + frame["adp_bonus"] + frame["role_bonus"] * float(config["role_bonus_weight"])
    )

    ranked = _rank_desc(frame.loc[frame["is_rankable"]], "final_score", "final_rank")
    ranked["adp_gap"] = _compute_adp_gap(ranked, "final_rank")
    return ranked


def prepare_overall_board(hitters: pd.DataFrame, pitchers: pd.DataFrame) -> pd.DataFrame:
    merged = pd.concat([hitters, pitchers], ignore_index=True, sort=False)
    overall = _rank_desc(merged, "final_score", "overall_rank")
    overall["adp_gap"] = _compute_adp_gap(overall, "overall_rank")
    return overall


def round_for_export(df: pd.DataFrame, decimals: int = 3) -> pd.DataFrame:
    frame = df.copy()
    numeric_cols = frame.select_dtypes(include=["number"]).columns
    frame[numeric_cols] = frame[numeric_cols].round(decimals)
    return frame
