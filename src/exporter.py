from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from .file_writer import clean_folder, write_messages_file
from .manifest import manifest_filename, result_to_row, write_manifest
from .models import ExportArtifacts, ExportOptions, ExportResult, Message, Source, Status
from .telegram_login_client import TelegramLoginClient
from .telegram_public_web import PublicWebFetcher
from .utils import (
    HELSINKI_TZ,
    OUTPUTS_DIR,
    inclusive_date_range,
    is_complete_day,
    messages_filename,
    output_layout,
    pair_folder_name,
    path_for_display,
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
) -> tuple[ExportArtifacts, list[ExportResult]]:
    outputs_root = outputs_root or OUTPUTS_DIR
    downloaded_dir, manifests_dir, runs_dir = output_layout(outputs_root)
    run_id = _create_run_id(manifests_dir, runs_dir)
    days = inclusive_date_range(options.start_date, options.end_date)
    sources = [source.strip() for source in options.sources if source.strip()]
    if not sources:
        raise ValueError("At least one source is required")

    public_fetcher = public_fetcher or PublicWebFetcher()
    telegram_client = telegram_client or TelegramLoginClient()
    results: list[ExportResult] = []
    total = len(sources) * len(days)
    done = 0
    _log(log_callback, f"Export started: run_id={run_id}, mode={options.mode}, sources={len(sources)}, days={len(days)}")

    for raw_source in sources:
        slug = source_slug(raw_source)
        for day in days:
            done += 1
            pair_name = pair_folder_name(day, slug)
            pair_folder = downloaded_dir / pair_name
            complete_day = is_complete_day(day)
            label = f"{raw_source} / {day:%Y-%m-%d}"
            if progress_callback:
                progress_callback(done, total, label)
            _log(log_callback, f"Processing {label}")

            skipped = _maybe_reuse_existing_complete(pair_folder, slug, day, options.existing_mode)
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

    manifest_path = write_manifest(manifests_dir, run_id, results)
    run_path = _write_run_record(runs_dir, run_id, options, sources, days, downloaded_dir, manifest_path, results)
    artifacts = ExportArtifacts(
        run_id=run_id,
        manifest_path=manifest_path,
        run_path=run_path,
        downloaded_dir=downloaded_dir,
    )
    _log(log_callback, f"Export finished: manifest={manifest_path}")
    return artifacts, results


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


def _maybe_reuse_existing_complete(
    pair_folder: Path,
    slug: str,
    day: date,
    existing_mode: str,
) -> ExportResult | None:
    if existing_mode != "skip_complete":
        return None

    header = _messages_header_from_pair(pair_folder, slug, day)
    if not header:
        return None

    parsed = _parse_existing_complete_header(header, pair_folder, day)
    if parsed is None:
        return None
    return parsed


def _parse_existing_complete_header(header: dict[str, str], pair_folder: Path, expected_day: date) -> ExportResult | None:
    if not parse_bool(header.get("COMPLETE_DAY", "")):
        return None
    if header.get("STATUS") not in {"OK", "NO_MESSAGES"}:
        return None
    if header.get("DATE") != f"{expected_day:%Y-%m-%d}":
        return None
    if not header.get("SOURCE") or not header.get("SOURCE_TITLE"):
        return None
    if header.get("MODE") not in {"public_web", "telegram_login"}:
        return None

    source_type = header.get("SOURCE_TYPE", "unknown")
    if source_type not in {"channel", "private_channel", "group", "supergroup", "private_chat", "unknown"}:
        return None
    try:
        messages_count = int(header["MESSAGES_COUNT"])
        media_count = int(header["MEDIA_COUNT"])
    except (KeyError, TypeError, ValueError):
        return None

    return ExportResult(
        source=header["SOURCE"],
        source_title=header["SOURCE_TITLE"],
        source_type=source_type,  # type: ignore[arg-type]
        mode=header["MODE"],  # type: ignore[arg-type]
        day=expected_day,
        folder_path=pair_folder,
        messages_count=messages_count,
        media_count=media_count,
        status="SKIPPED_EXISTING_COMPLETE",
        complete_day=True,
    )


def _messages_header_from_pair(pair_folder: Path, slug: str, day: date) -> dict[str, str]:
    messages_file = pair_folder / messages_filename(day, slug)
    if not messages_file.exists():
        return {}
    try:
        return read_messages_header(messages_file)
    except OSError:
        return {}


def _create_run_id(manifests_dir: Path, runs_dir: Path, now: datetime | None = None) -> str:
    now = now or datetime.now(HELSINKI_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=HELSINKI_TZ)
    else:
        now = now.astimezone(HELSINKI_TZ)
    base = f"{now:%Y-%m-%d_%H%M}"
    candidate = base
    index = 2
    while (manifests_dir / manifest_filename(candidate)).exists() or (runs_dir / f"run_{candidate}.json").exists():
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _write_run_record(
    runs_dir: Path,
    run_id: str,
    options: ExportOptions,
    sources: list[str],
    days: list[date],
    downloaded_dir: Path,
    manifest_path: Path,
    results: list[ExportResult],
) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"run_{run_id}.json"
    data = {
        "run_id": run_id,
        "created_at": datetime.now(HELSINKI_TZ).isoformat(),
        "mode": options.mode,
        "sources": sources,
        "start_date": f"{days[0]:%Y-%m-%d}" if days else "",
        "end_date": f"{days[-1]:%Y-%m-%d}" if days else "",
        "existing_mode": options.existing_mode,
        "download_images": options.download_images,
        "downloaded_dir": path_for_display(downloaded_dir),
        "manifest_path": path_for_display(manifest_path),
        "results": [result_to_row(result) for result in results],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _log(log_callback: LogCallback | None, message: str) -> None:
    logging.info(message)
    if log_callback:
        log_callback(message)
