from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

VALID_CATEGORIES = ("decision", "pattern", "bug", "context", "learning")

CATEGORY_HEADINGS = {
    "decision": "Decisions",
    "pattern": "Patterns",
    "bug": "Bugs Fixed",
    "context": "Context",
    "learning": "Learnings",
}


@dataclass
class RawMemoryInput:
    """Raw input for creating a memory before processing."""

    title: str
    what: str
    why: Optional[str] = None
    impact: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    category: Optional[str] = None
    related_files: list[str] = field(default_factory=list)
    details: Optional[str] = None
    source: Optional[str] = None
    agent: Optional[str] = None


@dataclass
class Memory:
    """A memory record with all metadata and references."""

    id: str
    title: str
    what: str
    why: Optional[str]
    impact: Optional[str]
    tags: list[str]
    category: Optional[str]
    project: str
    source: Optional[str]
    agent: Optional[str]
    related_files: list[str]
    file_path: str
    section_anchor: str
    created_at: str
    updated_at: str

    @staticmethod
    def from_raw(raw: RawMemoryInput, project: str, file_path: str = "") -> Memory:
        """Create a Memory from RawMemoryInput with generated fields."""
        now = datetime.now(timezone.utc).isoformat()
        anchor = re.sub(r"[^a-z0-9]+", "-", raw.title.lower()).strip("-")
        return Memory(
            id=str(uuid.uuid4()),
            title=raw.title,
            what=raw.what,
            why=raw.why,
            impact=raw.impact,
            tags=raw.tags,
            category=raw.category,
            project=project,
            source=raw.source,
            agent=raw.agent,
            related_files=raw.related_files,
            file_path=file_path,
            section_anchor=anchor,
            created_at=now,
            updated_at=now,
        )


@dataclass
class MemoryDetail:
    """Full details/body content for a memory."""

    memory_id: str
    body: str


@dataclass
class Project:
    """A registered project."""

    name: str
    display_name: Optional[str]
    description: Optional[str]
    created_at: str


@dataclass
class TodoItem:
    """A persistent TODO item scoped to a project."""

    id: int
    project: str
    title: str
    description: Optional[str]
    status: str  # pending, in_progress, done, cancelled
    priority: int  # 0=normal, 1=high, 2=critical
    source_memory_id: Optional[str]
    created_at: str
    updated_at: str


@dataclass
class SearchResult:
    """Search result with score and metadata."""

    id: str
    title: str
    what: str
    why: Optional[str]
    impact: Optional[str]
    category: Optional[str]
    tags: list[str]
    project: str
    source: Optional[str]
    agent: Optional[str]
    score: float
    has_details: bool
    file_path: str
    created_at: str
