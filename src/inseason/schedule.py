from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import httpx
import pandas as pd

from src.config import load_app_config

TEAM_ABBREVIATION_MAP = {
    "AZ": "ARI",
    "WSH": "WSN",
}


def _normalize_team_code(team_code: str) -> str:
    normalized = str(team_code or "").strip().upper()
    return TEAM_ABBREVIATION_MAP.get(normalized, normalized)


def _cache_path(as_of: date, config_dir: str = "config") -> Path:
    config = load_app_config(config_dir)
    cache_dir = Path(config["file_paths"]["cache"]["base_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"schedule_{as_of.isoformat()}.json"


def _import_pybaseball(config_dir: str = "config") -> Any:
    config = load_app_config(config_dir)
    cache_dir = Path(config["file_paths"]["cache"]["base_dir"]) / "pybaseball"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYBASEBALL_CACHE", str(cache_dir.resolve()))
    os.environ.setdefault("MPLCONFIGDIR", str((cache_dir / "mpl").resolve()))

    import pybaseball

    return pybaseball


def _week_window(as_of: date) -> tuple[date, date]:
    week_start = as_of - timedelta(days=as_of.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def _read_cached_schedule(cache_path: Path) -> dict[str, Any]:
    return json.loads(cache_path.read_text(encoding="utf-8"))


def _write_cached_schedule(cache_path: Path, payload: dict[str, Any]) -> None:
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _fetch_week_schedule(as_of: date) -> dict[str, Any]:
    start_date, end_date = _week_window(as_of)
    url = "https://statsapi.mlb.com/api/v1/schedule"
    params = {
        "sportId": 1,
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "hydrate": "probablePitcher",
    }
    response = httpx.get(url, params=params, timeout=30.0)
    response.raise_for_status()
    return response.json()


def load_week_schedule(
    *,
    as_of: date | None = None,
    force: bool = False,
    config_dir: str = "config",
) -> dict[str, Any]:
    as_of = as_of or date.today()
    cache_path = _cache_path(as_of, config_dir=config_dir)
    if cache_path.exists() and not force:
        return _read_cached_schedule(cache_path)

    payload = _fetch_week_schedule(as_of)
    _write_cached_schedule(cache_path, payload)
    return payload


def _extract_probable_starts(schedule_payload: dict[str, Any]) -> list[dict[str, Any]]:
    starts: list[dict[str, Any]] = []
    for date_block in schedule_payload.get("dates", []):
        game_date = date_block.get("date")
        for game in date_block.get("games", []):
            teams = game.get("teams", {})
            for side in ("home", "away"):
                team_info = teams.get(side, {})
                opponent_side = "away" if side == "home" else "home"
                opponent_info = teams.get(opponent_side, {})
                probable_pitcher = team_info.get("probablePitcher") or {}
                if not probable_pitcher:
                    continue
                starts.append(
                    {
                        "name": probable_pitcher.get("fullName", ""),
                        "probable_pitcher_id": probable_pitcher.get("id"),
                        "mlb_team": _normalize_team_code(team_info.get("team", {}).get("abbreviation", "")),
                        "opponent_team": _normalize_team_code(opponent_info.get("team", {}).get("abbreviation", "")),
                        "game_date": game_date,
                        "is_home": side == "home",
                        "game_pk": game.get("gamePk"),
                        "game_status": game.get("status", {}).get("detailedState", ""),
                    }
                )
    return starts


def get_team_game_counts(
    *,
    as_of: date | None = None,
    force: bool = False,
    config_dir: str = "config",
) -> dict[str, int]:
    as_of = as_of or date.today()
    schedule_payload = load_week_schedule(as_of=as_of, force=force, config_dir=config_dir)

    game_counts: dict[str, int] = {}
    for date_block in schedule_payload.get("dates", []):
        for game in date_block.get("games", []):
            for side in ("home", "away"):
                team_info = game.get("teams", {}).get(side, {})
                team_code = _normalize_team_code(team_info.get("team", {}).get("abbreviation", ""))
                if not team_code:
                    continue
                game_counts[team_code] = game_counts.get(team_code, 0) + 1
    return game_counts


def _build_team_offense_map(as_of: date, config_dir: str = "config") -> dict[str, float]:
    pybaseball = _import_pybaseball(config_dir)
    try:
        frame = pybaseball.team_batting(
            as_of.year,
            as_of.year,
            qual=0,
            split_seasons=False,
            stat_columns=["Team", "wRC+"],
        )
    except Exception:
        return {}

    if frame.empty or "Team" not in frame.columns or "wRC+" not in frame.columns:
        return {}

    return {
        _normalize_team_code(team): float(wrc_plus)
        for team, wrc_plus in zip(frame["Team"], pd.to_numeric(frame["wRC+"], errors="coerce"))
        if pd.notna(wrc_plus)
    }


def rate_matchup(
    opponent_team: str,
    handedness: str | None = None,
    *,
    team_offense: dict[str, float] | None = None,
    as_of: date | None = None,
    config_dir: str = "config",
) -> dict[str, Any]:
    as_of = as_of or date.today()
    team_offense = team_offense or _build_team_offense_map(as_of, config_dir=config_dir)
    wrc_plus = float(team_offense.get(_normalize_team_code(opponent_team), 100.0))

    if wrc_plus <= 90:
        grade = "A"
    elif wrc_plus <= 100:
        grade = "B"
    elif wrc_plus <= 110:
        grade = "C"
    else:
        grade = "D"

    return {
        "matchup_grade": grade,
        "matchup_score": round(max(0.0, min(1.0, (120.0 - wrc_plus) / 40.0)), 3),
        "opponent_wRC_plus_vs_RHP_or_LHP": round(wrc_plus, 1),
        "split_basis": handedness or "overall",
    }


def _select_starts_for_players(
    players: Iterable[dict[str, Any]],
    schedule_payload: dict[str, Any],
    *,
    as_of: date,
    config_dir: str = "config",
) -> list[dict[str, Any]]:
    probable_starts = _extract_probable_starts(schedule_payload)
    team_offense = _build_team_offense_map(as_of, config_dir=config_dir)

    starts: list[dict[str, Any]] = []
    for player in players:
        positions = [str(position) for position in player.get("positions", [])]
        if "SP" not in positions:
            continue

        player_name = str(player.get("name", "")).strip().lower()
        player_team = _normalize_team_code(str(player.get("mlb_team", "")))
        for start in probable_starts:
            if start["mlb_team"] != player_team:
                continue
            if start["name"].strip().lower() != player_name:
                continue

            matchup = rate_matchup(
                start["opponent_team"],
                player.get("handedness"),
                team_offense=team_offense,
                as_of=as_of,
                config_dir=config_dir,
            )
            starts.append(
                {
                    "name": player.get("name", ""),
                    "probable_pitcher_id": start.get("probable_pitcher_id"),
                    "opponent_team": start["opponent_team"],
                    "game_date": start["game_date"],
                    "is_home": bool(start["is_home"]),
                    "game_pk": start.get("game_pk"),
                    "game_status": start.get("game_status", ""),
                    "matchup_grade": matchup["matchup_grade"],
                    "matchup_score": matchup["matchup_score"],
                    "opponent_wRC_plus_vs_RHP_or_LHP": matchup["opponent_wRC_plus_vs_RHP_or_LHP"],
                    "split_basis": matchup["split_basis"],
                }
            )
    return sorted(
        starts,
        key=lambda item: datetime.strptime(item["game_date"], "%Y-%m-%d"),
    )


def get_this_weeks_starts(
    team_roster: Iterable[dict[str, Any]],
    *,
    as_of: date | None = None,
    force: bool = False,
    config_dir: str = "config",
) -> list[dict[str, Any]]:
    as_of = as_of or date.today()
    schedule_payload = load_week_schedule(as_of=as_of, force=force, config_dir=config_dir)
    return _select_starts_for_players(team_roster, schedule_payload, as_of=as_of, config_dir=config_dir)


def get_free_agent_starts(
    free_agent_list: Iterable[dict[str, Any]],
    *,
    as_of: date | None = None,
    force: bool = False,
    config_dir: str = "config",
) -> list[dict[str, Any]]:
    as_of = as_of or date.today()
    schedule_payload = load_week_schedule(as_of=as_of, force=force, config_dir=config_dir)
    return _select_starts_for_players(free_agent_list, schedule_payload, as_of=as_of, config_dir=config_dir)
