"""Pydantic schemas for KPX."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class DatabaseInfo(BaseModel):
    """Summary info for an opened KeePass database."""

    path: str
    name: str = Field(description="Derived from the .kdbx filename")
    locked: bool = False
    entry_count: int = 0


class EntryResult(BaseModel):
    """A single search result (no secrets)."""

    title: str = ""
    username: str = ""
    url: str = ""
    uuid: str
    db_path: str
    group_path: str = ""


class EntryDetail(EntryResult):
    """Full entry including secrets."""

    password: str = ""
    notes: str = ""
    custom_fields: Dict[str, str] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """Wrapper for a list of search results."""

    entries: List[EntryResult] = Field(default_factory=list)
    total: int = 0


class UnlockRequest(BaseModel):
    """Payload for unlocking a database."""

    db_path: str
    password: str
    keyfile_path: Optional[str] = None
