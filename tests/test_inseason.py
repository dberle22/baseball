from __future__ import annotations

import pandas as pd

from src.inseason.matchup_tracker import build_category_tracker, build_sp_start_tracker
from src.inseason.rising_players import build_rising_player_rankings
from src.inseason.player_stats import get_recent_form_score
from src.inseason.projections import build_inseason_projection_boards
from src.inseason.schedule import _extract_probable_starts, rate_matchup
from src.inseason.waiver_ranker import _recent_stats_maps as waiver_recent_stats_maps
from src.inseason.waiver_ranker import build_general_pickup_rankings, build_sp_streamer_rankings


def test_get_recent_form_score_prefers_better_hitters_and_pitchers() -> None:
    frame = pd.DataFrame(
        [
            {"name": "Hot Hitter", "player_type": "H", "AVG": 0.340, "OBP": 0.430, "HR": 4, "SB": 2, "wRC+": 155},
            {"name": "Cold Hitter", "player_type": "H", "AVG": 0.210, "OBP": 0.260, "HR": 0, "SB": 0, "wRC+": 65},
            {"name": "Good Pitcher", "player_type": "P", "ERA": 2.10, "WHIP": 0.92, "K/9": 11.5, "K%": 0.31, "xFIP": 2.95},
            {"name": "Bad Pitcher", "player_type": "P", "ERA": 6.10, "WHIP": 1.58, "K/9": 6.1, "K%": 0.16, "xFIP": 4.90},
        ]
    )

    scores = get_recent_form_score(frame)

    assert scores.iloc[0] > scores.iloc[1]
    assert scores.iloc[2] > scores.iloc[3]
    assert scores.between(0, 1).all()


def test_extract_probable_starts_flattens_schedule_payload() -> None:
    payload = {
        "dates": [
            {
                "date": "2026-05-05",
                "games": [
                    {
                        "teams": {
                            "home": {
                                "team": {"abbreviation": "NYY"},
                                "probablePitcher": {"fullName": "Gerrit Cole"},
                            },
                            "away": {
                                "team": {"abbreviation": "BOS"},
                                "probablePitcher": {"fullName": "Garrett Crochet"},
                            },
                        }
                    }
                ],
            }
        ]
    }

    starts = _extract_probable_starts(payload)

    assert starts == [
        {
            "name": "Gerrit Cole",
            "probable_pitcher_id": None,
            "mlb_team": "NYY",
            "opponent_team": "BOS",
            "game_date": "2026-05-05",
            "is_home": True,
            "game_pk": None,
            "game_status": "",
        },
        {
            "name": "Garrett Crochet",
            "probable_pitcher_id": None,
            "mlb_team": "BOS",
            "opponent_team": "NYY",
            "game_date": "2026-05-05",
            "is_home": False,
            "game_pk": None,
            "game_status": "",
        },
    ]


def test_rate_matchup_uses_wrc_thresholds() -> None:
    favorable = rate_matchup("MIA", team_offense={"MIA": 88})
    neutral = rate_matchup("SEA", team_offense={"SEA": 103})
    difficult = rate_matchup("LAD", team_offense={"LAD": 118})

    assert favorable["matchup_grade"] == "A"
    assert neutral["matchup_grade"] == "C"
    assert difficult["matchup_grade"] == "D"
    assert favorable["matchup_score"] > difficult["matchup_score"]


def test_build_inseason_projection_boards_falls_back_to_draft_sources_when_inseason_files_missing() -> None:
    boards = build_inseason_projection_boards()

    assert {"hitters", "pitchers"} == set(boards)
    assert not boards["hitters"].empty
    assert not boards["pitchers"].empty
    assert {"player_id", "player_name", "position"}.issubset(boards["hitters"].columns)
    assert {"player_id", "player_name", "inferred_role"}.issubset(boards["pitchers"].columns)


def test_build_sp_streamer_rankings_scores_and_sorts_players() -> None:
    free_agents = [
        {"player_id": 1, "name": "Pitcher One", "positions": ["SP"], "position_type": "P", "percent_owned": 20, "mlb_team": "NYY"},
        {"player_id": 2, "name": "Pitcher Two", "positions": ["SP"], "position_type": "P", "percent_owned": 10, "mlb_team": "SEA"},
    ]
    starts = [
        {"name": "Pitcher One", "opponent_team": "MIA", "game_date": "2026-05-06", "is_home": True, "matchup_grade": "A", "matchup_score": 0.9},
        {"name": "Pitcher One", "opponent_team": "COL", "game_date": "2026-05-10", "is_home": False, "matchup_grade": "A", "matchup_score": 0.8},
        {"name": "Pitcher Two", "opponent_team": "LAD", "game_date": "2026-05-07", "is_home": False, "matchup_grade": "D", "matchup_score": 0.1},
    ]
    recent_stats = pd.DataFrame(
        [
            {"name": "Pitcher One", "player_type": "P", "recent_form": 0.8, "ERA": 2.5, "WHIP": 1.01, "K/9": 10.2},
            {"name": "Pitcher Two", "player_type": "P", "recent_form": 0.3, "ERA": 5.2, "WHIP": 1.42, "K/9": 7.1},
        ]
    )
    projections = pd.DataFrame(
        [
            {"player_id": 1, "player_name": "Pitcher One", "inferred_role": "SP", "IP": 140, "K": 170, "ERA": 3.6, "WHIP": 1.18},
            {"player_id": 2, "player_name": "Pitcher Two", "inferred_role": "SP", "IP": 120, "K": 110, "ERA": 4.4, "WHIP": 1.31},
        ]
    )

    ranked = build_sp_streamer_rankings(free_agents, starts, recent_stats, projections)

    assert list(ranked["name"]) == ["Pitcher One", "Pitcher Two"]
    assert ranked.iloc[0]["score"] > ranked.iloc[1]["score"]
    assert ranked.iloc[0]["start_count_this_week"] == 2
    assert bool(ranked.iloc[0]["two_start_week"]) is True
    assert ranked.iloc[0]["matchup_details"] == "vs MIA (A), vs COL (A)"


def test_build_general_pickup_rankings_splits_hitters_and_relievers(monkeypatch) -> None:
    free_agents = [
        {"player_id": 11, "name": "Useful Hitter", "positions": ["2B", "OF"], "position_type": "B", "percent_owned": 32, "mlb_team": "NYY"},
        {"player_id": 12, "name": "Spec RP", "positions": ["RP"], "position_type": "P", "percent_owned": 28, "mlb_team": "SEA"},
    ]
    roster = [
        {"player_id": 99, "name": "My Starter", "positions": ["C"], "is_starting": True},
    ]
    matchup = {
        "my_stats": {"Saves+Holds": 1},
        "opponent_stats": {"Saves+Holds": 2},
    }
    recent_stats = pd.DataFrame(
        [
            {"name": "Useful Hitter", "player_type": "H", "recent_form": 0.7, "AVG": 0.305, "OBP": 0.390, "HR": 3},
            {"name": "Spec RP", "player_type": "P", "recent_form": 0.65, "ERA": 2.2, "WHIP": 0.98, "K/9": 11.4},
        ]
    )
    hitters = pd.DataFrame(
        [
            {"player_id": 11, "player_name": "Useful Hitter", "position": "2B", "PA": 500, "R": 75, "RBI": 68, "HR": 24, "SB": 14, "AVG": 0.272, "OBP": 0.345, "Spd": 4.5, "adp": 180},
        ]
    )
    pitchers = pd.DataFrame(
        [
            {"player_id": 12, "player_name": "Spec RP", "inferred_role": "RP", "IP": 62, "QS": 0, "K": 84, "Saves_plus_Holds": 28, "ERA": 3.05, "WHIP": 1.09, "adp": 210},
        ]
    )

    monkeypatch.setattr(
        "src.inseason.waiver_ranker.get_team_game_counts",
        lambda **kwargs: {"NYY": 7, "SEA": 6},
    )

    groups = build_general_pickup_rankings(
        free_agents,
        recent_stats,
        hitters,
        pitchers,
        team_roster=roster,
        matchup=matchup,
    )

    assert list(groups["hitters"]["name"]) == ["Useful Hitter"]
    assert groups["hitters"].iloc[0]["matchup_grade"] == "7 games"
    assert list(groups["relievers"]["name"]) == ["Spec RP"]
    assert groups["relievers"].iloc[0]["matchup_grade"] == "SV+HLD priority"


def test_recent_stats_maps_handles_duplicate_names() -> None:
    recent_stats = pd.DataFrame(
        [
            {"name": "Duplicate Name", "recent_form": 0.35, "AVG": 0.220},
            {"name": "Duplicate Name", "recent_form": 0.81, "AVG": 0.333},
            {"name": "Unique Name", "recent_form": 0.52, "AVG": 0.255},
        ]
    )

    form_map, row_map = waiver_recent_stats_maps(recent_stats)

    assert form_map["Duplicate Name"] == 0.81
    assert row_map["Duplicate Name"]["AVG"] == 0.333
    assert form_map["Unique Name"] == 0.52


def test_build_rising_player_rankings_uses_transactions_and_ownership_trend() -> None:
    free_agents = [
        {"player_id": 21, "name": "Callup Bat", "positions": ["SS"], "position_type": "B", "percent_owned": 22},
        {"player_id": 22, "name": "IL Pitcher", "positions": ["RP"], "position_type": "P", "percent_owned": 36},
    ]
    previous_free_agents = [
        {"player_id": 21, "name": "Callup Bat", "percent_owned": 9},
        {"player_id": 22, "name": "IL Pitcher", "percent_owned": 33},
    ]
    transactions = [
        {"name": "Callup Bat", "type": "Recalled", "date": "2026-05-01"},
        {"name": "IL Pitcher", "type": "Reinstated", "date": "2026-05-03"},
    ]
    recent_stats = pd.DataFrame(
        [
            {"name": "Callup Bat", "player_type": "H", "recent_form": 0.84, "AVG": 0.333, "OBP": 0.402, "HR": 2},
            {"name": "IL Pitcher", "player_type": "P", "recent_form": 0.74, "ERA": 1.8, "WHIP": 0.95, "K/9": 12.1},
        ]
    )
    hitters = pd.DataFrame(
        [
            {"player_id": 21, "player_name": "Callup Bat", "position": "SS", "PA": 420, "R": 70, "RBI": 58, "HR": 19, "SB": 11, "AVG": 0.266, "OBP": 0.338, "Spd": 4.2, "adp": 240},
        ]
    )
    pitchers = pd.DataFrame(
        [
            {"player_id": 22, "player_name": "IL Pitcher", "inferred_role": "RP", "IP": 58, "QS": 0, "K": 79, "Saves_plus_Holds": 24, "ERA": 2.95, "WHIP": 1.05, "adp": 260},
        ]
    )

    ranked = build_rising_player_rankings(
        free_agents,
        recent_stats,
        hitters,
        pitchers,
        transactions=transactions,
        previous_free_agents=previous_free_agents,
    )

    assert list(ranked["name"]) == ["Callup Bat", "IL Pitcher"]
    assert "Called up 2026-05-01" in ranked.iloc[0]["notes"]
    assert ranked.iloc[0]["ownership_change"] == 13
    assert "Returned from IL 2026-05-03" in ranked.iloc[1]["notes"]


def test_build_category_tracker_projects_counting_categories(monkeypatch) -> None:
    matchup = {
        "categories": ["R", "ERA", "Saves+Holds"],
        "my_stats": {"R": 20, "ERA": 3.5, "Saves+Holds": 2},
        "opponent_stats": {"R": 18, "ERA": 3.1, "Saves+Holds": 3},
    }
    my_roster = [
        {"name": "Bat One", "positions": ["OF"], "mlb_team": "NYY", "is_starting": True},
        {"name": "Relief One", "positions": ["RP"], "mlb_team": "SEA", "is_starting": True},
    ]
    opponent_roster = [
        {"name": "Bat Two", "positions": ["OF"], "mlb_team": "BOS", "is_starting": True},
        {"name": "Relief Two", "positions": ["RP"], "mlb_team": "LAD", "is_starting": True},
    ]
    my_starts = [{"name": "Starter One", "game_date": "2026-05-08", "game_status": "Scheduled"}]
    opponent_starts = [{"name": "Starter Two", "game_date": "2026-05-09", "game_status": "Scheduled"}]
    schedule_payload = {
        "dates": [
            {
                "date": "2026-05-05",
                "games": [
                    {
                        "teams": {
                            "home": {"team": {"abbreviation": "NYY"}},
                            "away": {"team": {"abbreviation": "BOS"}},
                        }
                    },
                    {
                        "teams": {
                            "home": {"team": {"abbreviation": "SEA"}},
                            "away": {"team": {"abbreviation": "LAD"}},
                        }
                    },
                ],
            },
            {
                "date": "2026-05-08",
                "games": [
                    {
                        "teams": {
                            "home": {"team": {"abbreviation": "NYY"}},
                            "away": {"team": {"abbreviation": "SEA"}},
                        }
                    },
                    {
                        "teams": {
                            "home": {"team": {"abbreviation": "BOS"}},
                            "away": {"team": {"abbreviation": "LAD"}},
                        }
                    },
                ],
            },
        ]
    }

    monkeypatch.setattr("src.inseason.matchup_tracker.load_week_schedule", lambda **kwargs: schedule_payload)

    rows = build_category_tracker(
        matchup,
        my_roster,
        opponent_roster,
        my_starts,
        opponent_starts,
        as_of=pd.Timestamp("2026-05-06").date(),
    )

    assert rows[0]["category"] == "R"
    assert rows[0]["status"] == "Winning"
    assert rows[0]["my_projected_total"] == 40.0
    assert rows[1]["my_projected_total"] == 3.5
    assert rows[2]["projected_status"] == "Losing"


def test_build_sp_start_tracker_adds_projection_and_completed_line(monkeypatch) -> None:
    roster = [
        {"name": "Pitcher One", "mlb_team": "NYY", "positions": ["SP"], "is_starting": True},
    ]
    starts = [
        {
            "name": "Pitcher One",
            "probable_pitcher_id": 99,
            "opponent_team": "BOS",
            "game_date": "2026-05-04",
            "is_home": True,
            "game_pk": 123,
            "game_status": "Final",
            "matchup_grade": "A",
        }
    ]
    recent_stats = pd.DataFrame([{"name": "Pitcher One", "K/9": 10.4}])
    pitcher_projections = pd.DataFrame(
        [
            {
                "player_name": "Pitcher One",
                "team": "NYY",
                "IP": 150,
                "GS": 30,
                "K": 180,
                "ERA": 3.4,
                "WHIP": 1.11,
            }
        ]
    )
    boxscore = {
        "teams": {
            "home": {
                "players": {
                    "ID99": {
                        "person": {"id": 99, "fullName": "Pitcher One"},
                        "stats": {"pitching": {"inningsPitched": "6.0", "earnedRuns": 2, "strikeOuts": 8}},
                    }
                }
            },
            "away": {"players": {}},
        }
    }

    monkeypatch.setattr("src.inseason.matchup_tracker.get_this_weeks_starts", lambda *args, **kwargs: starts)
    monkeypatch.setattr("src.inseason.matchup_tracker._fetch_boxscore", lambda game_pk: boxscore)

    rows = build_sp_start_tracker(
        roster,
        recent_stats,
        pitcher_projections,
        as_of=pd.Timestamp("2026-05-05").date(),
    )

    assert rows[0]["home_away"] == "Home"
    assert rows[0]["projected_k"] == 6.0
    assert rows[0]["projected_era"] == 3.4
    assert rows[0]["actual_line"] == "6.0 IP, 2 ER, 8 K"
    assert bool(rows[0]["completed"]) is True
