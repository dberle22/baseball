from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd

from .blend import blend_sources
from .config import load_app_config
from .export import export_workbook
from .io import ensure_output_dirs, load_projection_sources, write_csv
from .recommendations import (
    add_hitter_notes,
    add_pitcher_notes,
    build_category_contribution,
    build_draft_day_queue,
    build_scarcity_sheet,
    build_sleepers_fades,
)
from .scoring import prepare_overall_board, round_for_export, score_hitters, score_pitchers
from .standardize import apply_hitter_positions, required_input_columns, standardize_projection, trim_projection_pool
from .tiers import add_score_dropoffs, assign_tiers


def build_draft_board(config_dir: str = "config", outdir: str | None = None, phase: str = "early") -> Dict[str, Any]:
    config = load_app_config(config_dir)
    paths = config["file_paths"]

    processed_dir = Path(paths["output"]["processed_dir"])
    exports_dir = Path(outdir or paths["output"]["exports_dir"])
    ensure_output_dirs(processed_dir, exports_dir)
    cleaned_sources_dir = processed_dir / "cleaned_sources"
    cleaned_sources_dir.mkdir(parents=True, exist_ok=True)

    hitter_sources_raw = load_projection_sources(
        paths["input_files"]["hitters"],
        usecols=required_input_columns("hitters"),
    )
    hitter_positions = pd.read_csv(Path(paths["input_files"]["positions"]), usecols=["Name", "POS"])
    pitcher_sources_raw = load_projection_sources(
        paths["input_files"]["pitchers"],
        usecols=required_input_columns("pitchers"),
    )

    hitter_sources = {
        source: trim_projection_pool(standardize_projection(frame, source, "hitters"), "hitters")
        for source, frame in hitter_sources_raw.items()
    }
    pitcher_sources = {
        source: trim_projection_pool(standardize_projection(frame, source, "pitchers"), "pitchers")
        for source, frame in pitcher_sources_raw.items()
    }

    for source_name, frame in hitter_sources.items():
        write_csv(frame, cleaned_sources_dir / f"{source_name}_hitters_clean.csv")
    for source_name, frame in pitcher_sources.items():
        write_csv(frame, cleaned_sources_dir / f"{source_name}_pitchers_clean.csv")

    hitters = blend_sources(
        hitter_sources,
        config["weights"]["blend"]["hitters"],
        ["PA", "R", "RBI", "HR", "SB", "AVG", "OBP", "K", "BB", "Spd"],
        "hitters",
    )
    hitters = apply_hitter_positions(hitters, hitter_positions)
    pitchers = blend_sources(
        pitcher_sources,
        config["weights"]["blend"]["pitchers"],
        ["IP", "QS", "ERA", "WHIP", "K", "Saves", "Holds", "GS", "G", "BB"],
        "pitchers",
    )

    thresholds = config["league_settings"]["thresholds"]
    hitters = score_hitters(hitters, config["weights"]["scoring"]["hitters"], thresholds["hitters_min_pa"])
    pitchers = score_pitchers(
        pitchers,
        config["weights"]["scoring"]["pitchers"],
        thresholds["pitchers_min_ip"],
        thresholds["relievers_min_svh"],
    )

    hitters = assign_tiers(hitters, "final_score", config["weights"]["tiering"])
    pitchers = assign_tiers(pitchers, "final_score", config["weights"]["tiering"])
    hitters = add_hitter_notes(hitters)
    pitchers = add_pitcher_notes(pitchers)
    hitters = add_score_dropoffs(hitters, "final_score", "final_rank")
    pitchers = add_score_dropoffs(pitchers, "final_score", "final_rank")

    overall_board = prepare_overall_board(hitters, pitchers)
    overall_board = assign_tiers(overall_board, "final_score", config["weights"]["tiering"])
    overall_board["specialist_flag"] = overall_board["specialist_flag"].fillna(0).astype(int)
    overall_board = add_score_dropoffs(overall_board, "final_score", "overall_rank")
    hitters_position_review = hitters.loc[hitters["inferred_role"] == "BAT"].copy()
    hitters_position_review = hitters_position_review[
        [
            "final_rank",
            "player_name",
            "player_name_ascii",
            "team",
            "player_id",
            "mlbam_id",
            "position",
            "inferred_role",
            "PA",
            "R",
            "RBI",
            "HR",
            "SB",
            "AVG",
            "OBP",
            "adp",
            "adp_gap",
            "tier",
            "final_score",
            "note",
        ]
    ]

    tier_sheet = pd.concat(
        [
            overall_board.assign(board_type="overall")[["board_type", "overall_rank", "player_name", "inferred_role", "tier", "final_score", "dropoff_to_next"]],
            hitters.assign(board_type="hitters")[["board_type", "final_rank", "player_name", "inferred_role", "tier", "final_score", "dropoff_to_next"]].rename(columns={"final_rank": "overall_rank"}),
            pitchers.assign(board_type="pitchers")[["board_type", "final_rank", "player_name", "inferred_role", "tier", "final_score", "dropoff_to_next"]].rename(columns={"final_rank": "overall_rank"}),
        ],
        ignore_index=True,
    )

    scarcity_sheet = build_scarcity_sheet(hitters, pitchers)
    category_contribution = build_category_contribution(overall_board)
    sleepers_fades = build_sleepers_fades(overall_board)
    draft_day_queue = build_draft_day_queue(overall_board, phase, config["weights"]["phase_adjustments"])

    export_sheets = {
        "overall_board": round_for_export(
            overall_board[
                [
                    "overall_rank",
                    "player_name",
                    "team",
                    "inferred_role",
                    "adp",
                    "adp_gap",
                    "tier",
                    "final_score",
                    "dropoff_to_next",
                    "note",
                    "player_type",
                ]
            ].assign(taken="")
        ),
        "hitters_board": round_for_export(
            hitters[
                [
                    "final_rank",
                    "player_name",
                    "team",
                    "inferred_role",
                    "position",
                    "PA",
                    "R",
                    "RBI",
                    "HR",
                    "SB",
                    "AVG",
                    "OBP",
                    "adp",
                    "adp_gap",
                    "tier",
                    "final_score",
                    "dropoff_to_next",
                    "note",
                ]
            ]
        ),
        "pitchers_board": round_for_export(
            pitchers[
                [
                    "final_rank",
                    "player_name",
                    "team",
                    "inferred_role",
                    "IP",
                    "QS",
                    "K",
                    "ERA",
                    "WHIP",
                    "Saves_plus_Holds",
                    "adp",
                    "adp_gap",
                    "tier",
                    "final_score",
                    "dropoff_to_next",
                    "note",
                ]
            ]
        ),
        "tier_sheet": round_for_export(tier_sheet),
        "scarcity_sheet": round_for_export(scarcity_sheet),
        "category_contribution": round_for_export(category_contribution),
        "sleepers_fades": round_for_export(sleepers_fades),
        "draft_day_queue": round_for_export(
            draft_day_queue[
                [
                    "queue_rank",
                    "overall_rank",
                    "player_name",
                    "team",
                    "inferred_role",
                    "adp",
                    "adp_gap",
                    "queue_score",
                    "final_score",
                    "dropoff_to_next",
                    "tier",
                    "note",
                ]
            ]
        ),
    }

    write_csv(round_for_export(hitters), processed_dir / "hitters_scored.csv")
    write_csv(round_for_export(hitters_position_review), processed_dir / "hitters_position_review.csv")
    write_csv(round_for_export(pitchers), processed_dir / "pitchers_scored.csv")
    write_csv(round_for_export(overall_board), processed_dir / "overall_board.csv")

    workbook_path = exports_dir / paths["output"]["workbook_name"]
    export_workbook(
        export_sheets,
        workbook_path,
        interactive_context={
            "overall_board": overall_board,
            "hitters": hitters,
            "pitchers": pitchers,
            "league": config["league_settings"]["league"],
        },
    )

    return {
        "hitters": hitters,
        "pitchers": pitchers,
        "overall_board": overall_board,
        "draft_day_queue": draft_day_queue,
        "hitters_position_review": hitters_position_review,
        "workbook_path": workbook_path,
        "processed_dir": processed_dir,
        "phase": phase,
    }
