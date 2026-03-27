# Fantasy Baseball Draft Assistant

Local-first Python MVP for generating fantasy baseball draft rankings and an Excel workbook from six Fangraphs projection CSVs.
Hitter positions are enriched from [data/2026_positions.csv](/Users/danberle/Desktop/baseball/data/2026_positions.csv) during the build.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python -m src.cli build-draft-board
```

Optional flags:

```bash
.venv/bin/python -m src.cli build-draft-board --phase early --outdir data/exports
```

## Test

```bash
.venv/bin/python -m pytest
```
