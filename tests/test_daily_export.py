import json
from datetime import date
from pathlib import Path

import daily_export
from src.models import ExportArtifacts, ExportResult


def _result(status: str, day: date = date(2026, 5, 1)) -> ExportResult:
    return ExportResult(
        source="@channel_a",
        source_title="Channel A",
        source_type="channel",
        mode="public_web",
        day=day,
        folder_path=Path("/tmp/channel_a-2026-05-01"),
        messages_count=1,
        media_count=0,
        status=status,  # type: ignore[arg-type]
        complete_day=True,
    )


class FakeRunExport:
    def __init__(self, results=None, error=None):
        self.results = results if results is not None else []
        self.error = error
        self.calls = []

    def __call__(self, options, **kwargs):
        self.calls.append((options, kwargs))
        if self.error is not None:
            raise self.error
        artifacts = ExportArtifacts(
            run_id="2026-05-01_1200",
            manifest_path=Path("/out/manifests/manifest_2026-05-01_1200.csv"),
            run_path=Path("/out/runs/run_2026-05-01_1200.json"),
            downloaded_dir=Path("/out/downloaded"),
        )
        return artifacts, self.results


def _last_json(capsys):
    out = capsys.readouterr().out.strip().splitlines()
    return json.loads(out[-1])


def test_build_proxy_default_and_disabled():
    assert daily_export.build_proxy(True, "127.0.0.1", 11808) == {
        "http": "socks5h://127.0.0.1:11808",
        "https": "socks5h://127.0.0.1:11808",
    }
    assert daily_export.build_proxy(False, "127.0.0.1", 11808) is None


def test_parse_sources_splits_and_strips():
    assert daily_export.parse_sources(" @channel_a , @channel_b ,, @channel_c ") == [
        "@channel_a",
        "@channel_b",
        "@channel_c",
    ]


def test_main_success_enables_proxy_and_returns_zero(monkeypatch, tmp_path, capsys):
    fake = FakeRunExport([_result("OK"), _result("NO_MESSAGES")])
    monkeypatch.setattr(daily_export, "run_export", fake)

    code = daily_export.main(
        ["--sources", "@channel_a,@channel_b", "--date", "2026-05-01", "--output-dir", str(tmp_path)]
    )

    assert code == 0
    payload = _last_json(capsys)
    assert payload["date"] == "2026-05-01"
    assert payload["sources"] == 2
    assert payload["OK"] == 1
    assert payload["NO_MESSAGES"] == 1
    assert payload["ERROR"] == 0
    assert Path(payload["manifest"]) == Path("/out/manifests/manifest_2026-05-01_1200.csv")
    assert Path(payload["run_report"]) == Path("/out/runs/run_2026-05-01_1200.json")
    assert payload["proxy"] == "socks5h://127.0.0.1:11808"

    options, kwargs = fake.calls[0]
    assert options.mode == "public_web"
    assert options.sources == ["@channel_a", "@channel_b"]
    assert options.start_date == options.end_date == date(2026, 5, 1)
    assert options.proxy == {"http": "socks5h://127.0.0.1:11808", "https": "socks5h://127.0.0.1:11808"}
    assert kwargs["outputs_root"] == tmp_path


def test_main_no_proxy_disables_proxy(monkeypatch, tmp_path, capsys):
    fake = FakeRunExport([_result("OK")])
    monkeypatch.setattr(daily_export, "run_export", fake)

    code = daily_export.main(["--sources", "@channel_a", "--date", "2026-05-01", "--no-proxy"])

    assert code == 0
    payload = _last_json(capsys)
    assert payload["proxy"] is None
    options, _ = fake.calls[0]
    assert options.proxy is None


def test_main_custom_proxy_host_and_port(monkeypatch, tmp_path, capsys):
    fake = FakeRunExport([_result("OK")])
    monkeypatch.setattr(daily_export, "run_export", fake)

    daily_export.main(
        [
            "--sources",
            "@channel_a",
            "--proxy-host",
            "10.0.0.5",
            "--proxy-port",
            "9050",
        ]
    )

    options, _ = fake.calls[0]
    assert options.proxy == {"http": "socks5h://10.0.0.5:9050", "https": "socks5h://10.0.0.5:9050"}


def test_main_error_status_returns_nonzero(monkeypatch, tmp_path, capsys):
    fake = FakeRunExport([_result("OK"), _result("ERROR")])
    monkeypatch.setattr(daily_export, "run_export", fake)

    code = daily_export.main(["--sources", "@channel_a,@channel_b", "--date", "2026-05-01"])

    assert code == 1
    payload = _last_json(capsys)
    assert payload["ERROR"] == 1
    assert payload["OK"] == 1


def test_main_exception_returns_nonzero_with_summary(monkeypatch, tmp_path, capsys):
    fake = FakeRunExport(error=RuntimeError("boom"))
    monkeypatch.setattr(daily_export, "run_export", fake)

    code = daily_export.main(["--sources", "@channel_a", "--date", "2026-05-01"])

    assert code == 1
    payload = _last_json(capsys)
    assert payload["error"] == "boom"
    assert payload["ERROR"] == 1


def test_main_empty_sources_returns_two(monkeypatch, capsys):
    fake = FakeRunExport([_result("OK")])
    monkeypatch.setattr(daily_export, "run_export", fake)

    code = daily_export.main(["--sources", " , "])

    assert code == 2
    assert fake.calls == []
    payload = _last_json(capsys)
    assert payload["sources"] == 0
    assert payload["error"] == "no sources provided"


def test_main_defaults_to_today_and_default_proxy(monkeypatch, capsys):
    fake = FakeRunExport([_result("OK")])
    monkeypatch.setattr(daily_export, "run_export", fake)

    daily_export.main(["--sources", "@channel_a"])

    options, _ = fake.calls[0]
    assert str(options.start_date) == str(daily_export.helsinki_today())
    assert options.proxy == {"http": "socks5h://127.0.0.1:11808", "https": "socks5h://127.0.0.1:11808"}