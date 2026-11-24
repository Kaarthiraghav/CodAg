"""Snapshots, file backups, trash directory, and undo manager."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import uuid
from typing import Any
from pydantic import BaseModel, Field


class UndoRecord(BaseModel):
    token: str
    action: str                       # "modify", "delete", "create", "move"
    original_path: str
    target_path: str | None = None
    backup_path: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SnapshotManager:
    def __init__(self, data_dir: Path | str | None = None) -> None:
        base = Path(data_dir).expanduser() if data_dir else Path.home() / ".codag"
        self.data_dir = base
        self.backups_dir = base / "backups"
        self.trash_dir = base / "trash"
        self.records_file = base / "undo_records.jsonl"
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)

    def _save_record(self, record: UndoRecord) -> None:
        with open(self.records_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.model_dump()) + "\n")

    def snapshot_before_modify(self, file_path: Path, turn_id: str | None = None) -> str:
        """Snapshot file before edit or overwrite; returns undo_token."""
        token = f"undo-{uuid.uuid4().hex[:10]}"
        turn_tag = turn_id or "general"
        dest_dir = self.backups_dir / turn_tag
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        backup_file = dest_dir / f"{token}_{file_path.name}"
        if file_path.exists():
            shutil.copy2(file_path, backup_file)
            record = UndoRecord(
                token=token,
                action="modify",
                original_path=str(file_path.resolve()),
                backup_path=str(backup_file.resolve()),
            )
        else:
            record = UndoRecord(
                token=token,
                action="create",
                original_path=str(file_path.resolve()),
            )
        self._save_record(record)
        return token

    def move_to_trash(self, file_path: Path) -> str:
        """Move file to trash instead of deleting; returns undo_token."""
        token = f"undo-{uuid.uuid4().hex[:10]}"
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        trash_subdir = self.trash_dir / ts
        trash_subdir.mkdir(parents=True, exist_ok=True)

        trash_dest = trash_subdir / f"{token}_{file_path.name}"
        shutil.move(file_path, trash_dest)

        record = UndoRecord(
            token=token,
            action="delete",
            original_path=str(file_path.resolve()),
            backup_path=str(trash_dest.resolve()),
        )
        self._save_record(record)
        return token

    def record_move(self, source_path: Path, dest_path: Path) -> str:
        """Record file move; returns undo_token."""
        token = f"undo-{uuid.uuid4().hex[:10]}"
        record = UndoRecord(
            token=token,
            action="move",
            original_path=str(source_path.resolve()),
            target_path=str(dest_path.resolve()),
        )
        self._save_record(record)
        return token

    def undo(self, token: str | None = None) -> tuple[bool, str]:
        """Undo action by token, or the last action if token is None."""
        if not self.records_file.exists():
            return False, "No undo records found."

        records: list[UndoRecord] = []
        with open(self.records_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(UndoRecord.model_validate(json.loads(line)))

        if not records:
            return False, "No undo records found."

        target: UndoRecord | None = None
        if token:
            for r in reversed(records):
                if r.token == token:
                    target = r
                    break
            if not target:
                return False, f"Undo token not found: {token}"
        else:
            target = records[-1]

        orig = Path(target.original_path)
        try:
            if target.action in {"modify", "delete"}:
                if not target.backup_path or not Path(target.backup_path).exists():
                    return False, f"Backup file missing: {target.backup_path}"
                orig.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target.backup_path, orig)
                return True, f"Restored {orig} from {target.action}"

            elif target.action == "create":
                if orig.exists():
                    orig.unlink()
                return True, f"Removed created file {orig}"

            elif target.action == "move":
                if target.target_path and Path(target.target_path).exists():
                    orig.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(target.target_path, orig)
                    return True, f"Moved {target.target_path} back to {orig}"
                return False, f"Target path missing: {target.target_path}"

            return False, f"Unknown action: {target.action}"
        except Exception as exc:
            return False, f"Undo failed: {exc}"
