"""Text LLM adapter: Anthropic Messages or OpenAI Chat Completions BYOK.

Default export remains FakeOpenAIAdapter for unit tests without keys.
Never logs full API keys or full prompt/response bodies.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from app.config import Settings, get_settings
from app.providers.fake import FakeOpenAIAdapter


class AnthropicCompatibleTextAdapter:
    """Anthropic-style POST {base}/v1/messages (or {base}/messages)."""

    provider = "openai"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self.calls: list[dict[str, Any]] = []
        self._tasks: dict[str, dict[str, Any]] = {}

    def configured(self) -> bool:
        return self._settings.text_llm_configured()

    def _headers(self) -> dict[str, str]:
        key = self._settings.text_llm_api_key.strip()
        return {
            "x-api-key": key,
            "Authorization": f"Bearer {key}",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _messages_url(self) -> str:
        base = self._settings.text_llm_base_url.rstrip("/")
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("TEXT_LLM not configured")
        prompt = str(request.get("prompt") or request.get("text") or "")
        task_id = f"text-{uuid4()}"
        self.calls.append(
            {"op": "create", "prompt_chars": len(prompt), "kind": request.get("kind")}
        )
        body = {
            "model": self._settings.text_llm_model,
            "max_tokens": int(request.get("max_tokens") or 512),
            "messages": [{"role": "user", "content": prompt}],
        }
        url = self._messages_url()
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
            try:
                data = resp.json()
            except Exception:
                data = {"raw_status": resp.status_code, "text": resp.text[:200]}
            if resp.status_code >= 400:
                err = f"text_llm http {resp.status_code}: {str(data)[:160]}"
                self._tasks[task_id] = {"status": "failed", "error": err, "text": ""}
                return {"remote_task_id": task_id, "status": "failed", "error": err}
            text_out = _extract_anthropic_text(data)
            self._tasks[task_id] = {
                "status": "succeeded",
                "text": text_out,
                "usage": data.get("usage") if isinstance(data, dict) else None,
            }
            return {
                "remote_task_id": task_id,
                "status": "succeeded",
                "text": text_out,
            }

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        task = self._tasks.get(remote_task_id)
        if task is None:
            return {"status": "failed", "error": "unknown task"}
        return {
            "status": task["status"],
            "progress": 1.0 if task["status"] == "succeeded" else 0.0,
            "text": task.get("text", ""),
            "error": task.get("error"),
        }

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        if remote_task_id in self._tasks:
            self._tasks[remote_task_id]["status"] = "cancelled"
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        task = self._tasks.get(remote_task_id) or {}
        raw_usage = task.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        in_tok = float(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        out_tok = float(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        return {
            "amount": 0.0,
            "currency": "USD",
            "units": in_tok + out_tok,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
        }


def _extract_anthropic_text(data: object) -> str:
    if not isinstance(data, dict):
        return str(data)[:2000]
    content = data.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        if parts:
            return "\n".join(parts)
    if isinstance(data.get("completion"), str):
        return str(data["completion"])
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        c0 = choices[0]
        if isinstance(c0, dict):
            msg = c0.get("message")
            if isinstance(msg, dict) and msg.get("content"):
                return str(msg["content"])
            if c0.get("text"):
                return str(c0["text"])
    return str(data)[:500]


def get_openai_adapter(*, allow_live: bool = False) -> Any:
    settings = get_settings()
    if settings.app_env == "test" and not allow_live:
        return FakeOpenAIAdapter()
    if settings.text_llm_configured():
        return AnthropicCompatibleTextAdapter(settings)
    return FakeOpenAIAdapter()


# Default export for tests that import OpenAIAdapter class name
OpenAIAdapter = FakeOpenAIAdapter
