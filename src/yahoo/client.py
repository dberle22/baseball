from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from .auth import get_league_id

DEFAULT_FREE_AGENT_POSITIONS = ("B", "P")


def _import_yfa():
    try:
        import yahoo_fantasy_api as yfa
    except ImportError as exc:
        raise RuntimeError(
            "Yahoo dependencies are not installed. Run `pip install -r requirements.txt` first."
        ) from exc
    return yfa


def _coerce_float(value: Any) -> float | str:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _normalize_league_id(sc, league_id: str | None = None) -> str:
    raw_league_id = (league_id or get_league_id()).strip()
    if ".l." in raw_league_id:
        return raw_league_id

    yfa = _import_yfa()
    game = yfa.Game(sc, "mlb")
    current_year = str(date.today().year)
    candidate_ids = game.league_ids(game_codes=["mlb"], seasons=[current_year])

    for candidate in candidate_ids:
        if candidate.endswith(f".l.{raw_league_id}"):
            return candidate

    legacy_candidates = game.league_ids(year=int(current_year))
    for candidate in legacy_candidates:
        if candidate.endswith(f".l.{raw_league_id}"):
            return candidate

    raise RuntimeError(
        f"Could not resolve `YAHOO_LEAGUE_ID={raw_league_id}` to a full Yahoo league key."
    )


def _get_league(sc, league_id: str | None = None):
    yfa = _import_yfa()
    resolved_league_id = _normalize_league_id(sc, league_id=league_id)
    return yfa.Game(sc, "mlb").to_league(resolved_league_id)


def _normalize_team_name(teams: dict[str, dict[str, Any]], team_key: str) -> str:
    return str(teams.get(team_key, {}).get("name", team_key))


def _extract_player_positions(player: dict[str, Any]) -> list[str]:
    positions = player.get("eligible_positions") or []
    if isinstance(positions, list):
        return [str(position) for position in positions]
    return []


def _extract_selected_position(player: dict[str, Any]) -> str:
    return str(player.get("selected_position", "") or "")


def _is_starting_position(selected_position: str) -> bool:
    return selected_position not in {"", "BN", "IL", "IL10", "IL15", "IL60", "NA"}


def _flatten_matchup_teams(node: Any) -> list[dict[str, Any]]:
    teams: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "team_key" in node and "team_stats" in node:
            teams.append(node)
        for value in node.values():
            teams.extend(_flatten_matchup_teams(value))
    elif isinstance(node, list):
        for value in node:
            teams.extend(_flatten_matchup_teams(value))
    return teams


def _extract_stats_from_team_payload(team_payload: dict[str, Any]) -> dict[str, float | str]:
    stats: dict[str, float | str] = {}
    team_stats = team_payload.get("team_stats", {})
    stat_entries = team_stats.get("stats", []) if isinstance(team_stats, dict) else []

    if isinstance(stat_entries, dict):
        stat_entries = stat_entries.get("stat", [])

    if isinstance(stat_entries, list):
        for entry in stat_entries:
            stat = entry.get("stat") if isinstance(entry, dict) else None
            if not isinstance(stat, dict):
                continue
            display_name = stat.get("display_name") or stat.get("name") or stat.get("stat_id")
            if display_name is None:
                continue
            stats[str(display_name)] = _coerce_float(stat.get("value"))
    return stats


def _build_matchup_team_map(scoreboard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    matchup_team_map: dict[str, dict[str, Any]] = {}
    for team_payload in _flatten_matchup_teams(scoreboard):
        team_key = team_payload.get("team_key")
        if team_key:
            matchup_team_map[str(team_key)] = {
                "team_key": str(team_key),
                "name": team_payload.get("name"),
                "stats": _extract_stats_from_team_payload(team_payload),
            }
    return matchup_team_map


def _normalize_stat_categories(stat_categories: Iterable[dict[str, Any]]) -> list[str]:
    categories: list[str] = []
    for category in stat_categories:
        display_name = category.get("display_name")
        if display_name:
            categories.append(str(display_name))
    return categories


def get_my_team(sc, league_id: str | None = None) -> list[dict[str, Any]]:
    league = _get_league(sc, league_id=league_id)
    team = league.to_team(league.team_key())
    return _serialize_roster(team.roster())


def _serialize_roster(roster: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "player_id": int(player["player_id"]),
            "name": str(player["name"]),
            "positions": _extract_player_positions(player),
            "status": str(player.get("status", "") or ""),
            "is_starting": _is_starting_position(_extract_selected_position(player)),
            "selected_position": _extract_selected_position(player),
            "mlb_team": str(player.get("editorial_team_abbr", "") or ""),
        }
        for player in roster
    ]


def get_team_roster(sc, team_key: str | None = None, league_id: str | None = None) -> list[dict[str, Any]]:
    league = _get_league(sc, league_id=league_id)
    target_team_key = str(team_key or league.team_key())
    team = league.to_team(target_team_key)
    return _serialize_roster(team.roster())


def get_current_matchup(sc, league_id: str | None = None) -> dict[str, Any]:
    league = _get_league(sc, league_id=league_id)
    week = league.current_week()
    my_team_key = league.team_key()
    opponent_team_key = league.to_team(my_team_key).matchup(week)
    scoreboard = league.matchups(week)
    teams = league.teams()
    matchup_team_map = _build_matchup_team_map(scoreboard)
    categories = _normalize_stat_categories(league.stat_categories())

    my_stats = matchup_team_map.get(my_team_key, {}).get("stats", {})
    opponent_stats = matchup_team_map.get(opponent_team_key, {}).get("stats", {})

    return {
        "week": week,
        "my_team_name": _normalize_team_name(teams, my_team_key),
        "opponent_team_name": _normalize_team_name(teams, opponent_team_key),
        "my_team_key": my_team_key,
        "opponent_team_key": opponent_team_key,
        "my_stats": my_stats,
        "opponent_stats": opponent_stats,
        "categories": categories,
    }


def get_free_agents(sc, position: str | None = None, count: int = 50, league_id: str | None = None) -> list[dict[str, Any]]:
    league = _get_league(sc, league_id=league_id)
    positions = (position,) if position else DEFAULT_FREE_AGENT_POSITIONS

    players_by_id: dict[int, dict[str, Any]] = {}
    for lookup_position in positions:
        for player in league.free_agents(lookup_position):
            players_by_id[int(player["player_id"])] = {
                "player_id": int(player["player_id"]),
                "name": str(player["name"]),
                "position_type": str(player.get("position_type", "") or ""),
                "positions": _extract_player_positions(player),
                "status": str(player.get("status", "") or ""),
                "mlb_team": str(player.get("editorial_team_abbr", "") or ""),
                "percent_owned": int(player.get("percent_owned", 0) or 0),
            }

    ranked_players = sorted(
        players_by_id.values(),
        key=lambda player: (-player["percent_owned"], player["name"]),
    )
    return ranked_players[:count]


def get_league_settings(sc, league_id: str | None = None) -> dict[str, Any]:
    league = _get_league(sc, league_id=league_id)
    settings = league.settings()
    stat_categories = league.stat_categories()
    roster_slots = league.positions()

    return {
        "league_id": _normalize_league_id(sc, league_id=league_id),
        "league_name": settings.get("name"),
        "scoring_type": settings.get("scoring_type"),
        "current_week": int(settings.get("current_week", league.current_week())),
        "team_count": int(settings.get("num_teams", 0) or 0),
        "stat_categories": stat_categories,
        "roster_slots": roster_slots,
        "uses_faab": bool(int(settings.get("uses_faab", 0) or 0)),
        "weekly_deadline": settings.get("weekly_deadline"),
    }


def get_standings(sc, league_id: str | None = None) -> list[dict[str, Any]]:
    league = _get_league(sc, league_id=league_id)
    standings = []

    for team in league.standings():
        outcome_totals = team.get("outcome_totals", {})
        standings.append(
            {
                "team_key": str(team.get("team_key", "")),
                "team_name": str(team.get("name", "")),
                "rank": int(team.get("rank", 0) or 0),
                "wins": int(outcome_totals.get("wins", 0) or 0),
                "losses": int(outcome_totals.get("losses", 0) or 0),
                "ties": int(outcome_totals.get("ties", 0) or 0),
                "percentage": str(outcome_totals.get("percentage", "")),
                "games_back": str(team.get("games_back", "")),
            }
        )

    return standings
