from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import Settings

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def load_settings() -> Settings:
    settings = Settings()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return settings
    if not isinstance(raw, dict):
        return settings
    for name, value in raw.items():
        if name not in Settings.__dataclass_fields__:
            continue
        current = getattr(settings, name)
        try:
            if isinstance(current, bool):
                value = bool(value)
            elif isinstance(current, int):
                value = int(value)
            elif isinstance(current, float):
                value = float(value)
            elif isinstance(current, str):
                value = str(value)
            else:
                continue
        except (TypeError, ValueError):
            continue
        setattr(settings, name, value)
    return settings


def save_settings(settings: Settings) -> None:
    try:
        CONFIG_PATH.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
