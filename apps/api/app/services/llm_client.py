from __future__ import annotations

import json
import time
from typing import Protocol

import httpx

from app.config import Settings


class ReportLLMClient(Protocol):
    def generate_report(self, context: dict) -> dict | None: ...


class DisabledLLMClient:
    def generate_report(self, context: dict) -> dict | None:
        return None


class HTTPReportLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        http_client: httpx.Client | None = None,
        response_format_json: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.http_client = http_client or httpx.Client(timeout=30.0)
        self.response_format_json = response_format_json

    def generate_report(self, context: dict) -> dict | None:
        try:
            request_body = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You generate concise vehicle reputation reports. "
                            "Return only one JSON object matching the requested report schema."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(context, ensure_ascii=False),
                    },
                ],
                "temperature": 0.1,
            }
            if self.response_format_json:
                request_body["response_format"] = {"type": "json_object"}
            response = self.http_client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=request_body,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            payload = json.loads(content)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            return None

        return payload if isinstance(payload, dict) else None


class AnthropicMessagesReportLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        http_client: httpx.Client | None = None,
        retry_delays: tuple[float, ...] = (0.5, 1.5),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.http_client = http_client or httpx.Client(timeout=60.0)
        self.retry_delays = retry_delays

    def generate_report(self, context: dict) -> dict | None:
        try:
            response = self._post_messages_with_retry(context)
            response.raise_for_status()
            content_blocks = response.json()["content"]
            content = "".join(
                block.get("text", "")
                for block in content_blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
            payload = json.loads(content)
        except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError):
            return None

        return payload if isinstance(payload, dict) else None

    def _post_messages_with_retry(self, context: dict) -> httpx.Response:
        retryable_status_codes = {429, 500, 502, 503, 504, 529}
        attempts = len(self.retry_delays) + 1
        for attempt_index in range(attempts):
            response = self.http_client.post(
                f"{self.base_url}/messages",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "anthropic-version": "2023-06-01",
                    "User-Agent": "claude-code/0.1.0",
                },
                json={
                    "model": self.model,
                    "max_tokens": 4096,
                    "system": (
                        "You generate concise vehicle reputation reports. "
                        "Return only one JSON object matching the requested report schema."
                    ),
                    "messages": [
                        {
                            "role": "user",
                            "content": json.dumps(context, ensure_ascii=False),
                        },
                    ],
                },
            )
            if response.status_code not in retryable_status_codes or attempt_index == attempts - 1:
                return response
            delay = self.retry_delays[attempt_index]
            if delay > 0:
                time.sleep(delay)
        return response


def build_report_llm_client(settings: Settings) -> ReportLLMClient:
    if not settings.llm_provider or not settings.llm_api_key or not settings.llm_base_url or not settings.llm_model_report:
        return DisabledLLMClient()
    provider = settings.llm_provider.strip().lower()
    if (
        (provider in {"kimi", "kimi-code", "kimi_code"} and "/coding" in settings.llm_base_url)
        or provider in {"minimax", "minimax-portal", "minimax_cn", "minimax-cn"}
    ):
        return AnthropicMessagesReportLLMClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model_report,
        )
    return HTTPReportLLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model_report,
        response_format_json=provider in {"deepseek", "deepseek-v4", "deepseekv4"},
    )
