# Draft Workflow

## Goal

Use the workbook as a live draft room tool:

- `overall_board` is the master list.
- `my_team` tracks your roster build and category shape.
- `targets_by_need` is the live recommendation sheet.
- `scarcity_sheet` and `tier_sheet` are the decision-support sheets when a pick is close.

## Before The Draft

1. Run the build:

```bash
.venv/bin/python -m src.cli build-draft-board
```

2. Open [data/exports/draft_board.xlsx](/Users/danberle/Desktop/baseball/data/exports/draft_board.xlsx).
3. Check `overall_board`, `my_team`, and `targets_by_need`.
4. If you updated positions in [data/2026_positions.csv](/Users/danberle/Desktop/baseball/data/2026_positions.csv), rebuild before the draft starts.

## During The Draft

### 1. Mark taken players

- Go to `overall_board`.
- In the `taken` column, type any marker for drafted players.
- This keeps `targets_by_need` focused on available players only.

### 2. Enter your own picks

- Go to `my_team`.
- Type your drafted player names in column `B` next to the correct slot.
- The sheet will fill the player stats and notes automatically.

### 3. Read your team summary

On `my_team`, use:

- Category summary:
  shows current totals, target totals, gap to target, and need weights.
- Position summary:
  shows how many `C`, `1B`, `2B`, `3B`, `SS`, `OF`, `SP`, `RP`, and `P` slots are filled versus target.

Interpretation:

- Positive gap on counting stats means you still need more.
- Positive gap on `ERA` or `WHIP` means you are worse than the target and should improve ratios.
- `effective_need` is what the target sheet uses.
- You can manually override `manual_need` if you want to force speed, ratios, saves+holds, or another category.

### 4. Use targets by need

- Go to `targets_by_need`.
- This sheet removes taken players and players already on your roster.
- It then re-ranks the remaining pool using:
  - base `final_score`
  - your current team needs
  - each player’s category profile

Use this as your main “who should I take next?” sheet.

### 5. Use scarcity and tiers as tie-breakers

- `tier_sheet`:
  use this to see whether you are at the edge of a tier break.
- `dropoff_to_next`:
  if this is large, the current player is a stronger “take now” candidate.
- `scarcity_sheet`:
  use this when deciding whether to wait on a position or push it now.

## Recommended Draft Routine

For each pick:

1. Mark the newly drafted players in `overall_board`.
2. Enter your own latest pick in `my_team`.
3. Check `my_team` for category and position gaps.
4. Look at the top of `targets_by_need`.
5. Compare the best 2-4 options on:
   - category fit
   - position fit
   - tier
   - `dropoff_to_next`
6. If the choice is close, use `scarcity_sheet` to decide whether the position can wait.

## When To Rebuild

You do not need to rebuild during the draft for normal use.

Rebuild only if you changed:

- projection CSVs
- config weights
- league settings
- hitter positions

If you rebuild, your workbook now preserves:

- `taken` marks in `overall_board`
- `my_team` player entries
- manual need overrides in `my_team`

## What The Main Tabs Mean

- `overall_board`: best baseline player list.
- `hitters_board`: hitter-only list with stats and dropoffs.
- `pitchers_board`: pitcher-only list with stats and dropoffs.
- `tier_sheet`: compact cross-board tier view.
- `scarcity_sheet`: top position checkpoints and dropoffs.
- `category_contribution`: best category each player helps.
- `sleepers_fades`: model vs ADP opportunities.
- `draft_day_queue`: phase-adjusted queue.
- `my_team`: your live roster and goals.
- `targets_by_need`: best available players for your current build.

## Practical Tips

- Do not follow `targets_by_need` blindly. Use it with `overall_board`.
- If your roster is balanced, favor tier and dropoff over small need-score differences.
- If you fall behind badly in one category, use `manual_need` to force the model to care more.
- If a position summary shows you are short and scarcity is thinning, address it before the room does.
