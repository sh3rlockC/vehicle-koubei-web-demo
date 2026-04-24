from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.services.llm_client import AnthropicMessagesReportLLMClient, DisabledLLMClient, HTTPReportLLMClient, build_report_llm_client


def test_http_report_llm_client_posts_chat_completion_and_parses_json_content() -> None:
    requests: list[httpx.Request] = []
    report = {
        "headline": "LLM headline",
        "executive_summary": "LLM summary",
        "strength_blocks": [],
        "weakness_blocks": [],
        "platform_difference_blocks": [],
        "action_blocks": [],
        "boss_brief": ["one", "two", "three"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(report),
                        }
                    }
                ]
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = HTTPReportLLMClient(
        base_url="https://llm.example/v1/",
        api_key="test-key",
        model="report-model",
        http_client=http_client,
    )

    payload = client.generate_report({"vehicle": "风云X3 PLUS"})

    assert payload == report
    assert len(requests) == 1
    assert str(requests[0].url) == "https://llm.example/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer test-key"
    body = json.loads(requests[0].content)
    assert body["model"] == "report-model"
    assert body["temperature"] <= 0.2
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"


def test_http_report_llm_client_can_request_json_response_format() -> None:
    requests: list[httpx.Request] = []
    report = {
        "headline": "DeepSeek headline",
        "executive_summary": "DeepSeek summary",
        "strength_blocks": [],
        "weakness_blocks": [],
        "platform_difference_blocks": [],
        "action_blocks": [],
        "boss_brief": ["one", "two", "three"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(report)}}]})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = HTTPReportLLMClient(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-v4-flash",
        http_client=http_client,
        response_format_json=True,
    )

    payload = client.generate_report({"vehicle": "风云X3L"})

    assert payload == report
    body = json.loads(requests[0].content)
    assert body["response_format"] == {"type": "json_object"}


def test_http_report_llm_client_returns_none_on_request_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream failed"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = HTTPReportLLMClient(
        base_url="https://llm.example/v1",
        api_key="test-key",
        model="report-model",
        http_client=http_client,
    )

    assert client.generate_report({"vehicle": "风云X3 PLUS"}) is None


def test_http_report_llm_client_returns_none_on_invalid_json_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = HTTPReportLLMClient(
        base_url="https://llm.example/v1",
        api_key="test-key",
        model="report-model",
        http_client=http_client,
    )

    assert client.generate_report({"vehicle": "风云X3 PLUS"}) is None


def test_anthropic_messages_report_llm_client_posts_messages_and_parses_text_block_json() -> None:
    requests: list[httpx.Request] = []
    report = {
        "headline": "MiniMax headline",
        "executive_summary": "MiniMax summary",
        "strength_blocks": [],
        "weakness_blocks": [],
        "platform_difference_blocks": [],
        "action_blocks": [],
        "boss_brief": ["one", "two", "three"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "type": "message",
                "content": [{"type": "text", "text": json.dumps(report)}],
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = AnthropicMessagesReportLLMClient(
        base_url="https://api.minimaxi.com/anthropic/v1/",
        api_key="test-key",
        model="MiniMax-M2.7",
        http_client=http_client,
        retry_delays=(0.0,),
    )

    payload = client.generate_report({"vehicle": "风云X3 PLUS"})

    assert payload == report
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.minimaxi.com/anthropic/v1/messages"
    assert requests[0].headers["authorization"] == "Bearer test-key"
    assert requests[0].headers["anthropic-version"] == "2023-06-01"
    body = json.loads(requests[0].content)
    assert body["model"] == "MiniMax-M2.7"
    assert body["system"]
    assert body["messages"][0]["role"] == "user"


def test_anthropic_messages_report_llm_client_retries_transient_provider_errors() -> None:
    requests: list[httpx.Request] = []
    report = {
        "headline": "MiniMax headline",
        "executive_summary": "MiniMax summary",
        "strength_blocks": [],
        "weakness_blocks": [],
        "platform_difference_blocks": [],
        "action_blocks": [],
        "boss_brief": ["one", "two", "three"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                529,
                json={"type": "error", "error": {"type": "overloaded_error", "message": "overloaded_error (529)"}},
            )
        return httpx.Response(200, json={"type": "message", "content": [{"type": "text", "text": json.dumps(report)}]})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = AnthropicMessagesReportLLMClient(
        base_url="https://api.minimaxi.com/anthropic/v1/",
        api_key="test-key",
        model="MiniMax-M2.7",
        http_client=http_client,
    )

    payload = client.generate_report({"vehicle": "风云X3 PLUS"})

    assert payload == report
    assert len(requests) == 2


def test_build_report_llm_client_uses_settings_and_defaults_to_disabled() -> None:
    disabled = build_report_llm_client(Settings(llm_provider="", llm_api_key="", llm_base_url="", llm_model_report=""))
    enabled = build_report_llm_client(
        Settings(
            llm_provider="openai",
            llm_api_key="test-key",
            llm_base_url="https://llm.example/v1",
            llm_model_report="report-model",
        )
    )

    assert isinstance(disabled, DisabledLLMClient)
    assert isinstance(enabled, HTTPReportLLMClient)


def test_build_report_llm_client_uses_kimi_code_client_for_coding_endpoint() -> None:
    enabled = build_report_llm_client(
        Settings(
            llm_provider="kimi",
            llm_api_key="test-key",
            llm_base_url="https://api.kimi.com/coding/v1",
            llm_model_report="kimi-for-coding",
        )
    )

    assert isinstance(enabled, AnthropicMessagesReportLLMClient)


def test_build_report_llm_client_uses_anthropic_messages_client_for_minimax() -> None:
    enabled = build_report_llm_client(
        Settings(
            llm_provider="minimax-portal",
            llm_api_key="test-key",
            llm_base_url="https://api.minimaxi.com/anthropic/v1",
            llm_model_report="MiniMax-M2.7",
        )
    )

    assert isinstance(enabled, AnthropicMessagesReportLLMClient)


def test_build_report_llm_client_uses_openai_compatible_client_for_deepseek_v4() -> None:
    enabled = build_report_llm_client(
        Settings(
            llm_provider="deepseek",
            llm_api_key="test-key",
            llm_base_url="https://api.deepseek.com",
            llm_model_report="deepseek-v4-flash",
        )
    )

    assert isinstance(enabled, HTTPReportLLMClient)
    assert enabled.model == "deepseek-v4-flash"
    assert enabled.response_format_json is True


def test_settings_reads_llm_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_MODEL_REPORT", "env-report-model")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "openai"
    assert settings.llm_api_key == "env-key"
    assert settings.llm_base_url == "https://llm.example/v1"
    assert settings.llm_model_report == "env-report-model"
