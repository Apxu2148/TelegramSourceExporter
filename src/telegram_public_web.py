from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from .file_writer import write_binary_file
from .models import Message, Source
from .utils import HELSINKI_TZ, display_source, image_filename, source_identifier


PHOTO_URL_RE = re.compile(r"background-image:url\(['\"]?(.*?)['\"]?\)")


class PublicWebFetcher:
    def __init__(
        self,
        session: requests.Session | None = None,
        max_pages: int = 100,
        proxy: dict[str, str] | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.max_pages = max_pages
        if proxy:
            self.session.proxies.update(proxy)
            self.session.trust_env = False
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                )
            }
        )

    def fetch_messages_for_day(
        self,
        raw_source: str,
        day: date,
        download_images: bool,
        output_folder: Path,
        slug: str,
    ) -> tuple[Source, list[Message]]:
        identifier = source_identifier(raw_source)
        if not identifier:
            raise ValueError("Source is empty")
        if "/" in identifier or identifier.startswith("+"):
            raise ValueError("Invite links are not supported in public_web mode")

        base_url = f"https://t.me/s/{identifier}"
        title = ""
        source = Source(raw=display_source(raw_source), title=title, source_type="channel")
        messages_by_id: dict[str, Message] = {}
        before: int | None = None

        for _ in range(self.max_pages):
            url = base_url if before is None else f"{base_url}?before={before}"
            response = self.session.get(url, timeout=30)
            if response.status_code >= 400:
                raise RuntimeError(f"Telegram web returned HTTP {response.status_code}")

            soup = BeautifulSoup(response.text, "html.parser")
            if not title:
                title = _extract_title(soup) or display_source(raw_source)
                source = Source(raw=display_source(raw_source), title=title, source_type="channel")

            nodes = soup.select(".tgme_widget_message")
            if not nodes:
                break

            page_datetimes: list[datetime] = []
            page_ids: list[int] = []
            for node in nodes:
                dt = _message_datetime(node)
                if dt is not None:
                    page_datetimes.append(dt)
                message_id = _message_id(node)
                if message_id is not None:
                    page_ids.append(message_id)
                message = _parse_message(node, source, day, download_images, output_folder, slug, self.session)
                if message is not None:
                    messages_by_id[message.message_id] = message

            if not page_datetimes or not page_ids:
                break
            if min(page_datetimes).date() < day:
                break

            next_before = min(page_ids)
            if before == next_before:
                break
            before = next_before

        messages = list(messages_by_id.values())
        messages.sort(key=lambda item: item.dt)
        return source, messages


def _extract_title(soup: BeautifulSoup) -> str:
    title_node = soup.select_one(".tgme_channel_info_header_title") or soup.select_one(".tgme_channel_info_header_username")
    return title_node.get_text(" ", strip=True) if title_node else ""


def _parse_message(
    node,
    source: Source,
    day: date,
    download_images: bool,
    output_folder: Path,
    slug: str,
    session: requests.Session,
) -> Message | None:
    dt = _message_datetime(node)
    if dt is None:
        return None
    if dt.date() != day:
        return None

    message_id = _message_id(node)
    message_id_text = str(message_id) if message_id is not None else dt.strftime("%H%M%S")
    text_node = node.select_one(".tgme_widget_message_text")
    text = text_node.get_text("\n", strip=True) if text_node else ""
    author_node = node.select_one(".tgme_widget_message_from_author") or node.select_one(".tgme_widget_message_author")
    author = author_node.get_text(" ", strip=True) if author_node else None
    photo_urls = _extract_photo_urls(node)
    media_files: list[str] = []

    if download_images:
        for index, photo_url in enumerate(photo_urls, start=1):
            try:
                content, ext = _download_image(session, photo_url)
            except Exception:
                continue
            file_name = image_filename(day, slug, message_id_text, dt, index, ext)
            write_binary_file(output_folder / file_name, content)
            media_files.append(file_name)

    if media_files:
        media = "image"
    elif photo_urls:
        media = "not_downloaded"
    else:
        media = "none"

    return Message(
        message_id=message_id_text,
        dt=dt,
        source=source.display,
        author=author,
        text=text,
        media=media,
        media_files=media_files,
    )


def _message_datetime(node) -> datetime | None:
    time_node = node.select_one("time[datetime]")
    if not time_node:
        return None
    return datetime.fromisoformat(time_node["datetime"].replace("Z", "+00:00")).astimezone(HELSINKI_TZ)


def _message_id(node) -> int | None:
    data_post = node.get("data-post", "")
    value = data_post.rsplit("/", 1)[-1] if "/" in data_post else data_post
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_photo_urls(node) -> list[str]:
    urls: list[str] = []
    for photo in node.select(".tgme_widget_message_photo_wrap, a.tgme_widget_message_photo_wrap"):
        style = photo.get("style", "")
        match = PHOTO_URL_RE.search(style)
        if match:
            urls.append(match.group(1))
    return urls


def _download_image(session: requests.Session, url: str) -> tuple[bytes, str]:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    ext = _extension_from_content_type(content_type) or _extension_from_url(url) or "jpg"
    return response.content, ext


def _extension_from_content_type(content_type: str) -> str:
    if "png" in content_type:
        return "png"
    if "webp" in content_type:
        return "webp"
    if "gif" in content_type:
        return "gif"
    if "jpeg" in content_type or "jpg" in content_type:
        return "jpg"
    return ""


def _extension_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return suffix if suffix in {"jpg", "jpeg", "png", "webp", "gif"} else ""
