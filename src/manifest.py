from __future__ import annotations

import csv
from pathlib import Path

from .models import ExportResult
from .utils import path_for_display


MANIFEST_FIELDS = [
    "source",
    "source_title",
    "source_type",
    "mode",
    "date",
    "folder_path",
    "messages_count",
    "media_count",
    "status",
    "complete_day",
    "error",
]


def result_to_row(result: ExportResult) -> dict[str, str | int]:
    return {
        "source": result.source,
        "source_title": result.source_title,
        "source_type": result.source_type,
        "mode": result.mode,
        "date": f"{result.day:%Y-%m-%d}",
        "folder_path": path_for_display(result.folder_path),
        "messages_count": result.messages_count,
        "media_count": result.media_count,
        "status": result.status,
        "complete_day": str(result.complete_day).lower(),
        "error": result.error,
    }


def write_manifest(export_dir: Path, results: list[ExportResult]) -> Path:
    path = export_dir / "manifest.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for result in results:
            writer.writerow(result_to_row(result))
    return path

