from pathlib import Path

from src.telegram_login_client import TelegramLoginClient, _dialog_source_type


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

