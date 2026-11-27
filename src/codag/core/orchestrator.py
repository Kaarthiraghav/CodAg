"""Multi-model orchestrator managing local Ollama and cloud Gemini (google-genai)."""

from collections.abc import Generator
from typing import Any

from codag.config import CodagConfig, MainModelConfig
from codag.core.events import EventLogger
from codag.llm import GeminiClient, LLMClient


class ModelOrchestrator:
    """Routes LLM calls between local Ollama and cloud Gemini with automatic fallback.

    Exposes the same `.chat(...)` and `.stream_chat(...)` interface as `LLMClient`
    so `Agent`, `SkillRouter`, `ProfileEngine`, and `code` work seamlessly.
    """

    VALID_MODES = ("auto", "local", "gemini")

    def __init__(
        self,
        config: CodagConfig,
        ollama_client: LLMClient | None = None,
        gemini_client: GeminiClient | None = None,
        logger: EventLogger | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.ollama = ollama_client or LLMClient(config.ollama, logger=logger)
        self.gemini = gemini_client or GeminiClient(config.gemini, logger=logger)
        self.mode = (
            config.orchestrator.mode
            if config.orchestrator.mode in self.VALID_MODES
            else "auto"
        )

    def set_mode(self, mode: str) -> str:
        clean = mode.strip().lower()
        if clean not in self.VALID_MODES:
            raise ValueError(f"Invalid orchestrator mode {mode!r}. Choose from: {', '.join(self.VALID_MODES)}")
        self.mode = clean
        return self.mode

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "local_model": self.config.models.main,
            "gemini_model": self.config.gemini.model,
            "gemini_available": self.gemini.is_available,
            "complex_skills": self.config.orchestrator.complex_skills,
        }

    def select_backend(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        skill_name: str | None = None,
        format_schema: dict[str, Any] | None = None,
        requested_model: str | None = None,
    ) -> tuple[str, str]:
        """Choose ('ollama'|'gemini', model_name) for the current call."""
        local_model = requested_model or self.config.models.main
        gemini_model = self.config.gemini.model

        if self.mode == "local" or not self.gemini.is_available:
            return "ollama", local_model

        if self.mode == "gemini":
            return "gemini", gemini_model

        # Auto mode:
        # 1. If a complex skill is active (code, web, custom_skills), use Gemini
        if skill_name and skill_name in self.config.orchestrator.complex_skills:
            return "gemini", gemini_model

        # 2. If tool definitions are attached for a complex tool-calling turn, check skill prefix
        if tools:
            tool_skills = {
                t.get("function", {}).get("name", "").split(".")[0]
                for t in tools
            }
            if tool_skills & set(self.config.orchestrator.complex_skills):
                return "gemini", gemini_model

        # 3. Context overflow guard: escalate large prompts to Gemini's large context
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        if total_chars > self.config.orchestrator.context_overflow_chars:
            return "gemini", gemini_model

        # 4. Default to fast, private local Ollama for simple chat, router, memory, and local tasks
        return "ollama", local_model

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        settings: MainModelConfig,
        tools: list[dict[str, Any]] | None = None,
        format_schema: dict[str, Any] | None = None,
        turn_id: str | None = None,
        skill_name: str | None = None,
    ) -> Any:
        provider, target_model = self.select_backend(
            messages=messages,
            tools=tools,
            skill_name=skill_name,
            format_schema=format_schema,
            requested_model=model,
        )

        if self.logger:
            self.logger.log(
                "orchestrator_route",
                turn_id=turn_id,
                mode=self.mode,
                provider=provider,
                model=target_model,
                skill=skill_name,
            )

        if provider == "gemini":
            try:
                return self.gemini.chat(
                    model=target_model,
                    messages=messages,
                    settings=settings,
                    tools=tools,
                    format_schema=format_schema,
                    turn_id=turn_id,
                )
            except Exception as exc:
                if self.logger:
                    self.logger.log(
                        "orchestrator_fallback",
                        turn_id=turn_id,
                        from_provider="gemini",
                        to_provider="ollama",
                        reason=str(exc),
                    )
                return self.ollama.chat(
                    model=model or self.config.models.main,
                    messages=messages,
                    settings=settings,
                    tools=tools,
                    format_schema=format_schema,
                    turn_id=turn_id,
                )

        return self.ollama.chat(
            model=target_model,
            messages=messages,
            settings=settings,
            tools=tools,
            format_schema=format_schema,
            turn_id=turn_id,
        )

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        settings: MainModelConfig,
        turn_id: str | None = None,
        skill_name: str | None = None,
    ) -> Generator[str, None, None]:
        provider, target_model = self.select_backend(
            messages=messages,
            skill_name=skill_name,
            requested_model=model,
        )
        if provider == "gemini":
            try:
                yield from self.gemini.stream_chat(
                    model=target_model,
                    messages=messages,
                    settings=settings,
                    turn_id=turn_id,
                )
                return
            except Exception:
                pass
        yield from self.ollama.stream_chat(
            model=model or self.config.models.main,
            messages=messages,
            settings=settings,
            turn_id=turn_id,
        )
