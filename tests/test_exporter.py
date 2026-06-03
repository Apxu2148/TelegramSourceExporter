from datetime import date, datetime

from src.exporter import run_export
from src.models import ExportOptions, Message, Source
from src.utils import HELSINKI_TZ, pair_folder_name


class FakePublicFetcher:
    def __init__(self, messages_by_source=None, errors=None):
        self.messages_by_source = messages_by_source or {}
        self.errors = errors or set()
        self.calls = []

    def fetch_messages_for_day(self, raw_source, day, download_images, output_folder, slug):
        self.calls.append((raw_source, day))
        if raw_source in self.errors:
            raise RuntimeError("Channel not available")
        messages = self.messages_by_source.get(raw_source, [])
        return Source(raw=f"@{raw_source}", title=raw_source.title(), source_type="channel"), messages


def test_exporter_writes_ok_no_messages_and_error(tmp_path):
    message = Message(
        message_id="1",
        dt=datetime(2026, 5, 1, 10, 0, tzinfo=HELSINKI_TZ),
        source="@source_a",
        text="Hello",
    )
    fetcher = FakePublicFetcher(messages_by_source={"source_a": [message]}, errors={"source_error"})
    options = ExportOptions(
        mode="public_web",
        sources=["source_a", "source_empty", "source_error"],
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 1),
    )

    export_dir, results = run_export(options, outputs_root=tmp_path, public_fetcher=fetcher)

    assert (export_dir / "manifest.csv").exists()
    assert {result.status for result in results} == {"OK", "NO_MESSAGES", "ERROR"}
    assert not (export_dir / "media_index.txt").exists()


def test_exporter_skips_existing_complete(tmp_path):
    old_export, old_results = run_export(
        ExportOptions(
            mode="public_web",
            sources=["banksta"],
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
        ),
        outputs_root=tmp_path,
        public_fetcher=FakePublicFetcher(messages_by_source={"banksta": []}),
    )
    assert old_results[0].status == "NO_MESSAGES"

    fetcher = FakePublicFetcher(messages_by_source={"banksta": []})
    new_export, new_results = run_export(
        ExportOptions(
            mode="public_web",
            sources=["banksta"],
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            existing_mode="skip_complete",
        ),
        outputs_root=tmp_path,
        public_fetcher=fetcher,
    )

    assert new_results[0].status == "SKIPPED_EXISTING_COMPLETE"
    assert fetcher.calls == []
    assert (new_export / pair_folder_name(date(2026, 5, 1), "banksta")).exists()


def test_exporter_force_redownloads_and_cleans_pair_folder(tmp_path):
    export_dir, _ = run_export(
        ExportOptions(mode="public_web", sources=["banksta"], start_date=date(2026, 5, 1), end_date=date(2026, 5, 1)),
        outputs_root=tmp_path,
        public_fetcher=FakePublicFetcher(),
    )
    pair = export_dir / pair_folder_name(date(2026, 5, 1), "banksta")
    stale = pair / "stale.jpg"
    stale.write_bytes(b"old")

    fetcher = FakePublicFetcher()
    run_export(
        ExportOptions(
            mode="public_web",
            sources=["banksta"],
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            existing_mode="force",
        ),
        outputs_root=tmp_path,
        public_fetcher=fetcher,
    )

    assert fetcher.calls == [("banksta", date(2026, 5, 1))]

