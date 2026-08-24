"""Small client for project-local Qwen GGUF served by llama.cpp."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class LocalModelUnavailable(RuntimeError):
    pass


class LocalQwenClient:
    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.base_url = (base_url or os.getenv(
            "FINCTRL_MODEL_URL", "http://127.0.0.1:8001/v1"
        )).rstrip("/")
        self.model = model or os.getenv("FINCTRL_MODEL", "qwen3.5-4b-q4_k_m")
        self.timeout = float(os.getenv("FINCTRL_MODEL_TIMEOUT", "90"))
        # Local inference must never be routed through a corporate/system HTTP
        # proxy. Besides leaking prompts, proxy lookup can turn a missing local
        # server into a long hang instead of a fast, safe fallback.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"model": self.model, **payload}).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise LocalModelUnavailable(str(exc)) from exc

    def choose_tool(self, question: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
        response = self._complete({
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
            "chat_template_kwargs": {"enable_thinking": False},
            "temperature": 0,
            "max_tokens": 128,
        })
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
        response = self._complete({
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
            "chat_template_kwargs": {"enable_thinking": False},
            "temperature": 0,
            "max_tokens": 400,
        })
        try:
            return response["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, AttributeError) as exc:
            raise LocalModelUnavailable("model returned no grounded answer") from exc
