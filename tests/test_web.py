from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import scripts.start as start
from src.web.app import app, load_dashboard_context


def _write_config(config_dir: Path, cache_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "file_paths.yaml").write_text(
        f"cache:\n  base_dir: {cache_dir}\n",
        encoding="utf-8",
    )
    (config_dir / "league_settings.yaml").write_text("league: {}\n", encoding="utf-8")
    (config_dir / "weights.yaml").write_text("inseason: {}\n", encoding="utf-8")


def _write_summary(cache_dir: Path) -> None:
    payload = {
        "matchup": {
            "my_team_name": "Dan's Dingers",
            "opponent_team_name": "Rival Squad",
            "week": 6,
        },
        "matchup_tracker": [
            {
                "category": "HR",
                "my_total": 5,
                "opponent_total": 4,
                "status": "Winning",
                "my_projected_total": 9,
                "opponent_projected_total": 7,
                "projected_status": "Winning",
                "my_remaining_opportunities": 18,
                "opponent_remaining_opportunities": 16,
            }
        ],
        "roster_starts": [
            {
                "name": "Pitcher One",
                "game_date": "2026-05-06",
                "opponent_team": "MIA",
                "home_away": "Home",
                "matchup_grade": "A",
                "projected_k": 7.2,
                "projected_era": 3.45,
                "projected_whip": 1.12,
                "completed": True,
                "actual_line": "6 IP, 2 ER, 8 K",
                "game_status": "Final",
            }
        ],
        "waiver_groups": {
            "sp_streamers": [
                {
                    "name": "Streamer A",
                    "score": 0.88,
                    "matchup_grade": "A",
                    "start_count_this_week": 2,
                    "key_stats": "14d ERA 2.80",
                }
            ],
            "hitters": [
                {
                    "name": "Bat A",
                    "position": "2B",
                    "type": "Hitter",
                    "score": 0.7,
                    "matchup_grade": "7 games",
                    "notes": "Hot bat",
                }
            ],
            "relievers": [
                {
                    "name": "Relief A",
                    "position": "RP",
                    "type": "RP",
                    "score": 0.65,
                    "matchup_grade": "SV+HLD priority",
                    "notes": "Category help",
                }
            ],
            "rising_players": [
                {
                    "name": "Prospect A",
                    "position": "SS",
                    "score": 0.72,
                    "notes": "Called up 2026-05-05",
                }
            ],
        },
    }
    (cache_dir / "refresh_summary_2026-05-05.json").write_text(json.dumps(payload), encoding="utf-8")


def test_load_dashboard_context_reads_latest_summary(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    _write_config(config_dir, cache_dir)
    _write_summary(cache_dir)

    context = load_dashboard_context(str(config_dir))

    assert context["has_data"] is True
    assert context["team_name"] == "Dan's Dingers"
    assert context["opponent_name"] == "Rival Squad"
    assert context["matchup_tracker"][0]["status_class"] == "status-win"
    assert context["sp_starts"][0]["grade_class"] == "grade-a"


def test_dashboard_and_refresh_routes(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    _write_config(config_dir, cache_dir)
    _write_summary(cache_dir)

    monkeypatch.setenv("BASEBALL_CONFIG_DIR", str(config_dir))

    calls: list[list[str]] = []

    def fake_run(command: list[str], check: bool, cwd: str) -> None:
        calls.append(command)

    monkeypatch.setattr("src.web.app.subprocess.run", fake_run)

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Week 6 vs Rival Squad" in response.text
    assert "6 IP, 2 ER, 8 K" in response.text
    assert "SP Streamers" in response.text

    refresh_response = client.post("/refresh", follow_redirects=False)
    assert refresh_response.status_code == 303
    assert refresh_response.headers["location"] == "/"
    assert calls


def test_cache_is_stale(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    _write_config(config_dir, cache_dir)

    assert start.cache_is_stale(str(config_dir)) is True

    _write_summary(cache_dir)

    assert start.cache_is_stale(str(config_dir)) is False
