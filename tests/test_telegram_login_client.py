from pathlib import Path

import telethon

from src.telegram_login_client import TelegramLoginClient, _dialog_source_type, _run


class Entity:
    def __init__(self, username=None, megagroup=False):
        self.username = username
        self.megagroup = megagroup


class Dialog:
    def __init__(self, is_user=False, is_group=False, is_channel=False, entity=None):
        self.is_user = is_user
        self.is_group = is_group
        self.is_channel = is_channel
        self.entity = entity or Entity()


def test_dialog_type_mapping():
    assert _dialog_source_type(Dialog(is_user=True)) == "private_chat"
    assert _dialog_source_type(Dialog(is_group=True, entity=Entity(megagroup=False))) == "group"
    assert _dialog_source_type(Dialog(is_group=True, entity=Entity(megagroup=True))) == "supergroup"
    assert _dialog_source_type(Dialog(is_channel=True, entity=Entity(username="pub"))) == "channel"
    assert _dialog_source_type(Dialog(is_channel=True, entity=Entity(username=None))) == "private_channel"


def test_delete_session_removes_session_files(tmp_path):
    client = TelegramLoginClient(tmp_path / "telegram")
    (tmp_path / "telegram.session").write_text("session")
    (tmp_path / "telegram.session-journal").write_text("journal")

    assert client.session_exists()
    assert client.delete_session() == 2
    assert not list(Path(tmp_path).glob("telegram.session*"))


class _FakeTelegramClient:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


def _capture_telegram_client(monkeypatch):
    captured: dict[str, object] = {}

    def factory(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeTelegramClient(*args, **kwargs)

    monkeypatch.setattr(telethon, "TelegramClient", factory)
    return captured


def test_client_without_proxy_keeps_default_behaviour(monkeypatch, tmp_path):
    captured = _capture_telegram_client(monkeypatch)
    client = TelegramLoginClient(tmp_path / "telegram")

    _run(client._client("123", "abc"))

    assert captured["args"][:1] == (str(tmp_path / "telegram"),)
    assert captured["args"][1:] == (123, "abc")
    assert captured["kwargs"] == {"proxy": None}


def test_client_with_proxy_passes_it_to_telegram_client(monkeypatch, tmp_path):
    captured = _capture_telegram_client(monkeypatch)
    client = TelegramLoginClient(tmp_path / "telegram")
    proxy = {"proxy_type": "socks5", "addr": "127.0.0.1", "port": 11808, "rdns": True}

    _run(client._client("123", "abc", proxy))

    assert captured["kwargs"] == {"proxy": proxy}


def test_public_methods_accept_proxy_without_breaking_default(tmp_path):
    client = TelegramLoginClient(tmp_path / "telegram")

    assert client.fetch_messages_for_day.__defaults__[-1] is None
    assert client.request_login_code.__defaults__[-1] is None
    assert client.complete_login.__defaults__[-1] is None
    assert client.list_dialogs.__defaults__[-1] is None

