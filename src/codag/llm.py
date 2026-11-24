"""Ollama client wrapper supporting plain, streaming, tool-calling, and structured chat."""

from collections.abc import Generator
import time
from typing import Any
import ollama

from codag.config import MainModelConfig, OllamaConfig
from codag.core.events import EventLogger


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
