from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import CONFIG_DIR, ensure_runtime_dirs


SETTINGS_PATH = CONFIG_DIR / "settings.json"
SAFE_SETTINGS_KEYS = {
    "last_sources",
    "last_dates",
    "last_mode",
    "last_output_dir",
    "last_manifest_path",
    "last_run_path",
    "download_images",
    "existing_mode",
}
DEFAULT_SETTINGS: dict[str, Any] = {
    "last_sources": "",
    "last_dates": {},
    "last_mode": "public_web",
    "last_output_dir": "",
    "last_manifest_path": "",
    "last_run_path": "",
    "download_images": True,
    "existing_mode": "skip_complete",
}


def sanitize_settings(data: dict[str, Any]) -> dict[str, Any]:
    safe = DEFAULT_SETTINGS.copy()
    for key, value in data.items():
        if key in SAFE_SETTINGS_KEYS:
            safe[key] = value
    return safe


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    ensure_runtime_dirs()
    if not path.exists():
        save_settings(DEFAULT_SETTINGS, path)
        return DEFAULT_SETTINGS.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    return sanitize_settings(data)


def save_settings(settings: dict[str, Any], path: Path = SETTINGS_PATH) -> None:
    ensure_runtime_dirs()
    safe = sanitize_settings(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
