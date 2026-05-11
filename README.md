# Fantasy Baseball Analytics Manager

Local-first Python project for two related workflows:

- draft preparation with blended Fangraphs projections and an Excel workbook
- in-season management with Yahoo roster/matchup data and a local web dashboard

The draft workflow is still fully supported. The in-season architecture is now scaffolded under `src/yahoo/`, `src/inseason/`, `src/web/`, `scripts/`, `data/fangraphs/`, and `data/cache/`.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Add Yahoo credentials to the project root `.env` file for in-season work:

```bash
YAHOO_CLIENT_ID=your_client_id_here
YAHOO_CLIENT_SECRET=your_client_secret_here
YAHOO_LEAGUE_ID=your_league_id_here
YAHOO_CALLBACK_URI=https://localhost:8080/callback
```

Optional for sandboxed or alternate local runs:

```bash
YAHOO_TOKEN_PATH=data/cache/yahoo_token.json
YAHOO_OPEN_BROWSER=1
```

## Draft Workflow

```bash
.venv/bin/python -m src.cli build-draft-board
```

Optional flags:

```bash
.venv/bin/python -m src.cli build-draft-board --phase early --outdir data/exports
```

Projection CSVs now live under `data/fangraphs/`.

## Yahoo Smoke Test

```bash
.venv/bin/python scripts/test_yahoo.py
```

The first successful run should create or update `~/.yahoo_fantasy_token.json`, generate a local self-signed certificate if needed, open Yahoo login in your browser, and complete via the local HTTPS callback.

If you want a repo-local token file while testing:

```bash
YAHOO_TOKEN_PATH=data/cache/yahoo_token.json .venv/bin/python scripts/test_yahoo.py
```

Your browser may show a one-time certificate warning for `https://localhost:8080/callback`; that is expected because the local certificate is self-signed.

If you need to fall back to out-of-band auth:

```bash
YAHOO_CALLBACK_URI=oob
```

## In-Season Dashboard

Refresh the local cache manually:

```bash
.venv/bin/python scripts/refresh.py
```

Start the dashboard:

```bash
.venv/bin/python scripts/start.py
```

The start script refreshes automatically when the newest cached summary is older than 24 hours, then launches the app at `http://localhost:8080`.

Daily workflow:

1. Export fresh in-season Fangraphs hitter and pitcher CSVs into `data/fangraphs/`.
2. Run `scripts/start.py` to refresh stale cache data and open the dashboard.
3. Use the in-app `Refresh` button when you want to pull a fresh Yahoo snapshot without restarting the server.

## Test

```bash
.venv/bin/python -m pytest
```
