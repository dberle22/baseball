from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import httpx
import pandas as pd

from src.config import load_app_config
from src.inseason.player_stats import get_recent_form_score
from src.scoring import score_hitters, score_pitchers

CALL_UP_TYPES = {
    "contract selected",
    "recalled",
    "recall",
    "selected from minors",
    "selected contract",
    "purchased contract",
}
IL_RETURN_TYPES = {
    "returned",
    "returned from rehab",
    "reinstated",
    "reinstated from injured list",
    "activated",
    "activated from injured list",
}


def _normalize_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _cache_path(as_of: date, config_dir: str = "config") -> Path:
    config = load_app_config(config_dir)
    cache_dir = Path(config["file_paths"]["cache"]["base_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"transactions_{as_of.isoformat()}.json"


def _read_cached_transactions(cache_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    return list(payload.get("transactions", []))


def _write_cached_transactions(cache_path: Path, as_of: date, transactions: list[dict[str, Any]]) -> None:
    payload = {
        "as_of": as_of.isoformat(),
        "transactions": transactions,
    }
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _extract_player_name(transaction: dict[str, Any]) -> str:
    person = transaction.get("person") or {}
    return str(person.get("fullName") or transaction.get("playerName") or "")


def _extract_transaction_type(transaction: dict[str, Any]) -> str:
    return str(transaction.get("typeDesc") or transaction.get("typeCode") or transaction.get("description") or "")


def load_recent_transactions(
    *,
    as_of: date | None = None,
    lookback_days: int = 14,
    force: bool = False,
    config_dir: str = "config",
) -> list[dict[str, Any]]:
    as_of = as_of or date.today()
    cache_path = _cache_path(as_of, config_dir=config_dir)
    if cache_path.exists() and not force:
        return _read_cached_transactions(cache_path)

    params = {
        "sportId": 1,
        "startDate": (as_of - timedelta(days=max(lookback_days - 1, 0))).isoformat(),
        "endDate": as_of.isoformat(),
    }
    response = httpx.get("https://statsapi.mlb.com/api/v1/transactions", params=params, timeout=30.0)
    response.raise_for_status()
    raw_transactions = response.json().get("transactions", [])

    transactions = [
        {
            "name": _extract_player_name(transaction),
            "type": _extract_transaction_type(transaction),
            "date": str(transaction.get("date") or ""),
            "from_team": str((transaction.get("fromTeam") or {}).get("abbreviation") or ""),
            "to_team": str((transaction.get("toTeam") or {}).get("abbreviation") or ""),
            "description": str(transaction.get("description") or ""),
        }
        for transaction in raw_transactions
        if _extract_player_name(transaction)
    ]
    _write_cached_transactions(cache_path, as_of, transactions)
    return transactions


def load_previous_free_agent_snapshot(
    *,
    as_of: date | None = None,
    config_dir: str = "config",
) -> list[dict[str, Any]]:
    as_of = as_of or date.today()
    config = load_app_config(config_dir)
    cache_dir = Path(config["file_paths"]["cache"]["base_dir"])
    target_date = as_of - timedelta(days=7)
    exact = cache_dir / f"refresh_summary_{target_date.isoformat()}.json"
    if exact.exists():
        payload = json.loads(exact.read_text(encoding="utf-8"))
        return list(payload.get("free_agents", []))

    candidates = sorted(cache_dir.glob("refresh_summary_*.json"))
    latest_before_target: Path | None = None
    for candidate in candidates:
        try:
            candidate_date = date.fromisoformat(candidate.stem.replace("refresh_summary_", ""))
        except ValueError:
            continue
        if candidate_date < as_of and candidate_date <= target_date:
            latest_before_target = candidate

    if latest_before_target is None:
        return []

    payload = json.loads(latest_before_target.read_text(encoding="utf-8"))
    return list(payload.get("free_agents", []))


def _empty_recommendations() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "name",
            "position",
            "type",
            "score",
            "matchup_grade",
            "recent_form",
            "key_stats",
            "start_count_this_week",
            "notes",
            "percent_owned",
            "ownership_change",
        ]
    )


def _build_projection_score_map(
    free_agents: Iterable[dict[str, Any]],
    hitters: pd.DataFrame,
    pitchers: pd.DataFrame,
    *,
    config_dir: str = "config",
) -> dict[int, float]:
    config = load_app_config(config_dir)
    thresholds = config["league_settings"]["thresholds"]

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
    free_agent_ids = {int(player["player_id"]) for player in free_agents}
    combined = pd.concat(
        [
            scored_hitters.loc[scored_hitters["player_id"].isin(free_agent_ids), ["player_id", "final_score"]],
            scored_pitchers.loc[scored_pitchers["player_id"].isin(free_agent_ids), ["player_id", "final_score"]],
        ],
        ignore_index=True,
    ).drop_duplicates(subset=["player_id"], keep="first")
    if combined.empty:
        return {}

    scores = combined["final_score"]
    spread = float(scores.max() - scores.min()) if not scores.empty else 0.0
    if spread <= 0:
        combined["projection_signal"] = 0.5
    else:
        combined["projection_signal"] = (scores - float(scores.min())) / spread
    return combined.set_index("player_id")["projection_signal"].to_dict()


def _transaction_note_maps(transactions: Iterable[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    call_up_notes: dict[str, str] = {}
    il_return_notes: dict[str, str] = {}

    for transaction in transactions:
        name = _normalize_name(transaction.get("name"))
        tx_type = str(transaction.get("type", "")).strip()
        tx_type_key = tx_type.lower()
        tx_date = str(transaction.get("date") or "")
        if not name or not tx_type_key:
            continue

        if tx_type_key in CALL_UP_TYPES:
            call_up_notes[name] = f"Called up {tx_date}"
        elif tx_type_key in IL_RETURN_TYPES:
            il_return_notes[name] = f"Returned from IL {tx_date}"

    return call_up_notes, il_return_notes


def _recent_stats_maps(recent_stats: pd.DataFrame) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    if recent_stats.empty:
        return {}, {}
    frame = recent_stats.copy()
    if "recent_form" not in frame.columns:
        frame["recent_form"] = get_recent_form_score(frame)
    frame["recent_form"] = pd.to_numeric(frame["recent_form"], errors="coerce").fillna(0.5)
    frame = frame.sort_values("recent_form", ascending=False).drop_duplicates(subset="name", keep="first")
    return (
        frame.set_index("name")["recent_form"].to_dict(),
        frame.set_index("name").to_dict(orient="index"),
    )


def _position_label(player: dict[str, Any]) -> tuple[str, str]:
    positions = [str(position) for position in player.get("positions", []) if position]
    if "SP" in positions:
        return "SP", "SP"
    if "RP" in positions:
        return "RP", "RP"
    if positions:
        return positions[0], "H"
    if str(player.get("position_type", "")).upper() == "P":
        return "P", "P"
    return "BAT", "H"


def _key_stats(player_type: str, stats: dict[str, Any]) -> str:
    if player_type in {"SP", "RP", "P"}:
        return (
            f"14d ERA {stats.get('ERA', 'NA')}, WHIP {stats.get('WHIP', 'NA')}, "
            f"K/9 {stats.get('K/9', 'NA')}"
        )
    return (
        f"14d AVG {stats.get('AVG', 'NA')}, OBP {stats.get('OBP', 'NA')}, "
        f"HR {stats.get('HR', 'NA')}"
    )


def build_rising_player_rankings(
    free_agents: Iterable[dict[str, Any]],
    recent_stats: pd.DataFrame,
    hitters: pd.DataFrame,
    pitchers: pd.DataFrame,
    *,
    transactions: Iterable[dict[str, Any]] | None = None,
    previous_free_agents: Iterable[dict[str, Any]] | None = None,
    config_dir: str = "config",
) -> pd.DataFrame:
    free_agent_list = list(free_agents)
    if not free_agent_list:
        return _empty_recommendations()

    projection_score_map = _build_projection_score_map(
        free_agent_list,
        hitters,
        pitchers,
        config_dir=config_dir,
    )
    form_map, recent_map = _recent_stats_maps(recent_stats)
    previous_ownership = {
        int(player["player_id"]): int(player.get("percent_owned", 0) or 0)
        for player in (previous_free_agents or [])
        if player.get("player_id") is not None
    }
    call_up_notes, il_return_notes = _transaction_note_maps(transactions or [])

    recommendations: list[dict[str, Any]] = []
    for player in free_agent_list:
        player_id = int(player["player_id"])
        name = str(player.get("name", ""))
        name_key = _normalize_name(name)
        percent_owned = int(player.get("percent_owned", 0) or 0)
        ownership_change = percent_owned - previous_ownership.get(player_id, percent_owned)
        recent_form = float(form_map.get(name, 0.5) or 0.5)
        projection_signal = float(projection_score_map.get(player_id, 0.5) or 0.5)
        call_up_note = call_up_notes.get(name_key, "")
        il_return_note = il_return_notes.get(name_key, "")

        transaction_bonus = 0.0
        notes: list[str] = []
        if call_up_note:
            transaction_bonus += 0.25
            notes.append(call_up_note)
        if il_return_note and recent_form >= 0.5:
            transaction_bonus += 0.20
            notes.append(il_return_note)
        if ownership_change >= 5:
            notes.append(f"Yahoo ownership up {ownership_change} pts vs last week")

        if not notes and ownership_change < 5 and recent_form < 0.7:
            continue

        ownership_signal = min(max(ownership_change, 0), 25) / 25.0
        score = ownership_signal * 0.45 + recent_form * 0.25 + projection_signal * 0.20 + transaction_bonus

        position, player_type = _position_label(player)
        recommendations.append(
            {
                "name": name,
                "position": position,
                "type": player_type,
                "score": round(score, 3),
                "matchup_grade": "Rising",
                "recent_form": round(recent_form, 3),
                "key_stats": _key_stats(player_type, recent_map.get(name, {})),
                "start_count_this_week": 0,
                "notes": ", ".join(notes) if notes else "Trending up",
                "percent_owned": percent_owned,
                "ownership_change": ownership_change,
            }
        )

    if not recommendations:
        return _empty_recommendations()

    frame = pd.DataFrame(recommendations)
    return frame.sort_values(["score", "percent_owned"], ascending=[False, False]).head(5).reset_index(drop=True)
