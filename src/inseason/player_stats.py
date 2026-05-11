from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.config import load_app_config


def _cache_path(as_of: date, config_dir: str = "config") -> Path:
    config = load_app_config(config_dir)
    cache_dir = Path(config["file_paths"]["cache"]["base_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"player_stats_{as_of.isoformat()}.json"


def _import_pybaseball(config_dir: str = "config") -> Any:
    config = load_app_config(config_dir)
    cache_dir = Path(config["file_paths"]["cache"]["base_dir"]) / "pybaseball"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYBASEBALL_CACHE", str(cache_dir.resolve()))
    os.environ.setdefault("MPLCONFIGDIR", str((cache_dir / "mpl").resolve()))

    import pybaseball

    return pybaseball


def _normalize_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _load_advanced_stat_maps(as_of: date, config_dir: str = "config") -> tuple[dict[str, float], dict[str, float]]:
    pybaseball = _import_pybaseball(config_dir)
    season = as_of.year

    hitter_wrc_plus: dict[str, float] = {}
    pitcher_xfip: dict[str, float] = {}

    try:
        hitters = pybaseball.batting_stats(
            season,
            season,
            qual=0,
            split_seasons=False,
            stat_columns=["Name", "wRC+"],
        )
        if not hitters.empty and "Name" in hitters.columns and "wRC+" in hitters.columns:
            hitter_wrc_plus = {
                _normalize_name(name): float(value)
                for name, value in zip(hitters["Name"], _safe_numeric(hitters["wRC+"]))
                if pd.notna(value)
            }
    except Exception:
        hitter_wrc_plus = {}

    try:
        pitchers = pybaseball.pitching_stats(
            season,
            season,
            qual=0,
            split_seasons=False,
            stat_columns=["Name", "xFIP"],
        )
        if not pitchers.empty and "Name" in pitchers.columns and "xFIP" in pitchers.columns:
            pitcher_xfip = {
                _normalize_name(name): float(value)
                for name, value in zip(pitchers["Name"], _safe_numeric(pitchers["xFIP"]))
                if pd.notna(value)
            }
    except Exception:
        pitcher_xfip = {}

    return hitter_wrc_plus, pitcher_xfip


def _build_hitter_frame(
    raw: pd.DataFrame,
    player_names: set[str],
    hitter_wrc_plus: dict[str, float],
) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(
            columns=["name", "player_type", "AVG", "OBP", "HR", "SB", "wRC+", "recent_form"]
        )

    frame = raw.copy()
    frame["name"] = frame["Name"]
    frame["player_name_key"] = frame["name"].map(_normalize_name)
    frame = frame.loc[frame["player_name_key"].isin(player_names)].copy()

    if frame.empty:
        return pd.DataFrame(
            columns=["name", "player_type", "AVG", "OBP", "HR", "SB", "wRC+", "recent_form"]
        )

    frame["AVG"] = _safe_numeric(frame["BA"])
    frame["OBP"] = _safe_numeric(frame["OBP"])
    frame["HR"] = _safe_numeric(frame["HR"])
    frame["SB"] = _safe_numeric(frame["SB"])
    frame["wRC+"] = frame["player_name_key"].map(hitter_wrc_plus)
    missing_wrc = frame["wRC+"].isna()
    if missing_wrc.any():
        ops = _safe_numeric(frame["OPS"])
        league_ops = float(ops.mean()) if pd.notna(ops.mean()) and float(ops.mean()) > 0 else 0.720
        frame.loc[missing_wrc, "wRC+"] = (ops.loc[missing_wrc] / league_ops) * 100.0

    frame["player_type"] = "H"
    return frame[["name", "player_type", "AVG", "OBP", "HR", "SB", "wRC+"]]


def _build_pitcher_frame(
    raw: pd.DataFrame,
    player_names: set[str],
    pitcher_xfip: dict[str, float],
) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(
            columns=["name", "player_type", "ERA", "WHIP", "K/9", "K%", "recent_ip", "xFIP", "recent_form"]
        )

    frame = raw.copy()
    frame["name"] = frame["Name"]
    frame["player_name_key"] = frame["name"].map(_normalize_name)
    frame = frame.loc[frame["player_name_key"].isin(player_names)].copy()

    if frame.empty:
        return pd.DataFrame(
            columns=["name", "player_type", "ERA", "WHIP", "K/9", "K%", "recent_ip", "xFIP", "recent_form"]
        )

    frame["ERA"] = _safe_numeric(frame["ERA"])
    frame["WHIP"] = _safe_numeric(frame["WHIP"])
    frame["K/9"] = _safe_numeric(frame["SO9"])
    frame["recent_ip"] = _safe_numeric(frame["IP"])
    strikeouts = _safe_numeric(frame["SO"])
    batters_faced = _safe_numeric(frame["BF"])
    frame["K%"] = np.where(batters_faced.fillna(0) > 0, strikeouts / batters_faced, np.nan)
    frame["xFIP"] = frame["player_name_key"].map(pitcher_xfip)
    frame["player_type"] = "P"
    return frame[["name", "player_type", "ERA", "WHIP", "K/9", "K%", "recent_ip", "xFIP"]]


def _score_to_unit_interval(series: pd.Series, *, invert: bool = False) -> pd.Series:
    numeric = _safe_numeric(series)
    if numeric.dropna().empty:
        return pd.Series(0.5, index=series.index, dtype="float64")

    minimum = float(numeric.min())
    maximum = float(numeric.max())
    if maximum == minimum:
        return pd.Series(0.5, index=series.index, dtype="float64")

    scaled = (numeric - minimum) / (maximum - minimum)
    if invert:
        scaled = 1.0 - scaled
    return scaled.fillna(0.5)


def get_recent_form_score(player_stats: pd.DataFrame) -> pd.Series:
    frame = player_stats.copy()
    if frame.empty:
        return pd.Series(dtype="float64")

    scores = pd.Series(0.0, index=frame.index, dtype="float64")
    hitter_mask = frame["player_type"].eq("H")
    pitcher_mask = frame["player_type"].eq("P")

    if hitter_mask.any():
        hitters = frame.loc[hitter_mask]
        hitter_score = (
            _score_to_unit_interval(hitters.get("AVG", pd.Series(index=hitters.index, dtype="float64"))) * 0.20
            + _score_to_unit_interval(hitters.get("OBP", pd.Series(index=hitters.index, dtype="float64"))) * 0.20
            + _score_to_unit_interval(hitters.get("HR", pd.Series(index=hitters.index, dtype="float64"))) * 0.20
            + _score_to_unit_interval(hitters.get("SB", pd.Series(index=hitters.index, dtype="float64"))) * 0.15
            + _score_to_unit_interval(hitters.get("wRC+", pd.Series(index=hitters.index, dtype="float64"))) * 0.25
        )
        scores.loc[hitter_mask] = hitter_score

    if pitcher_mask.any():
        pitchers = frame.loc[pitcher_mask]
        pitcher_score = (
            _score_to_unit_interval(pitchers.get("ERA", pd.Series(index=pitchers.index, dtype="float64")), invert=True) * 0.25
            + _score_to_unit_interval(pitchers.get("WHIP", pd.Series(index=pitchers.index, dtype="float64")), invert=True) * 0.20
            + _score_to_unit_interval(pitchers.get("K/9", pd.Series(index=pitchers.index, dtype="float64"))) * 0.20
            + _score_to_unit_interval(pitchers.get("K%", pd.Series(index=pitchers.index, dtype="float64"))) * 0.20
            + _score_to_unit_interval(pitchers.get("xFIP", pd.Series(index=pitchers.index, dtype="float64")), invert=True) * 0.15
        )
        scores.loc[pitcher_mask] = pitcher_score

    return scores.clip(lower=0.0, upper=1.0)


def _read_cached_stats(cache_path: Path) -> pd.DataFrame:
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    return pd.DataFrame(payload.get("players", []))


def _write_cached_stats(cache_path: Path, as_of: date, frame: pd.DataFrame) -> None:
    payload = {
        "as_of": as_of.isoformat(),
        "players": frame.to_dict(orient="records"),
    }
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_recent_stats(
    player_names: Iterable[str],
    days: int = 14,
    *,
    as_of: date | None = None,
    force: bool = False,
    config_dir: str = "config",
) -> pd.DataFrame:
    as_of = as_of or date.today()
    cache_path = _cache_path(as_of, config_dir=config_dir)
    if cache_path.exists() and not force:
        cached = _read_cached_stats(cache_path)
        if not cached.empty:
            wanted = {_normalize_name(name) for name in player_names}
            if not wanted:
                return cached
            return cached.loc[cached["name"].map(_normalize_name).isin(wanted)].reset_index(drop=True)

    names = {_normalize_name(name) for name in player_names if _normalize_name(name)}
    if not names:
        return pd.DataFrame()

    pybaseball = _import_pybaseball(config_dir)
    start_date = as_of - timedelta(days=max(days - 1, 0))
    hitter_wrc_plus, pitcher_xfip = _load_advanced_stat_maps(as_of, config_dir=config_dir)

    hitters_raw = pybaseball.batting_stats_range(start_date.isoformat(), as_of.isoformat())
    pitchers_raw = pybaseball.pitching_stats_range(start_date.isoformat(), as_of.isoformat())
    hitter_frame = _build_hitter_frame(hitters_raw, names, hitter_wrc_plus)
    pitcher_frame = _build_pitcher_frame(pitchers_raw, names, pitcher_xfip)

    combined = pd.concat([hitter_frame, pitcher_frame], ignore_index=True, sort=False)
    if combined.empty:
        _write_cached_stats(cache_path, as_of, combined)
        return combined

    combined["recent_form"] = get_recent_form_score(combined)
    _write_cached_stats(cache_path, as_of, combined)
    return combined.reset_index(drop=True)
