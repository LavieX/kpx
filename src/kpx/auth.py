"""Pairing and session authentication for KPX server."""

from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class _PairingCode:
    code: str
    expires_at: float


@dataclass
class _SessionToken:
    token: str
    created_at: float
    expires_at: float


class AuthManager:
    """Manages pairing codes and session tokens. Thread-safe singleton."""

    _instance: AuthManager | None = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> AuthManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, session_ttl_hours: float = 24.0, pairing_ttl_seconds: float = 300.0):
        if self._initialized:
            return
        self._initialized = True
        self._session_ttl = session_ttl_hours * 3600
        self._pairing_ttl = pairing_ttl_seconds
        self._mu = threading.Lock()
        self._pairing_codes: dict[str, _PairingCode] = {}
        self._sessions: dict[str, _SessionToken] = {}
        # Rate limiting for pairing: list of timestamps
        self._pair_attempts: list[float] = []
        self._pair_rate_limit = 5  # max attempts per 60s window

    # ------------------------------------------------------------------
    # Pairing
    # ------------------------------------------------------------------

    def generate_pairing_code(self) -> str:
        """Generate a 6-digit numeric pairing code (valid for 5 min)."""
        code = f"{random.randint(0, 999999):06d}"
        with self._mu:
            self._cleanup_pairing()
            self._pairing_codes[code] = _PairingCode(
                code=code,
                expires_at=time.time() + self._pairing_ttl,
            )
        return code

    def validate_pairing(self, code: str) -> str | None:
        """Validate a pairing code. Returns a session token on success, None on failure.

        Also enforces rate limiting (max 5 attempts per minute).
        """
        now = time.time()
        with self._mu:
            # Rate limiting
            self._pair_attempts = [t for t in self._pair_attempts if now - t < 60]
            if len(self._pair_attempts) >= self._pair_rate_limit:
                return None
            self._pair_attempts.append(now)

            self._cleanup_pairing()
            entry = self._pairing_codes.pop(code, None)
            if entry is None:
                return None

        # Code is valid — issue a session token
        return self._create_session()

    def is_rate_limited(self) -> bool:
        """Check if pairing attempts are currently rate-limited."""
        now = time.time()
        with self._mu:
            self._pair_attempts = [t for t in self._pair_attempts if now - t < 60]
            return len(self._pair_attempts) >= self._pair_rate_limit

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def validate_token(self, token: str) -> bool:
        """Return True if the token is valid and not expired."""
        now = time.time()
        with self._mu:
            session = self._sessions.get(token)
            if session is None:
                return False
            if now > session.expires_at:
                del self._sessions[token]
                return False
            return True

    def revoke_token(self, token: str) -> bool:
        """Remove a session token. Returns True if it existed."""
        with self._mu:
            return self._sessions.pop(token, None) is not None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _create_session(self) -> str:
        token = str(uuid.uuid4())
        now = time.time()
        with self._mu:
            self._sessions[token] = _SessionToken(
                token=token,
                created_at=now,
                expires_at=now + self._session_ttl,
            )
        return token

    def _cleanup_pairing(self) -> None:
        """Remove expired pairing codes. Caller must hold self._mu."""
        now = time.time()
        expired = [k for k, v in self._pairing_codes.items() if now > v.expires_at]
        for k in expired:
            del self._pairing_codes[k]

    @classmethod
    def reset(cls) -> None:
        """Reset singleton — mainly useful for tests."""
        with cls._lock:
            cls._instance = None
