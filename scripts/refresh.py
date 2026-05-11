from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_app_config
from src.inseason.matchup_tracker import build_category_tracker, build_sp_start_tracker
from src.inseason.player_stats import get_recent_stats
from src.inseason.projections import build_inseason_projection_boards
from src.inseason.rising_players import load_previous_free_agent_snapshot, load_recent_transactions
from src.inseason.schedule import get_free_agent_starts, get_this_weeks_starts
from src.inseason.waiver_ranker import build_waiver_recommendation_groups, build_waiver_recommendations
from src.yahoo.auth import get_sc
from src.yahoo.client import get_current_matchup, get_free_agents, get_my_team, get_team_roster


def _summary_cache_path(as_of: date, config_dir: str = "config") -> Path:
    config = load_app_config(config_dir)
    cache_dir = Path(config["file_paths"]["cache"]["base_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"refresh_summary_{as_of.isoformat()}.json"


def run_refresh(*, force: bool = False, config_dir: str = "config") -> dict[str, object]:
    as_of = date.today()
    sc = get_sc()
    roster = get_my_team(sc)
    matchup = get_current_matchup(sc)
    opponent_roster = get_team_roster(sc, matchup.get("opponent_team_key"))
    free_agents = get_free_agents(sc, count=75)

    roster_starts = get_this_weeks_starts(roster, as_of=as_of, force=force, config_dir=config_dir)
    opponent_starts = get_this_weeks_starts(opponent_roster, as_of=as_of, force=force, config_dir=config_dir)
    free_agent_starts = get_free_agent_starts(free_agents, as_of=as_of, force=force, config_dir=config_dir)
    player_names = [player["name"] for player in roster] + [player["name"] for player in free_agents]
    recent_stats = get_recent_stats(player_names, as_of=as_of, force=force, config_dir=config_dir)
    projection_boards = build_inseason_projection_boards(config_dir=config_dir)
    matchup_categories = build_category_tracker(
        matchup,
        roster,
        opponent_roster,
        roster_starts,
        opponent_starts,
        as_of=as_of,
        force_schedule=force,
        config_dir=config_dir,
    )
    sp_start_tracker = build_sp_start_tracker(
        roster,
        recent_stats,
        projection_boards["pitchers"],
        as_of=as_of,
        force_schedule=force,
        config_dir=config_dir,
    )
    recent_transactions = load_recent_transactions(as_of=as_of, force=force, config_dir=config_dir)
    previous_free_agents = load_previous_free_agent_snapshot(as_of=as_of, config_dir=config_dir)
    waiver_groups = build_waiver_recommendation_groups(
        free_agents,
        free_agent_starts,
        recent_stats,
        team_roster=roster,
        matchup=matchup,
        projection_boards=projection_boards,
        rising_transactions=recent_transactions,
        previous_free_agents=previous_free_agents,
        as_of=as_of,
        force_schedule=force,
        config_dir=config_dir,
    )
    waiver_recommendations = build_waiver_recommendations(
        free_agents,
        free_agent_starts,
        recent_stats,
        team_roster=roster,
        matchup=matchup,
        projection_boards=projection_boards,
        rising_transactions=recent_transactions,
        previous_free_agents=previous_free_agents,
        as_of=as_of,
        force_schedule=force,
        config_dir=config_dir,
    )

    payload = {
        "as_of": as_of.isoformat(),
        "roster": roster,
        "opponent_roster": opponent_roster,
        "matchup": matchup,
        "matchup_tracker": matchup_categories,
        "free_agents": free_agents,
        "roster_starts": sp_start_tracker,
        "opponent_starts": opponent_starts,
        "free_agent_starts": free_agent_starts,
        "recent_stats": recent_stats.to_dict(orient="records"),
        "waiver_groups": {
            name: frame.to_dict(orient="records")
            for name, frame in waiver_groups.items()
        },
        "waiver_recommendations": waiver_recommendations.to_dict(orient="records"),
    }
    summary_path = _summary_cache_path(as_of, config_dir=config_dir)
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    summary = {
        "roster_count": len(roster),
        "free_agent_count": len(free_agents),
        "sp_start_count": len(roster_starts),
        "summary_path": str(summary_path),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh in-season fantasy baseball cache data.")
    parser.add_argument("--force", action="store_true", help="Bypass daily cache files and re-pull data.")
    args = parser.parse_args()

    summary = run_refresh(force=args.force)
    print(
        "Refreshed: "
        f"{summary['roster_count']} roster players, "
        f"{summary['free_agent_count']} free agents, "
        f"{summary['sp_start_count']} SP starts this week"
    )


if __name__ == "__main__":
    main()
