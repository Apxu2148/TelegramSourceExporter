import json
from datetime import date, datetime

from src.exporter import run_export
from src.file_writer import write_messages_file
from src.models import ExportOptions, Message, Source
from src.utils import HELSINKI_TZ, messages_filename, pair_folder_name


class FakePublicFetcher:
    def __init__(self, messages_by_source=None, errors=None):
        self.messages_by_source = messages_by_source or {}
        self.errors = errors or set()
        self.calls = []

    def fetch_messages_for_day(self, raw_source, day, download_images, output_folder, slug):
        self.calls.append((raw_source, day, output_folder, slug))
        if raw_source in self.errors:
            raise RuntimeError("Channel not available")
        messages = self.messages_by_source.get(raw_source, [])
        return Source(raw=f"@{raw_source}", title=raw_source.title(), source_type="channel"), messages


def test_exporter_writes_downloaded_manifest_run_and_statuses(tmp_path):
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

    artifacts, results = run_export(options, outputs_root=tmp_path, public_fetcher=fetcher)

    assert artifacts.downloaded_dir == tmp_path / "downloaded"
    assert artifacts.manifest_path.parent == tmp_path / "manifests"
    assert artifacts.manifest_path.name.startswith("manifest_")
    assert artifacts.run_path.parent == tmp_path / "runs"
    assert artifacts.run_path.name.startswith("run_")
    assert (tmp_path / "downloaded" / "source_a-2026-05-01").exists()
    assert (tmp_path / "downloaded" / "source_empty-2026-05-01").exists()
    assert (tmp_path / "downloaded" / "source_error-2026-05-01").exists()
    assert {result.status for result in results} == {"OK", "NO_MESSAGES", "ERROR"}
    assert not (tmp_path / "downloaded" / "media_index.txt").exists()

    manifest_text = artifacts.manifest_path.read_text(encoding="utf-8-sig")
    assert "downloaded/source_a-2026-05-01" in manifest_text.replace("\\", "/")

    run_data = json.loads(artifacts.run_path.read_text(encoding="utf-8"))
    assert run_data["mode"] == "public_web"
    assert "api_id" not in json.dumps(run_data)
    assert "api_hash" not in json.dumps(run_data)


def test_exporter_skips_existing_complete_in_downloaded(tmp_path):
    _, old_results = run_export(
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
    artifacts, new_results = run_export(
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
    assert (artifacts.downloaded_dir / pair_folder_name(date(2026, 5, 1), "banksta")).exists()
    assert "SKIPPED_EXISTING_COMPLETE" in artifacts.manifest_path.read_text(encoding="utf-8-sig")


def test_exporter_force_redownloads_and_cleans_pair_folder(tmp_path):
    artifacts, _ = run_export(
        ExportOptions(mode="public_web", sources=["banksta"], start_date=date(2026, 5, 1), end_date=date(2026, 5, 1)),
        outputs_root=tmp_path,
        public_fetcher=FakePublicFetcher(),
    )
    pair = artifacts.downloaded_dir / pair_folder_name(date(2026, 5, 1), "banksta")
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

    assert [(raw, day) for raw, day, _, _ in fetcher.calls] == [("banksta", date(2026, 5, 1))]
    assert not stale.exists()


def test_exporter_redownloads_incomplete_existing_folder(tmp_path):
    pair = tmp_path / "downloaded" / pair_folder_name(date(2026, 6, 4), "banksta")
    write_messages_file(
        pair,
        Source(raw="@banksta", title="Banksta", source_type="channel"),
        "banksta",
        "public_web",
        date(2026, 6, 4),
        False,
        "OK",
        [],
        0,
    )
    stale = pair / "stale.jpg"
    stale.write_bytes(b"old")

    fetcher = FakePublicFetcher()
    _, results = run_export(
        ExportOptions(
            mode="public_web",
            sources=["banksta"],
            start_date=date(2026, 6, 4),
            end_date=date(2026, 6, 4),
            existing_mode="skip_complete",
        ),
        outputs_root=tmp_path,
        public_fetcher=fetcher,
    )

    assert results[0].status == "NO_MESSAGES"
    assert [(raw, day) for raw, day, _, _ in fetcher.calls] == [("banksta", date(2026, 6, 4))]
    assert not stale.exists()


def test_exporter_redownloads_error_unknown_or_missing_metadata(tmp_path):
    cases = [
        ("error_complete", True, "ERROR", True),
        ("unknown_status", True, "MAYBE", True),
        ("missing_txt", True, "OK", False),
    ]

    for slug, complete_day, status, write_txt in cases:
        pair = tmp_path / "downloaded" / pair_folder_name(date(2026, 5, 1), slug)
        pair.mkdir(parents=True, exist_ok=True)
        stale = pair / "stale.jpg"
        stale.write_bytes(b"old")
        if write_txt:
            write_messages_file(
                pair,
                Source(raw=f"@{slug}", title=slug, source_type="channel"),
                slug,
                "public_web",
                date(2026, 5, 1),
                complete_day,
                status,  # type: ignore[arg-type]
                [],
                0,
            )

    fetcher = FakePublicFetcher()
    _, results = run_export(
        ExportOptions(
            mode="public_web",
            sources=[case[0] for case in cases],
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            existing_mode="skip_complete",
        ),
        outputs_root=tmp_path,
        public_fetcher=fetcher,
    )

    assert [result.status for result in results] == ["NO_MESSAGES", "NO_MESSAGES", "NO_MESSAGES"]
    assert [(raw, day) for raw, day, _, _ in fetcher.calls] == [
        ("error_complete", date(2026, 5, 1)),
        ("unknown_status", date(2026, 5, 1)),
        ("missing_txt", date(2026, 5, 1)),
    ]
    for slug, _, _, _ in cases:
        pair = tmp_path / "downloaded" / pair_folder_name(date(2026, 5, 1), slug)
        assert not (pair / "stale.jpg").exists()


def test_exporter_ignores_legacy_export_folders(tmp_path):
    legacy_pair = tmp_path / "export_2026-06-03_1242" / "banksta-2026-05-01"
    write_messages_file(
        legacy_pair,
        Source(raw="@banksta", title="Banksta", source_type="channel"),
        "banksta",
        "public_web",
        date(2026, 5, 1),
        True,
        "NO_MESSAGES",
        [],
        0,
    )

    fetcher = FakePublicFetcher()
    _, results = run_export(
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

    assert results[0].status == "NO_MESSAGES"
    assert [(raw, day) for raw, day, _, _ in fetcher.calls] == [("banksta", date(2026, 5, 1))]
    assert (tmp_path / "downloaded" / "banksta-2026-05-01").exists()


def test_exporter_requires_exact_messages_txt_for_skip(tmp_path):
    pair = tmp_path / "downloaded" / "banksta-2026-05-01"
    pair.mkdir(parents=True)
    wrong_name = pair / "2026-05-01__banksta__messages.txt"
    wrong_name.write_text("COMPLETE_DAY: true\nSTATUS: NO_MESSAGES\n", encoding="utf-8-sig")

    fetcher = FakePublicFetcher()
    _, results = run_export(
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

    assert results[0].status == "NO_MESSAGES"
    assert fetcher.calls
    assert not wrong_name.exists()
    assert (pair / messages_filename(date(2026, 5, 1), "banksta")).exists()
