"""Tests for the ace-upload CLI. These mock httpx — no Django needed."""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def config_file(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('server = "http://localhost:8000/ace"\ntoken = "test-token-123"\n')
    return config


def test_upload_single_file(config_file, tmp_path):
    from apps.ingest.cli import load_config, upload_file
    session_file = tmp_path / "test.jsonl"
    session_file.write_text('{"type":"system","subtype":"init","session_id":"s1"}\n')
    config = load_config(config_file)
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "data": {"session_slug": "abc", "message_count": 1, "cli_session_id": "s1"},
        "error": None,
    }
    with patch("httpx.post", return_value=mock_response) as mock_post:
        result = upload_file(session_file, config)
    assert result is True
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "Bearer test-token-123" in str(call_kwargs)


def test_upload_duplicate_returns_false(config_file, tmp_path):
    from apps.ingest.cli import load_config, upload_file
    session_file = tmp_path / "test.jsonl"
    session_file.write_text('{"type":"system"}\n')
    config = load_config(config_file)
    mock_response = MagicMock()
    mock_response.status_code = 409
    mock_response.json.return_value = {
        "data": None,
        "error": {"code": "duplicate", "message": "already uploaded"},
    }
    with patch("httpx.post", return_value=mock_response):
        result = upload_file(session_file, config)
    assert result is False


def test_load_config(config_file):
    from apps.ingest.cli import load_config
    config = load_config(config_file)
    assert config.server == "http://localhost:8000/ace"
    assert config.token == "test-token-123"


def test_load_config_missing_raises(tmp_path):
    from apps.ingest.cli import load_config
    with pytest.raises(SystemExit):
        load_config(tmp_path / "nonexistent.toml")
