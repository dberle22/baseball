from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def add_hitter_notes(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    conditions = [
        frame["SB_z"] >= 1.0,
        frame["HR_z"] >= 1.0,
        (frame["AVG_z"] >= 0.75) | (frame["OBP_z"] >= 0.75),
        frame["adp_gap"] >= 20,
    ]
    choices = ["speed specialist", "power boost", "ratio stabilizer", "value target"]
    frame["note"] = np.select(conditions, choices, default="balanced bat")
    frame["specialist_flag"] = np.where((frame["SB_z"] >= 1.0) | (frame["HR_z"] >= 1.0), 1, 0)
    return frame


def add_pitcher_notes(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    conditions = [
        frame["Saves_plus_Holds_z"] >= 1.0,
        frame["K_z"] >= 1.0,
        (frame["ERA_z"] >= 0.75) | (frame["WHIP_z"] >= 0.75),
        (frame["inferred_role"] == "SP") & (frame["adp_gap"] >= 15),
    ]
    choices = ["RP saves+holds", "strikeout arm", "ratio stabilizer", "SP value"]
    frame["note"] = np.select(conditions, choices, default="pitching depth")
    frame["specialist_flag"] = np.where(frame["Saves_plus_Holds_z"] >= 1.0, 1, 0)
    return frame


def build_sleepers_fades(overall_board: pd.DataFrame) -> pd.DataFrame:
    frame = overall_board.copy()
    frame["market_call"] = np.where(frame["adp_gap"] >= 15, "Sleeper", np.where(frame["adp_gap"] <= -15, "Fade", "Neutral"))
    frame = frame.loc[frame["market_call"] != "Neutral"].copy()

    rows = []
    position_order = ["C", "1B", "2B", "3B", "SS", "OF", "SP", "RP", "DH", "BAT", "P"]
    available_positions = [position for position in position_order if position in frame["inferred_role"].unique()]

    for market_call, ascending in [("Sleeper", False), ("Fade", True)]:
        subset = frame.loc[frame["market_call"] == market_call]
        for position in available_positions:
            position_group = subset.loc[subset["inferred_role"] == position].sort_values("adp_gap", ascending=ascending).head(5).copy()
            if position_group.empty:
                continue
            position_group["position_group"] = position
            position_group["position_rank"] = range(1, len(position_group) + 1)
            rows.append(position_group)

    shortlist = pd.concat(rows, ignore_index=True) if rows else frame.head(0).copy()
    return shortlist[
        [
            "market_call",
            "position_group",
            "position_rank",
            "overall_rank",
            "player_name",
            "team",
            "inferred_role",
            "adp",
            "adp_gap",
            "tier",
            "dropoff_to_next",
            "note",
        ]
    ]


def build_category_contribution(overall_board: pd.DataFrame) -> pd.DataFrame:
    frame = overall_board.copy()
    z_cols = [col for col in frame.columns if col.endswith("_z")]
    frame["best_category"] = frame[z_cols].idxmax(axis=1).str.replace("_z", "", regex=False)
    frame["best_category_score"] = frame[z_cols].max(axis=1)
    keep_cols = [
        "overall_rank",
        "player_name",
        "team",
        "inferred_role",
        "best_category",
        "best_category_score",
        "note",
    ] + z_cols
    return frame[keep_cols].sort_values("overall_rank")


def build_scarcity_sheet(hitters: pd.DataFrame, pitchers: pd.DataFrame) -> pd.DataFrame:
    hitter_position_order = ["C", "1B", "2B", "3B", "SS", "OF", "DH", "BAT"]
    hitter_rows = pd.concat(
        [
            _scarcity_from_group(hitters.loc[hitters["inferred_role"] == position], position)
            for position in hitter_position_order
        ],
        ignore_index=True,
    )
    pitcher_rows = pd.concat(
        [
            _scarcity_from_group(pitchers.loc[pitchers["inferred_role"] == "SP"], "SP"),
            _scarcity_from_group(pitchers.loc[pitchers["inferred_role"] == "RP"], "RP"),
            _scarcity_from_group(pitchers.loc[pitchers["inferred_role"] == "P"], "P"),
        ],
        ignore_index=True,
    )
    return pd.concat([hitter_rows, pitcher_rows], ignore_index=True)


def _scarcity_from_group(df: pd.DataFrame, label: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["group", "sample_rank", "player_name", "final_score", "gap_from_prev"])
    frame = df.sort_values("final_score", ascending=False).reset_index(drop=True).copy()
    frame["sample_rank"] = frame.index + 1
    frame["gap_from_prev"] = frame["final_score"].shift(1) - frame["final_score"]
    checkpoints = frame.loc[frame["sample_rank"].isin([1, 12, 24, 36, 48, 60])].copy()
    checkpoints["group"] = label
    return checkpoints[["group", "sample_rank", "player_name", "final_score", "gap_from_prev"]]


def build_draft_day_queue(overall_board: pd.DataFrame, phase: str, phase_adjustments: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    frame = overall_board.copy()
    adjustments = phase_adjustments[phase]
    frame["queue_score"] = frame["final_score"]
    frame.loc[frame["player_type"] == "H", "queue_score"] += float(adjustments["hitters"])
    frame.loc[frame["player_type"] == "P", "queue_score"] += float(adjustments["pitchers"])
    frame.loc[frame["specialist_flag"] == 1, "queue_score"] += float(adjustments["specialists"])
    frame.loc[frame["note"] == "RP saves+holds", "queue_score"] += float(adjustments["relievers"])
    queue = frame.sort_values("queue_score", ascending=False).reset_index(drop=True)
    queue["queue_rank"] = queue.index + 1
    return queue
