# TelegramSourceExporter

TelegramSourceExporter is a local Streamlit application for exporting Telegram messages into TXT files for a selected date range.

Main export granularity:

```text
1 source x 1 day = 1 folder
```

## Run

Use `run.bat` from this folder:

```bat
run.bat
```

The script creates `.venv` inside `C:\Python\TelegramSourceExporter`, installs dependencies from `requirements.txt` into that local environment, starts Streamlit, and opens `http://127.0.0.1:8501`.

## Modes

`public_web` reads public Telegram web pages such as `https://t.me/s/channel_name`. It works only for public sources and can break if Telegram changes its HTML.

`telegram_login` uses Telethon and the user's local Telegram account session. It can access public channels, private channels the account already belongs to, groups, supergroups, and private chats.

Invite links are not supported in v1.

## Credentials Safety

Do not put real Telegram credentials into code, tests, or README.

The UI accepts these values locally:

```text
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=your_phone
```

`api_id`, `api_hash`, `phone`, Telegram login code, and 2FA password are not saved in `config/settings.json`.

Telegram session data is stored separately in:

```text
sessions/telegram.session
```

Use the UI button `Удалить Telegram-сессию` to remove local session files.

## API ID and API Hash

Create Telegram API credentials in your own browser at Telegram's developer portal. Enter them only in the local Streamlit UI.

## Outputs

Each run creates:

```text
outputs/
  export_YYYY-MM-DD_HHMM/
    manifest.csv
    YYYY-MM-DD__source_slug/
      YYYY-MM-DD__source_slug__messages.txt
      YYYY-MM-DD__source_slug__msg_12345__091500__photo_01.jpg
```

`messages.txt` and `manifest.csv` are written as `utf-8-sig`.

The application does not create ZIP archives and does not create `media_index.txt`.

## COMPLETE_DAY

Timezone is always `Europe/Helsinki`.

`COMPLETE_DAY=true` when the exported date is earlier than today's date in `Europe/Helsinki`.

`COMPLETE_DAY=false` when the exported date is today's date.

## Repeat Exports

When `Пропускать COMPLETE_DAY=true` is selected, an already exported pair is skipped only if a previous `messages.txt` exists, `COMPLETE_DAY=true`, and status is `OK` or `NO_MESSAGES`. The previous folder is copied into the new export folder and the manifest row gets `SKIPPED_EXISTING_COMPLETE`.

When `Принудительно перескачать всё` is selected, every pair folder is cleaned and created again.

## Media

v1 downloads only images when possible.

Videos, documents, stickers, voice messages, unsupported media, OCR, and image-content analysis are not included in v1. Unsupported media is marked as `media: not_downloaded`.

## v1 Limits

- Public web mode works only with public Telegram sources.
- Public web mode is best-effort and depends on Telegram HTML.
- Invite links are not supported.
- Only images are downloaded.
- LLM analysis, scoring, backtesting, OCR, EXE builds, ZIP archives, and schedulers are not included.
- Real Telegram credentials must never be added to code, tests, or README.

