from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.exporter import run_export, summarize_results
from src.manifest import result_to_row
from src.models import ExportOptions
from src.settings import load_settings, save_settings
from src.telegram_login_client import TelegramLoginClient, TwoFactorRequiredError
from src.utils import DOWNLOADED_DIR, LOGS_DIR, OUTPUTS_DIR, ensure_runtime_dirs, inclusive_date_range


APP_TITLE = "TelegramSourceExporter"


def main() -> None:
    ensure_runtime_dirs()
    _configure_logging()
    settings = load_settings()

    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)

    if "run_log" not in st.session_state:
        st.session_state.run_log = []
    if "dialogs" not in st.session_state:
        st.session_state.dialogs = []
    if "phone_code_hash" not in st.session_state:
        st.session_state.phone_code_hash = ""

    mode = st.radio(
        "Режим доступа",
        ["public_web", "telegram_login"],
        index=0 if settings.get("last_mode") == "public_web" else 1,
        horizontal=True,
    )

    api_id = api_hash = ""
    if mode == "telegram_login":
        api_id, api_hash = _telegram_auth_block()
    proxy = _proxy_block(mode)

    manual_sources = st.text_area(
        "Ручной ввод источников (один источник на строку)",
        value=settings.get("last_sources", ""),
        height=130,
    )

    selected_dialog_sources: list[str] = []
    if mode == "telegram_login":
        selected_dialog_sources = _dialog_selector(api_id, api_hash)

    col_start, col_end = st.columns(2)
    today = date.today()
    with col_start:
        start_date = st.date_input("Дата начала", value=today)
    with col_end:
        end_date = st.date_input("Дата окончания", value=today)

    existing_label = st.selectbox(
        "Режим существующих выгрузок",
        ["Пропускать COMPLETE_DAY=true", "Принудительно перескачать всё"],
        index=0 if settings.get("existing_mode") != "force" else 1,
    )
    existing_mode = "force" if existing_label.startswith("Принудительно") else "skip_complete"
    download_images = st.checkbox("Скачивать изображения", value=bool(settings.get("download_images", True)))

    sources = _collect_sources(manual_sources, selected_dialog_sources)
    try:
        days = inclusive_date_range(start_date, end_date)
    except ValueError:
        days = []
        st.error("Дата окончания должна быть не раньше даты начала.")

    if sources and days and len(sources) * len(days) > 100:
        st.warning("Количество источников × дней больше 100. Запуск разрешён, но может занять много времени.")

    if st.button("Сформировать TXT", type="primary", disabled=not sources or not days):
        settings.update(
            {
                "last_sources": manual_sources,
                "last_dates": {"start": str(start_date), "end": str(end_date)},
                "last_mode": mode,
                "download_images": download_images,
                "existing_mode": existing_mode,
            }
        )
        save_settings(settings)
        _run_export_ui(
            mode,
            sources,
            start_date,
            end_date,
            existing_mode,
            download_images,
            api_id,
            api_hash,
            proxy,
            settings,
        )

    _results_block(settings)


def _telegram_auth_block() -> tuple[str, str]:
    client = TelegramLoginClient()
    with st.expander("Telegram-авторизация", expanded=True):
        st.caption("Credentials вводятся только локально и не сохраняются в settings.json.")
        api_id = st.text_input("api_id", value="", placeholder="your_api_id")
        api_hash = st.text_input("api_hash", value="", type="password", placeholder="your_api_hash")
        phone = st.text_input("phone", value="", placeholder="your_phone")
        code = st.text_input("login code", value="")
        password = st.text_input("2FA password", value="", type="password")

        col_code, col_login, col_delete = st.columns(3)
        with col_code:
            if st.button("Отправить код Telegram"):
                try:
                    st.session_state.phone_code_hash = client.request_login_code(api_id, api_hash, phone)
                    st.success("Код отправлен. Введите login code и нажмите \"Войти в Telegram\".")
                except Exception as exc:
                    st.error(f"Не удалось отправить код: {exc}")
        with col_login:
            if st.button("Войти в Telegram"):
                try:
                    ok = client.complete_login(api_id, api_hash, phone, code, st.session_state.phone_code_hash, password)
                    st.success("Telegram-сессия авторизована." if ok else "Авторизация не завершена.")
                except TwoFactorRequiredError:
                    st.warning("Введите 2FA password и повторите вход.")
                except Exception as exc:
                    st.error(f"Ошибка авторизации: {exc}")
        with col_delete:
            if st.button("Удалить Telegram-сессию"):
                removed = client.delete_session()
                st.session_state.phone_code_hash = ""
                st.success(f"Удалено session-файлов: {removed}")

        st.info("Сессия найдена." if client.session_exists() else "Сессия пока не создана.")
    return api_id, api_hash


def _proxy_block(mode: str) -> dict[str, object] | None:
    with st.expander("SOCKS5 proxy", expanded=False):
        st.caption("Значения proxy не сохраняются в settings.json.")
        use_proxy = st.checkbox("Use SOCKS5 proxy", value=False)
        host = st.text_input("proxy host", value="127.0.0.1", disabled=not use_proxy)
        port = st.number_input(
            "proxy port",
            min_value=1,
            max_value=65535,
            value=11808,
            step=1,
            disabled=not use_proxy,
        )
        username = st.text_input("proxy username (опционально)", value="", disabled=not use_proxy)
        password = st.text_input(
            "proxy password (опционально)",
            value="",
            type="password",
            disabled=not use_proxy,
        )

    if not use_proxy:
        return None

    host = host.strip()
    port = int(port)
    user = username.strip()

    if mode == "public_web":
        auth = f"{user}:{password}@" if user else ""
        url = f"socks5h://{auth}{host}:{port}"
        return {"http": url, "https": url}

    proxy: dict[str, object] = {
        "proxy_type": "socks5",
        "addr": host,
        "port": port,
        "rdns": True,
    }
    if user:
        proxy["username"] = user
    if password:
        proxy["password"] = password
    return proxy


def _dialog_selector(api_id: str, api_hash: str) -> list[str]:
    client = TelegramLoginClient()
    with st.expander("Доступные источники аккаунта", expanded=False):
        st.caption("Используются api_id/api_hash из блока авторизации выше; значения не сохраняются.")
        if st.button("Загрузить доступные источники"):
            try:
                st.session_state.dialogs = client.list_dialogs(api_id, api_hash)
                st.success(f"Загружено источников: {len(st.session_state.dialogs)}")
            except Exception as exc:
                st.error(f"Не удалось загрузить источники: {exc}")

        search = st.text_input("Поиск/фильтр по названию", value="")
        type_options = {
            "channels": st.checkbox("Каналы", value=True),
            "private_channel": st.checkbox("Приватные каналы", value=True),
            "group": st.checkbox("Группы", value=True),
            "supergroup": st.checkbox("Супергруппы", value=True),
            "private_chat": st.checkbox("Личные переписки", value=True),
        }

        selected: list[str] = []
        for dialog in st.session_state.dialogs:
            if search and search.lower() not in dialog.title.lower():
                continue
            if dialog.source_type == "channel" and not type_options["channels"]:
                continue
            if dialog.source_type in type_options and not type_options[dialog.source_type]:
                continue
            label = f"{dialog.title} ({dialog.source_type}) [{dialog.raw}]"
            if st.checkbox(label, value=False, key=f"dialog_{dialog.raw}_{dialog.source_type}"):
                selected.append(dialog.raw)
        return selected


def _collect_sources(manual_sources: str, selected_dialog_sources: list[str]) -> list[str]:
    sources = [line.strip() for line in manual_sources.splitlines() if line.strip()]
    for item in selected_dialog_sources:
        if item not in sources:
            sources.append(item)
    return sources


def _run_export_ui(
    mode: str,
    sources: list[str],
    start_date: date,
    end_date: date,
    existing_mode: str,
    download_images: bool,
    api_id: str,
    api_hash: str,
    proxy: dict[str, object] | None,
    settings: dict,
) -> None:
    st.session_state.run_log = []
    progress = st.progress(0)
    status_box = st.empty()
    log_box = st.empty()

    def progress_callback(done: int, total: int, label: str) -> None:
        progress.progress(done / total if total else 0)
        status_box.info(f"Текущий источник/день: {label}")

    def log_callback(message: str) -> None:
        st.session_state.run_log.append(message)
        log_box.text("\n".join(st.session_state.run_log[-80:]))

    options = ExportOptions(
        mode=mode,
        sources=sources,
        start_date=start_date,
        end_date=end_date,
        existing_mode=existing_mode,
        download_images=download_images,
        api_id=api_id,
        api_hash=api_hash,
        proxy=proxy,
    )
    artifacts, results = run_export(options, progress_callback=progress_callback, log_callback=log_callback)
    settings["last_manifest_path"] = str(artifacts.manifest_path)
    settings["last_run_path"] = str(artifacts.run_path)
    settings["last_output_dir"] = str(artifacts.downloaded_dir)
    st.session_state.last_manifest_path = str(artifacts.manifest_path)
    save_settings(settings)
    st.success(f"Готово: {artifacts.manifest_path}")
    st.write(f"Папка downloaded: `{artifacts.downloaded_dir}`")
    st.dataframe(pd.DataFrame([result_to_row(result) for result in results]))
    st.write(dict(summarize_results(results)))


def _results_block(settings: dict) -> None:
    st.subheader("Результаты")
    st.write(f"Папка outputs: `{OUTPUTS_DIR}`")
    st.write(f"Папка downloaded: `{DOWNLOADED_DIR}`")

    last_manifest_raw = st.session_state.get("last_manifest_path") or settings.get("last_manifest_path") or ""
    last_manifest_path = Path(last_manifest_raw) if last_manifest_raw else None

    col_outputs, col_downloaded, col_manifest = st.columns(3)
    with col_outputs:
        if st.button("Открыть папку outputs"):
            _open_folder(OUTPUTS_DIR)
    with col_downloaded:
        if st.button("Открыть папку downloaded"):
            _open_folder(DOWNLOADED_DIR)
    with col_manifest:
        if st.button("Открыть папку manifest", disabled=last_manifest_path is None):
            _open_folder(last_manifest_path.parent if last_manifest_path else OUTPUTS_DIR)

    view_mode = st.radio(
        "Показать результаты",
        ["Последний запуск", "Вся история"],
        horizontal=True,
    )
    if view_mode == "Последний запуск":
        _last_run_results(last_manifest_path)
    else:
        _history_results()

    if st.session_state.run_log:
        st.text_area("Лог выполнения", value="\n".join(st.session_state.run_log), height=240)


def _last_run_results(manifest_path: Path | None) -> None:
    if manifest_path is None:
        st.info("Manifest последнего запуска пока не найден.")
        return
    st.write(f"Manifest: `{manifest_path}`")
    if not manifest_path.exists():
        st.warning("Файл manifest последнего запуска не найден.")
        return
    try:
        dataframe = pd.read_csv(manifest_path, encoding="utf-8-sig")
    except Exception as exc:
        st.error(f"Не удалось прочитать manifest: {exc}")
        return
    st.dataframe(dataframe)


def _history_results() -> None:
    rows = _downloaded_history_rows(DOWNLOADED_DIR)
    if not rows:
        st.info("В outputs/downloaded пока нет скачанных папок.")
        return

    page_size = 100
    total_pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = 1
    if total_pages > 1:
        page = int(st.number_input("Страница", min_value=1, max_value=total_pages, value=1, step=1))

    start = (page - 1) * page_size
    end = start + page_size
    st.write(f"Показаны {start + 1}-{min(end, len(rows))} из {len(rows)} папок.")
    st.dataframe(pd.DataFrame(rows[start:end]))


def _downloaded_history_rows(downloaded_dir: Path) -> list[dict[str, str]]:
    if not downloaded_dir.exists():
        return []
    rows: list[dict[str, str]] = []
    for folder in downloaded_dir.iterdir():
        if not folder.is_dir():
            continue
        source_slug, day_text = _parse_downloaded_folder_name(folder.name)
        rows.append(
            {
                "source_slug": source_slug,
                "date": day_text,
                "folder_name": folder.name,
                "folder_path": str(folder),
            }
        )
    rows.sort(key=lambda row: (row["source_slug"].lower(), row["date"], row["folder_name"].lower()))
    return rows


def _parse_downloaded_folder_name(folder_name: str) -> tuple[str, str]:
    match = re.match(r"^(?P<source>.+)-(?P<date>\d{4}-\d{2}-\d{2})$", folder_name)
    if not match:
        return folder_name, ""
    return match.group("source"), match.group("date")


def _open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(path))
    else:
        st.info(str(path))


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOGS_DIR / "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    logging.info("Application started")


if __name__ == "__main__":
    main()
