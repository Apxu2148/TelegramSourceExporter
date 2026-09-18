from __future__ import annotations

import asyncio
import threading
from datetime import date
from pathlib import Path
from typing import Any

from .file_writer import write_binary_file
from .models import DialogSource, Message, Source, SourceType
from .utils import HELSINKI_TZ, SESSIONS_DIR, day_bounds_utc, display_source, image_filename, source_slug


SESSION_BASE = SESSIONS_DIR / "telegram"
SESSION_FILE = SESSIONS_DIR / "telegram.session"


class TwoFactorRequiredError(RuntimeError):
    pass


class TelegramLoginClient:
    def __init__(self, session_base: Path = SESSION_BASE) -> None:
        self.session_base = session_base
        self.session_base.parent.mkdir(parents=True, exist_ok=True)

    def session_exists(self) -> bool:
        return any(self.session_base.parent.glob(f"{self.session_base.name}.session*"))

    def delete_session(self) -> int:
        count = 0
        for path in self.session_base.parent.glob(f"{self.session_base.name}.session*"):
            path.unlink(missing_ok=True)
            count += 1
        return count

    def request_login_code(
        self,
        api_id: str,
        api_hash: str,
        phone: str,
        proxy: dict[str, object] | None = None,
    ) -> str:
        return _run(self._request_login_code(api_id, api_hash, phone, proxy))

    def complete_login(
        self,
        api_id: str,
        api_hash: str,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: str = "",
        proxy: dict[str, object] | None = None,
    ) -> bool:
        return _run(self._complete_login(api_id, api_hash, phone, code, phone_code_hash, password, proxy))

    def list_dialogs(
        self,
        api_id: str,
        api_hash: str,
        proxy: dict[str, object] | None = None,
    ) -> list[DialogSource]:
        return _run(self._list_dialogs(api_id, api_hash, proxy))

    def fetch_messages_for_day(
        self,
        raw_source: str,
        day: date,
        download_images: bool,
        output_folder: Path,
        slug: str | None = None,
        api_id: str = "",
        api_hash: str = "",
        proxy: dict[str, object] | None = None,
    ) -> tuple[Source, list[Message]]:
        return _run(
            self._fetch_messages_for_day(
                raw_source, day, download_images, output_folder, slug, api_id, api_hash, proxy
            )
        )

    async def _client(self, api_id: str, api_hash: str, proxy: dict[str, object] | None = None):
        from telethon import TelegramClient

        if not api_id or not api_hash:
            raise ValueError("api_id and api_hash are required for telegram_login mode")
        return TelegramClient(str(self.session_base), int(api_id), api_hash, proxy=proxy)

    async def _request_login_code(
        self,
        api_id: str,
        api_hash: str,
        phone: str,
        proxy: dict[str, object] | None = None,
    ) -> str:
        client = await self._client(api_id, api_hash, proxy)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
            return sent.phone_code_hash
        finally:
            await client.disconnect()

    async def _complete_login(
        self,
        api_id: str,
        api_hash: str,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: str,
        proxy: dict[str, object] | None = None,
    ) -> bool:
        from telethon.errors import SessionPasswordNeededError

        client = await self._client(api_id, api_hash, proxy)
        await client.connect()
        try:
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            except SessionPasswordNeededError as exc:
                if not password:
                    raise TwoFactorRequiredError("Telegram 2FA password is required") from exc
                await client.sign_in(password=password)
            return bool(await client.is_user_authorized())
        finally:
            await client.disconnect()

    async def _list_dialogs(
        self,
        api_id: str,
        api_hash: str,
        proxy: dict[str, object] | None = None,
    ) -> list[DialogSource]:
        client = await self._client(api_id, api_hash, proxy)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError("Telegram session is not authorized")
            dialogs: list[DialogSource] = []
            async for dialog in client.iter_dialogs():
                source_type = _dialog_source_type(dialog)
                raw = _dialog_identifier(dialog)
                dialogs.append(DialogSource(raw=raw, title=dialog.name or raw, source_type=source_type))
            dialogs.sort(key=lambda item: (item.source_type, item.title.lower()))
            return dialogs
        finally:
            await client.disconnect()

    async def _fetch_messages_for_day(
        self,
        raw_source: str,
        day: date,
        download_images: bool,
        output_folder: Path,
        slug: str | None,
        api_id: str,
        api_hash: str,
        proxy: dict[str, object] | None = None,
    ) -> tuple[Source, list[Message]]:
        client = await self._client(api_id, api_hash, proxy)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError("Telegram session is not authorized")
            entity = await client.get_entity(raw_source)
            title = _entity_title(entity) or display_source(raw_source)
            source_type = _entity_source_type(entity)
            source = Source(raw=display_source(raw_source), title=title, source_type=source_type)
            start_utc, end_utc = day_bounds_utc(day)
            messages: list[Message] = []
            effective_slug = slug or source_slug(raw_source)

            async for msg in client.iter_messages(entity, offset_date=end_utc):
                if msg.date is None:
                    continue
                if msg.date < start_utc:
                    break
                if not (start_utc <= msg.date < end_utc):
                    continue
                messages.append(await _message_from_telethon(client, msg, source, day, output_folder, effective_slug, download_images))

            messages.reverse()
            return source, messages
        finally:
            await client.disconnect()


def _run(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    if not loop.is_running():
        return loop.run_until_complete(coro)

    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _dialog_source_type(dialog: Any) -> SourceType:
    entity = getattr(dialog, "entity", None)
    if getattr(dialog, "is_user", False):
        return "private_chat"
    if getattr(dialog, "is_group", False):
        return "supergroup" if getattr(entity, "megagroup", False) else "group"
    if getattr(dialog, "is_channel", False):
        return "channel" if getattr(entity, "username", None) else "private_channel"
    return "unknown"


def _dialog_identifier(dialog: Any) -> str:
    entity = getattr(dialog, "entity", None)
    username = getattr(entity, "username", None)
    if username:
        return f"@{username}"
    return str(getattr(entity, "id", "") or getattr(dialog, "id", "") or dialog.name)


def _entity_source_type(entity: Any) -> SourceType:
    if getattr(entity, "bot", False) or getattr(entity, "first_name", None) is not None:
        return "private_chat"
    if getattr(entity, "broadcast", False):
        return "channel" if getattr(entity, "username", None) else "private_channel"
    if getattr(entity, "megagroup", False):
        return "supergroup"
    if entity.__class__.__name__.lower().endswith("chat"):
        return "group"
    return "unknown"


def _entity_title(entity: Any) -> str:
    title = getattr(entity, "title", None)
    if title:
        return title
    first = getattr(entity, "first_name", "") or ""
    last = getattr(entity, "last_name", "") or ""
    username = getattr(entity, "username", "") or ""
    return " ".join(part for part in (first, last, f"@{username}" if username else "") if part).strip()


async def _message_from_telethon(
    client: Any,
    msg: Any,
    source: Source,
    day: date,
    output_folder: Path,
    slug: str,
    download_images: bool,
) -> Message:
    local_dt = msg.date.astimezone(HELSINKI_TZ)
    media_files: list[str] = []
    media = "none"

    if getattr(msg, "photo", None):
        media = "not_downloaded"
        if download_images:
            file_name = image_filename(day, slug, str(msg.id), local_dt, 1, "jpg")
            target = output_folder / file_name
            downloaded = await client.download_media(msg, file=str(target))
            if downloaded:
                media = "image"
                media_files.append(Path(downloaded).name)
    elif getattr(msg, "media", None):
        media = "not_downloaded"

    sender = None
    try:
        sender = await msg.get_sender()
    except Exception:
        sender = None

    return Message(
        message_id=str(msg.id),
        dt=local_dt,
        source=source.display,
        author=_sender_display(sender),
        reply_to_message_id=str(msg.reply_to_msg_id) if getattr(msg, "reply_to_msg_id", None) else None,
        text=msg.message or "",
        media=media,
        media_files=media_files,
    )


def _sender_display(sender: Any) -> str | None:
    if sender is None:
        return None
    title = getattr(sender, "title", None)
    if title:
        return title
    first = getattr(sender, "first_name", "") or ""
    last = getattr(sender, "last_name", "") or ""
    username = getattr(sender, "username", "") or ""
    parts = [part for part in (first, last) if part]
    name = " ".join(parts)
    if username:
        return f"{name} (@{username})".strip()
    return name or None
