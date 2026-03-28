"""FastAPI server for KPX — local-only credential bridge."""

from __future__ import annotations

import asyncio
import re
import secrets
import string
from contextlib import asynccontextmanager
from typing import Any

import click
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from kpx import __version__
from kpx.auth import AuthManager
from kpx.db_manager import DatabaseManager
from kpx.models import UnlockRequest

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(application: FastAPI):
    """Run a background idle-checker every 60 seconds."""
    async def _idle_checker():
        db = DatabaseManager()
        while True:
            await asyncio.sleep(60)
            locked = db.check_idle()
            if locked:
                click.echo(f"Auto-locked {locked} database(s) due to inactivity.")

    task = asyncio.create_task(_idle_checker())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="KPX", version=__version__, lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome|moz)-extension://.*$",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class PairRequest(BaseModel):
    code: str | None = None


class LockRequest(BaseModel):
    db_path: str | None = None
    all: bool = False


class ConfigRequest(BaseModel):
    auto_lock_minutes: float


# ---------------------------------------------------------------------------
# Origin validation middleware
# ---------------------------------------------------------------------------

_ALLOWED_ORIGIN_PATTERN = re.compile(r"^(chrome|moz)-extension://")


@app.middleware("http")
async def validate_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    # Allow requests with no Origin (e.g. direct localhost curl, CLI tools)
    if origin is not None and not _ALLOWED_ORIGIN_PATTERN.match(origin):
        return JSONResponse(
            status_code=403,
            content={"error": "Forbidden origin"},
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def _get_auth() -> AuthManager:
    return AuthManager()


def _get_db() -> DatabaseManager:
    return DatabaseManager()


async def require_auth(authorization: str | None = Header(default=None)) -> str:
    """Dependency that enforces a valid Bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization[7:]
    auth = _get_auth()
    if not auth.validate_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    # Update activity timestamp on every authenticated request
    _get_db().touch()
    return token


# ---------------------------------------------------------------------------
# Public endpoints (no auth)
# ---------------------------------------------------------------------------


@app.get("/health")
async def health(db: DatabaseManager = Depends(_get_db)) -> dict[str, Any]:
    databases = db.get_databases()
    return {
        "status": "ok",
        "databases": len(databases),
        "version": __version__,
    }


@app.post("/pair")
async def pair(
    body: PairRequest | None = None,
    auth: AuthManager = Depends(_get_auth),
) -> dict[str, str]:
    if body is None or body.code is None:
        # First call: generate code and print to console
        if auth.is_rate_limited():
            raise HTTPException(status_code=429, detail="Too many pairing attempts. Try again later.")
        code = auth.generate_pairing_code()
        click.echo(f"\n{'='*40}")
        click.echo(f"  PAIRING CODE:  {code}")
        click.echo(f"{'='*40}\n")
        return {"message": "Check CLI/server console for pairing code"}
    else:
        # Second call: validate the code
        if auth.is_rate_limited():
            raise HTTPException(status_code=429, detail="Too many pairing attempts. Try again later.")
        token = auth.validate_pairing(body.code)
        if token is None:
            raise HTTPException(status_code=401, detail="Invalid or expired pairing code")
        return {"token": token}


# ---------------------------------------------------------------------------
# Authenticated endpoints
# ---------------------------------------------------------------------------


@app.post("/unlock")
async def unlock(
    body: UnlockRequest,
    _token: str = Depends(require_auth),
    db: DatabaseManager = Depends(_get_db),
) -> dict[str, Any]:
    try:
        info = db.unlock(
            db_path=body.db_path,
            password=body.password,
            keyfile_path=getattr(body, "keyfile_path", None),
        )
        return info.model_dump() if hasattr(info, "model_dump") else info.__dict__
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/lock")
async def lock(
    body: LockRequest,
    _token: str = Depends(require_auth),
    db: DatabaseManager = Depends(_get_db),
) -> dict[str, str]:
    try:
        if body.all:
            db.lock_all()
            return {"status": "all databases locked"}
        elif body.db_path:
            db.lock(body.db_path)
            return {"status": f"locked {body.db_path}"}
        else:
            raise HTTPException(status_code=400, detail="Provide db_path or set all=true")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/databases")
async def databases(
    _token: str = Depends(require_auth),
    db: DatabaseManager = Depends(_get_db),
) -> list[dict[str, Any]]:
    dbs = db.get_databases()
    return [d.model_dump() if hasattr(d, "model_dump") else d.__dict__ for d in dbs]


@app.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    db_path: str | None = Query(default=None, alias="db"),
    _token: str = Depends(require_auth),
    db: DatabaseManager = Depends(_get_db),
) -> dict[str, Any]:
    try:
        result = db.search(query=q, db_path=db_path)
        if hasattr(result, "model_dump"):
            return result.model_dump()
        elif isinstance(result, list):
            return {"results": [r.model_dump() if hasattr(r, "model_dump") else r.__dict__ for r in result]}
        return result.__dict__
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/entry/{uuid}")
async def entry(
    uuid: str,
    db_path: str = Query(..., alias="db"),
    _token: str = Depends(require_auth),
    db: DatabaseManager = Depends(_get_db),
) -> dict[str, Any]:
    try:
        detail = db.get_entry(uuid=uuid, db_path=db_path)
        if detail is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        return detail.model_dump() if hasattr(detail, "model_dump") else detail.__dict__
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/autofill")
async def autofill(
    url: str = Query(..., min_length=1),
    _token: str = Depends(require_auth),
    db: DatabaseManager = Depends(_get_db),
) -> dict[str, Any]:
    try:
        result = db.autofill(url=url)
        if result is None:
            raise HTTPException(status_code=404, detail="No matching entry found")
        return result.model_dump() if hasattr(result, "model_dump") else result.__dict__
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------


@app.get("/config")
async def get_config(
    _token: str = Depends(require_auth),
    db: DatabaseManager = Depends(_get_db),
) -> dict[str, Any]:
    timeout_seconds = db.get_auto_lock_timeout()
    return {
        "auto_lock_minutes": timeout_seconds / 60,
        "auto_lock_enabled": timeout_seconds > 0,
    }


@app.post("/config")
async def set_config(
    body: ConfigRequest,
    _token: str = Depends(require_auth),
    db: DatabaseManager = Depends(_get_db),
) -> dict[str, Any]:
    if body.auto_lock_minutes < 0:
        raise HTTPException(status_code=400, detail="auto_lock_minutes must be >= 0")
    db.set_auto_lock_timeout(body.auto_lock_minutes)
    return {
        "auto_lock_minutes": body.auto_lock_minutes,
        "auto_lock_enabled": body.auto_lock_minutes > 0,
    }


# ---------------------------------------------------------------------------
# Password generator (no auth required)
# ---------------------------------------------------------------------------


@app.get("/generate")
async def generate_password(
    length: int = Query(default=20, ge=1, le=256),
    symbols: bool = Query(default=True),
    numbers: bool = Query(default=True),
    uppercase: bool = Query(default=True),
    lowercase: bool = Query(default=True),
    count: int = Query(default=1, ge=1, le=100),
) -> dict[str, Any]:
    alphabet = ""
    if lowercase:
        alphabet += string.ascii_lowercase
    if uppercase:
        alphabet += string.ascii_uppercase
    if numbers:
        alphabet += string.digits
    if symbols:
        alphabet += string.punctuation
    if not alphabet:
        raise HTTPException(
            status_code=400,
            detail="At least one character class must be enabled",
        )
    passwords = [
        "".join(secrets.choice(alphabet) for _ in range(length))
        for _ in range(count)
    ]
    if count == 1:
        return {"password": passwords[0]}
    return {"passwords": passwords}


# ---------------------------------------------------------------------------
# Server runner
# ---------------------------------------------------------------------------


def run_server(host: str = "127.0.0.1", port: int = 19455) -> None:
    """Start the KPX server. Called by ``kpx serve``."""
    click.echo(f"KPX server starting on http://{host}:{port}")
    click.echo("Press Ctrl+C to stop.")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
