from __future__ import annotations

import logging
import shutil
from collections import Counter
from pathlib import Path
from typing import Callable

from .file_writer import clean_folder, write_messages_file
from .manifest import write_manifest
from .models import ExportOptions, ExportResult, Message, Source, Status
from .telegram_login_client import TelegramLoginClient
from .telegram_public_web import PublicWebFetcher
from .utils import (
    OUTPUTS_DIR,
    create_export_dir,
    inclusive_date_range,
    is_complete_day,
    pair_folder_name,
    parse_bool,
    read_messages_header,
    source_slug,
)


ProgressCallback = Callable[[int, int, str], None]
LogCallback = Callable[[str], None]


def run_export(
    options: ExportOptions,
    outputs_root: Path | None = None,
    public_fetcher: PublicWebFetcher | None = None,
    telegram_client: TelegramLoginClient | None = None,
    progress_callback: ProgressCallback | None = None,
    log_callback: LogCallback | None = None,
) -> tuple[Path, list[ExportResult]]:
    outputs_root = outputs_root or OUTPUTS_DIR
    days = inclusive_date_range(options.start_date, options.end_date)
    sources = [source.strip() for source in options.sources if source.strip()]
    if not sources:
        raise ValueError("At least one source is required")

    export_dir = create_export_dir(outputs_root)
    public_fetcher = public_fetcher or PublicWebFetcher()
    telegram_client = telegram_client or TelegramLoginClient()
    results: list[ExportResult] = []
    total = len(sources) * len(days)
    done = 0
    _log(log_callback, f"Export started: mode={options.mode}, sources={len(sources)}, days={len(days)}")

    for raw_source in sources:
        slug = source_slug(raw_source)
        for day in days:
            done += 1
            pair_name = pair_folder_name(day, slug)
            pair_folder = export_dir / pair_name
            complete_day = is_complete_day(day)
            label = f"{raw_source} / {day:%Y-%m-%d}"
            if progress_callback:
                progress_callback(done, total, label)
            _log(log_callback, f"Processing {label}")

            skipped = _maybe_copy_existing_complete(outputs_root, export_dir, pair_name, pair_folder, complete_day, options.existing_mode)
            if skipped is not None:
                results.append(skipped)
                _log(log_callback, f"Skipped existing complete: {label}")
                continue

            clean_folder(pair_folder)
            try:
                source, messages = _fetch_pair(options, raw_source, day, pair_folder, slug, public_fetcher, telegram_client)
                media_count = sum(len(message.media_files) for message in messages)
                status: Status = "OK" if messages else "NO_MESSAGES"
                write_messages_file(pair_folder, source, slug, options.mode, day, complete_day, status, messages, media_count)
                result = ExportResult(
                    source=source.display,
                    source_title=source.title or source.display,
                    source_type=source.source_type,
                    mode=options.mode,
                    day=day,
                    folder_path=pair_folder,
                    messages_count=len(messages),
                    media_count=media_count,
                    status=status,
                    complete_day=complete_day,
                )
                _log(log_callback, f"Status {status}: {label}")
            except Exception as exc:
                source = Source(raw=raw_source, title=raw_source, source_type="unknown")
                error = str(exc)
                write_messages_file(pair_folder, source, slug, options.mode, day, complete_day, "ERROR", [], 0, error)
                result = ExportResult(
                    source=source.display,
                    source_title=source.title,
                    source_type=source.source_type,
                    mode=options.mode,
                    day=day,
                    folder_path=pair_folder,
                    messages_count=0,
                    media_count=0,
                    status="ERROR",
                    complete_day=complete_day,
                    error=error,
                )
                logging.exception("Export failed for %s", label)
                _log(log_callback, f"ERROR {label}: {error}")
            results.append(result)

    write_manifest(export_dir, results)
    _log(log_callback, f"Export finished: {export_dir}")
    return export_dir, results


def summarize_results(results: list[ExportResult]) -> Counter:
    return Counter(result.status for result in results)


def _fetch_pair(
    options: ExportOptions,
    raw_source: str,
    day,
    pair_folder: Path,
    slug: str,
    public_fetcher: PublicWebFetcher,
    telegram_client: TelegramLoginClient,
) -> tuple[Source, list[Message]]:
    if options.mode == "public_web":
        return public_fetcher.fetch_messages_for_day(raw_source, day, options.download_images, pair_folder, slug)
    return telegram_client.fetch_messages_for_day(
        raw_source,
        day,
        options.download_images,
        pair_folder,
        slug,
        api_id=options.api_id,
        api_hash=options.api_hash,
    )


def _maybe_copy_existing_complete(
    outputs_root: Path,
    current_export_dir: Path,
    pair_name: str,
    pair_folder: Path,
    complete_day: bool,
    existing_mode: str,
) -> ExportResult | None:
    if existing_mode != "skip_complete" or not complete_day:
        return None

    existing = find_existing_complete_pair(outputs_root, current_export_dir, pair_name)
    if existing is None:
        return None

    if pair_folder.exists():
        shutil.rmtree(pair_folder)
    shutil.copytree(existing, pair_folder)
    header = _messages_header_from_pair(pair_folder)
    day_text = header.get("DATE", pair_name.split("__", 1)[0])
    from datetime import date

    return ExportResult(
        source=header.get("SOURCE", ""),
        source_title=header.get("SOURCE_TITLE", ""),
        source_type=header.get("SOURCE_TYPE", "unknown"),
        mode=header.get("MODE", "public_web"),
        day=date.fromisoformat(day_text),
        folder_path=pair_folder,
        messages_count=int(header.get("MESSAGES_COUNT") or 0),
        media_count=int(header.get("MEDIA_COUNT") or 0),
        status="SKIPPED_EXISTING_COMPLETE",
        complete_day=True,
    )


def find_existing_complete_pair(outputs_root: Path, current_export_dir: Path, pair_name: str) -> Path | None:
    if not outputs_root.exists():
        return None
    export_dirs = [path for path in outputs_root.glob("export_*") if path.is_dir() and path != current_export_dir]
    export_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for export_dir in export_dirs:
        pair_folder = export_dir / pair_name
        if not pair_folder.is_dir():
            continue
        header = _messages_header_from_pair(pair_folder)
        if not header:
            continue
        if (
            parse_bool(header.get("COMPLETE_DAY", "false"))
            and header.get("STATUS") in {"OK", "NO_MESSAGES"}
        ):
            return pair_folder
    return None


def _messages_header_from_pair(pair_folder: Path) -> dict[str, str]:
    messages_files = list(pair_folder.glob("*__messages.txt"))
    if not messages_files:
        return {}
    return read_messages_header(messages_files[0])


def _log(log_callback: LogCallback | None, message: str) -> None:
    logging.info(message)
    if log_callback:
        log_callback(message)

