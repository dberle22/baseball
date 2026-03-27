from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


HITTER_POSITIONS = {"C", "1B", "2B", "3B", "SS", "OF"}
PITCHER_POSITIONS = {"SP", "RP", "P"}
CATEGORY_ORDER = ["R", "RBI", "HR", "SB", "AVG", "OBP", "QS", "K", "Saves_plus_Holds", "ERA", "WHIP"]


@dataclass(frozen=True)
class AvailablePlayer:
    queue_rank: int
    overall_rank: int
    player_name: str
    team: str
    inferred_role: str
    adp: float
    adp_gap: float
    queue_score: float
    final_score: float
    dropoff_to_next: float
    tier: int
    note: str


@dataclass(frozen=True)
class TeamPlayer:
    slot: str
    player_name: str
    role: str
    type: str
    final_score: float
    note: str


@dataclass(frozen=True)
class CategoryNeed:
    category: str
    current: float
    goal: float
    gap: float
    effective_need: float


@dataclass(frozen=True)
class Recommendation:
    player: AvailablePlayer
    need_boost: float
    rank_tuple: tuple[float, float, float, float, float]


def load_available_players(path: str | Path) -> list[AvailablePlayer]:
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return [
            AvailablePlayer(
                queue_rank=int(row["queue_rank"]),
                overall_rank=int(row["overall_rank"]),
                player_name=row["player_name"],
                team=row["team"],
                inferred_role=row["inferred_role"],
                adp=float(row["adp"]),
                adp_gap=float(row["adp_gap"]),
                queue_score=float(row["queue_score"]),
                final_score=float(row["final_score"]),
                dropoff_to_next=float(row["dropoff_to_next"]),
                tier=int(row["tier"]),
                note=row["note"],
            )
            for row in reader
        ]


def load_team_context(path: str | Path) -> tuple[list[TeamPlayer], list[CategoryNeed], Counter]:
    roster_players: list[TeamPlayer] = []
    category_needs: list[CategoryNeed] = []
    position_counts: Counter = Counter()

    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row["player_name"]:
                roster_players.append(
                    TeamPlayer(
                        slot=row["slot"],
                        player_name=row["player_name"],
                        role=row["role"],
                        type=row["type"],
                        final_score=float(row["final_score"] or 0),
                        note=row["note"],
                    )
                )
                if row["role"] in HITTER_POSITIONS | PITCHER_POSITIONS:
                    position_counts[row["role"]] += 1

            if row["category"]:
                category_needs.append(
                    CategoryNeed(
                        category=row["category"],
                        current=float(row["current"]),
                        goal=float(row["goal"]),
                        gap=float(row["gap"]),
                        effective_need=float(row["effective_need"]),
                    )
                )

    return roster_players, category_needs, position_counts


def summarize_position_needs(roster_players: list[TeamPlayer]) -> list[str]:
    filled_slots = {player.slot: player.player_name for player in roster_players}
    priority_order = ["C", "1B", "2B", "3B", "SS", "OF", "SP", "RP", "P"]
    missing_counts: Counter = Counter()

    for slot in ["C", "1B", "2B", "3B", "SS", "OF1", "OF2", "OF3", "SP1", "SP2", "RP1", "RP2", "P1", "P2", "P3", "P4"]:
        if filled_slots.get(slot):
            continue
        role = slot.rstrip("1234")
        missing_counts[role] += 1

    return [role for role in priority_order if missing_counts[role] > 0]


def summarize_category_priorities(category_needs: list[CategoryNeed]) -> list[str]:
    positives = [need for need in category_needs if need.effective_need > 0]
    if not positives:
        return []
    positives.sort(key=lambda need: need.effective_need, reverse=True)
    return [need.category for need in positives[:4]]


def _note_category_map(player_type: str, note: str) -> set[str]:
    if note == "power boost":
        return {"R", "RBI", "HR"}
    if note == "speed specialist":
        return {"R", "SB"}
    if note == "strikeout arm":
        return {"QS", "K"}
    if note == "RP saves+holds":
        return {"Saves_plus_Holds"}
    if note == "ratio stabilizer":
        return {"AVG", "OBP"} if player_type == "H" else {"ERA", "WHIP"}
    return set()


def _player_type(role: str) -> str:
    return "P" if role in PITCHER_POSITIONS else "H"


def rank_players(available_players: list[AvailablePlayer], position_needs: list[str], category_priorities: list[str]) -> list[Recommendation]:
    top_position_needs = set(position_needs[:2])
    top_categories = set(category_priorities[:3])
    recommendations: list[Recommendation] = []

    for player in available_players:
        need_boost = 0.0
        if player.inferred_role in top_position_needs:
            need_boost += 0.08
        if _note_category_map(_player_type(player.inferred_role), player.note) & top_categories:
            need_boost += 0.06

        rank_tuple = (
            player.queue_score,
            player.final_score,
            -float(player.tier),
            player.dropoff_to_next,
            need_boost,
        )
        recommendations.append(Recommendation(player=player, need_boost=need_boost, rank_tuple=rank_tuple))

    recommendations.sort(key=lambda item: item.rank_tuple, reverse=True)
    return recommendations


def players_to_wait_on(available_players: list[AvailablePlayer], top_names: set[str]) -> list[str]:
    role_counts = Counter(player.inferred_role for player in available_players)
    waiters: list[str] = []
    for player in available_players:
        if player.player_name in top_names:
            continue
        if role_counts[player.inferred_role] < 5:
            continue
        if player.dropoff_to_next > 0.04:
            continue
        if player.inferred_role not in {"RP", "C", "2B", "SS"}:
            continue
        waiters.append(player.player_name)
        if len(waiters) == 4:
            break
    return waiters


def build_two_player_plan(recommendations: list[Recommendation]) -> str:
    if len(recommendations) < 2:
        return ""

    first = recommendations[0].player
    for candidate in recommendations[1:6]:
        second = candidate.player
        if second.inferred_role != first.inferred_role:
            return f"{first.player_name} + {second.player_name}"
    second = recommendations[1].player
    return f"{first.player_name} + {second.player_name}"


def format_recommendation_report(available_path: str | Path, team_path: str | Path) -> str:
    available_players = load_available_players(available_path)
    roster_players, category_needs, _position_counts = load_team_context(team_path)
    position_needs = summarize_position_needs(roster_players)
    category_priorities = summarize_category_priorities(category_needs)
    recommendations = rank_players(available_players, position_needs, category_priorities)

    top_ten = recommendations[:10]
    top_names = {item.player.player_name for item in top_ten}
    best_pick = top_ten[0].player
    waiters = players_to_wait_on(available_players, top_names)
    two_player_plan = build_two_player_plan(recommendations[:8])

    lines = [
        f"Best pick: {best_pick.player_name} ({best_pick.inferred_role}) | queue {best_pick.queue_score:.3f} | final {best_pick.final_score:.3f} | tier {best_pick.tier} | dropoff {best_pick.dropoff_to_next:.3f}",
        "Top 10: " + ", ".join(
            f"{item.player.player_name} ({item.player.inferred_role})" for item in top_ten
        ),
        "Category priorities: " + (", ".join(category_priorities) if category_priorities else "none"),
        "Position priorities: " + (", ".join(position_needs[:4]) if position_needs else "none"),
        "Approach: value first; use needs only as tie-breakers.",
    ]

    if waiters:
        lines.append("Can likely wait: " + ", ".join(waiters))
    if two_player_plan:
        lines.append("2-player plan: " + two_player_plan)

    return "\n".join(lines)
