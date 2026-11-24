from __future__ import annotations

import contextlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from .models import Settings

_LEGACY_CONFIG = Path(__file__).resolve().parent / "config.json"


def _user_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "immich-dvd" / "config.json"


def _config_path() -> Path:
    # Keep using the old package-local file when it already exists, otherwise
    # store settings in the per-user config folder (works for pip installs).
    override = os.environ.get("IMMICH_DVD_CONFIG")
    if override:
        return Path(override).expanduser()
    return _LEGACY_CONFIG if _LEGACY_CONFIG.exists() else _user_config_path()


CONFIG_PATH = _config_path()


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
    with contextlib.suppress(OSError):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
