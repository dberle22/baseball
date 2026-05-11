# In-Season Fantasy Baseball Manager — Strategy

## Product Goal

Build a local-first in-season fantasy baseball manager that answers the most important roster and waiver questions from a single source of truth.

The product should combine:

- historical MLB player performance
- rolling and recent-form trends
- rest-of-season projections
- schedule and probable-start context
- Yahoo league context: roster state, opponent state, and waiver eligibility

The output should be a daily app that helps decide:

- what matters in this week's matchup
- which players to add, hold, stream, bench, or deprioritize
- how to balance short-term category needs against longer-term roster value

---

## Product Questions

### Matchup questions

1. Which categories am I currently winning, losing, or still live in this week?
2. Which categories are most likely to swing before the week ends?
3. Do I have enough remaining hitter games, starter turns, or reliever opportunities to catch up?
4. Which of my SP starts are good enough to use, and which are dangerous to expose?

### Roster management questions

1. Which of my players are hot, cold, overperforming, or declining?
2. Which players on my roster are helping me now versus only carrying rest-of-season value?
3. Where is my roster structurally weak by position, role, and category contribution?
4. Which bench players are replacement-level in this specific league?

### Waiver questions

1. Who are the best waiver adds right now overall?
2. Who are the best short-term SP streamers for this week?
3. Which free-agent hitters have the best combination of role, schedule, form, and rest-of-season value?
4. Which relievers matter if Saves+Holds is a live category need?
5. Which players are rising because of role change, call-up, IL return, usage shift, or skills growth?

### Planning questions

1. What moves help this week without damaging the medium-term roster too much?
2. Which players should I pre-target before the waiver market catches up?
3. Which recommendations are category patches versus actual talent upgrades?
4. What has changed over the last 7, 14, and 30 days that should change my decisions?

---

## Product Principles

- Local-first: data and analysis live on the machine.
- League-specific: the app is optimized for this exact Yahoo format.
- Explainable: every recommendation should be traceable to stats, projections, schedule, and league need.
- Durable: core player analysis should live in a database, not only in one-day cache files.
- Practical: outputs should support decisions, not just surface stats.
- Incremental: start with a strong player spine and rolling stats, not every baseball event on day one.

---

## Success Criteria

This architecture is successful if:

- the app can analyze all relevant players, not only ad hoc daily subsets
- Yahoo is used to determine league context and availability, not as the main analysis source
- recommendations combine actual historical performance, recent trends, projections, and schedule
- the same database supports `My Team`, `My Week`, `Waivers`, and player exploration
- recommendation logic becomes easier to test, explain, and refine over time
