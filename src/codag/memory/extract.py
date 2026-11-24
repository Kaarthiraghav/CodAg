"""Fact extraction from user messages only, with sensitive data filtering."""

import json
import re
from typing import Any

from codag.config import MainModelConfig
from codag.llm import LLMClient

# Deterministic pattern filter for sensitive data (Section 8.3)
SENSITIVE_PATTERNS = [
    re.compile(r"-----BEGIN[ A-Z0-9_-]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(api[_-]?key|secret|token|password|passwd|auth)\b", re.IGNORECASE),
    re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),  # Credit card numbers
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
    re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b"),  # API keys
    re.compile(r"\bghp_[a-zA-Z0-9]{30,}\b"),  # GitHub tokens
]


def is_sensitive(text: str) -> bool:
    """Check whether text contains sensitive credentials or confidential identifiers."""
    for pat in SENSITIVE_PATTERNS:
        if pat.search(text):
            return True
    return False


def extract_facts_from_user_message(
    user_message: str,
    llm: LLMClient | None = None,
    model: str = "qwen3.5:9b",
) -> list[dict[str, str]]:
    """Extract atomic facts strictly from user messages.
    
    Security invariant: This function must NEVER be called on tool outputs,
    web pages, or external file contents.
    """
    cleaned = user_message.strip()
    if not cleaned or len(cleaned) < 5 or is_sensitive(cleaned):
        return []

    # Fast heuristic check: only extract if user states personal preferences, facts, or habits
    fact_indicators = [
        "i prefer", "i use", "i like", "my name is", "i am", "i have",
        "i work with", "i always", "never use", "my project uses",
        "remember that", "note that", "keep in mind", "i live in",
    ]
    if not any(ind in cleaned.lower() for ind in fact_indicators):
        return []

    if llm is None:
        # Fallback simple extractor if no LLM provided
        return []

    prompt = f"""Extract permanent facts about the user from their message.
Discard greetings, temporary requests, questions, or sensitive info.

Message: "{cleaned}"

Output JSON array matching schema: [{{"key": "short_unique_key", "value": "atomic statement", "category": "preference|system|project|general"}}]
If no permanent facts exist, return []
"""
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
                "category": {"type": "string"},
            },
            "required": ["key", "value", "category"],
        },
    }

    try:
        res = llm.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            settings=MainModelConfig(temperature=0.0, num_ctx=2048),
            format_schema=schema,
        )
        data = json.loads(res.message.content)
        facts: list[dict[str, str]] = []
        for item in data:
            val = item.get("value", "")
            key = item.get("key", "")
            cat = item.get("category", "general")
            if val and key and not is_sensitive(val) and not is_sensitive(key):
                facts.append({"key": key.lower(), "value": val, "category": cat.lower()})
        return facts
    except Exception:
        return []
