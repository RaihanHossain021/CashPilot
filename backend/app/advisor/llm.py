"""Thin Gemini function-calling and structured-output wrapper (Phase 7)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from google import genai
from google.genai import types

from app.config import settings


@dataclass(frozen=True)
class ToolCallRequest:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolStepResult:
    tool_calls: list[ToolCallRequest]
    text: str | None
    raw_content: Any
    token_usage: dict[str, int]


@dataclass(frozen=True)
class StructuredAnswerResult:
    payload: dict[str, Any]
    token_usage: dict[str, int]


class AdvisorLLM(Protocol):
    """Injectable LLM interface for production Gemini and deterministic tests."""

    model_name: str

    def step_with_tools(
        self,
        contents: list[Any],
        system_instruction: str,
        tool_declarations: list[dict[str, Any]],
        timeout_seconds: float,
    ) -> ToolStepResult: ...

    def generate_structured_json(
        self,
        contents: list[Any],
        system_instruction: str,
        response_schema: dict[str, Any],
        timeout_seconds: float,
    ) -> StructuredAnswerResult: ...


def has_configured_gemini_key() -> bool:
    key = settings.gemini_api_key.strip()
    return bool(key) and key.lower() not in {"your-key", "change-me", "none"}


def _extract_usage(response: Any) -> dict[str, int]:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return {}
    usage: dict[str, int] = {}
    for field in ("prompt_token_count", "candidates_token_count", "total_token_count"):
        val = getattr(meta, field, None)
        if isinstance(val, int):
            usage[field] = val
    return usage


class GeminiAdvisorLLM:
    """Google GenAI SDK wrapper with automatic function calling disabled."""

    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        self.api_key = (api_key or settings.gemini_api_key).strip()
        self.model_name = (model_name or settings.gemini_model).strip()
        self._client = genai.Client(api_key=self.api_key)

    def step_with_tools(
        self,
        contents: list[Any],
        system_instruction: str,
        tool_declarations: list[dict[str, Any]],
        timeout_seconds: float,
    ) -> ToolStepResult:
        declarations = [
            types.FunctionDeclaration(
                name=td["name"],
                description=td["description"],
                parameters_json_schema=td["parameters"],
            )
            for td in tool_declarations
        ]
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.1,
            http_options=types.HttpOptions(timeout=max(1000, int(timeout_seconds * 1000))),
        )
        response = self._client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config,
        )

        calls: list[ToolCallRequest] = []
        raw_content = None
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            raw_content = getattr(candidates[0], "content", None)
            parts = getattr(raw_content, "parts", None) or []
            for part in parts:
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    calls.append(
                        ToolCallRequest(
                            name=str(fc.name),
                            args=dict(fc.args or {}),
                        )
                    )

        text = getattr(response, "text", None) if not calls else None
        return ToolStepResult(
            tool_calls=calls,
            text=text,
            raw_content=raw_content,
            token_usage=_extract_usage(response),
        )

    def generate_structured_json(
        self,
        contents: list[Any],
        system_instruction: str,
        response_schema: dict[str, Any],
        timeout_seconds: float,
    ) -> StructuredAnswerResult:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_json_schema=response_schema,
            temperature=0.1,
            http_options=types.HttpOptions(timeout=max(1000, int(timeout_seconds * 1000))),
        )
        response = self._client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config,
        )
        raw_text = (getattr(response, "text", None) or "").strip()
        parsed = json.loads(raw_text)
        if not isinstance(parsed, dict):
            raise ValueError("Structured advisor response must be a JSON object")
        return StructuredAnswerResult(payload=parsed, token_usage=_extract_usage(response))
