from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.config import load_app_config

APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parents[1]
TEMPLATES = Jinja2Templates(directory=str(APP_ROOT / "templates"))

app = FastAPI(title="Fantasy Baseball In-Season Dashboard")


def get_config_dir() -> str:
    return os.environ.get("BASEBALL_CONFIG_DIR", "config")


def _cache_dir(config_dir: str | None = None) -> Path:
    config_dir = config_dir or get_config_dir()
    config = load_app_config(config_dir)
    return Path(config["file_paths"]["cache"]["base_dir"])


def _latest_summary_path(config_dir: str | None = None) -> Path | None:
    cache_dir = _cache_dir(config_dir)
    candidates = sorted(cache_dir.glob("refresh_summary_*.json"))
    if not candidates:
        return None
    return candidates[-1]


def _status_class(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "winning":
        return "status-win"
    if normalized == "losing":
        return "status-lose"
    return "status-close"


def _grade_class(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized.startswith("A"):
        return "grade-a"
    if normalized.startswith("B"):
        return "grade-b"
    if normalized.startswith("C"):
        return "grade-c"
    if normalized.startswith("D") or normalized.startswith("F"):
        return "grade-d"
    return "grade-neutral"


def _last_refreshed_label(summary_path: Path) -> str:
    return datetime.fromtimestamp(summary_path.stat().st_mtime).strftime("%Y-%m-%d %I:%M %p")


def load_dashboard_context(config_dir: str | None = None) -> dict[str, Any]:
    config_dir = config_dir or get_config_dir()
    summary_path = _latest_summary_path(config_dir)
    if summary_path is None:
        return {
            "has_data": False,
            "team_name": "Fantasy Team",
            "week": "N/A",
            "opponent_name": "N/A",
            "last_refreshed": "Never",
            "matchup_tracker": [],
            "sp_starts": [],
            "waiver_groups": {"sp_streamers": [], "hitters": [], "relievers": [], "rising_players": []},
            "summary_path": None,
        }

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    matchup = payload.get("matchup", {})
    waiver_groups = payload.get("waiver_groups", {})
    matchup_tracker = list(payload.get("matchup_tracker", []))
    sp_starts = list(payload.get("roster_starts", []))

    for row in matchup_tracker:
        row["status_class"] = _status_class(str(row.get("status", "")))
        row["projected_status_class"] = _status_class(str(row.get("projected_status", "")))

    for start in sp_starts:
        start["grade_class"] = _grade_class(str(start.get("matchup_grade", "")))

    for group_rows in waiver_groups.values():
        for row in group_rows:
            row["grade_class"] = _grade_class(str(row.get("matchup_grade", "")))

    return {
        "has_data": True,
        "team_name": matchup.get("my_team_name", "Fantasy Team"),
        "week": matchup.get("week", "N/A"),
        "opponent_name": matchup.get("opponent_team_name", "N/A"),
        "last_refreshed": _last_refreshed_label(summary_path),
        "matchup_tracker": matchup_tracker,
        "sp_starts": sp_starts,
        "waiver_groups": {
            "sp_streamers": list(waiver_groups.get("sp_streamers", [])),
            "hitters": list(waiver_groups.get("hitters", [])),
            "relievers": list(waiver_groups.get("relievers", [])),
            "rising_players": list(waiver_groups.get("rising_players", [])),
        },
        "summary_path": str(summary_path),
    }


def _render(request: Request, template_name: str, *, config_dir: str | None = None) -> Any:
    context = load_dashboard_context(config_dir)
    context["request"] = request
    return TEMPLATES.TemplateResponse(request, template_name, context)


@app.get("/")
def dashboard(request: Request) -> Any:
    return _render(request, "dashboard.html")


@app.get("/waiver")
def waiver(request: Request) -> Any:
    return _render(request, "waiver.html")


@app.get("/my-week")
def my_week(request: Request) -> Any:
    return _render(request, "my_week.html")


@app.post("/refresh")
def refresh() -> RedirectResponse:
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "refresh.py")],
        check=True,
        cwd=str(PROJECT_ROOT),
    )
    return RedirectResponse(url="/", status_code=303)
