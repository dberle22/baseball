# In-Season Fantasy Baseball Manager — Architecture

## System Layers

The architecture separates into four layers.

1. **Source layer** — pull external data from Yahoo, Fangraphs/manual CSVs, MLB Stats API, and `pybaseball`
2. **Database layer** — store canonical player, stats, projections, schedule, and Yahoo snapshot tables
3. **Analysis layer** — build reusable derived tables and recommendation logic from the database
4. **App layer** — query analysis outputs and filter them into views for `my team`, `my matchup`, and `waiver wire`

### Before and after

Before:
- refresh job pulls live data → Python computes outputs in memory → writes to JSON cache → app renders cache

After:
- refresh job loads source data into database tables → derived analysis tables are materialized → dashboard summary generated → app reads database-backed views, optionally with a thin cached summary for speed

---

## Database

**Use DuckDB** as the local analytical database.

- excellent for local analytics and table scans
- easy to load from CSV, pandas, and parquet
- simple local file deployment
- good fit for rolling stats, joins, derived tables, and app-facing read models

SQLite would work but DuckDB is the better fit for the analytical joins and refresh-time transformations this system is trending toward.

---

## Data Model

### 1. Player spine — `players`

Canonical identity layer for all baseball analysis.

Columns: `player_key`, `player_name`, `player_name_ascii`, `mlbam_id`, `yahoo_player_id`, `fangraphs_player_id`, `team`, `bats`, `throws`, `primary_position`, `eligible_positions`, `is_active`, `rookie_status`

- `player_key` is the repo's canonical ID. `mlbam_id` is the best base key when available.
- Yahoo and Fangraphs IDs map onto that key.

### 2. Projections — `projection_source_values`, `player_projections_ros`

`projection_source_values`: `as_of_date`, `source_name`, `player_key`, stat columns

`player_projections_ros`: `as_of_date`, `player_key`, `projection_type`, blended stat columns, `blend_confidence`, `source_count`

### 3. Historical performance — `player_stats_daily` or `player_stats_rolling`

`player_stats_daily`: `game_date`, `player_key`, `team`, `opponent`, `player_type`, hitting/pitching stats, appearance flags, role flags

`player_stats_rolling`: `as_of_date`, `player_key`, `window_days`, rolling stat columns

Long term: keep daily logs. Short term: rolling tables are acceptable if they materially speed delivery.

### 4. Schedule and opportunity — `team_schedule`, `probable_starts`

`team_schedule`: `game_date`, `team`, `opponent`, `is_home`, `game_pk`, `game_status`

`probable_starts`: `game_date`, `player_key`, `team`, `opponent`, `is_home`, `game_pk`, `game_status`, `matchup_grade`, `matchup_score`

### 5. Yahoo league-state snapshots

`yahoo_roster_snapshots`: `snapshot_date`, `week`, `fantasy_team_key`, `player_key`, `selected_position`, `is_starting`, `status`

`yahoo_free_agent_snapshots`: `snapshot_date`, `week`, `player_key`, `percent_owned`, `position_type`, `eligible_positions`

`yahoo_matchup_snapshots`: `snapshot_date`, `week`, `my_team_key`, `opponent_team_key`, category totals for both sides

### 6. Derived analytical feature tables

Precomputed to avoid recomputing expensive logic in the app.

- `player_trend_features`
- `player_value_scores`
- `waiver_candidate_scores`
- `matchup_category_outlook`
- `roster_player_cards`

---

## Data Sources

| Source | What it provides | How we get it |
|---|---|---|
| Yahoo | roster, opponent, matchup totals, standings, free agents, ownership % | existing OAuth + `yahoo-fantasy-api` |
| Fangraphs | rest-of-season projections | manual CSV exports |
| MLB Stats API | schedule, probable starters, transactions, game status | direct HTTP requests |
| pybaseball | player stats, team offense context, recent ranges | existing pull logic |

Storage patterns:
- Yahoo: snapshot tables by refresh date and week
- Fangraphs: raw source projection tables + blended projection table keyed to `player_key`
- MLB Stats API: append/update weekly schedule, probable starts, transactions by date
- pybaseball: daily logs or rolling stat snapshots + team offense tables

---

## Analysis Layer

### 1. Player trend analysis

Features: rolling 7/14/30-day production, rolling rate stats, usage trends, role stability, trend delta vs. ROS baseline, recent playing-time trend

Outputs: `recent_form_score`, `trend_direction`, `playing_time_trend`, `skills_gain_flag`, `role_change_flag`

### 2. Rest-of-season value analysis

Features: blended ROS projection, category z-scores by league scoring, role-specific value, position adjustment, projection confidence

Outputs: `ros_value_score`, `category_contribution_profile`, `position_value_rank`

### 3. Short-term matchup analysis

Features: remaining hitter games, reliever opportunities, probable starter counts, matchup grades per start, category pace and projected finish

Outputs: `weekly_matchup_score`, `category_swing_probability`, `start_sit_risk_flag`

### 4. Waiver analysis

Dimensions: ROS value, recent form, playing-time security, schedule quality, categorical need fit, roster fit, ownership trend, transaction/news signal

Outputs: `waiver_score_overall`, `streamer_score`, `hitter_pickup_score`, `reliever_pickup_score`, `rising_player_score`

### 5. Roster audit analysis

Features: category strengths/weaknesses, position depth, replaceability, dead-roster risk, bench utilization, overlap and redundancy

Outputs: `roster_strength_summary`, `replaceable_player_flags`, `category_deficit_summary`

---

## App Structure

### Query pattern

The app queries broad analysis tables first, then applies Yahoo filters.

- `my team` = `roster_player_cards` joined to today's `yahoo_roster_snapshots`
- `waiver wire` = `waiver_candidate_scores` joined to today's `yahoo_free_agent_snapshots`
- `my week` = `matchup_category_outlook` + `probable_starts` filtered to today's roster snapshot

Analyze everyone, then filter to my players and waiver-eligible players — not the reverse.

### App sections

**Dashboard** — daily summary: matchup headline, urgent categories, SP decisions, top waiver adds, rising-player watchlist, roster risk alerts

**My Team** — player cards with recent stats, projections, trend, and role context; category contribution summary; replaceable player list; bench vs. starter value

**My Week** — category tracker, projected finish, remaining opportunity counts, SP start board, recommended category focus

**Waiver Wire** — best overall adds, SP streamers, hitters by position, relievers for SV+HLD, rising players, explanation per recommendation

**Player Explorer** — inspect any player regardless of roster status: recent trends, season stats, projections, role notes, Yahoo availability

---

## Refresh Pipeline Stages

1. **Source pulls** — Yahoo snapshot, schedule, transactions, player stats, projection CSV load
2. **Canonicalization** — map source IDs to `player_key`, standardize teams/positions/names, validate join coverage
3. **Load database tables** — upsert player dimension, write source fact tables, write snapshot tables
4. **Build derived tables** — rolling stats, trend features, ROS value scores, matchup outlook, waiver and roster views
5. **Build app summary objects** — optional dashboard summary table or JSON cache
6. **Run validations** — row-count checks, key-coverage checks, stale-source checks, null-rate checks on required fields
