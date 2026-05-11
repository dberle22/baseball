from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd

from src.blend import blend_sources
from src.config import load_app_config
from src.io import load_projection_sources
from src.standardize import (
    apply_hitter_positions,
    required_input_columns,
    standardize_projection,
    trim_projection_pool,
)


def _resolve_source_paths(
    paths: Dict[str, Any],
    preferred_key: str,
    fallback_key: str,
) -> Dict[str, str]:
    preferred = {
        source_name: source_path
        for source_name, source_path in paths["input_files"][preferred_key].items()
        if Path(source_path).exists()
    }
    if preferred:
        return preferred

    fallback = {
        source_name: source_path
        for source_name, source_path in paths["input_files"][fallback_key].items()
        if Path(source_path).exists()
    }
    if fallback:
        return fallback

    raise FileNotFoundError(
        f"No projection CSVs found for `{preferred_key}` or fallback `{fallback_key}`."
    )


def build_inseason_projection_boards(
    config_dir: str = "config",
    allow_fallback: bool = True,
) -> Dict[str, pd.DataFrame]:
    config = load_app_config(config_dir)
    paths = config["file_paths"]

    hitter_key = "inseason_hitters"
    pitcher_key = "inseason_pitchers"
    hitter_fallback_key = "hitters"
    pitcher_fallback_key = "pitchers"

    if allow_fallback:
        hitter_paths = _resolve_source_paths(paths, hitter_key, hitter_fallback_key)
        pitcher_paths = _resolve_source_paths(paths, pitcher_key, pitcher_fallback_key)
    else:
        hitter_paths = paths["input_files"][hitter_key]
        pitcher_paths = paths["input_files"][pitcher_key]

    hitter_sources_raw = load_projection_sources(
        hitter_paths,
        usecols=required_input_columns("hitters"),
    )
    pitcher_sources_raw = load_projection_sources(
        pitcher_paths,
        usecols=required_input_columns("pitchers"),
    )
    hitter_positions = pd.read_csv(Path(paths["input_files"]["positions"]), usecols=["Name", "POS"])

    hitter_sources = {
        source_name: trim_projection_pool(
            standardize_projection(frame, source_name, "hitters"),
            "hitters",
        )
        for source_name, frame in hitter_sources_raw.items()
    }
    pitcher_sources = {
        source_name: trim_projection_pool(
            standardize_projection(frame, source_name, "pitchers"),
            "pitchers",
        )
        for source_name, frame in pitcher_sources_raw.items()
    }

    hitters = blend_sources(
        hitter_sources,
        config["weights"]["blend"]["hitters"],
        ["PA", "R", "RBI", "HR", "SB", "AVG", "OBP", "K", "BB", "Spd"],
        "hitters",
    )
    hitters = apply_hitter_positions(hitters, hitter_positions)
    pitchers = blend_sources(
        pitcher_sources,
        config["weights"]["blend"]["pitchers"],
        ["IP", "QS", "ERA", "WHIP", "K", "Saves", "Holds", "GS", "G", "BB"],
        "pitchers",
    )

    return {
        "hitters": hitters,
        "pitchers": pitchers,
    }
