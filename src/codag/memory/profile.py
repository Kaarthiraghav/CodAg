"""User profile synthesis, habit mining, and implicit reflection engine."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from codag.config import MainModelConfig
from codag.llm import LLMClient
from codag.memory.extract import is_sensitive


class ProfileEngine:
    """Maintains a living, structured persona and behavioral profile of the user.
    
    Tracks:
    - User traits & preferences (e.g. communication style, output depth)
    - Workflows & recurring tasks (e.g. studying course materials, creating PDFs)
    - Environments & tools used (e.g. external drives, favorite languages, IDEs)
    - Active projects & focus areas
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        base = Path(db_path).expanduser() if db_path else Path.home() / ".codag" / "memory.db"
        self.db_path = base
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    aspect TEXT UNIQUE NOT NULL,      -- e.g. 'identity', 'work_style', 'projects', 'environment'
                    summary TEXT NOT NULL,           -- synthesized markdown/prose summary
                    details TEXT NOT NULL,           -- JSON array of specific bullet points / observations
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS interaction_reflections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL,
                    reflection TEXT NOT NULL,
                    inferred_traits TEXT NOT NULL,   -- JSON array
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def get_aspect(self, aspect: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM user_profile WHERE aspect = ?", (aspect.strip().lower(),))
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            try:
                res["details"] = json.loads(res["details"])
            except Exception:
                res["details"] = []
            return res

    def update_aspect(self, aspect: str, summary: str, details: list[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        clean_details = [d for d in details if not is_sensitive(d)]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO user_profile (aspect, summary, details, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(aspect) DO UPDATE SET
                    summary = excluded.summary,
                    details = excluded.details,
                    updated_at = excluded.updated_at
            """, (aspect.strip().lower(), summary.strip(), json.dumps(clean_details), now))
            conn.commit()

    def get_full_profile(self) -> dict[str, Any]:
        """Return the complete profile across all aspects."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM user_profile ORDER BY aspect ASC")
            profile = {}
            for row in cur.fetchall():
                d = dict(row)
                try:
                    d["details"] = json.loads(d["details"])
                except Exception:
                    d["details"] = []
                profile[d["aspect"]] = d
            return profile

    def format_profile_for_prompt(self, budget_chars: int = 2500) -> str:
        """Format the synthesized user profile for injection into the system prompt."""
        profile = self.get_full_profile()
        if not profile:
            return ""

        sections = ["<user_profile_and_habits>"]
        total = len(sections[0])

        aspect_order = ["identity", "work_style", "projects", "environment", "general"]
        sorted_aspects = sorted(
            profile.keys(),
            key=lambda a: aspect_order.index(a) if a in aspect_order else 99,
        )

        for aspect in sorted_aspects:
            item = profile[aspect]
            header = f"\n### {aspect.replace('_', ' ').title()}"
            body = item.get("summary", "")
            bullets = "\n".join(f"- {d}" for d in item.get("details", [])[:4])
            block = f"{header}\n{body}\n{bullets}".strip()
            if total + len(block) + 40 > budget_chars:
                break
            sections.append(block)
            total += len(block) + 1

        sections.append("</user_profile_and_habits>")
        return "\n".join(sections)

    def reflect_on_interaction(
        self,
        turn_id: str,
        user_message: str,
        assistant_message: str,
        tools_used: list[str],
        llm: LLMClient,
        model: str,
    ) -> list[str]:
        """Reflect on a completed interaction to extract implicit habits, traits, and projects."""
        if is_sensitive(user_message) or is_sensitive(assistant_message):
            return []

        # Fast filter: skip purely short or trivial greetings
        if len(user_message.strip()) < 8 and not tools_used:
            return []

        prompt = f"""You are an autonomous agent profile synthesizer.
Analyze this interaction between the user and assistant.
Identify any implicit habits, preferences, workflows, technical stacks, project names, or communication styles demonstrated by the user.

Do NOT extract secrets, passwords, or temporary instructions.
Focus on learning who the user is and how they work.

User Message: "{user_message}"
Assistant Tools Used: {tools_used}
Assistant Response Snippet: "{assistant_message[:400]}"

Output a JSON object with this schema:
{{
  "traits": [
    {{"aspect": "identity|work_style|projects|environment", "observation": "concise observation about the user"}}
  ]
}}
If no durable traits can be inferred, return {{"traits": []}}
"""
        schema = {
            "type": "object",
            "properties": {
                "traits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "aspect": {"type": "string"},
                            "observation": {"type": "string"},
                        },
                        "required": ["aspect", "observation"],
                    },
                }
            },
            "required": ["traits"],
        }

        try:
            res = llm.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                settings=MainModelConfig(temperature=0.0, num_ctx=2048),
                format_schema=schema,
            )
            data = json.loads(res.message.content)
            traits = data.get("traits", [])
            if not traits:
                return []

            now = datetime.now(timezone.utc).isoformat()
            saved_obs: list[str] = []

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO interaction_reflections (turn_id, reflection, inferred_traits, created_at)
                    VALUES (?, ?, ?, ?)
                """, (turn_id, f"Interaction reflection for {turn_id}", json.dumps(traits), now))
                conn.commit()

            # Group by aspect and update user profile
            aspect_map: dict[str, list[str]] = {}
            for t in traits:
                asp = t.get("aspect", "work_style").strip().lower()
                obs = t.get("observation", "").strip()
                if obs and not is_sensitive(obs):
                    aspect_map.setdefault(asp, []).append(obs)
                    saved_obs.append(obs)

            for asp, new_details in aspect_map.items():
                existing = self.get_aspect(asp)
                if existing:
                    merged = list(dict.fromkeys(existing.get("details", []) + new_details))[-10:]
                    summary = existing.get("summary", "")
                    if not summary or len(summary) < 10:
                        summary = f"Synthesized observations for {asp}."
                    self.update_aspect(asp, summary, merged)
                else:
                    self.update_aspect(asp, f"Observations on user's {asp}.", new_details)

            return saved_obs
        except Exception:
            return []
