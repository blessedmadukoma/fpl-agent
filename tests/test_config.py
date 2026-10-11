"""Parse tracing settings without loading the user's environment file."""

import pytest

from fpl import config


@pytest.mark.parametrize(("raw", "expected"), [
    (None, True), ("true", True), (" TRUE ", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), (" FALSE ", False), ("0", False), ("no", False), ("off", False),
])
def test_tracing_flag_is_parsed_explicitly(tmp_path, monkeypatch, raw, expected):
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("FPL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("FPL_ENTRY_ID", raising=False)
    if raw is None:
        monkeypatch.delenv("LANGFUSE_TRACING_ENABLED", raising=False)
    else:
        monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", raw)
    assert config.load_settings().langfuse_tracing_enabled is expected


def test_invalid_tracing_flag_is_rejected_without_echoing_its_value(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("FPL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("FPL_ENTRY_ID", raising=False)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "mistaken-secret-value")
    with pytest.raises(ValueError, match="LANGFUSE_TRACING_ENABLED") as failure:
        config.load_settings()
    assert "mistaken-secret-value" not in str(failure.value)
