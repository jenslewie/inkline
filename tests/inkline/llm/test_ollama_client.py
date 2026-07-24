import json
from unittest.mock import MagicMock

from inkline.llm.ollama import OllamaChatConfig, chat_json, chat_text, extract_json_value


def test_extract_json_value_from_wrapped_response() -> None:
    assert extract_json_value('before {"answer": "ok"} after') == {"answer": "ok"}


def test_chat_json_wraps_top_level_list_as_items(monkeypatch) -> None:
    response = MagicMock()
    response.read.return_value = json.dumps(
        {"message": {"content": '[{"a": 1}, {"a": 2}]'}}, ensure_ascii=False
    ).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    monkeypatch.setattr("urllib.request.urlopen", MagicMock(return_value=response))

    parsed = chat_json(
        OllamaChatConfig(model="qwen-test", api_url="http://example.test/api/chat"),
        messages=[{"role": "user", "content": "json only"}],
    )

    assert parsed == {"items": [{"a": 1}, {"a": 2}]}


def test_chat_text_does_not_request_json_format(monkeypatch) -> None:
    response = MagicMock()
    response.read.return_value = json.dumps(
        {"message": {"content": "plain answer"}}, ensure_ascii=False
    ).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    urlopen = MagicMock(return_value=response)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    text = chat_text(
        OllamaChatConfig(model="qwen-test", api_url="http://example.test/api/chat"),
        messages=[{"role": "user", "content": "answer normally"}],
    )

    request = urlopen.call_args.args[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert text == "plain answer"
    assert "format" not in payload
