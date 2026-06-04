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

The script creates `.venv` inside `C:\Python\TelegramSourceExporter`, installs dependencies from `requirements.txt`, starts Streamlit, and opens `http://127.0.0.1:8501`.

If Streamlit is already running on `http://127.0.0.1:8501`, `run.bat` opens the existing local address instead of starting a second server. Streamlit usage stats are disabled through `.streamlit/config.toml` and `STREAMLIT_BROWSER_GATHER_USAGE_STATS=false`.

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

Downloaded history is a flat visual list:

```text
outputs/
  downloaded/
    markettwits-2026-06-01/
      markettwits-2026-06-01__messages.txt
      markettwits-2026-06-01__msg_12345__091500__photo_01.jpg
    markettwits-2026-06-02/
    stanizlavsky-2026-06-01/
    radarrussia-2026-06-02/
  manifests/
    manifest_YYYY-MM-DD_HHMM.csv
  runs/
    run_YYYY-MM-DD_HHMM.json
```

`outputs/downloaded` is intentionally not grouped by year, month, run, or source. A user can open it and immediately see which source/date pairs have already been downloaded.

`messages.txt` and `manifest_*.csv` are written as `utf-8-sig`.

The application does not create ZIP archives and does not create `media_index.txt`.

## Results UI

The results block has two views:

- `Последний запуск` reads only the last manifest from `outputs/manifests`.
- `Вся история` lists folders from `outputs/downloaded` with pagination by 100 folders.

History sorting is stable: by `source_slug`, then by date.

## COMPLETE_DAY

Timezone is always `Europe/Helsinki`.

`COMPLETE_DAY=true` when the exported date is earlier than today's date in `Europe/Helsinki`.

`COMPLETE_DAY=false` when the exported date is today's date.

## Repeat Exports

When `Пропускать COMPLETE_DAY=true` is selected, an existing pair folder is skipped only if the exact messages file exists, can be read, has `COMPLETE_DAY=true`, and has `STATUS: OK` or `STATUS: NO_MESSAGES`.

All other folders are treated as doubtful and are fully cleaned and downloaded again, including:

- `COMPLETE_DAY=false` with `OK`, `NO_MESSAGES`, or `ERROR`;
- `COMPLETE_DAY=true` with `ERROR`;
- missing TXT;
- unreadable or incomplete metadata;
- unknown status.

When `Принудительно перескачать всё` is selected, every requested pair folder is cleaned and created again.

Old `outputs/export_*` folders are ignored. They are not migrated and are not used for skip.

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
