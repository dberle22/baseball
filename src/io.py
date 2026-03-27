from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd


def ensure_output_dirs(processed_dir: Path, exports_dir: Path) -> None:
    processed_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)


def load_projection_sources(
    source_paths: Dict[str, str],
    usecols: Optional[Iterable[str]] = None,
) -> Dict[str, pd.DataFrame]:
    frames: Dict[str, pd.DataFrame] = {}
    for source_name, source_path in source_paths.items():
        path = Path(source_path)
        frames[source_name] = pd.read_csv(path, usecols=usecols)
    return frames


def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)
