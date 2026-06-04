from src.settings import sanitize_settings


def test_sanitize_settings_keeps_only_safe_keys():
    sanitized = sanitize_settings(
        {
            "last_sources": "@banksta",
            "last_manifest_path": "outputs/manifests/manifest_2026-06-04_1200.csv",
            "last_run_path": "outputs/runs/run_2026-06-04_1200.json",
            "api_id": "123",
            "api_hash": "secret",
            "phone": "+1000",
            "code": "11111",
            "password": "2fa",
        }
    )

    assert sanitized["last_sources"] == "@banksta"
    assert sanitized["last_manifest_path"].endswith("manifest_2026-06-04_1200.csv")
    assert sanitized["last_run_path"].endswith("run_2026-06-04_1200.json")
    assert "api_id" not in sanitized
    assert "api_hash" not in sanitized
    assert "phone" not in sanitized
    assert "code" not in sanitized
    assert "password" not in sanitized
