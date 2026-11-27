"""LLM client wrappers for local Ollama and cloud Gemini (google-genai)."""

from collections.abc import Generator
from dataclasses import dataclass, field
import json
import os
import time
from typing import Any
import ollama

from codag.config import GeminiConfig, MainModelConfig, OllamaConfig
from codag.core.events import EventLogger


@dataclass
class _NormalizedFunction:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class _NormalizedToolCall:
    function: _NormalizedFunction

    def model_dump(self) -> dict[str, Any]:
        return {"function": {"name": self.function.name, "arguments": self.function.arguments}}


@dataclass
class _NormalizedMessage:
    content: str = ""
    tool_calls: list[_NormalizedToolCall] | None = None


@dataclass
class _NormalizedResponse:
    message: _NormalizedMessage
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    provider: str = "ollama"


class LLMClient:
    def __init__(
        self,
        ollama_cfg: OllamaConfig,
        logger: EventLogger | None = None,
        client: ollama.Client | None = None,
    ) -> None:
        self.host = ollama_cfg.host
        self.keep_alive = ollama_cfg.keep_alive
        self.logger = logger
        self._client = client or ollama.Client(host=self.host)

    def _prepare_call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        settings: MainModelConfig,
        tools: list[dict[str, Any]] | None = None,
        format_schema: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": settings.temperature,
            "num_ctx": settings.num_ctx,
        }
        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "options": options,
            "keep_alive": self.keep_alive,
            "stream": stream,
        }
        if tools:
            call_kwargs["tools"] = tools
        if format_schema is not None:
            call_kwargs["format"] = format_schema
        if settings.think is not None:
            call_kwargs["think"] = settings.think
        return call_kwargs

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        settings: MainModelConfig,
        tools: list[dict[str, Any]] | None = None,
        format_schema: dict[str, Any] | None = None,
        turn_id: str | None = None,
    ) -> Any:
        call_kwargs = self._prepare_call(
            model=model,
            messages=messages,
            settings=settings,
            tools=tools,
            format_schema=format_schema,
            stream=False,
        )
        start_time = time.perf_counter()
        response = self._client.chat(**call_kwargs)
        duration_s = time.perf_counter() - start_time

        content = response.message.content or ""
        tool_calls = getattr(response.message, "tool_calls", None)
        prompt_tokens = getattr(response, "prompt_eval_count", None)
        completion_tokens = getattr(response, "eval_count", None)

        # Context window warning: log warning when prompt tokens exceed 85% of num_ctx
        if prompt_tokens and prompt_tokens > 0.85 * settings.num_ctx:
            if self.logger:
                self.logger.log(
                    "context_warning",
                    turn_id=turn_id,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    num_ctx=settings.num_ctx,
                    message=f"Prompt size ({prompt_tokens} tokens) exceeds 85% of num_ctx ({settings.num_ctx}). Risk of silent context truncation.",
                )

        if self.logger:
            self.logger.log(
                "model_call",
                turn_id=turn_id,
                model=model,
                prompt=messages[-1].get("content", "") if messages else "",
                response=content,
                tool_calls=[tc.model_dump() if hasattr(tc, "model_dump") else str(tc) for tc in (tool_calls or [])],
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_s=round(duration_s, 3),
            )

        return response

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        settings: MainModelConfig,
        turn_id: str | None = None,
    ) -> Generator[str, None, None]:
        call_kwargs = self._prepare_call(
            model=model,
            messages=messages,
            settings=settings,
            stream=True,
        )
        start_time = time.perf_counter()
        full_content: list[str] = []

        response_chunks = self._client.chat(**call_kwargs)
        for chunk in response_chunks:
            delta = chunk.message.content or ""
            if delta:
                full_content.append(delta)
                yield delta

        duration_s = time.perf_counter() - start_time
        if self.logger:
            self.logger.log(
                "model_call",
                turn_id=turn_id,
                model=model,
                prompt=messages[-1].get("content", "") if messages else "",
                response="".join(full_content),
                latency_s=round(duration_s, 3),
            )


class GeminiClient:
    """Wrapper around Google's google-genai SDK producing Ollama-compatible responses."""

    def __init__(
        self,
        gemini_cfg: GeminiConfig,
        logger: EventLogger | None = None,
        api_key: str | None = None,
        client: Any = None,
    ) -> None:
        self.cfg = gemini_cfg
        self.logger = logger
        self._api_key = api_key or os.environ.get(gemini_cfg.api_key_env, "")
        self._client = client

    @property
    def is_available(self) -> bool:
        return bool(self.cfg.enabled and (self._client is not None or self._api_key))

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    f"Gemini API key not found in environment variable {self.cfg.api_key_env}."
                )
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert OpenAI/Ollama-style chat messages to Gemini system_instruction + contents."""
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            text = msg.get("content") or ""
            if role == "system":
                if text:
                    system_parts.append(text)
            elif role == "assistant":
                parts: list[dict[str, Any]] = []
                if text:
                    parts.append({"text": text})
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                    if fn.get("name"):
                        parts.append({"function_call": {"name": fn["name"], "args": fn.get("arguments") or {}}})
                if parts:
                    contents.append({"role": "model", "parts": parts})
            elif role == "tool":
                fn_name = msg.get("name") or "tool"
                contents.append({
                    "role": "user",
                    "parts": [{"function_response": {"name": fn_name, "response": {"result": text}}}],
                })
            else:
                contents.append({"role": "user", "parts": [{"text": text}]})

        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return system_instruction, contents

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]] | None) -> list[Any] | None:
        if not tools:
            return None
        from google.genai import types

        decls = []
        for t in tools:
            fn = t.get("function", {})
            decls.append(
                types.FunctionDeclaration(
                    name=fn["name"],
                    description=fn.get("description", ""),
                    parameters_json_schema=fn.get("parameters"),
                )
            )
        return [types.Tool(function_declarations=decls)]

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        settings: MainModelConfig,
        tools: list[dict[str, Any]] | None = None,
        format_schema: dict[str, Any] | None = None,
        turn_id: str | None = None,
    ) -> _NormalizedResponse:
        from google.genai import types

        client = self._get_client()
        target_model = model or self.cfg.model
        system_instruction, contents = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)

        config_kwargs: dict[str, Any] = {
            "temperature": settings.temperature,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if gemini_tools:
            config_kwargs["tools"] = gemini_tools
        if format_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = format_schema

        gen_config = types.GenerateContentConfig(**config_kwargs)

        start_time = time.perf_counter()
        raw_resp = client.models.generate_content(
            model=target_model,
            contents=contents,
            config=gen_config,
        )
        duration_s = time.perf_counter() - start_time

        text_parts: list[str] = []
        parsed_calls: list[_NormalizedToolCall] = []

        candidates = getattr(raw_resp, "candidates", None) or []
        if candidates and getattr(candidates[0], "content", None):
            for part in getattr(candidates[0].content, "parts", None) or []:
                p_text = getattr(part, "text", None)
                if p_text:
                    text_parts.append(p_text)
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", None):
                    args = getattr(fc, "args", None) or {}
                    if not isinstance(args, dict):
                        try:
                            args = dict(args)
                        except Exception:
                            args = {}
                    parsed_calls.append(
                        _NormalizedToolCall(function=_NormalizedFunction(name=fc.name, arguments=args))
                    )

        content = "".join(text_parts)
        if not content and getattr(raw_resp, "text", None) and not parsed_calls:
            content = raw_resp.text

        usage = getattr(raw_resp, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", None) if usage else None
        completion_tokens = getattr(usage, "candidates_token_count", None) if usage else None

        if self.logger:
            self.logger.log(
                "model_call",
                turn_id=turn_id,
                provider="gemini",
                model=target_model,
                prompt=messages[-1].get("content", "") if messages else "",
                response=content,
                tool_calls=[tc.model_dump() for tc in parsed_calls],
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_s=round(duration_s, 3),
            )

        return _NormalizedResponse(
            message=_NormalizedMessage(
                content=content,
                tool_calls=parsed_calls or None,
            ),
            prompt_eval_count=prompt_tokens,
            eval_count=completion_tokens,
            provider="gemini",
        )

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        settings: MainModelConfig,
        turn_id: str | None = None,
    ) -> Generator[str, None, None]:
        resp = self.chat(model=model, messages=messages, settings=settings, turn_id=turn_id)
        if resp.message.content:
            yield resp.message.content
