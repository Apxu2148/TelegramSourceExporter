from datetime import date, datetime

from src.file_writer import write_messages_file
from src.manifest import write_manifest
from src.models import ExportResult, Message, Source
from src.utils import HELSINKI_TZ


def test_write_messages_ok_utf8_sig(tmp_path):
    source = Source(raw="@banksta", title="Banksta", source_type="channel")
    message = Message(
        message_id="12345",
        dt=datetime(2026, 6, 1, 9, 15, tzinfo=HELSINKI_TZ),
        source="@banksta",
        author=None,
        reply_to_message_id=None,
        text="Hello",
        media="none",
    )

    path = write_messages_file(tmp_path, source, "banksta", "public_web", date(2026, 6, 1), False, "OK", [message], 0)

    assert path.name == "banksta-2026-06-01__messages.txt"
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    assert "STATUS: OK" in text
    assert "author: none" in text
    assert "media_files:\nnone" in text


def test_write_messages_no_messages(tmp_path):
    source = Source(raw="@banksta", title="Banksta", source_type="channel")
    path = write_messages_file(tmp_path, source, "banksta", "public_web", date(2026, 6, 1), False, "NO_MESSAGES", [], 0)

    text = path.read_text(encoding="utf-8-sig")
    assert "STATUS: NO_MESSAGES" in text
    assert text.strip().endswith("NO_MESSAGES")


def test_manifest_utf8_sig(tmp_path):
    result = ExportResult(
        source="@banksta",
        source_title="Banksta",
        source_type="channel",
        mode="public_web",
        day=date(2026, 6, 1),
        folder_path=tmp_path / "downloaded" / "banksta-2026-06-01",
        messages_count=1,
        media_count=0,
        status="OK",
        complete_day=False,
    )
    path = write_manifest(tmp_path, "2026-06-04_1200", [result])

    assert path.name == "manifest_2026-06-04_1200.csv"
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    text = path.read_text(encoding="utf-8-sig")
    assert "source,source_title,source_type,mode,date,folder_path" in text
    assert "@banksta,Banksta,channel,public_web,2026-06-01" in text
