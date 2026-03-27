# Fantasy Baseball Draft Assistant Brief

## 1. Executive Summary

Build a local-first Python tool that creates a practical fantasy baseball draft assistant for one specific Yahoo league.

Primary goal:
- Support an upcoming Yahoo fantasy baseball draft next Tuesday night.
- Focus on draft preparation first.
- Provide lightweight draft-day support through a spreadsheet export.

V1 scope:
- Ingest and blend projection systems.
- Add market context when available.
- Calculate league-specific rankings.
- Produce tiers, scarcity views, category views, and draft recommendations.
- Export a spreadsheet that serves as the main draft-day tool.

Success criteria:
- Rank players for this exact league format.
- Build tiers and identify positional scarcity.
- Show category contribution and matchup balance.
- Compare internal rankings to market value.
- Surface sleepers, fades, and draft targets.
- Create a spreadsheet that is easy to use with one minute per pick.

## 2. Non-Goals

Do not:
- Build a web app first.
- Prioritize live Yahoo integration.
- Spend time on in-season roster management in V1.
- Depend on live APIs for V1.
- Overcomplicate the ranking model before the data pipeline works.
- Spend time on perfect visual design.
- Assume optional datasets exist unless confirmed.

## 3. League Context

Use these settings as the source of truth.

League format:
- Platform: Yahoo
- Format: Head-to-head categories
- Teams: 12
- Draft type: Snake
- League type: Redraft

Hitting categories:
- R
- RBI
- HR
- AVG
- OBP
- SB

Pitching categories:
- QS
- ERA
- WHIP
- K
- Saves + Holds

Starting lineup:
- C
- 1B
- 2B
- 3B
- SS
- OF x3
- UTIL x2
- SP x2
- RP x2
- P x4

Bench and reserve:
- BN x5
- IL x3

Other rules:
- 6 transactions per week
- Position eligibility is defined by Yahoo
- Standard Yahoo assumptions otherwise

## 4. User Strategy and Recommendation Style

The recommendation layer should reflect the user's preferred draft style.

Core draft tendencies:
- Start with position players.
- Wait on pitching.
- Draft best player available with category awareness.
- Target one or two steals specialists.
- Prefer upside in middle and late rounds.
- Avoid injury risks unless clearly undervalued.
- Avoid aging veterans where possible.
- Avoid high-strikeout, low-average hitters where possible.
- Weight recommendations roughly 70% upside and 30% safety.

Recommendation style:
- Be concise.
- Explain tradeoffs briefly.
- End with a clear recommendation.
- Challenge the user’s instincts when needed.

## 5. Data Inputs

Available now:
- 3 hitter projection CSVs
- 3 pitcher projection CSVs

These six CSVs are the core projection inputs for V1.

Optional or likely-needed inputs:
- ADP dataset
- Yahoo eligibility mapping or manual eligibility file
- Manual overrides file
- Player notes file

Fallback requirement:
- The project must still function if optional datasets are missing.

## 6. Default Projection Blend

Use these default V1 weights unless implementation constraints make a different blend materially easier.

Hitters:
- ATC: 40%
- Steamer: 35%
- THE BAT X: 25%

Pitchers:
- ATC: 40%
- Steamer: 35%
- Depth Charts: 25%

These weights should be configurable in a settings file.

## 7. V1 Features and Outputs

Priority 1 outputs:
- Overall draft board
- Player rankings table
- Overall tiers
- Positional tiers
- Draft-day queue or shortlist

Priority 2 outputs:
- Positional scarcity sheet
- Category contribution view
- Sleepers list
- Fades list
- Comparison tool

Priority 3 outputs:
- Post-draft review

Core functional requirements:

Data ingestion:
- Read the 6 projection CSV files.
- Normalize player names and keys across sources.
- Separate hitter and pitcher pipelines.
- Preserve raw projected stats from each source.
- Create a clean player master table.
- Support ADP and eligibility ingestion once available.

Data standardization:
- Standardize column names across sources.
- Handle mismatched player names robustly.
- Identify hitter vs pitcher records.
- Preserve source-specific projection values.
- Build a canonical player ID or stable player key.
- Be modular enough to absorb slightly different CSV schemas.

Projection blending:
- Blend hitter projections using configurable weights.
- Blend pitcher projections using configurable weights.
- Preserve source-level columns for auditability.
- Output one clean hitter table and one clean pitcher table.
- Allow future custom user adjustments.

Ranking and valuation:
- Calculate raw projected stats.
- Calculate category z-scores.
- Calculate an overall category contribution score.
- Apply positional adjustment.
- Add ADP gap once ADP is available.
- Add upside score.
- Add risk score.
- Produce a final draft ranking score.

Category framework:
- Use z-scores to measure category strength.
- Preserve projected raw stats in outputs.
- Support matchup-style balance.
- Avoid implicitly punting SB.
- Avoid implicitly punting Saves + Holds.

Recommendation logic:
- Prioritize hitter value early.
- Avoid reaching on pitching too early.
- Begin targeting useful pitchers in the middle rounds.
- Surface category specialists when needed.
- Adjust slightly by draft phase.
- Produce short recommendation notes.

Spreadsheet export:
- The spreadsheet is the main draft-day artifact.
- It should optimize for practical usability over visual polish.

Workbook tabs:
- `overall_board`
- `hitters_board`
- `pitchers_board`
- `tier_sheet`
- `scarcity_sheet`
- `category_contribution`
- `sleepers_fades`
- `compare_players`
- `draft_day_queue`

Draft-day spreadsheet expectations:
- One row per player
- Clear ranks
- Visible tiers
- Key categories visible
- ADP and value gap visible
- Short notes visible
- Draft-day queue tab should be concise and easy to filter

## 8. Technical Design

### Data Model

Plan the project around a simple medallion-style flow.

Raw layer:
- Purpose: store source extracts with minimal changes
- Suggested assets:
  - `raw_hitters_source_1`
  - `raw_hitters_source_2`
  - `raw_hitters_source_3`
  - `raw_pitchers_source_1`
  - `raw_pitchers_source_2`
  - `raw_pitchers_source_3`
  - `raw_adp`
  - `raw_eligibility`

Clean layer:
- Purpose: standardized tables with harmonized columns
- Suggested outputs:
  - `hitters_clean_all_sources`
  - `pitchers_clean_all_sources`
  - `player_master`
  - `adp_clean`
  - `eligibility_clean`

Model layer:
- Purpose: blended projections and scoring outputs
- Suggested outputs:
  - `hitters_blended`
  - `pitchers_blended`
  - `hitters_scored`
  - `pitchers_scored`
  - `rankings_overall`
  - `rankings_by_position`
  - `tiers_overall`
  - `tiers_by_position`
  - `scarcity_summary`
  - `category_summary`
  - `sleepers_fades`
  - `draft_day_queue`

### Suggested Project Structure

```text
fantasy_baseball_draft_assistant/
  README.md
  requirements.txt
  config/
    league_settings.yaml
    weights.yaml
    file_paths.yaml
  data/
    raw/
    processed/
    exports/
  notebooks/
    01_data_intake.ipynb
    02_standardize_and_match.ipynb
    03_blend_projections.ipynb
    04_rankings_and_tiers.ipynb
    05_export_workbook.ipynb
  src/
    __init__.py
    config.py
    io.py
    standardize.py
    matching.py
    blend.py
    scoring.py
    tiers.py
    recommendations.py
    export.py
  tests/
```

### Config Files

`league_settings.yaml` should contain:
- Team count
- Roster slots
- Category list
- Draft type
- Bench count
- IL count
- Strategic toggles if needed later

`weights.yaml` should contain:
- Projection source blend weights
- Overall ranking component weights
- Upside vs safety weight
- Optional early, middle, late draft phase tweaks

`file_paths.yaml` should contain:
- Paths to the 6 source projection CSVs
- ADP file path
- Eligibility file path
- Export output path

### Canonical Column Design

Hitter core columns:
- `player_name`
- `player_key`
- `mlb_team`
- `positions`
- `PA`
- `R`
- `RBI`
- `HR`
- `SB`
- `AVG`
- `OBP`
- `age` if available
- Source-specific projection columns
- Blended projection columns
- Category z-score columns
- `upside_score`
- `risk_score`
- `adp`
- `adp_gap`
- `final_rank_score`
- `tier`
- `notes`

Pitcher core columns:
- `player_name`
- `player_key`
- `mlb_team`
- `positions`
- `IP` if available
- `QS`
- `K`
- `ERA`
- `WHIP`
- `Saves`
- `Holds`
- `Saves_plus_Holds`
- `age` if available
- Source-specific projection columns
- Blended projection columns
- Category z-score columns
- `upside_score`
- `risk_score`
- `adp`
- `adp_gap`
- `final_rank_score`
- `tier`
- `notes`

## 9. Modeling Guidance

Ranking logic should be practical for V1, not overly research-heavy.

Recommended ranking components:
- Category z-score aggregate
- Positional adjustment
- ADP value gap
- Upside score
- Risk penalty
- Matchup balance adjustment

Logic principles:
- Rankings should not rely only on raw totals.
- Rankings must be league-specific.
- The system must recognize this is head-to-head categories, not roto.
- The model should avoid encouraging category punts in SB and Saves + Holds.
- The recommendation layer should favor hitters early and allow stronger pitcher recommendations later.

Tier logic:
- Generate both overall tiers and positional tiers.
- Acceptable V1 approaches include score-gap tiers, clustering, or manual breakpoints from sorted values.
- The output should be interpretable and useful, not mathematically fancy for its own sake.

Scarcity logic:
- Highlight catcher drop-offs.
- Highlight middle infield drop-offs.
- Highlight RP depth and Saves + Holds coverage.
- Highlight overall player-pool cliffs by position.
- V1 does not need a perfect replacement-level model.

Sleepers and fades:
- Sleepers are players whose internal rank materially beats ADP without unacceptable downside.
- Fades are players whose market price is too high relative to internal value, or who look risky and overpriced.

Specialist tags to consider:
- Steals specialist
- Power specialist
- Ratio stabilizer
- Strikeout arm
- Saves plus holds specialist

Manual overrides:
- Optional in V1
- Should allow the user to raise or lower a player
- Should allow breakout and avoid tags
- Should allow notes
- Should allow injury or role caution flags

## 10. Delivery Plan

Implementation phases:

Phase 1:
- Confirm data schemas for all 6 projection CSVs
- Build file path config
- Read and validate all 6 files
- Standardize columns
- Create player matching logic

Phase 2:
- Blend projections
- Create canonical hitter and pitcher tables
- Add category z-scores
- Add a first-pass ranking score

Phase 3:
- Build tiers
- Build scarcity sheet
- Build category contribution sheet
- Add sleepers and fades logic

Phase 4:
- Export workbook
- Build draft-day queue tab
- Add short recommendation notes

Phase 5 if time remains:
- Add manual overrides
- Add compare players sheet
- Add post-draft review

Risks:

Data risks:
- The 6 projection CSVs may use inconsistent player names.
- Different sources may use different column names.
- Some stats may be missing or named differently by source.
- ADP may not yet be clean or available.
- Eligibility may need to be entered manually.

Product risks:
- Overbuilding the model before outputs exist.
- Spending too much time on risk nuance.
- Building a draft tracker instead of a prep tool.
- Making the workbook too complex to use in one minute per pick.

Mitigations:
- Make the pipeline robust to missing optional inputs.
- Prioritize clean rankings and exports first.
- Keep advanced enrichments optional.
- Keep the workbook simple.

## 11. Expected Deliverables From Codex

Codex should produce:
- A concrete implementation plan with phases, file structure, dependencies, and estimated effort
- A data intake review of the 6 CSV schemas plus a proposed canonical schema
- An architecture recommendation for Python modules, configs, and outputs
- A first-pass build order for reaching a working V1 quickly
- A short list of true blockers or ambiguities found after reviewing the data

## 12. Final Instruction

Use this brief to plan a realistic V1 that can be built quickly and used for an actual draft next Tuesday night.

Start by reviewing the 6 existing projection CSVs and propose:
- The canonical schema
- The file structure
- The data processing steps
- The ranking logic approach
- The export workbook design
- The fastest path to a usable V1

Prioritize practicality, speed, and draft usefulness over completeness.
