# In-Season Fantasy Baseball Manager — Backlog

## Current State

### Done

- [x] Yahoo OAuth and Yahoo Fantasy API integration
- [x] Live pulls for roster, matchup, opponent roster, free agents, standings, and league settings
- [x] Weekly MLB schedule + probable starter matching
- [x] Recent-form pulls via `pybaseball`
- [x] In-season projection loading and blending from Fangraphs CSVs
- [x] Waiver recommendation groups for SP streamers, hitters, relievers, and rising players
- [x] Matchup tracker with projected category outcomes
- [x] Local FastAPI dashboard backed by daily cache files

### Code locations

- Yahoo integration: `src/yahoo/`
- In-season analytics: `src/inseason/`
- Daily refresh job: `scripts/refresh.py`
- Web app: `src/web/`
- Shared scoring/blend/standardize: `src/scoring.py`, `src/blend.py`, `src/standardize.py`

### Current limitation

The analytical center is transient. We pull data, compute rankings, and write cache files, but we do not maintain a durable player-level fact base. That is the main gap these next phases close.

---

## Phase 6 — Database Foundation

**Goal:** Create the local analytical spine for in-season analysis.

- [ ] Add DuckDB dependency and local database file path to config
- [ ] Create database bootstrap module
- [ ] Create initial schema: `players`, `player_projections_ros`, `team_schedule`, `probable_starts`, `yahoo_roster_snapshots`, `yahoo_free_agent_snapshots`, `yahoo_matchup_snapshots`
- [ ] Add ID-mapping strategy and validation checks
- [ ] Document assumptions and known ID gaps

Verify:
- database initializes cleanly
- refresh can write snapshot tables
- player keys remain stable across refreshes

---

## Phase 7 — Historical Stats Spine

**Goal:** Store actual player performance history in a reusable format.

- [ ] Decide whether first version is `player_stats_daily` or `player_stats_rolling`
- [ ] Build pull/load job for historical hitter and pitcher data
- [ ] Add rolling 7/14/30-day stat generation
- [ ] Add team offense context table for matchup grading
- [ ] Add tests for player history coverage and rolling-window correctness

Verify:
- every app-facing player has usable actual-stat context
- rolling features can be reproduced deterministically

---

## Phase 8 — Derived Analysis Tables

**Goal:** Move recommendation logic onto durable database-backed tables.

- [ ] Build `player_trend_features`
- [ ] Build `player_value_scores`
- [ ] Build `matchup_category_outlook`
- [ ] Build `waiver_candidate_scores`
- [ ] Build `roster_player_cards`
- [ ] Refactor current Python ranking code to read from these tables where practical

Verify:
- current waiver and matchup outputs can be reproduced from DB-backed views
- recommendation logic is explainable row by row

---

## Phase 9 — App Refactor

**Goal:** Make the app query the analytical database instead of only reading a prebuilt cache.

- [ ] Add a data-access layer for app queries
- [ ] Build `My Team` view
- [ ] Build `Player Explorer` view
- [ ] Refactor `Waivers` and `My Week` to use database-backed views
- [ ] Keep optional summary cache for fast landing-page loads

Verify:
- app can render from the database even when a prebuilt summary is absent
- views stay responsive on local machine

---

## Phase 10 — Decision Quality and Explainability

**Goal:** Make outputs stronger, clearer, and easier to trust.

- [ ] Add explanation text per recommendation
- [ ] Add recommendation type labels: short-term streamer, category patch, medium-term hold, talent upgrade
- [ ] Add confidence flags and small-sample warnings
- [ ] Add change tracking since previous refresh

Verify:
- every surfaced recommendation has a reason, not just a score

---

## Open Design Questions

- [ ] Should first-pass historical storage be full daily logs or rolling snapshots only?
- [ ] What is the canonical ID strategy when `mlbam_id` is missing or Yahoo-only players appear?
- [ ] Should projection history be versioned daily or only stored for the current refresh?
- [ ] How much of the current JSON summary pattern should survive once database-backed views exist?
- [ ] Should the app show rest-of-season rank and short-term rank separately everywhere?
- [ ] Do we want explicit add/drop candidate pairing logic in the first database-backed version?

---

## Risks and Tradeoffs

**Main risk:** ID mapping across Yahoo, MLBAM, and projection sources is the hardest technical problem. If identity resolution is weak, the whole analysis layer becomes unreliable.

**Simplicity tradeoff:** The fastest path is database → player spine → rolling stats → projections → Yahoo snapshots → derived recommendation tables. The slowest path is trying to build a perfect baseball warehouse before improving the app.

**Recommended bias:** Be ambitious in structure, conservative in scope. Build the schema cleanly, choose a manageable first set of tables, move the app onto them incrementally, and preserve the current working dashboard until the new path is clearly better.
