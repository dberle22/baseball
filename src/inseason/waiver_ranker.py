from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable

import pandas as pd

from src.config import load_app_config
from src.inseason.projections import build_inseason_projection_boards
from src.inseason.rising_players import build_rising_player_rankings
from src.inseason.schedule import get_team_game_counts
from src.scoring import score_hitters, score_pitchers

RECOMMENDATION_COLUMNS = [
    "name",
    "position",
    "type",
    "score",
    "matchup_grade",
    "recent_form",
    "key_stats",
    "start_count_this_week",
    "notes",
]


def _empty_recommendations(extra_columns: Iterable[str] | None = None) -> pd.DataFrame:
    columns = RECOMMENDATION_COLUMNS + list(extra_columns or [])
    return pd.DataFrame(columns=list(dict.fromkeys(columns)))


def _free_agent_frame(free_agents: Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(list(free_agents))
    if frame.empty:
        return pd.DataFrame(
            columns=["player_id", "name", "positions", "position_type", "percent_owned", "mlb_team"]
        )
    return frame.rename(columns={"name": "player_name"})


def _recent_stats_maps(recent_stats: pd.DataFrame) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    if recent_stats.empty:
        return {}, {}

    frame = recent_stats.copy()
    if "recent_form" not in frame.columns:
        frame["recent_form"] = 0.5

    frame["recent_form"] = pd.to_numeric(frame["recent_form"], errors="coerce").fillna(0.5)
    frame = frame.sort_values("recent_form", ascending=False).drop_duplicates(subset="name", keep="first")

    form_map = frame.set_index("name")["recent_form"].to_dict()
    row_map = frame.set_index("name").to_dict(orient="index")
    return form_map, row_map


def _normalize_category_name(value: str) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _find_matchup_stat(matchup: dict[str, Any] | None, aliases: Iterable[str]) -> tuple[float, float]:
    if not matchup:
        return 0.0, 0.0

    alias_keys = {_normalize_category_name(alias) for alias in aliases}
    my_stats = matchup.get("my_stats", {})
    opponent_stats = matchup.get("opponent_stats", {})

    for key, my_value in my_stats.items():
        if _normalize_category_name(str(key)) not in alias_keys:
            continue
        opponent_value = opponent_stats.get(key, 0.0)
        try:
            return float(my_value), float(opponent_value)
        except (TypeError, ValueError):
            return 0.0, 0.0
    return 0.0, 0.0


def _needs_saves_holds_help(matchup: dict[str, Any] | None) -> bool:
    my_value, opponent_value = _find_matchup_stat(
        matchup,
        ["Saves+Holds", "Saves + Holds", "SV+HLD", "Saves_plus_Holds"],
    )
    return my_value <= opponent_value


def _position_needs(team_roster: Iterable[dict[str, Any]], config_dir: str = "config") -> dict[str, float]:
    config = load_app_config(config_dir)
    required_slots = config["league_settings"]["league"]["roster"]
    relevant_slots = ["C", "1B", "2B", "3B", "SS", "OF", "UTIL"]
    current_counts = {slot: 0 for slot in relevant_slots}

    for player in team_roster:
        for position in player.get("positions", []):
            if position in current_counts:
                current_counts[position] += 1

    needs: dict[str, float] = {}
    for slot in relevant_slots:
        required = int(required_slots.get(slot, 0) or 0)
        if required <= 0:
            continue
        current = current_counts.get(slot, 0)
        needs[slot] = max(required - current, 0) / required

    util_need = 0.0
    total_required_hitters = sum(int(required_slots.get(slot, 0) or 0) for slot in relevant_slots)
    if total_required_hitters > 0:
        rostered_hitters = sum(
            1
            for player in team_roster
            if any(position not in {"SP", "RP", "P"} for position in player.get("positions", []))
        )
        util_slots = int(required_slots.get("UTIL", 0) or 0)
        util_need = max(total_required_hitters + util_slots - rostered_hitters, 0) / max(util_slots, 1)
    needs["UTIL"] = min(util_need, 1.0)
    return needs


def _position_need_score(positions: Any, needs: dict[str, float]) -> float:
    if not isinstance(positions, list):
        return 0.0
    applicable = [float(needs.get(str(position), 0.0)) for position in positions if str(position) in needs]
    if not applicable and any(str(position) not in {"SP", "RP", "P"} for position in positions):
        applicable = [float(needs.get("UTIL", 0.0))]
    return max(applicable, default=0.0)


def _start_summary(starts: list[dict[str, Any]]) -> dict[str, Any]:
    if not starts:
        return {
            "matchup_score": 0.0,
            "start_count_this_week": 0,
            "matchup_details": "",
            "matchup_grade": "",
            "notes": "",
        }

    avg_score = sum(float(start.get("matchup_score", 0.0) or 0.0) for start in starts) / len(starts)
    details = ", ".join(
        f"vs {start['opponent_team']} ({start['matchup_grade']})"
        for start in starts
    )
    notes = ", ".join(
        f"{start['game_date']} vs {start['opponent_team']} ({start['matchup_grade']})"
        for start in starts
    )
    return {
        "matchup_score": round(avg_score, 3),
        "start_count_this_week": len(starts),
        "matchup_details": details,
        "matchup_grade": details,
        "notes": notes,
    }


def build_sp_streamer_rankings(
    free_agents: Iterable[dict[str, Any]],
    free_agent_starts: Iterable[dict[str, Any]],
    recent_stats: pd.DataFrame,
    pitcher_projections: pd.DataFrame,
    *,
    config_dir: str = "config",
) -> pd.DataFrame:
    config = load_app_config(config_dir)
    weights = config["weights"]["inseason"]["streamers"]

    free_agent_frame = _free_agent_frame(free_agents)
    if free_agent_frame.empty:
        return _empty_recommendations(
            [
                "matchup_details",
                "recent_era",
                "recent_whip",
                "recent_k9",
                "projected_k_rate",
                "projected_era",
                "projected_whip",
                "two_start_week",
            ]
        )

    starts_by_name: dict[str, list[dict[str, Any]]] = {}
    for start in free_agent_starts:
        starts_by_name.setdefault(str(start.get("name", "")), []).append(start)

    projection_frame = pitcher_projections.drop(columns=["player_name"], errors="ignore").copy()
    projection_frame = projection_frame.loc[projection_frame["inferred_role"].eq("SP")].copy()

    merged = free_agent_frame.merge(projection_frame, on="player_id", how="inner")
    merged = merged.loc[
        merged["positions"].apply(lambda positions: "SP" in positions if isinstance(positions, list) else False)
    ].copy()
    if merged.empty:
        return _empty_recommendations()

    summaries = {name: _start_summary(starts) for name, starts in starts_by_name.items()}
    form_map, recent_map = _recent_stats_maps(recent_stats)
    merged["recent_form"] = merged["player_name"].map(form_map).fillna(0.5)
    merged["matchup_score"] = merged["player_name"].map(
        lambda name: summaries.get(name, {}).get("matchup_score", 0.0)
    )
    merged["start_count_this_week"] = merged["player_name"].map(
        lambda name: summaries.get(name, {}).get("start_count_this_week", 0)
    )
    merged["matchup_details"] = merged["player_name"].map(
        lambda name: summaries.get(name, {}).get("matchup_details", "")
    )
    merged["matchup_grade"] = merged["matchup_details"]
    merged["notes"] = merged["player_name"].map(lambda name: summaries.get(name, {}).get("notes", ""))
    merged = merged.loc[merged["start_count_this_week"] > 0].copy()
    if merged.empty:
        return _empty_recommendations()

    merged["projected_k_rate"] = (merged["K"].fillna(0.0) / merged["IP"].replace(0, pd.NA)).fillna(0.0)
    era_score = 1.0 - ((merged["ERA"].fillna(5.5).clip(lower=2.0, upper=6.0) - 2.0) / 4.0)
    whip_score = 1.0 - ((merged["WHIP"].fillna(1.6).clip(lower=0.9, upper=1.6) - 0.9) / 0.7)
    merged["projected_ratios"] = (era_score + whip_score) / 2.0
    merged["score"] = (
        merged["matchup_score"] * float(weights["matchup_grade"])
        + merged["recent_form"] * float(weights["recent_form"])
        + merged["projected_k_rate"] * float(weights["projected_k_rate"])
        + merged["projected_ratios"] * float(weights["projected_era_whip"])
    )

    def _key_stats(name: str) -> str:
        stats = recent_map.get(name, {})
        return (
            f"14d ERA {stats.get('ERA', 'NA')}, WHIP {stats.get('WHIP', 'NA')}, "
            f"K/9 {stats.get('K/9', 'NA')}"
        )

    merged["key_stats"] = merged["player_name"].map(_key_stats)
    merged["recent_era"] = merged["player_name"].map(lambda name: recent_map.get(name, {}).get("ERA"))
    merged["recent_whip"] = merged["player_name"].map(lambda name: recent_map.get(name, {}).get("WHIP"))
    merged["recent_k9"] = merged["player_name"].map(lambda name: recent_map.get(name, {}).get("K/9"))
    merged["projected_era"] = merged["ERA"]
    merged["projected_whip"] = merged["WHIP"]
    merged["two_start_week"] = merged["start_count_this_week"] >= 2
    merged["type"] = "SP"
    merged["position"] = "SP"

    ranked = merged.sort_values(
        ["score", "start_count_this_week", "percent_owned"],
        ascending=[False, False, False],
    ).head(10)
    return ranked.rename(columns={"player_name": "name"})[
        RECOMMENDATION_COLUMNS
        + [
            "matchup_details",
            "recent_era",
            "recent_whip",
            "recent_k9",
            "projected_k_rate",
            "projected_era",
            "projected_whip",
            "two_start_week",
        ]
    ].reset_index(drop=True)


def build_general_pickup_rankings(
    free_agents: Iterable[dict[str, Any]],
    recent_stats: pd.DataFrame,
    hitters: pd.DataFrame,
    pitchers: pd.DataFrame,
    *,
    team_roster: Iterable[dict[str, Any]] | None = None,
    matchup: dict[str, Any] | None = None,
    as_of: date | None = None,
    force_schedule: bool = False,
    config_dir: str = "config",
) -> dict[str, pd.DataFrame]:
    config = load_app_config(config_dir)
    thresholds = config["league_settings"]["thresholds"]
    free_agent_frame = _free_agent_frame(free_agents)
    if free_agent_frame.empty:
        return {
            "hitters": _empty_recommendations(["games_this_week", "position_need_score"]),
            "relievers": _empty_recommendations(["svh_priority"]),
        }

    roster_player_ids = {int(player["player_id"]) for player in (team_roster or []) if player.get("player_id") is not None}
    free_agent_frame = free_agent_frame.loc[~free_agent_frame["player_id"].isin(roster_player_ids)].copy()
    if free_agent_frame.empty:
        return {
            "hitters": _empty_recommendations(["games_this_week", "position_need_score"]),
            "relievers": _empty_recommendations(["svh_priority"]),
        }

    free_agent_ids = set(free_agent_frame["player_id"].astype(int))
    form_map, recent_map = _recent_stats_maps(recent_stats)

    scored_hitters = score_hitters(
        hitters,
        config["weights"]["scoring"]["hitters"],
        thresholds["hitters_min_pa"],
    )
    scored_pitchers = score_pitchers(
        pitchers,
        config["weights"]["scoring"]["pitchers"],
        thresholds["pitchers_min_ip"],
        thresholds["relievers_min_svh"],
    )

    team_game_counts = get_team_game_counts(
        as_of=as_of,
        force=force_schedule,
        config_dir=config_dir,
    )
    max_games = max(team_game_counts.values(), default=7)
    position_needs = _position_needs(team_roster or [], config_dir=config_dir)
    recent_form_boost = float(config["weights"]["inseason"]["general_pickups"]["recent_form_boost"])

    hitter_pickups = free_agent_frame.merge(
        scored_hitters,
        on="player_id",
        how="inner",
        suffixes=("", "_projection"),
    )
    if not hitter_pickups.empty:
        hitter_pickups["recent_form"] = hitter_pickups["player_name"].map(form_map).fillna(0.5)
        hitter_pickups["games_this_week"] = hitter_pickups["mlb_team"].map(team_game_counts).fillna(0).astype(int)
        hitter_pickups["schedule_score"] = hitter_pickups["games_this_week"] / max(max_games, 1)
        hitter_pickups["position_need_score"] = hitter_pickups["positions"].map(
            lambda positions: _position_need_score(positions, position_needs)
        )
        hitter_pickups["score"] = (
            hitter_pickups["final_score"]
            + hitter_pickups["recent_form"] * recent_form_boost
            + hitter_pickups["schedule_score"] * 0.15
            + hitter_pickups["position_need_score"] * 0.10
        )
        hitter_pickups["type"] = "H"
        hitter_pickups["position"] = hitter_pickups["position"].fillna(
            hitter_pickups["positions"].map(
                lambda positions: next((str(position) for position in positions if position not in {"SP", "RP", "P"}), "BAT")
            )
        )
        hitter_pickups["matchup_grade"] = hitter_pickups["games_this_week"].map(lambda games: f"{games} games")
        hitter_pickups["start_count_this_week"] = 0
        hitter_pickups["key_stats"] = hitter_pickups["player_name"].map(
            lambda name: (
                f"14d AVG {recent_map.get(name, {}).get('AVG', 'NA')}, "
                f"OBP {recent_map.get(name, {}).get('OBP', 'NA')}, "
                f"HR {recent_map.get(name, {}).get('HR', 'NA')}"
            )
        )
        hitter_pickups["notes"] = hitter_pickups.apply(
            lambda row: f"{int(row['games_this_week'])} games this week; position coverage boost {row['position_need_score']:.2f}",
            axis=1,
        )
        hitter_pickups = hitter_pickups.sort_values(
            ["score", "games_this_week", "percent_owned"],
            ascending=[False, False, False],
        ).head(5)
    else:
        hitter_pickups = _empty_recommendations(["games_this_week", "position_need_score"])

    rp_pickups = free_agent_frame.merge(
        scored_pitchers.loc[scored_pitchers["inferred_role"].eq("RP")].copy(),
        on="player_id",
        how="inner",
        suffixes=("", "_projection"),
    )
    if not rp_pickups.empty:
        rp_pickups["recent_form"] = rp_pickups["player_name"].map(form_map).fillna(0.5)
        rp_pickups["svh_priority"] = 1.0 if _needs_saves_holds_help(matchup) else 0.0
        rp_pickups["score"] = (
            rp_pickups["final_score"]
            + rp_pickups["recent_form"] * recent_form_boost
            + rp_pickups["svh_priority"] * 0.25
        )
        rp_pickups["type"] = "RP"
        rp_pickups["position"] = "RP"
        rp_pickups["matchup_grade"] = rp_pickups["svh_priority"].map(
            lambda value: "SV+HLD priority" if value > 0 else ""
        )
        rp_pickups["start_count_this_week"] = 0
        rp_pickups["key_stats"] = rp_pickups["player_name"].map(
            lambda name: (
                f"14d ERA {recent_map.get(name, {}).get('ERA', 'NA')}, "
                f"WHIP {recent_map.get(name, {}).get('WHIP', 'NA')}, "
                f"K/9 {recent_map.get(name, {}).get('K/9', 'NA')}"
            )
        )
        rp_pickups["notes"] = rp_pickups["svh_priority"].map(
            lambda value: "Closer/spec saves+holds help this week" if value > 0 else "Relief ratio and SV+HLD pickup"
        )
        rp_pickups = rp_pickups.sort_values(
            ["score", "percent_owned"],
            ascending=[False, False],
        ).head(5)
    else:
        rp_pickups = _empty_recommendations(["svh_priority"])

    return {
        "hitters": hitter_pickups.rename(columns={"player_name": "name"})[
            RECOMMENDATION_COLUMNS + ["games_this_week", "position_need_score"]
        ].reset_index(drop=True),
        "relievers": rp_pickups.rename(columns={"player_name": "name"})[
            RECOMMENDATION_COLUMNS + ["svh_priority"]
        ].reset_index(drop=True),
    }


def build_waiver_recommendation_groups(
    free_agents: Iterable[dict[str, Any]],
    free_agent_starts: Iterable[dict[str, Any]],
    recent_stats: pd.DataFrame,
    *,
    team_roster: Iterable[dict[str, Any]] | None = None,
    matchup: dict[str, Any] | None = None,
    projection_boards: Dict[str, pd.DataFrame] | None = None,
    rising_transactions: Iterable[dict[str, Any]] | None = None,
    previous_free_agents: Iterable[dict[str, Any]] | None = None,
    as_of: date | None = None,
    force_schedule: bool = False,
    config_dir: str = "config",
) -> dict[str, pd.DataFrame]:
    boards = projection_boards or build_inseason_projection_boards(config_dir=config_dir)
    streamers = build_sp_streamer_rankings(
        free_agents,
        free_agent_starts,
        recent_stats,
        boards["pitchers"],
        config_dir=config_dir,
    )
    general = build_general_pickup_rankings(
        free_agents,
        recent_stats,
        boards["hitters"],
        boards["pitchers"],
        team_roster=team_roster,
        matchup=matchup,
        as_of=as_of,
        force_schedule=force_schedule,
        config_dir=config_dir,
    )
    rising = build_rising_player_rankings(
        free_agents,
        recent_stats,
        boards["hitters"],
        boards["pitchers"],
        transactions=rising_transactions,
        previous_free_agents=previous_free_agents,
        config_dir=config_dir,
    )
    return {
        "sp_streamers": streamers,
        "hitters": general["hitters"],
        "relievers": general["relievers"],
        "rising_players": rising,
    }


def build_waiver_recommendations(
    free_agents: Iterable[dict[str, Any]],
    free_agent_starts: Iterable[dict[str, Any]],
    recent_stats: pd.DataFrame,
    *,
    team_roster: Iterable[dict[str, Any]] | None = None,
    matchup: dict[str, Any] | None = None,
    projection_boards: Dict[str, pd.DataFrame] | None = None,
    rising_transactions: Iterable[dict[str, Any]] | None = None,
    previous_free_agents: Iterable[dict[str, Any]] | None = None,
    as_of: date | None = None,
    force_schedule: bool = False,
    config_dir: str = "config",
) -> pd.DataFrame:
    groups = build_waiver_recommendation_groups(
        free_agents,
        free_agent_starts,
        recent_stats,
        team_roster=team_roster,
        matchup=matchup,
        projection_boards=projection_boards,
        rising_transactions=rising_transactions,
        previous_free_agents=previous_free_agents,
        as_of=as_of,
        force_schedule=force_schedule,
        config_dir=config_dir,
    )
    combined = pd.concat(groups.values(), ignore_index=True, sort=False)
    if combined.empty:
        return combined
    return combined.sort_values("score", ascending=False).reset_index(drop=True)
