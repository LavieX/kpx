"""KPX client — lightweight helper for scripts and automation (e.g. Playwright)."""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional


class KPXClient:
    """Thin HTTP client for the KPX server."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:19455",
        token: Optional[str] = None,
    ):
        self.base_url = base_url
        self.token = token or self._load_token()

    @staticmethod
    def _load_token() -> Optional[str]:
        p = Path.home() / ".kpx" / "session.token"
        return p.read_text().strip() if p.exists() else None

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def get_credentials(self, url: str) -> dict:
        """Get username + password for a URL in one call.

        Returns: {"title", "username", "password", "url", "uuid", "db_path"}
        """
        match = self._request("GET", f"/autofill?url={urllib.request.quote(url, safe='')}")
        entry = self._request("GET", f"/entry/{match['uuid']}?db={urllib.request.quote(match['db_path'], safe='')}")
        return entry

    def search(self, query: str) -> list[dict]:
        """Search all open databases. Returns list of entries (no passwords)."""
        result = self._request("GET", f"/search?q={urllib.request.quote(query, safe='')}")
        return result.get("entries", [])

    def get_entry(self, uuid: str, db_path: str) -> dict:
        """Get full entry including password."""
        return self._request("GET", f"/entry/{uuid}?db={urllib.request.quote(db_path, safe='')}")

    def databases(self) -> list[dict]:
        """List all open databases."""
        return self._request("GET", "/databases")

    def is_available(self) -> bool:
        """Check if the server is running and token is valid."""
        try:
            self._request("GET", "/databases")
            return True
        except Exception:
            return False
