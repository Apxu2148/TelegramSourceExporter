from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from .models import Message, Mode, Source, Status
from .utils import TIMEZONE_NAME, HELSINKI_TZ, messages_filename


SEPARATOR = "=" * 50
MESSAGE_SEPARATOR = "-" * 50


def clean_folder(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_binary_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def write_messages_file(
    folder: Path,
    source: Source,
    slug: str,
    mode: Mode,
    day: date,
    complete_day: bool,
    status: Status,
    messages: list[Message],
    media_count: int,
    error: str = "",
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / messages_filename(day, slug)
    lines: list[str] = [
        f"SOURCE: {source.display}",
        f"SOURCE_TITLE: {source.title or source.display}",
        f"SOURCE_TYPE: {source.source_type}",
        f"MODE: {mode}",
        f"DATE: {day:%Y-%m-%d}",
        f"TIMEZONE: {TIMEZONE_NAME}",
        f"COMPLETE_DAY: {str(complete_day).lower()}",
        f"MESSAGES_COUNT: {len(messages)}",
        f"MEDIA_COUNT: {media_count}",
        f"STATUS: {status}",
        "",
        SEPARATOR,
        "",
    ]

    if status == "ERROR":
        lines.extend(["ERROR_MESSAGE:", error or "Unknown error"])
    elif status == "NO_MESSAGES":
        lines.append("NO_MESSAGES")
    else:
        for index, message in enumerate(messages, start=1):
            lines.extend(_message_lines(index, message))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig", newline="\n")
    return path


def _message_lines(index: int, message: Message) -> list[str]:
    local_dt = message.dt.astimezone(HELSINKI_TZ) if message.dt.tzinfo else message.dt.replace(tzinfo=HELSINKI_TZ)
    text = message.text.strip() or ("[IMAGE WITHOUT TEXT]" if message.media == "image" else "")
    if not text:
        text = ""

    lines = [
        f"[{index}]",
        f"message_id: {message.message_id}",
        f"datetime: {local_dt:%Y-%m-%d %H:%M:%S}",
        f"source: {message.source}",
        f"author: {message.author or 'none'}",
        f"reply_to_message_id: {message.reply_to_message_id or 'none'}",
        f"media: {message.media}",
        "media_files:",
    ]

    if message.media_files:
        lines.extend(f"- {file_name}" for file_name in message.media_files)
    else:
        lines.append("none")

    lines.extend(["", "text:", text, "", MESSAGE_SEPARATOR, ""])
    return lines
