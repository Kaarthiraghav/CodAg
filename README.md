# CodAg

**CodAg** is a local, open-source personal AI assistant running entirely on Apple Silicon (optimized for Mac Mini M4, 16 GB unified RAM). It combines multi-turn conversational intelligence, durable memory, local file and shell tools, web search with source citations, semantic document retrieval, and safe code generation behind an un-bypassable permission engine.

---

## Features

- **Local & Private:** Runs with local models served via Ollama (`qwen3.5:9b` / `qwen3:8b`, `nomic-embed-text`, `qwen2.5-coder:7b`).
- **Deterministic Python Core:** Deterministic turn pipeline where the model proposes actions and Python enforces safety, permissions, and execution boundaries.
- **Dynamic Skill Routing:** Exposes only relevant tools per turn (capped at 8) using a two-stage router (fast keyword matching + model fallback).
- **Hardened Permission Engine:**
  - `READ (0)`: Runs freely (reading files, web searches, memory recall).
  - `SAFE_WRITE (1)`: Runs freely within workspace roots (`~/CodAg/workspace`).
  - `CONFIRM (2)`: Interactive terminal prompt for deletions, moves, overwrites, writes outside workspace, or non-allowlisted commands.
  - `FORBIDDEN (3)`: Hard denial for `sudo`, dangerous shell operators, and deny-listed paths (`~/.ssh`, `.env`, `.pem`).
- **Taint Tracking & Anti-Injection:** Untrusted external web content and foreign files automatically taint the turn context, escalating subsequent write actions to `CONFIRM`.
- **Durable Memory:**
  - Atomic facts in SQLite extracted strictly from user messages.
  - Semantic vector search with ChromaDB and `nomic-embed-text`.
  - Sensitive credential filter automatically discards passwords, API keys, and private tokens.
- **Skills Ecosystem:**
  - `files`: Read, search, create, edit, move, delete with snapshotting and trash recovery.
  - `shell`: Subprocess execution with strict operator blocking and command allowlists.
  - `tasks`: SQLite-backed personal task list.
  - `notes`: Markdown notes creation, appending, and keyword search.
  - `memory`: Remember, recall, and hard-forget user preferences and facts.
  - `web`: Internet search via DuckDuckGo and readable page extraction via Trafilatura.
  - `knowledge`: Semantic document indexing with incremental hashing and Q&A citations.
  - `code`: Test-first software project planner and builder with git-per-task commits (`CONFIRM` tier).
  - `system`: macOS desktop actions: notifications, clipboard, opening/quitting apps, and settings (`CONFIRM` for quitting/settings).
  - `scheduler`: APScheduler-backed reminders and daily briefings delivered as desktop notifications.
- **Multi-Project Chat Sessions:**
  - Maintain separate conversations isolated per project or workspace directory.
  - Automatic project workspace injection directing relative file operations, code plans, and builds to the active project folder.
  - Native interactive terminal chat (`codag chat [session]`, `codag chats`) with auto-detected project directories.

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/user/codag.git
cd CodAg

# 2. Setup Python 3.12 virtual environment using uv
uv venv --python 3.12 .venv
source .venv/bin/activate

# 3. Install CodAg with development dependencies using uv
uv pip install -e ".[dev]"

# 4. Pull required Ollama models
ollama pull nomic-embed-text
```

---

## Configuration

CodAg uses two TOML configuration files in `config/`:

- `config/codag.toml`: Configures models, temperatures, token limits, and data directories.
- `config/policy.toml`: Defines workspace boundaries, read roots, deny patterns, and shell command allowlists.

---

## CLI Usage

```bash
# System checkup
uv run codag doctor
# or with venv active:
codag doctor

# Interactive terminal chat with tools, multi-project context, and slash commands
codag chat
codag chat "Web Mining Study" --project "/Volumes/Black Hole/Web Mining"

# In-chat slash commands available during `codag chat`:
#   /help             Show available in-chat commands
#   /chats            List saved sessions
#   /switch <name>    Switch active chat session
#   /new <title>      Start a new chat session
#   /project [path]   View or change active project folder
#   /pdf [title]      Export last response as PDF and open in macOS Preview
#   /undo             Undo last file modification
#   /clear            Clear screen
#   /exit             Exit chat

# Manage multi-project chat sessions directly
codag chats list
codag chats new "CLI Tool" --project ~/projects/cli_tool
codag chats show <session_id>
codag chats delete <session_id>

# Single-shot question or task
codag ask "List my pending tasks"

# Memory management
codag memory list
codag memory forget <id_or_key>
codag memory export --format markdown

# Audit trail & undo
codag audit
codag undo [<token>]

# Evaluation suite
codag eval
```

---

## Privacy & Safety Notes

1. **Web Queries:** When web search is enabled, queries are sent to DuckDuckGo via the provider interface. All other operations (LLM inference, embeddings, storage, tools) run 100% locally on your Mac.
2. **Reversibility:** Any file deletion moves files to `~/.codag/trash/`. File modifications create automatic snapshots in `~/.codag/backups/`. Running `codag undo` will restore previous states.
3. **Audit Log:** Every tool call and permission decision is logged to append-only JSONL files at `~/.codag/audit/`.

---

## Contributing & License

Open source under the [MIT License](LICENSE).
Contributions are welcome—please ensure `pytest tests` and `codag eval` pass before submitting pull requests.
