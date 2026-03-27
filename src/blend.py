from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd


def blend_sources(
    standardized_sources: Dict[str, pd.DataFrame],
    source_weights: Dict[str, float],
    blend_stats: List[str],
    player_type: str,
) -> pd.DataFrame:
    merged: pd.DataFrame | None = None

    for source_name, frame in standardized_sources.items():
        rename_map = {}
        for col in blend_stats + ["adp"]:
            if col in frame.columns:
                rename_map[col] = f"{source_name}_{col}"

        source_frame = frame.rename(columns=rename_map).copy()
        source_frame = source_frame.drop(columns=["source"])

        if merged is None:
            merged = source_frame
            continue

        overlap_to_drop = []
        for col in ["player_name", "player_name_ascii", "team", "mlbam_id", "inferred_role"]:
            if col in source_frame.columns and col in merged.columns:
                overlap_to_drop.append(col)
        source_frame = source_frame.drop(columns=overlap_to_drop)
        merged = merged.merge(source_frame, on="player_id", how="outer")

    assert merged is not None

    for col in ["player_name", "player_name_ascii", "team", "mlbam_id", "inferred_role"]:
        source_columns = [f"{source}_{col}" for source in standardized_sources if f"{source}_{col}" in merged.columns]
        if col in merged.columns:
            source_columns = [col] + source_columns
        if source_columns:
            merged[col] = merged[source_columns].bfill(axis=1).iloc[:, 0]

    presence_cols = []
    for source_name in standardized_sources:
        sample_col = f"{source_name}_{blend_stats[0]}"
        merged[f"has_{source_name}"] = merged[sample_col].notna() if sample_col in merged.columns else False
        presence_cols.append(f"has_{source_name}")
    merged["source_count"] = merged[presence_cols].sum(axis=1)
    merged["blend_confidence"] = merged["source_count"] / max(len(standardized_sources), 1)
    merged["player_type"] = "H" if player_type == "hitters" else "P"

    for stat in blend_stats + ["adp"]:
        stat_columns = [f"{source}_{stat}" for source in standardized_sources if f"{source}_{stat}" in merged.columns]
        if not stat_columns:
            continue
        weights = pd.Series(
            {
                column: float(source_weights.get(source_name, 0.0))
                for source_name in standardized_sources
                for column in [f"{source_name}_{stat}"]
                if column in stat_columns
            },
            dtype="float64",
        )
        values = merged[stat_columns].apply(pd.to_numeric, errors="coerce")
        numerator = values.mul(weights, axis=1).sum(axis=1, skipna=True)
        denominator = values.notna().mul(weights, axis=1).sum(axis=1)
        merged[stat] = numerator / denominator.replace(0.0, np.nan)

    if player_type == "pitchers":
        merged["Saves_plus_Holds"] = merged["Saves"].fillna(0.0) + merged["Holds"].fillna(0.0)

    return merged
