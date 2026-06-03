from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo


TIMEZONE_NAME = "Europe/Helsinki"
HELSINKI_TZ = ZoneInfo(TIMEZONE_NAME)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
LOGS_DIR = PROJECT_ROOT / "logs"
CONFIG_DIR = PROJECT_ROOT / "config"
SESSIONS_DIR = PROJECT_ROOT / "sessions"

WINDOWS_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_runtime_dirs() -> None:
    for path in (OUTPUTS_DIR, LOGS_DIR, CONFIG_DIR, SESSIONS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def inclusive_date_range(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end date must be greater than or equal to start date")
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def helsinki_today(now: datetime | None = None) -> date:
    if now is None:
        now = datetime.now(HELSINKI_TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=HELSINKI_TZ)
    else:
        now = now.astimezone(HELSINKI_TZ)
    return now.date()


def is_complete_day(day: date, now: datetime | None = None) -> bool:
    return day < helsinki_today(now)


def day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time.min, tzinfo=HELSINKI_TZ)
    end_local = start_local + timedelta(days=1)
    utc = ZoneInfo("UTC")
    return start_local.astimezone(utc), end_local.astimezone(utc)


def source_identifier(raw_source: str) -> str:
    raw = raw_source.strip()
    if not raw:
        return ""

    if raw.startswith("@"):
        return raw[1:].strip()

    parsed = urlparse(raw)
    if parsed.netloc.lower() == "t.me":
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0].lower() == "s":
            parts = parts[1:]
        if parts:
            return unquote(parts[0]).strip()

    for prefix in ("https://t.me/s/", "http://t.me/s/", "https://t.me/", "http://t.me/"):
        if raw.lower().startswith(prefix):
            return raw[len(prefix) :].split("/", 1)[0].split("?", 1)[0].strip()

    return raw.split("/", 1)[0].split("?", 1)[0].strip()


def display_source(raw_source: str) -> str:
    ident = source_identifier(raw_source)
    if ident and not ident.startswith("@") and not ident.lstrip("-").isdigit():
        return f"@{ident}"
    return raw_source.strip()


def safe_filename_part(value: str, fallback: str = "source") -> str:
    cleaned = WINDOWS_FORBIDDEN_RE.sub("_", value.strip())
    cleaned = SAFE_CHARS_RE.sub("_", cleaned)
    cleaned = cleaned.strip("._-")
    return cleaned[:120] or fallback


def source_slug(raw_source: str) -> str:
    return safe_filename_part(source_identifier(raw_source), "source")


def export_folder_name(now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now(HELSINKI_TZ)
    else:
        now = now.astimezone(HELSINKI_TZ) if now.tzinfo else now.replace(tzinfo=HELSINKI_TZ)
    return f"export_{now:%Y-%m-%d_%H%M}"


def create_export_dir(outputs_root: Path | None = None) -> Path:
    outputs_root = outputs_root or OUTPUTS_DIR
    outputs_root.mkdir(parents=True, exist_ok=True)
    base = outputs_root / export_folder_name()
    candidate = base
    index = 2
    while candidate.exists():
        candidate = outputs_root / f"{base.name}_{index}"
        index += 1
    candidate.mkdir(parents=True)
    return candidate


def messages_filename(day: date, slug: str) -> str:
    return f"{day:%Y-%m-%d}__{slug}__messages.txt"


def pair_folder_name(day: date, slug: str) -> str:
    return f"{day:%Y-%m-%d}__{slug}"


def image_filename(day: date, slug: str, message_id: str, dt: datetime, index: int, ext: str) -> str:
    normalized_ext = ext.lower().lstrip(".") or "jpg"
    if normalized_ext == "jpeg":
        normalized_ext = "jpg"
    return (
        f"{day:%Y-%m-%d}__{slug}__msg_{safe_filename_part(str(message_id), 'unknown')}"
        f"__{dt.astimezone(HELSINKI_TZ):%H%M%S}__photo_{index:02d}.{normalized_ext}"
    )


def parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def extract_header_value(text: str, key: str) -> str:
    prefix = f"{key}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def read_messages_header(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    keys = (
        "SOURCE",
        "SOURCE_TITLE",
        "SOURCE_TYPE",
        "MODE",
        "DATE",
        "TIMEZONE",
        "COMPLETE_DAY",
        "MESSAGES_COUNT",
        "MEDIA_COUNT",
        "STATUS",
    )
    return {key: extract_header_value(text, key) for key in keys}


def path_for_display(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)

