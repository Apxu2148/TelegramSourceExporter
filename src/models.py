from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal


Mode = Literal["public_web", "telegram_login"]
SourceType = Literal["channel", "private_channel", "group", "supergroup", "private_chat", "unknown"]
Status = Literal["OK", "NO_MESSAGES", "ERROR", "SKIPPED_EXISTING_COMPLETE"]
ExistingMode = Literal["skip_complete", "force"]


@dataclass(frozen=True)
class Source:
    raw: str
    title: str = ""
    source_type: SourceType = "unknown"

    @property
    def display(self) -> str:
        return self.raw.strip()


@dataclass
class Message:
    message_id: str
    dt: datetime
    source: str
    author: str | None = None
    reply_to_message_id: str | None = None
    text: str = ""
    media: str = "none"
    media_files: list[str] = field(default_factory=list)


@dataclass
class ExportResult:
    source: str
    source_title: str
    source_type: SourceType
    mode: Mode
    day: date
    folder_path: Path
    messages_count: int
    media_count: int
    status: Status
    complete_day: bool
    error: str = ""


@dataclass
class ExportOptions:
    mode: Mode
    sources: list[str]
    start_date: date
    end_date: date
    existing_mode: ExistingMode = "skip_complete"
    download_images: bool = True
    api_id: str = ""
    api_hash: str = ""


@dataclass(frozen=True)
class DialogSource:
    raw: str
    title: str
    source_type: SourceType

