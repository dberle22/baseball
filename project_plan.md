Summary
Build a Python CLI that reads the six existing Fangraphs projection CSVs from data/, blends hitter and pitcher projections, computes league-specific value scores for this Yahoo H2H categories league, infers rough positions for MVP, and exports a draft-night Excel workbook.

This MVP is optimized for speed to usefulness, not modeling completeness. It will rely on the embedded Fangraphs PlayerId for cross-source joins and the embedded ADP column for market context. The first usable version should produce an overall board, hitter board, pitcher board, tiers, a simple scarcity view, sleepers/fades, and a filtered draft queue.

Implementation Changes
Product shape
Primary interface: CLI command that generates all processed outputs and the workbook in one run.
Core command: python -m src.cli build-draft-board
Inputs: the 6 CSV files already in data/
Outputs:
processed blended/scored hitter and pitcher tables as CSV
one Excel workbook for draft day
one lightweight validation/report summary printed to terminal
Data pipeline
Create a minimal project structure with src/, config/, data/processed/, data/exports/, and tests/.
Add config files for league settings, blend weights, and file paths.
Ingest all six CSVs with a small source registry:
hitters: atc, steamer, batx
pitchers: atc, steamer, depth_charts
Normalize columns to a canonical schema and cast all scoring fields to numeric.
Use PlayerId as the canonical join key.
Keep source-specific stat columns for auditability, but only carry forward the stats needed for MVP scoring/export.
Use embedded Fangraphs ADP as the MVP market-price field.
Infer positions for MVP:
hitters: infer coarse buckets from statistical profile and playing-time context only where needed for output labels
pitchers: classify as SP, RP, or P primarily from GS, G, SV, HLD, and IP
treat inferred positions as approximate and avoid hard roster-slot optimization in MVP
If a player exists in only one source, keep them with a lower-confidence flag rather than dropping them.
Ranking model
Blend projections with the specified default weights from the brief, stored in config.
Score hitters on the league’s hitting categories: R, RBI, HR, AVG, OBP, SB
Score pitchers on the league’s pitching categories: QS, ERA, WHIP, K, Saves_plus_Holds
Derive Saves_plus_Holds = SV + HLD
Use z-scores within hitter and pitcher pools for the first-pass category scoring model.
Invert ERA and WHIP so lower is better.
Preserve raw stats in outputs alongside z-scores.
Build a practical final score:
hitters: weighted category aggregate + modest ADP value bonus + small upside proxy
pitchers: weighted category aggregate + modest ADP value bonus + small role/stability adjustment
Add draft-phase recommendation rules outside the core ranking formula:
early phase: boost hitters, suppress pitchers slightly
middle phase: relax pitcher suppression
later phase: prioritize category specialists and closers/setup arms with strong SV + HLD
Do not attempt full risk modeling, replacement-level optimization, matchup simulation, or roster construction in MVP.
Workbook and outputs
Export one Excel workbook with these tabs:
overall_board
hitters_board
pitchers_board
tier_sheet
scarcity_sheet
category_contribution
sleepers_fades
draft_day_queue
overall_board: top merged board with final rank, player, team, inferred role, ADP, ADP gap, tier, key category columns, and short note
hitters_board and pitchers_board: same but role-specific columns
tier_sheet: overall tiers plus separate hitter/pitcher tiers
scarcity_sheet: cliffs by inferred role bucket, especially catcher-like scarcity deferred unless eligibility arrives
category_contribution: sortable view of strongest category contributors and specialists
sleepers_fades: biggest positive and negative gaps versus ADP with simple filters
draft_day_queue: concise draft-night shortlist sorted by phase-adjusted recommendation score
Notes field should be rules-based and short, e.g. power boost, speed specialist, ratio stabilizer, SP value, RP saves+holds
Public interfaces and config
CLI:
python -m src.cli build-draft-board
optional flags: --config, --outdir, --phase early|middle|late
Config files:
config/league_settings.yaml
config/weights.yaml
config/file_paths.yaml
Core output schemas:
hitters_scored.csv
pitchers_scored.csv
overall_board.csv
draft_board.xlsx
Internal modules:
io.py for loading and writing
standardize.py for canonical schemas and typing
blend.py for weighted source merges
scoring.py for category z-scores and final scores
tiers.py for simple score-gap tiers
recommendations.py for tags and phase-specific queue logic
export.py for workbook generation
cli.py for orchestration
Test Plan
Ingestion tests:
all six CSVs load successfully
expected core columns exist
numeric scoring columns parse cleanly
PlayerId joins across sources without duplicate-key corruption
Standardization tests:
hitter and pitcher schemas normalize consistently across all sources
missing optional columns fall back cleanly
Saves_plus_Holds is derived correctly
Blending tests:
weighted blends produce expected values for a small fixed sample
single-source fallback players remain in output
Scoring tests:
z-score direction is correct for ERA and WHIP
higher SV + HLD improves reliever value
ADP gap is computed correctly
phase adjustments change queue ordering in expected ways
Export tests:
workbook is created
required tabs exist
row counts match processed tables
Acceptance scenarios:
one command generates a complete workbook from the current data/ folder
the workbook surfaces usable top-player rankings for draft night without any optional datasets
the user can sort/filter the queue and compare internal value to ADP immediately
Assumptions and Defaults
Use the embedded Fangraphs ADP column as MVP ADP; no separate ADP ingest in MVP.
Primary interface is CLI plus workbook, not notebook-first.
Position handling in MVP is inferred/approximate because Yahoo eligibility is not present in current files.
Position-specific roster optimization is out of scope for MVP; position-aware outputs remain lightweight until an eligibility file is added.
Tiers use simple score-gap logic, not clustering.
Recommendation notes are rules-based strings, not generated text.
Manual overrides, compare-player UI, and post-draft review are deferred until after the first working workbook exists.