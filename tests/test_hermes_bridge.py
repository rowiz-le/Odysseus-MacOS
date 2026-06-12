from pathlib import Path

import httpx

from src import hermes_bridge


def _settings(values):
    return lambda key, default=None: values.get(key, default)


def test_local_hermes_uses_gateway_key_from_hermes_env(tmp_path, monkeypatch):
    tmp_path.joinpath(".env").write_text(
        "API_SERVER_KEY=generated-local-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(
        hermes_bridge,
        "get_setting",
        _settings({
            "hermes_api_base": "http://127.0.0.1:8642/v1",
            "hermes_api_key": "change-me-local-dev",
        }),
    )

    assert hermes_bridge._headers()["Authorization"] == "Bearer generated-local-key"


def test_explicit_hermes_key_wins_over_local_env(tmp_path, monkeypatch):
    tmp_path.joinpath(".env").write_text(
        "API_SERVER_KEY=generated-local-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(
        hermes_bridge,
        "get_setting",
        _settings({
            "hermes_api_base": "http://127.0.0.1:8642/v1",
            "hermes_api_key": "user-configured-key",
        }),
    )

    assert hermes_bridge._headers()["Authorization"] == "Bearer user-configured-key"


def test_remote_hermes_does_not_borrow_local_gateway_key(tmp_path, monkeypatch):
    tmp_path.joinpath(".env").write_text(
        "API_SERVER_KEY=generated-local-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(
        hermes_bridge,
        "get_setting",
        _settings({
            "hermes_api_base": "https://hermes.example.com/v1",
            "hermes_api_key": "change-me-local-dev",
        }),
    )

    assert hermes_bridge._headers()["Authorization"] == "Bearer change-me-local-dev"


def test_unauthorized_response_has_actionable_message():
    response = httpx.Response(
        401,
        json={"error": {"message": "Invalid API key", "code": "invalid_api_key"}},
    )

    message = hermes_bridge._response_error(response)

    assert "API_SERVER_KEY" in message
    assert "~/.hermes/.env" in message


def test_hermes_final_text_snapshots_are_not_streamed_twice():
    first = list(hermes_bridge._map_hermes_event({"delta": "OK"}, "run-1"))
    repeated_text = list(
        hermes_bridge._map_hermes_event({"text": "OK"}, "run-1", emitted_text="OK")
    )
    repeated_output = list(
        hermes_bridge._map_hermes_event({"output": "OK"}, "run-1", emitted_text="OK")
    )

    assert first == ['data: {"delta": "OK"}\n\n']
    assert repeated_text == []
    assert repeated_output == []


def test_chat_stream_surfaces_backend_message_field():
    source = Path("static/js/chat.js").read_text(encoding="utf-8")
    assert "const errMsg = json.message" in source
    assert "typeof json.error === 'string'" in source
