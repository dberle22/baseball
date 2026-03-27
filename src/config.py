from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_app_config(config_dir: Optional[str] = None) -> Dict[str, Any]:
    base_dir = Path(config_dir or "config")
    return {
        "league_settings": load_yaml(base_dir / "league_settings.yaml"),
        "weights": load_yaml(base_dir / "weights.yaml"),
        "file_paths": load_yaml(base_dir / "file_paths.yaml"),
    }
