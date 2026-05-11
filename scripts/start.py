from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.web.app import _latest_summary_path, get_config_dir

STALE_AFTER = timedelta(hours=24)


def cache_is_stale(config_dir: str | None = None) -> bool:
    config_dir = config_dir or get_config_dir()
    summary_path = _latest_summary_path(config_dir)
    if summary_path is None:
        return True
    modified_at = datetime.fromtimestamp(summary_path.stat().st_mtime)
    return datetime.now() - modified_at > STALE_AFTER


def run_refresh() -> None:
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "refresh.py")],
        check=True,
        cwd=str(PROJECT_ROOT),
    )


def main() -> None:
    if cache_is_stale():
        run_refresh()

    print("Dashboard running at http://localhost:8080")
    uvicorn.run("src.web.app:app", reload=True, port=8080)


if __name__ == "__main__":
    main()
