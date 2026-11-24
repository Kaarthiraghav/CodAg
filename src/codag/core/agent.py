"""Agent turn pipeline implementing the core loop and safety gate."""

from collections.abc import Generator
import uuid
from typing import Any

from codag.config import CodagConfig
from codag.core.events import EventLogger
from codag.core.router import SkillRouter
from codag.core.types import AgentEvent, Decision, RiskTier, ToolCall, ToolResult, ToolSpec, TurnContext
from codag.llm import LLMClient
from codag.prompts import SYSTEM_PROMPT
from codag.safety.audit import AuditLogger
from codag.safety.confirm import ConfirmUX
from codag.safety.permissions import PermissionEngine
from codag.safety.sandbox import Sandbox
from codag.safety.snapshots import SnapshotManager
from codag.memory.store import MemoryStore
from codag.memory.profile import ProfileEngine
from codag.memory.vectors import ChromaVectorStore
from codag.memory.retrieve import configure_memory, format_memory_context, retrieve_relevant_facts
from codag.memory.extract import extract_facts_from_user_message
from codag.skills.files.tools import configure_file_tools
from codag.skills.notes.tools import configure_notes
from codag.skills.registry import SkillRegistry, default_registry
from codag.skills.shell.tools import configure_shell
from codag.skills.tasks.tools import configure_tasks
from codag.skills.web.tools import configure_web
from codag.skills.knowledge.tools import configure_knowledge
from codag.skills.code.tools import configure_code
from codag.skills.custom import configure_custom_skills
import codag.skills.system.tools
from codag.skills.scheduler.tools import configure_scheduler
from codag.core.chats import ChatManager


class Agent:
    def __init__(
        self,
        config: CodagConfig,
        llm: LLMClient | None = None,
        registry: SkillRegistry | None = None,
        confirm_ux: ConfirmUX | None = None,
        router: SkillRouter | None = None,
    ) -> None:
        self.config = config
        data_dir = config.paths.resolved_data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        self.logger = EventLogger(data_dir / "events.jsonl")
        self.audit = AuditLogger(data_dir)
        self.snapshots = SnapshotManager(data_dir)
        self.sandbox = Sandbox(config.policy)
        self.permissions = PermissionEngine(config.policy, self.sandbox)
        self.confirm_ux = confirm_ux or ConfirmUX()
        self.registry = registry or default_registry
        self.llm = llm or LLMClient(config.ollama, logger=self.logger)
        self.router = router or SkillRouter(self.llm, model=self.config.models.main)

        # Configure environment for all skills
        self.memory_store = MemoryStore(data_dir / "memory.db")
        self.profile_engine = ProfileEngine(data_dir / "memory.db")
        self.vector_store = ChromaVectorStore(
            data_dir / "vectors",
            embedding_model=self.config.models.embedding,
        )
        configure_memory(self.memory_store, self.vector_store)

        configure_file_tools(self.sandbox, self.snapshots)
        ws_root = self.sandbox.workspace_roots[0] if self.sandbox.workspace_roots else data_dir / "workspace"
        configure_shell(ws_root)
        configure_tasks(data_dir / "tasks.db")
        configure_notes(data_dir / "notes")
        configure_web(fetch_max_bytes=self.config.web.fetch_max_bytes)
        configure_knowledge(self.sandbox, self.vector_store)
        configure_code(
            sandbox=self.sandbox,
            audit=self.audit,
            snapshots=self.snapshots,
            llm=self.llm,
            coder_model=self.config.models.coder,
            main_model=self.config.models.main,
        )
        configure_scheduler(data_dir / "scheduler.db", data_dir / "tasks.db")
        configure_custom_skills(data_dir / "skills", registry=self.registry)
        self.chat_manager = ChatManager(data_dir / "chats.db")

    def _convert_specs_to_ollama_tools(self, specs: list[ToolSpec]) -> list[dict[str, Any]]:
        ollama_tools = []
        for s in specs:
            ollama_tools.append({
                "type": "function",
                "function": {
                    "name": s.name,
                    "description": s.description,
                    "parameters": s.parameters,
                },
            })
        return ollama_tools

    def run_turn(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
    ) -> Generator[str, None, None]:
        """Execute a full turn through the pipeline, yielding text chunks and status."""
        turn_id = f"turn-{uuid.uuid4().hex[:8]}"
        ctx = TurnContext(turn_id=turn_id, tainted=False)

        # 0. Session and Project Context resolution
        session = self.chat_manager.get_session(session_id) if session_id else None
        if session and history is None:
            history = self.chat_manager.get_messages(session.id, limit=20)
        if session:
            self.chat_manager.add_message(session.id, "user", user_message, turn_id=turn_id)
        if session and session.project_path:
            try:
                self.sandbox.add_workspace_root(session.project_path)
            except Exception:
                pass

        # 1. Route to select relevant skill (or none for plain conversation)
        selected_skill = self.router.route(user_message, settings=self.config.main)
        if selected_skill:
            specs = self.registry.get_specs_for_skill(selected_skill)[:8]
            tool_definitions = self._convert_specs_to_ollama_tools(specs)
        else:
            specs = []
            tool_definitions = []

        # 2. Retrieve background memory facts and build context
        relevant_facts = retrieve_relevant_facts(user_message, limit=5)
        memory_block = format_memory_context(relevant_facts)
        profile_block = self.profile_engine.format_profile_for_prompt()

        system_content = SYSTEM_PROMPT
        if session and session.project_path:
            system_content += f"\n\nActive Project Workspace: {session.project_path}\nAll relative file operations, builds, and code plans should target this project path.\n"
        if profile_block:
            system_content += f"\n\n{profile_block}\n"
        if memory_block:
            system_content += f"\n\n{memory_block}\n"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content}
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        max_model_calls = self.config.limits.max_model_calls_per_turn
        max_tool_calls = self.config.limits.max_tool_calls_per_turn

        while ctx.model_calls_count < max_model_calls and ctx.tool_calls_count < max_tool_calls:
            ctx.model_calls_count += 1
            response = self.llm.chat(
                model=self.config.models.main,
                messages=messages,
                settings=self.config.main,
                tools=tool_definitions if tool_definitions else None,
                turn_id=turn_id,
            )

            msg = response.message
            raw_tool_calls = getattr(msg, "tool_calls", None)

            # If no tool calls, emit final answer
            if not raw_tool_calls:
                content = msg.content or ""
                yield content
                messages.append({"role": "assistant", "content": content})
                break

            # Append assistant message with tool calls to context
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in raw_tool_calls
                ],
            })

            # Process each tool call through the permission engine
            for tc in raw_tool_calls:
                ctx.tool_calls_count += 1
                fn_name = tc.function.name
                fn_args = tc.function.arguments or {}
                call_id = getattr(tc, "id", None) or f"call_{uuid.uuid4().hex[:6]}"
                call = ToolCall(id=call_id, name=fn_name, arguments=fn_args)

                spec = self.registry.get_spec(fn_name)
                if not spec:
                    err_msg = f"Unknown tool: {fn_name}"
                    messages.append({"role": "tool", "content": err_msg, "name": fn_name})
                    continue

                decision = self.permissions.decide(call, spec, ctx)

                if decision.action == "deny":
                    self.audit.log_decision(
                        call=call,
                        decision=decision,
                        turn_id=turn_id,
                        ok=False,
                        result_summary=f"Denied: {decision.reason}",
                    )
                    messages.append({
                        "role": "tool",
                        "content": f"Permission denied: {decision.reason}",
                        "name": fn_name,
                    })
                    yield f"\n[Permission Denied for {fn_name}: {decision.reason}]\n"
                    continue

                user_approved = True
                if decision.action == "ask":
                    user_approved = self.confirm_ux.request_approval(
                        call=call,
                        reason=decision.reason,
                        tainted=ctx.tainted,
                    )
                    if not user_approved:
                        self.audit.log_decision(
                            call=call,
                            decision=decision,
                            turn_id=turn_id,
                            user_approved=False,
                            ok=False,
                            result_summary="Declined by user",
                        )
                        messages.append({
                            "role": "tool",
                            "content": "User declined to approve this action.",
                            "name": fn_name,
                        })
                        yield f"\n[Action cancelled by user for {fn_name}]\n"
                        continue

                # Execute tool
                yield f"\n[Executing {fn_name}...]\n"
                tool_def = self.registry.get_tool(fn_name)
                if not tool_def:
                    err_msg = f"Tool implementation not found for {fn_name}"
                    messages.append({"role": "tool", "content": err_msg, "name": fn_name})
                    continue

                result: ToolResult = tool_def(**fn_args)
                if result.untrusted:
                    ctx.tainted = True

                self.audit.log_decision(
                    call=call,
                    decision=decision,
                    turn_id=turn_id,
                    user_approved=user_approved if decision.action == "ask" else None,
                    ok=result.ok,
                    result_summary=result.content,
                    undo_token=result.undo_token,
                )

                messages.append({
                    "role": "tool",
                    "content": result.content,
                    "name": fn_name,
                })

        if ctx.model_calls_count >= max_model_calls or ctx.tool_calls_count >= max_tool_calls:
            yield "\n[Turn limits reached. Stopping tool loop.]\n"

        # 3. Post-turn: extract durable facts strictly from user_message
        final_content = ""
        for m in reversed(messages):
            if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                final_content = m["content"]
                break

        if not final_content and ctx.tool_calls_count > 0:
            try:
                summary_resp = self.llm.chat(
                    model=self.config.models.main,
                    messages=messages,
                    settings=self.config.main,
                    tools=None,
                    turn_id=turn_id,
                )
                final_content = summary_resp.message.content or ""
                if final_content:
                    yield AgentEvent(event_type="text_delta", turn_id=turn_id, payload={"text": final_content})
            except Exception:
                pass

        if not final_content and ctx.tool_calls_count > 0:
            try:
                summary_resp = self.llm.chat(
                    model=self.config.models.main,
                    messages=messages,
                    settings=self.config.main,
                    tools=None,
                    turn_id=turn_id,
                )
                final_content = summary_resp.message.content or ""
                if final_content:
                    yield final_content
            except Exception:
                pass

        if session and final_content:
            try:
                self.chat_manager.add_message(session.id, "assistant", final_content, turn_id=turn_id)
            except Exception:
                pass

        try:
            self.memory_store.add_episode(turn_id, user_message, final_content)

            extracted = extract_facts_from_user_message(
                user_message,
                llm=self.llm,
                model=self.config.models.main,
            )
            for fact in extracted:
                fid = self.memory_store.add_or_update_fact(
                    key=fact["key"],
                    value=fact["value"],
                    category=fact["category"],
                    source_turn=turn_id,
                )
                self.vector_store.upsert(
                    "facts",
                    f"fact_{fid}",
                    f"{fact['key']}: {fact['value']}",
                    metadata=fact,
                )
        except Exception:
            pass

    def run_turn_events(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
        confirmation_resolver: Any = None,
        speakable: bool = False,
        session_id: str | None = None,
    ) -> Generator[AgentEvent, None, None]:
        """Execute turn yielding AgentEvent stream (Section 12 / Web / Voice)."""
        turn_id = f"turn-{uuid.uuid4().hex[:8]}"
        ctx = TurnContext(turn_id=turn_id, tainted=False)

        # 0. Session and Project Context resolution
        session = self.chat_manager.get_session(session_id) if session_id else None
        if session and history is None:
            history = self.chat_manager.get_messages(session.id, limit=20)
        if session:
            try:
                self.chat_manager.add_message(session.id, "user", user_message, turn_id=turn_id)
            except Exception:
                pass
        if session and session.project_path:
            try:
                self.sandbox.add_workspace_root(session.project_path)
            except Exception:
                pass

        selected_skill = self.router.route(user_message, settings=self.config.main)
        if selected_skill:
            specs = self.registry.get_specs_for_skill(selected_skill)[:8]
            tool_definitions = self._convert_specs_to_ollama_tools(specs)
        else:
            specs = []
            tool_definitions = []

        relevant_facts = retrieve_relevant_facts(user_message, limit=5)
        memory_block = format_memory_context(relevant_facts)

        system_content = SYSTEM_PROMPT
        if session and session.project_path:
            system_content += f"\n\nActive Project Workspace: {session.project_path}\nAll relative file operations, builds, and code plans should target this project path.\n"
        if speakable:
            system_content += "\n\nNote: Speakable mode is active. Keep sentences concise, conversational, and direct. Do not include markdown code fences, tables, or ASCII art unless explicitly requested.\n"
        if memory_block:
            system_content += f"\n\n{memory_block}\n"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content}
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        max_model_calls = self.config.limits.max_model_calls_per_turn
        max_tool_calls = self.config.limits.max_tool_calls_per_turn

        while ctx.model_calls_count < max_model_calls and ctx.tool_calls_count < max_tool_calls:
            ctx.model_calls_count += 1
            response = self.llm.chat(
                model=self.config.models.main,
                messages=messages,
                settings=self.config.main,
                tools=tool_definitions if tool_definitions else None,
                turn_id=turn_id,
            )

            msg = response.message
            raw_tool_calls = getattr(msg, "tool_calls", None)

            if not raw_tool_calls:
                content = msg.content or ""
                yield AgentEvent(event_type="text_delta", turn_id=turn_id, payload={"text": content})
                messages.append({"role": "assistant", "content": content})
                break

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in raw_tool_calls
                ],
            })

            for tc in raw_tool_calls:
                ctx.tool_calls_count += 1
                fn_name = tc.function.name
                fn_args = tc.function.arguments or {}
                call_id = getattr(tc, "id", None) or f"call_{uuid.uuid4().hex[:6]}"
                call = ToolCall(id=call_id, name=fn_name, arguments=fn_args)

                spec = self.registry.get_spec(fn_name)
                if not spec:
                    err_msg = f"Unknown tool: {fn_name}"
                    yield AgentEvent(event_type="error", turn_id=turn_id, payload={"error": err_msg})
                    messages.append({"role": "tool", "content": err_msg, "name": fn_name})
                    continue

                decision = self.permissions.decide(call, spec, ctx)

                if decision.action == "deny":
                    self.audit.log_decision(
                        call=call,
                        decision=decision,
                        turn_id=turn_id,
                        ok=False,
                        result_summary=f"Denied: {decision.reason}",
                    )
                    err_text = f"Permission denied: {decision.reason}"
                    yield AgentEvent(event_type="error", turn_id=turn_id, payload={"error": err_text})
                    messages.append({
                        "role": "tool",
                        "content": err_text,
                        "name": fn_name,
                    })
                    continue

                user_approved = True
                if decision.action == "ask":
                    approval_id = f"appr_{uuid.uuid4().hex[:6]}"
                    yield AgentEvent(
                        event_type="confirmation_requested",
                        turn_id=turn_id,
                        payload={
                            "approval_id": approval_id,
                            "tool": fn_name,
                            "arguments": fn_args,
                            "reason": decision.reason,
                            "tainted": ctx.tainted,
                        },
                    )

                    if confirmation_resolver:
                        user_approved = confirmation_resolver(approval_id, call, decision.reason)
                    else:
                        user_approved = self.confirm_ux.request_approval(
                            call=call,
                            reason=decision.reason,
                            tainted=ctx.tainted,
                        )

                    yield AgentEvent(
                        event_type="confirmation_resolved",
                        turn_id=turn_id,
                        payload={"approval_id": approval_id, "approved": user_approved},
                    )

                    if not user_approved:
                        self.audit.log_decision(
                            call=call,
                            decision=decision,
                            turn_id=turn_id,
                            user_approved=False,
                            ok=False,
                            result_summary="Declined by user",
                        )
                        messages.append({
                            "role": "tool",
                            "content": "User declined to approve this action.",
                            "name": fn_name,
                        })
                        continue

                yield AgentEvent(
                    event_type="tool_started",
                    turn_id=turn_id,
                    payload={"tool": fn_name, "arguments": fn_args},
                )
                tool_def = self.registry.get_tool(fn_name)
                if not tool_def:
                    err_msg = f"Tool implementation not found for {fn_name}"
                    yield AgentEvent(event_type="error", turn_id=turn_id, payload={"error": err_msg})
                    messages.append({"role": "tool", "content": err_msg, "name": fn_name})
                    continue

                result: ToolResult = tool_def(**fn_args)
                if result.untrusted:
                    ctx.tainted = True

                self.audit.log_decision(
                    call=call,
                    decision=decision,
                    turn_id=turn_id,
                    user_approved=user_approved if decision.action == "ask" else None,
                    ok=result.ok,
                    result_summary=result.content,
                    undo_token=result.undo_token,
                )

                yield AgentEvent(
                    event_type="tool_finished",
                    turn_id=turn_id,
                    payload={"tool": fn_name, "ok": result.ok, "content": result.content},
                )

                messages.append({
                    "role": "tool",
                    "content": result.content,
                    "name": fn_name,
                })

        final_content = ""
        for m in reversed(messages):
            if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                final_content = m["content"]
                break

        if not final_content and ctx.tool_calls_count > 0:
            try:
                summary_resp = self.llm.chat(
                    model=self.config.models.main,
                    messages=messages,
                    settings=self.config.main,
                    tools=None,
                    turn_id=turn_id,
                )
                final_content = summary_resp.message.content or ""
                if final_content:
                    yield AgentEvent(event_type="text_delta", turn_id=turn_id, payload={"text": final_content})
            except Exception:
                pass

        try:
            self.memory_store.add_episode(turn_id, user_message, final_content)
            extracted = extract_facts_from_user_message(
                user_message,
                llm=self.llm,
                model=self.config.models.main,
            )
            for fact in extracted:
                fid = self.memory_store.add_or_update_fact(
                    key=fact["key"],
                    value=fact["value"],
                    category=fact["category"],
                    source_turn=turn_id,
                )
                self.vector_store.upsert(
                    "facts",
                    f"fact_{fid}",
                    f"{fact['key']}: {fact['value']}",
                    metadata=fact,
                )
            # Implicit interaction reflection (Hermes-style user profiling)
            tool_names = [call.tool for call in ctx.tool_calls]
            self.profile_engine.reflect_on_interaction(
                turn_id=turn_id,
                user_message=user_message,
                assistant_message=final_content,
                tools_used=tool_names,
                llm=self.llm,
                model=self.config.models.main,
            )
        except Exception:
            pass

        if session and final_content:
            try:
                self.chat_manager.add_message(session.id, "assistant", final_content, turn_id=turn_id)
            except Exception:
                pass

        yield AgentEvent(
            event_type="turn_finished",
            turn_id=turn_id,
            payload={"content": final_content, "session_id": session_id},
        )
