from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.utils import (
    HELSINKI_TZ,
    image_filename,
    inclusive_date_range,
    is_complete_day,
    messages_filename,
    pair_folder_name,
    source_slug,
)


def test_source_slug_normalizes_common_forms():
    assert source_slug("@banksta") == "banksta"
    assert source_slug("https://t.me/banksta") == "banksta"
    assert source_slug("https://t.me/s/banksta") == "banksta"
    assert source_slug("bad:name?") == "bad-name"
    assert source_slug("@Market Twits") == "market-twits"
    assert source_slug("CON") == "source-con"


def test_output_names_use_source_date_prefix():
    day = date(2026, 6, 1)
    dt = datetime(2026, 6, 1, 9, 15, tzinfo=HELSINKI_TZ)

    assert pair_folder_name(day, "markettwits") == "markettwits-2026-06-01"
    assert messages_filename(day, "markettwits") == "markettwits-2026-06-01__messages.txt"
    assert image_filename(day, "markettwits", "12345", dt, 1, "jpeg") == (
        "markettwits-2026-06-01__msg_12345__091500__photo_01.jpg"
    )


def test_inclusive_date_range_includes_end_date():
    assert inclusive_date_range(date(2026, 5, 1), date(2026, 5, 3)) == [
        date(2026, 5, 1),
        date(2026, 5, 2),
        date(2026, 5, 3),
    ]


def test_complete_day_uses_helsinki_date():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=HELSINKI_TZ)
    assert is_complete_day(date(2026, 5, 31), now)
    assert not is_complete_day(date(2026, 6, 1), now)


def test_complete_day_converts_timezone():
    now_utc = datetime(2026, 5, 31, 22, 30, tzinfo=ZoneInfo("UTC"))
    assert not is_complete_day(date(2026, 6, 1), now_utc)
