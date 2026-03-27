from __future__ import annotations

from typing import Dict, List

import pandas as pd

HITTER_BLEND_STATS = ["PA", "R", "RBI", "HR", "SB", "AVG", "OBP", "SO", "BB", "Spd"]
PITCHER_BLEND_STATS = ["IP", "QS", "ERA", "WHIP", "SO", "SV", "HLD", "GS", "G", "BB"]
COMMON_META_COLUMNS = ["Name", "NameASCII", "Team", "PlayerId", "MLBAMID", "ADP"]


def _numeric_columns(player_type: str) -> List[str]:
    return HITTER_BLEND_STATS if player_type == "hitters" else PITCHER_BLEND_STATS


def required_input_columns(player_type: str) -> List[str]:
    return COMMON_META_COLUMNS + _numeric_columns(player_type)


def _rename_columns(player_type: str) -> Dict[str, str]:
    mapping = {
        "Name": "player_name",
        "NameASCII": "player_name_ascii",
        "Team": "team",
        "PlayerId": "player_id",
        "MLBAMID": "mlbam_id",
        "ADP": "adp",
        "SO": "K",
    }
    if player_type == "pitchers":
        mapping["SV"] = "Saves"
        mapping["HLD"] = "Holds"
    return mapping


def standardize_projection(df: pd.DataFrame, source_name: str, player_type: str) -> pd.DataFrame:
    keep_cols = [col for col in COMMON_META_COLUMNS + _numeric_columns(player_type) if col in df.columns]
    frame = df[keep_cols].copy()
    frame = frame.rename(columns=_rename_columns(player_type))
    frame["source"] = source_name

    for col in frame.columns:
        if col in {"player_name", "player_name_ascii", "team", "source"}:
            continue
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    frame["player_id"] = frame["player_id"].astype("Int64")
    frame["mlbam_id"] = frame["mlbam_id"].astype("Int64")

    if player_type == "hitters":
        frame["inferred_role"] = "BAT"
    else:
        frame["Saves"] = frame.get("Saves", 0).fillna(0.0)
        frame["Holds"] = frame.get("Holds", 0).fillna(0.0)
        frame["Saves_plus_Holds"] = frame["Saves"] + frame["Holds"]
        frame["inferred_role"] = frame.apply(infer_pitcher_role, axis=1)

    return frame


def apply_hitter_positions(df: pd.DataFrame, positions_df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    position_map = (
        positions_df.rename(columns={"Name": "player_name_ascii", "POS": "position"})
        .loc[:, ["player_name_ascii", "position"]]
        .dropna(subset=["player_name_ascii", "position"])
        .drop_duplicates(subset=["player_name_ascii"], keep="first")
    )
    frame = frame.merge(position_map, on="player_name_ascii", how="left")
    frame["inferred_role"] = frame["position"].fillna("BAT")
    return frame


def trim_projection_pool(df: pd.DataFrame, player_type: str) -> pd.DataFrame:
    frame = df.copy()
    frame = frame.dropna(subset=["player_id"])
    frame = frame.drop_duplicates(subset=["player_id"], keep="first")

    if player_type == "hitters":
        keep_mask = (frame["PA"].fillna(0) >= 75) | (frame["adp"].fillna(9999) <= 500)
    else:
        keep_mask = (
            (frame["IP"].fillna(0) >= 25)
            | (frame["Saves_plus_Holds"].fillna(0) >= 5)
            | (frame["adp"].fillna(9999) <= 500)
        )

    return frame.loc[keep_mask].reset_index(drop=True)


def infer_pitcher_role(row: pd.Series) -> str:
    gs = float(row.get("GS", 0.0) or 0.0)
    games = float(row.get("G", 0.0) or 0.0)
    svh = float(row.get("Saves_plus_Holds", 0.0) or 0.0)
    ip = float(row.get("IP", 0.0) or 0.0)

    if gs >= 8 or (games > 0 and gs / max(games, 1) >= 0.45):
        return "SP"
    if svh >= 8 or (games >= 20 and gs <= 3 and ip <= 95):
        return "RP"
    return "P"
