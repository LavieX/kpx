"""Multi-database KeePass manager (singleton, thread-safe)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from pykeepass import PyKeePass

from kpx.models import DatabaseInfo, EntryDetail, EntryResult, SearchResult


class DatabaseManager:
    """Holds multiple unlocked PyKeePass instances keyed by absolute path."""

    _instance: Optional["DatabaseManager"] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "DatabaseManager":
        with cls._init_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._registry: Dict[str, PyKeePass] = {}
                inst._lock = threading.Lock()
                inst._last_activity: float = time.time()
                inst._auto_lock_timeout: float = 15 * 60  # 15 minutes default
                cls._instance = inst
            return cls._instance

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def unlock(
        self,
        db_path: str,
        password: str,
        keyfile: Optional[str] = None,
        keyfile_path: Optional[str] = None,
    ) -> DatabaseInfo:
        """Open a .kdbx file and store it in the registry."""
        abs_path = str(Path(db_path).resolve())
        kf = keyfile or keyfile_path
        kp = PyKeePass(abs_path, password=password, keyfile=kf)
        with self._lock:
            self._registry[abs_path] = kp
        return self._db_info(abs_path, kp)

    def lock(self, db_path: str) -> bool:
        """Remove a database from the registry. Returns True if it was open."""
        abs_path = str(Path(db_path).resolve())
        with self._lock:
            return self._registry.pop(abs_path, None) is not None

    def lock_all(self) -> int:
        """Lock every open database. Returns count of databases locked."""
        with self._lock:
            count = len(self._registry)
            self._registry.clear()
            return count

    # ------------------------------------------------------------------
    # Idle / session management
    # ------------------------------------------------------------------

    def touch(self) -> None:
        """Update last_activity timestamp."""
        with self._lock:
            self._last_activity = time.time()

    def check_idle(self) -> int:
        """Lock all databases if idle timeout exceeded. Returns count locked, 0 if not idle."""
        with self._lock:
            if self._auto_lock_timeout <= 0:
                return 0
            if not self._registry:
                return 0
            elapsed = time.time() - self._last_activity
            if elapsed < self._auto_lock_timeout:
                return 0
            count = len(self._registry)
            self._registry.clear()
        return count

    def get_auto_lock_timeout(self) -> float:
        """Return the auto-lock timeout in seconds."""
        with self._lock:
            return self._auto_lock_timeout

    def set_auto_lock_timeout(self, minutes: float) -> None:
        """Set the auto-lock timeout. 0 disables auto-lock."""
        with self._lock:
            self._auto_lock_timeout = minutes * 60

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_databases(self) -> List[DatabaseInfo]:
        """Return info for every open database."""
        with self._lock:
            registry_snapshot = dict(self._registry)
        return [
            self._db_info(path, kp) for path, kp in registry_snapshot.items()
        ]

    def search(
        self, query: str, db_path: Optional[str] = None
    ) -> SearchResult:
        """Case-insensitive substring search across title, username, url, notes."""
        q = query.lower()
        with self._lock:
            if db_path:
                abs_path = str(Path(db_path).resolve())
                targets = {abs_path: self._registry[abs_path]} if abs_path in self._registry else {}
            else:
                targets = dict(self._registry)

        results: List[EntryResult] = []
        for path, kp in targets.items():
            for entry in kp.entries:
                if self._matches(entry, q):
                    results.append(self._to_entry_result(entry, path))
        return SearchResult(entries=results, total=len(results))

    def get_entry(self, uuid_str: str, db_path: str) -> Optional[EntryDetail]:
        """Return full entry detail including password."""
        abs_path = str(Path(db_path).resolve())
        with self._lock:
            kp = self._registry.get(abs_path)
        if kp is None:
            return None

        for entry in kp.entries:
            if str(entry.uuid) == uuid_str:
                return self._to_entry_detail(entry, abs_path)
        return None

    def autofill(self, url: str) -> Optional[EntryResult]:
        """Find the best matching entry by URL domain across all open DBs."""
        target_domain = self._extract_domain(url)
        if not target_domain:
            return None

        with self._lock:
            registry_snapshot = dict(self._registry)

        best: Optional[EntryResult] = None
        best_score = 0

        for path, kp in registry_snapshot.items():
            for entry in kp.entries:
                entry_url = entry.url or ""
                if not entry_url:
                    continue
                entry_domain = self._extract_domain(entry_url)
                if not entry_domain:
                    continue
                score = self._domain_match_score(target_domain, entry_domain)
                if score > best_score:
                    best_score = score
                    best = self._to_entry_result(entry, path)

        return best

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _db_info(path: str, kp: PyKeePass) -> DatabaseInfo:
        name = Path(path).stem
        entries = kp.entries or []
        return DatabaseInfo(
            path=path,
            name=name,
            locked=False,
            entry_count=len(entries),
        )

    @staticmethod
    def _matches(entry, query: str) -> bool:
        """Check if any searchable field contains the query substring."""
        fields = [
            entry.title or "",
            entry.username or "",
            entry.url or "",
            entry.notes or "",
        ]
        return any(query in f.lower() for f in fields)

    @staticmethod
    def _group_path(entry) -> str:
        """Build a slash-separated group path."""
        parts = []
        group = entry.group
        while group:
            if group.name:
                parts.append(group.name)
            group = group.parentgroup
        parts.reverse()
        return "/".join(parts)

    @classmethod
    def _to_entry_result(cls, entry, db_path: str) -> EntryResult:
        return EntryResult(
            title=entry.title or "",
            username=entry.username or "",
            url=entry.url or "",
            uuid=str(entry.uuid),
            db_path=db_path,
            group_path=cls._group_path(entry),
        )

    @classmethod
    def _to_entry_detail(cls, entry, db_path: str) -> EntryDetail:
        custom = {}
        if entry.custom_properties:
            custom = dict(entry.custom_properties)
        return EntryDetail(
            title=entry.title or "",
            username=entry.username or "",
            url=entry.url or "",
            uuid=str(entry.uuid),
            db_path=db_path,
            group_path=cls._group_path(entry),
            password=entry.password or "",
            notes=entry.notes or "",
            custom_fields=custom,
        )

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from a URL, tolerating missing schemes."""
        if not url:
            return ""
        if "://" not in url:
            url = "https://" + url
        try:
            return urlparse(url).hostname or ""
        except Exception:
            return ""

    @staticmethod
    def _domain_match_score(target: str, candidate: str) -> int:
        """Score how well two domains match. Higher is better, 0 means no match."""
        target = target.lower()
        candidate = candidate.lower()
        if target == candidate:
            return 100
        # subdomain match: e.g. login.example.com vs example.com
        if target.endswith("." + candidate) or candidate.endswith("." + target):
            return 80
        # shared base domain (last two parts)
        t_parts = target.rsplit(".", 2)
        c_parts = candidate.rsplit(".", 2)
        if len(t_parts) >= 2 and len(c_parts) >= 2:
            if t_parts[-2:] == c_parts[-2:]:
                return 60
        return 0
