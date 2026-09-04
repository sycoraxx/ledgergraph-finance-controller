"""Provider-neutral, read-only language-model client.

The language model is optional. It can explain evidence produced by the
deterministic controller, but it cannot calculate money, select a match,
approve a journal, or post an entry.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class LocalModelUnavailable(RuntimeError):
    """Kept for compatibility; raised for any unavailable explanation model."""


PROVIDER_DEFAULTS = {
    "local": ("http://127.0.0.1:8001/v1", "qwen3.5-4b-q4_k_m"),
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-20b"),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-2.5-flash-lite",
    ),
}


class ExplanationModelClient:
    """Minimal OpenAI-compatible client for optional evidence explanations."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
    ):
        configured_provider = provider or os.getenv("FINCTRL_MODEL_PROVIDER")
        if not configured_provider:
            configured_provider = (
                "local" if base_url or os.getenv("FINCTRL_MODEL_URL") else "none"
            )
        self.provider = configured_provider.strip().lower()
        if self.provider not in {*PROVIDER_DEFAULTS, "openai_compatible", "none"}:
            raise ValueError(
                "FINCTRL_MODEL_PROVIDER must be local, groq, gemini, "
                "openai_compatible, or none"
            )

        default_url, default_model = PROVIDER_DEFAULTS.get(self.provider, ("", ""))
        self.base_url = (base_url or os.getenv("FINCTRL_MODEL_URL") or default_url).rstrip("/")
        self.model = model or os.getenv("FINCTRL_MODEL") or default_model
        self.timeout = float(os.getenv("FINCTRL_MODEL_TIMEOUT", "90"))
        provider_key_name = {
            "groq": "GROQ_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }.get(self.provider)
        self.api_key = (
            api_key
            or os.getenv("FINCTRL_MODEL_API_KEY")
            or (os.getenv(provider_key_name) if provider_key_name else None)
            or ""
        )

        # Local inference must not be sent through a corporate/system proxy.
        # Hosted providers intentionally use the system proxy configuration.
        self.opener = (
            urllib.request.build_opener(urllib.request.ProxyHandler({}))
            if self.provider == "local"
            else urllib.request.build_opener()
        )

    @property
    def label(self) -> str:
        labels = {
            "local": "Local Qwen · project-hosted",
            "groq": "Hosted AI · Groq",
            "gemini": "Hosted AI · Gemini",
            "openai_compatible": "Hosted AI · OpenAI-compatible",
            "none": "Deterministic evidence renderer",
        }
        return labels[self.provider]

    def health_status(self, timeout: float = 0.75) -> dict[str, Any]:
        """Return a truthful readiness status without calling hosted models."""
        common = {
            "provider": self.provider,
            "label": self.label,
            "endpoint": self.base_url or None,
            "model": self.model or None,
        }
        if self.provider == "none":
            return {**common, "available": False, "status": "disabled"}
        if not self.base_url or not self.model:
            return {**common, "available": False, "status": "incomplete_configuration"}
        if self.provider != "local":
            return {
                **common,
                "available": bool(self.api_key),
                "status": "configured" if self.api_key else "missing_api_key",
            }

        server_url = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        request = urllib.request.Request(server_url + "/health", method="GET")
        try:
            with self.opener.open(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            status = str(payload.get("status", "unknown"))
            return {
                **common,
                "available": status in {"ok", "no slot available"},
                "status": status,
                "endpoint": server_url,
            }
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return {
                **common,
                "available": False,
                "status": "unavailable",
                "endpoint": server_url,
                "detail": str(exc),
            }

    def _complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        status = self.health_status()
        if not status["available"]:
            raise LocalModelUnavailable(f"explanation model is {status['status']}")
        body = json.dumps({"model": self.model, **payload}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.provider == "local":
            headers["Authorization"] = "Bearer local"
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise LocalModelUnavailable(str(exc)) from exc

    def choose_tool(self, question: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a read-only settlement question router. Select exactly one "
                        "available tool. Never calculate money, invent identifiers, request a "
                        "write, or answer from memory."
                    ),
                },
                {"role": "user", "content": question},
            ],
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": 128,
        }
        if self.provider == "local":
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        response = self._complete(payload)
        try:
            message = response["choices"][0]["message"]
            call = message["tool_calls"][0]["function"]
            arguments = call.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            return {"name": call["name"], "arguments": arguments}
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LocalModelUnavailable("model returned no parseable tool call") from exc

    def grounded_answer(self, question: str, evidence: dict[str, Any]) -> str:
        payload: dict[str, Any] = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer only from the supplied evidence. Preserve all monetary values "
                        "exactly. Every monetary value is INR: use INR or the ₹ symbol and never "
                        "a dollar sign. Do not perform new arithmetic. Cite the supplied citations. "
                        "If the evidence is insufficient, say so."
                    ),
                },
                {
                    "role": "user",
                    "content": question + "\n\nEVIDENCE_JSON:\n" + json.dumps(evidence),
                },
            ],
            "temperature": 0,
            "max_tokens": 400,
        }
        if self.provider == "local":
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        response = self._complete(payload)
        try:
            return response["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, AttributeError) as exc:
            raise LocalModelUnavailable("model returned no grounded answer") from exc


# Preserve the old public name for existing integrations and tests.
LocalQwenClient = ExplanationModelClient
