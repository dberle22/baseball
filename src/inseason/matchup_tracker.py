from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import httpx
import pandas as pd

from src.inseason.schedule import get_this_weeks_starts, load_week_schedule

LOWER_IS_BETTER_CATEGORIES = {"era", "whip"}
RATIO_CATEGORIES = {"avg", "obp", "era", "whip"}
HITTER_CATEGORIES = {"r", "rbi", "hr", "avg", "obp", "sb"}
STARTER_CATEGORIES = {"qs", "k", "era", "whip"}
RELIEVER_CATEGORIES = {"savesholds", "savesplusholds", "svhld", "svh"}


def _normalize_category_name(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_completed_game_status(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"final", "game over", "completed early"}


def _is_start_completed(start: dict[str, Any], as_of: date) -> bool:
    game_date = start.get("game_date")
    if not game_date:
        return False

    try:
        start_date = datetime.strptime(str(game_date), "%Y-%m-%d").date()
    except ValueError:
        return False

    if _is_completed_game_status(str(start.get("game_status", ""))):
        return True
    return start_date < as_of


def _team_game_counts(schedule_payload: dict[str, Any], *, remaining_only: bool, as_of: date) -> dict[str, int]:
    counts: dict[str, int] = {}
    for date_block in schedule_payload.get("dates", []):
        try:
            game_date = datetime.strptime(str(date_block.get("date", "")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if remaining_only and game_date < as_of:
            continue
        for game in date_block.get("games", []):
            for side in ("home", "away"):
                team_info = game.get("teams", {}).get(side, {})
                team_code = str(team_info.get("team", {}).get("abbreviation", "") or "").upper()
                if not team_code:
                    continue
                counts[team_code] = counts.get(team_code, 0) + 1
    return counts


def _active_players(roster: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [player for player in roster if bool(player.get("is_starting"))]


def _remaining_hitter_games(roster: Iterable[dict[str, Any]], counts: dict[str, int]) -> int:
    total = 0
    for player in _active_players(roster):
        positions = {str(position) for position in player.get("positions", [])}
        if positions.intersection({"SP", "RP", "P"}):
            continue
        total += int(counts.get(str(player.get("mlb_team", "")).upper(), 0))
    return total


def _remaining_reliever_games(roster: Iterable[dict[str, Any]], counts: dict[str, int]) -> int:
    total = 0
    for player in _active_players(roster):
        positions = {str(position) for position in player.get("positions", [])}
        if "RP" not in positions:
            continue
        total += int(counts.get(str(player.get("mlb_team", "")).upper(), 0))
    return total


def _opportunity_counts(
    roster: Iterable[dict[str, Any]],
    starts: Iterable[dict[str, Any]],
    schedule_payload: dict[str, Any],
    *,
    as_of: date,
) -> dict[str, float]:
    remaining_game_counts = _team_game_counts(schedule_payload, remaining_only=True, as_of=as_of)
    total_game_counts = _team_game_counts(schedule_payload, remaining_only=False, as_of=as_of)
    remaining_starts = [start for start in starts if not _is_start_completed(start, as_of)]

    hitter_total = _remaining_hitter_games(roster, total_game_counts)
    hitter_remaining = _remaining_hitter_games(roster, remaining_game_counts)
    reliever_total = _remaining_reliever_games(roster, total_game_counts)
    reliever_remaining = _remaining_reliever_games(roster, remaining_game_counts)

    return {
        "hitter_total": float(hitter_total),
        "hitter_remaining": float(hitter_remaining),
        "starter_total": float(len(list(starts))),
        "starter_remaining": float(len(remaining_starts)),
        "reliever_total": float(reliever_total),
        "reliever_remaining": float(reliever_remaining),
    }


def _category_opportunity_key(category_name: str) -> tuple[str, str]:
    normalized = _normalize_category_name(category_name)
    if normalized in HITTER_CATEGORIES:
        return "hitter_total", "hitter_remaining"
    if normalized in RELIEVER_CATEGORIES:
        return "reliever_total", "reliever_remaining"
    if normalized in STARTER_CATEGORIES:
        return "starter_total", "starter_remaining"
    return "hitter_total", "hitter_remaining"


def _project_counting_stat(current_value: float, total_opportunities: float, remaining_opportunities: float) -> float:
    elapsed_opportunities = max(total_opportunities - remaining_opportunities, 0.0)
    if elapsed_opportunities <= 0:
        return current_value
    current_rate = current_value / elapsed_opportunities
    return current_value + current_rate * remaining_opportunities


def _close_margin(value_a: float, value_b: float) -> float:
    baseline = max(abs(value_a), abs(value_b), 1.0)
    return baseline * 0.05


def _determine_status(category_name: str, my_value: float, opponent_value: float) -> str:
    margin = _close_margin(my_value, opponent_value)
    if abs(my_value - opponent_value) <= margin:
        return "Close"

    normalized = _normalize_category_name(category_name)
    if normalized in LOWER_IS_BETTER_CATEGORIES:
        return "Winning" if my_value < opponent_value else "Losing"
    return "Winning" if my_value > opponent_value else "Losing"


def build_category_tracker(
    matchup: dict[str, Any],
    my_roster: Iterable[dict[str, Any]],
    opponent_roster: Iterable[dict[str, Any]],
    my_starts: Iterable[dict[str, Any]],
    opponent_starts: Iterable[dict[str, Any]],
    *,
    as_of: date | None = None,
    force_schedule: bool = False,
    config_dir: str = "config",
) -> list[dict[str, Any]]:
    as_of = as_of or date.today()
    schedule_payload = load_week_schedule(as_of=as_of, force=force_schedule, config_dir=config_dir)
    my_counts = _opportunity_counts(my_roster, my_starts, schedule_payload, as_of=as_of)
    opponent_counts = _opportunity_counts(opponent_roster, opponent_starts, schedule_payload, as_of=as_of)

    rows: list[dict[str, Any]] = []
    for category in matchup.get("categories", []):
        my_value = _safe_float(matchup.get("my_stats", {}).get(category, 0.0))
        opponent_value = _safe_float(matchup.get("opponent_stats", {}).get(category, 0.0))
        total_key, remaining_key = _category_opportunity_key(category)

        if _normalize_category_name(category) in RATIO_CATEGORIES:
            my_projected = my_value
            opponent_projected = opponent_value
        else:
            my_projected = _project_counting_stat(my_value, my_counts[total_key], my_counts[remaining_key])
            opponent_projected = _project_counting_stat(
                opponent_value,
                opponent_counts[total_key],
                opponent_counts[remaining_key],
            )

        rows.append(
            {
                "category": category,
                "my_total": round(my_value, 3),
                "opponent_total": round(opponent_value, 3),
                "status": _determine_status(category, my_value, opponent_value),
                "my_projected_total": round(my_projected, 3),
                "opponent_projected_total": round(opponent_projected, 3),
                "projected_status": _determine_status(category, my_projected, opponent_projected),
                "my_remaining_opportunities": round(my_counts[remaining_key], 1),
                "opponent_remaining_opportunities": round(opponent_counts[remaining_key], 1),
            }
        )

    return rows


def _find_projection_row(
    player_name: str,
    mlb_team: str,
    pitcher_projections: pd.DataFrame,
) -> dict[str, Any]:
    frame = pitcher_projections.copy()
    if frame.empty:
        return {}

    name_mask = frame["player_name"].astype(str).str.casefold().eq(str(player_name).casefold())
    team_mask = frame["team"].astype(str).str.upper().eq(str(mlb_team).upper())
    matched = frame.loc[name_mask & team_mask]
    if matched.empty:
        matched = frame.loc[name_mask]
    if matched.empty:
        return {}
    return matched.iloc[0].to_dict()


def _find_recent_row(player_name: str, recent_stats: pd.DataFrame) -> dict[str, Any]:
    if recent_stats.empty:
        return {}
    names = recent_stats["name"].astype(str).str.casefold()
    matched = recent_stats.loc[names.eq(str(player_name).casefold())]
    if matched.empty:
        return {}
    return matched.iloc[0].to_dict()


def _fetch_boxscore(game_pk: int) -> dict[str, Any]:
    response = httpx.get(f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore", timeout=30.0)
    response.raise_for_status()
    return response.json()


def _extract_pitching_line(boxscore: dict[str, Any], start: dict[str, Any]) -> str:
    target_id = start.get("probable_pitcher_id")
    target_name = str(start.get("name", "")).casefold()
    for team_side in ("home", "away"):
        players = boxscore.get("teams", {}).get(team_side, {}).get("players", {})
        for player in players.values():
            person = player.get("person", {})
            if target_id and person.get("id") == target_id:
                stats = player.get("stats", {}).get("pitching", {})
                return _format_pitching_line(stats)
            if str(person.get("fullName", "")).casefold() == target_name:
                stats = player.get("stats", {}).get("pitching", {})
                return _format_pitching_line(stats)
    return ""


def _format_pitching_line(stats: dict[str, Any]) -> str:
    innings = stats.get("inningsPitched")
    earned_runs = stats.get("earnedRuns")
    strikeouts = stats.get("strikeOuts")
    if innings in (None, ""):
        return ""
    return f"{innings} IP, {earned_runs or 0} ER, {strikeouts or 0} K"


def build_sp_start_tracker(
    roster: Iterable[dict[str, Any]],
    recent_stats: pd.DataFrame,
    pitcher_projections: pd.DataFrame,
    *,
    as_of: date | None = None,
    force_schedule: bool = False,
    config_dir: str = "config",
) -> list[dict[str, Any]]:
    as_of = as_of or date.today()
    starts = get_this_weeks_starts(roster, as_of=as_of, force=force_schedule, config_dir=config_dir)
    boxscore_cache: dict[int, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []

    for start in starts:
        roster_player = next(
            (
                player
                for player in roster
                if str(player.get("name", "")).casefold() == str(start.get("name", "")).casefold()
            ),
            {},
        )
        projection_row = _find_projection_row(
            str(start.get("name", "")),
            str(roster_player.get("mlb_team", "") or ""),
            pitcher_projections,
        )
        recent_row = _find_recent_row(str(start.get("name", "")), recent_stats)
        game_pk = start.get("game_pk")

        actual_line = ""
        completed = _is_start_completed(start, as_of)
        if completed and isinstance(game_pk, int):
            if game_pk not in boxscore_cache:
                try:
                    boxscore_cache[game_pk] = _fetch_boxscore(game_pk)
                except Exception:
                    boxscore_cache[game_pk] = {}
            actual_line = _extract_pitching_line(boxscore_cache[game_pk], start)

        projected_ip = _safe_float(projection_row.get("IP"))
        projected_k = _safe_float(projection_row.get("K"))
        projected_era = projection_row.get("ERA")
        projected_whip = projection_row.get("WHIP")
        projected_starts = max(_safe_float(projection_row.get("GS")), 1.0)

        rows.append(
            {
                "name": start.get("name", ""),
                "game_date": start.get("game_date", ""),
                "opponent_team": start.get("opponent_team", ""),
                "home_away": "Home" if bool(start.get("is_home")) else "Away",
                "matchup_grade": start.get("matchup_grade", ""),
                "projected_k": round(projected_k / projected_starts, 1) if projected_k else None,
                "projected_era": round(_safe_float(projected_era), 2) if projected_era is not None else None,
                "projected_whip": round(_safe_float(projected_whip), 2) if projected_whip is not None else None,
                "projected_ip": round(projected_ip / projected_starts, 1) if projected_ip else None,
                "recent_k9": round(_safe_float(recent_row.get("K/9")), 1) if recent_row else None,
                "completed": completed,
                "actual_line": actual_line,
                "game_status": start.get("game_status", ""),
            }
        )

    return sorted(rows, key=lambda item: (item["game_date"], item["name"]))
