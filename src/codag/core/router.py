"""Two-stage skill router: fast keyword path and model fallback with structured output."""

import re
from typing import Any
from pydantic import BaseModel, Field

from codag.config import MainModelConfig
from codag.llm import LLMClient
from codag.skills.base import SkillManifest, load_manifest


class RouterDecision(BaseModel):
    skill: str | None = Field(description="Name of the selected skill or None for plain conversation")
    confidence: float = Field(default=1.0, description="Confidence score between 0.0 and 1.0")


SKILL_DESCRIPTIONS: dict[str, str] = {
    "files": "Work with files and directories (list, read, search, create, edit, move, delete).",
    "shell": "Execute shell commands or CLI developer tools in the workspace.",
    "tasks": "Manage personal to-do tasks and checklists.",
    "notes": "Create, append to, and search markdown notes.",
    "memory": "Remember, recall, or forget personal facts and preferences.",
    "web": "Search the internet or fetch text from web pages.",
    "knowledge": "Index local folders of documents and ask questions with passage citations.",
    "code": "Plan and build software projects with test-first architecture and git-per-task commits.",
    "system": "Perform macOS actions (notifications, clipboard, open app, quit app, system settings).",
    "scheduler": "Schedule reminders and daily briefings delivered as macOS notifications.",
    "custom_skills": "Create, list, inspect, and synthesize new custom tools and skills autonomously.",
}

KEYWORD_PATTERNS: dict[str, list[str]] = {
    "custom_skills": [
        "custom skill", "custom skills", "create skill", "learn skill", "new skill",
        "synthesize tool", "add skill", "list skills", "my skills",
    ],
    "files": [
        "file", "files", "folder", "folders", "directory", "directories",
        "create file", "read file", "edit file", "delete file", "move file",
        "rename file", "search files", "list files", "mkdir", "save to",
        "create", "rename", "delete", "edit", ".md", ".txt", ".json", ".py",
        "pdf", "create pdf", "give me pdf", "export pdf", "save as pdf", "generate pdf",
    ],
    "shell": [
        "run command", "run the command", "terminal", "shell", "bash", "execute", "cli",
        "git status", "git diff", "git log", "git commit", "pytest", "ruff", "ruff check",
        "python script", "npm test", "cargo check", "pwd",
    ],
    "tasks": [
        "task", "tasks", "todo", "todos", "to-do", "checklist",
        "remind me to", "add task", "complete task", "list tasks", "my tasks",
    ],
    "notes": [
        "note", "notes", "memo", "jot", "jot down", "take a note", "make a note",
        "create note", "create a note", "write down", "search notes", "list notes", "my notes",
    ],
    "memory": [
        "remember", "recall", "forget", "my preferences", "what do you know about me",
        "memorize", "save fact", "delete fact", "list facts",
    ],
    "web": [
        "search web", "google", "duckduckgo", "look up online", "browse",
        "website", "url", "web page", "fetch page", "online", "internet",
        "latest news", "latest information", "what is the latest", "find online",
        "research", "fact check", "verify", "cross check", "cross-check",
        "sources", "citations", "scrape", "download pdf", "download file",
        "download", "download papers", "arxiv",
    ],
    "knowledge": [
        "document", "documents", "pdf", "index folder", "ask documents",
        "search documents", "read folder", "knowledge base", "my docs", "paper",
    ],
    "code": [
        "write code", "source code", "coding", "code project", "code app", "codebase",
        "build project", "create project", "plan project", "build a", "build an app",
        "todo app", "cli app", "software project", "develop app", "implement project",
    ],
    "system": [
        "notify", "notification", "desktop notification", "clipboard", "pbcopy", "pbpaste",
        "open app", "launch app", "quit app", "close app", "system setting", "dark mode",
        "osascript", "system volume",
    ],
    "scheduler": [
        "schedule reminder", "create reminder", "list reminders", "cancel reminder",
        "daily briefing", "morning briefing", "remind me in", "remind me at",
        "scheduled reminders", "set alarm", "briefing",
    ],
}


class SkillRouter:
    def __init__(self, llm: LLMClient | None = None, model: str = "qwen3.5:9b") -> None:
        self.llm = llm
        self.model = model
        self.dynamic_skills: dict[str, list[str]] = {}

    def register_dynamic_skill(self, name: str, description: str, keywords: list[str]) -> None:
        """Register a dynamic user-created skill into the router."""
        SKILL_DESCRIPTIONS[name] = description
        self.dynamic_skills[name] = keywords
        KEYWORD_PATTERNS[name] = keywords

    def route_fast_path(self, text: str) -> str | None:
        """Fast keyword/pattern matching without model invocation."""
        cleaned = text.lower().strip()
        scores: dict[str, int] = {skill: 0 for skill in KEYWORD_PATTERNS}

        for skill, patterns in KEYWORD_PATTERNS.items():
            for pat in patterns:
                # Check exact phrase or word boundary match
                if " " in pat:
                    if pat in cleaned:
                        scores[skill] += 3
                else:
                    if re.search(r"\b" + re.escape(pat) + r"\b", cleaned):
                        scores[skill] += 1

        best_skill = None
        max_score = 0
        tie = False

        for skill, score in scores.items():
            if score > max_score:
                max_score = score
                best_skill = skill
                tie = False
            elif score == max_score and score > 0:
                tie = True

        if max_score >= 1 and not tie:
            return best_skill
        return None

    def route(self, text: str, settings: MainModelConfig | None = None) -> str | None:
        """Two-stage route: fast-path first, model fallback for ambiguous cases."""
        fast = self.route_fast_path(text)
        if fast is not None:
            return fast

        # If plain greetings / generic conversation, return None immediately
        greetings = {"hi", "hello", "hey", "how are you", "who are you", "what can you do", "thanks", "thank you"}
        if text.lower().strip() in greetings or len(text.strip().split()) <= 2:
            return None

        # Model fallback
        if not self.llm:
            return None

        prompt = f"""You are the skill router for CodAg. Select which skill handles this request, or 'none' if it is plain conversation without tools.

Skills:
- files: {SKILL_DESCRIPTIONS['files']}
- shell: {SKILL_DESCRIPTIONS['shell']}
- tasks: {SKILL_DESCRIPTIONS['tasks']}
- notes: {SKILL_DESCRIPTIONS['notes']}
- none: General chit-chat, greetings, or questions requiring no tool.

Request: {text}

Respond in JSON only with schema: {{"skill": "files"|"shell"|"tasks"|"notes"|"none", "confidence": 0.0 to 1.0}}
"""
        try:
            schema = {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "enum": ["files", "shell", "tasks", "notes", "none"]},
                    "confidence": {"type": "number"},
                },
                "required": ["skill", "confidence"],
            }
            chat_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "settings": settings or MainModelConfig(temperature=0.0, num_ctx=2048),
                "format_schema": schema,
            }
            if hasattr(self.llm, "select_backend"):
                chat_kwargs["skill_name"] = "router"
            res = self.llm.chat(**chat_kwargs)
            import json
            data = json.loads(res.message.content)
            selected = data.get("skill", "none")
            conf = float(data.get("confidence", 0.0))
            if conf >= 0.6 and selected in SKILL_DESCRIPTIONS:
                return selected
        except Exception:
            pass

        return None
