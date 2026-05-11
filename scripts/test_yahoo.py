from __future__ import annotations

from pprint import pprint
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.yahoo import (
    get_current_matchup,
    get_free_agents,
    get_league_settings,
    get_my_team,
    get_sc,
    get_standings,
)


def main() -> None:
    sc = get_sc()

    print("== My Team ==")
    pprint(get_my_team(sc))
    print()

    print("== Current Matchup ==")
    pprint(get_current_matchup(sc))
    print()

    print("== League Settings ==")
    pprint(get_league_settings(sc))
    print()

    print("== Standings ==")
    pprint(get_standings(sc))
    print()

    print("== Free Agents ==")
    pprint(get_free_agents(sc, count=25))


if __name__ == "__main__":
    main()
