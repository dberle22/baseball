from __future__ import annotations

import argparse
from pathlib import Path

from .live_pick import format_recommendation_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fantasy baseball draft assistant MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build-draft-board", help="Build rankings and workbook")
    build_parser.add_argument("--config", default="config", help="Config directory")
    build_parser.add_argument("--outdir", default=None, help="Workbook output directory")
    build_parser.add_argument("--phase", choices=["early", "middle", "late"], default="early")

    recommend_parser = subparsers.add_parser("recommend-pick", help="Recommend the next pick from live CSVs")
    recommend_parser.add_argument("--available", default="draft/available_players.csv", help="Available players TSV export")
    recommend_parser.add_argument("--team", default="draft/my_current_team.csv", help="Current team TSV export")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "build-draft-board":
        from .pipeline import build_draft_board

        result = build_draft_board(config_dir=args.config, outdir=args.outdir, phase=args.phase)
        overall_board = result["overall_board"]
        top_rows = overall_board.head(10)[["overall_rank", "player_name", "team", "inferred_role", "note"]]
        print(f"Built workbook: {result['workbook_path']}")
        print(f"Processed CSVs: {Path(result['processed_dir']).resolve()}")
        print(f"Phase: {result['phase']}")
        print(f"Players ranked: hitters={len(result['hitters'])}, pitchers={len(result['pitchers'])}, overall={len(overall_board)}")
        print("Top 10 overall:")
        print(top_rows.to_string(index=False))
    elif args.command == "recommend-pick":
        print(format_recommendation_report(available_path=args.available, team_path=args.team))


if __name__ == "__main__":
    main()
