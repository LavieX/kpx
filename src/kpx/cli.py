"""KPX CLI -- thin client that talks to the local KPX server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import click

from kpx import __version__

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 19455
SERVER_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
KPX_DIR = Path.home() / ".kpx"
PID_FILE = KPX_DIR / "server.pid"
TOKEN_FILE = KPX_DIR / "session.token"


# ---------------------------------------------------------------------------
# Helpers -- lightweight HTTP via urllib (no extra deps for the CLI client)
# ---------------------------------------------------------------------------

def _request(
    method: str,
    path: str,
    body: Optional[dict] = None,
    timeout: int = 10,
    auth: bool = True,
) -> dict:
    """Make an HTTP request to the KPX server. Returns parsed JSON."""
    import urllib.request
    import urllib.error

    url = f"{SERVER_URL}{path}"
    data = json.dumps(body).encode() if body else None
    headers: dict[str, str] = {}
    if data:
        headers["Content-Type"] = "application/json"
    if auth:
        token = _load_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode())
        except Exception:
            detail = {"detail": str(exc)}
        if exc.code == 401:
            raise click.ClickException(
                "Authentication required. Run: kpx pair"
            )
        raise click.ClickException(detail.get("detail", detail.get("error", str(exc))))
    except urllib.error.URLError as exc:
        raise click.ClickException(
            f"Cannot reach KPX server at {SERVER_URL}: {exc.reason}"
        )


def _server_is_running() -> bool:
    """Check if the KPX server is responding."""
    try:
        _request("GET", "/health", auth=False, timeout=2)
        return True
    except click.ClickException:
        return False


def _ensure_server() -> None:
    """Start the server in the background if it is not already running."""
    if _server_is_running():
        return
    click.echo(click.style("Starting KPX server in background...", fg="yellow"))
    _start_daemon()
    for _ in range(30):
        time.sleep(0.3)
        if _server_is_running():
            click.echo(click.style("Server started.", fg="green"))
            return
    raise click.ClickException("Server failed to start within 9 seconds.")


def _start_daemon() -> None:
    """Launch the KPX server as a background subprocess."""
    KPX_DIR.mkdir(parents=True, exist_ok=True)
    log_file = KPX_DIR / "server.log"
    with open(log_file, "a") as lf:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "kpx.server:app",
             "--host", DEFAULT_HOST, "--port", str(DEFAULT_PORT),
             "--log-level", "info"],
            stdout=lf,
            stderr=lf,
            start_new_session=True,
        )
    PID_FILE.write_text(str(proc.pid))


def _save_token(token: str) -> None:
    """Persist the session token to disk."""
    KPX_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)


def _load_token() -> Optional[str]:
    """Load the session token from disk."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return None


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(__version__, prog_name="kpx")
def cli():
    """KPX -- KeePass credential bridge."""


# ---------------------------------------------------------------------------
# pair
# ---------------------------------------------------------------------------

@cli.command()
def pair():
    """Pair the CLI with the running server (generates a session token)."""
    _ensure_server()
    # Step 1: request a pairing code (server prints it to its console)
    _request("POST", "/pair", body={}, auth=False)
    click.echo("A pairing code has been printed on the server console.")
    code = click.prompt("Enter the 6-digit pairing code")
    # Step 2: validate the code and get a token
    result = _request("POST", "/pair", body={"code": code}, auth=False)
    token = result.get("token")
    if not token:
        raise click.ClickException("Pairing failed -- no token returned.")
    _save_token(token)
    click.echo(click.style("Paired successfully. Token saved.", fg="green"))


# ---------------------------------------------------------------------------
# unlock
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("dbpath", type=click.Path(exists=True))
@click.option("--keyfile", type=click.Path(exists=True), default=None, help="Path to key file.")
def unlock(dbpath: str, keyfile: Optional[str]):
    """Unlock a KeePass database."""
    _ensure_server()
    abs_path = str(Path(dbpath).resolve())
    password = click.prompt("Password", hide_input=True)
    body: dict = {"db_path": abs_path, "password": password}
    if keyfile:
        body["keyfile_path"] = str(Path(keyfile).resolve())
    result = _request("POST", "/unlock", body)
    name = result.get("name", Path(abs_path).stem)
    count = result.get("entry_count", "?")
    click.echo(
        click.style(f"Unlocked {name}", fg="green") + f"  ({count} entries)"
    )


# ---------------------------------------------------------------------------
# lock
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("dbpath", required=False, type=click.Path())
@click.option("--all", "lock_all", is_flag=True, help="Lock all open databases.")
def lock(dbpath: Optional[str], lock_all: bool):
    """Lock a KeePass database (or all with --all)."""
    _ensure_server()
    if lock_all:
        result = _request("POST", "/lock", {"all": True})
        click.echo(click.style(result.get("status", "All locked."), fg="yellow"))
    elif dbpath:
        abs_path = str(Path(dbpath).resolve())
        result = _request("POST", "/lock", {"db_path": abs_path})
        click.echo(click.style(result.get("status", "Locked."), fg="yellow"))
    else:
        raise click.ClickException("Provide a database path or use --all.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@cli.command()
def status():
    """Show open databases and server status."""
    if not _server_is_running():
        click.echo(click.style("Server: not running", fg="red"))
        return
    health = _request("GET", "/health", auth=False)
    version = health.get("version", "?")
    click.echo(
        click.style("Server: running", fg="green")
        + f"  ({SERVER_URL}, v{version})"
    )
    try:
        databases = _request("GET", "/databases")
    except click.ClickException:
        click.echo("  (authenticate with 'kpx pair' to see databases)")
        return
    if not databases:
        click.echo("  No databases open.")
        return
    click.echo()
    for db in databases:
        name = db.get("name", "?")
        path = db.get("path", "?")
        count = db.get("entry_count", "?")
        click.echo(f"  {click.style(name, fg='cyan', bold=True)}  ({count} entries)")
        click.echo(f"    {path}")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("query")
@click.option("--db", default=None, help="Limit search to a specific database path.")
def search(query: str, db: Optional[str]):
    """Search all open databases."""
    _ensure_server()
    params = f"?q={query}"
    if db:
        params += f"&db={Path(db).resolve()}"
    result = _request("GET", f"/search{params}")
    entries = result.get("entries", result.get("results", []))
    total = result.get("total", len(entries))
    if total == 0:
        click.echo("No results.")
        return
    click.echo(f"{total} result(s):\n")
    for i, e in enumerate(entries, 1):
        title = click.style(e.get("title", ""), fg="cyan", bold=True)
        user = e.get("username", "")
        url = e.get("url", "")
        group = e.get("group_path", "")
        click.echo(f"  {i}. {title}")
        if user:
            click.echo(f"     user: {user}")
        if url:
            click.echo(f"     url:  {url}")
        if group:
            click.echo(f"     path: {group}")
        click.echo()


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

@cli.command("get")
@click.argument("query")
@click.option("--show", is_flag=True, help="Print password instead of copying to clipboard.")
@click.option("--db", default=None, help="Limit search to a specific database path.")
def get_entry(query: str, show: bool, db: Optional[str]):
    """Search, pick a result interactively, and copy its password."""
    _ensure_server()
    params = f"?q={query}"
    if db:
        params += f"&db={Path(db).resolve()}"
    result = _request("GET", f"/search{params}")
    entries = result.get("entries", result.get("results", []))
    if not entries:
        click.echo("No results.")
        return

    if len(entries) == 1:
        chosen = entries[0]
    else:
        click.echo(f"{len(entries)} result(s):\n")
        for i, e in enumerate(entries, 1):
            title = click.style(e.get("title", ""), fg="cyan", bold=True)
            user = e.get("username", "")
            click.echo(f"  {i}. {title}  ({user})")
        click.echo()
        idx = click.prompt("Pick entry", type=click.IntRange(1, len(entries)))
        chosen = entries[idx - 1]

    # Fetch full entry detail
    entry_uuid = chosen["uuid"]
    entry_db = chosen["db_path"]
    detail = _request("GET", f"/entry/{entry_uuid}?db={entry_db}")
    password = detail.get("password", "")

    if show:
        click.echo(f"Password: {password}")
    else:
        if _copy_to_clipboard(password):
            click.echo(click.style("Password copied to clipboard.", fg="green"))
        else:
            click.echo(click.style("Clipboard not available. Password:", fg="yellow"))
            click.echo(password)


def _copy_to_clipboard(text: str) -> bool:
    """Try to copy text to the system clipboard."""
    for cmd in (
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["pbcopy"],
        ["clip.exe"],
    ):
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            proc.communicate(text.encode())
            if proc.returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--daemon", is_flag=True, help="Start the server in the background.")
@click.option("--host", default=DEFAULT_HOST, help="Bind address.")
@click.option("--port", default=DEFAULT_PORT, type=int, help="Port number.")
def serve(daemon: bool, host: str, port: int):
    """Start the KPX API server."""
    if daemon:
        _start_daemon()
        click.echo(click.style("KPX server started in background.", fg="green"))
        return

    # Foreground
    from kpx.server import run_server
    run_server(host=host, port=port)
