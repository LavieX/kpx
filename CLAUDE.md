# KPX — KeePass Credential Bridge

## What is this?
CLI + local server + Firefox browser extension that replaces KeePassXC's broken native messaging with a reliable localhost HTTP API. Supports multiple `.kdbx` files open simultaneously.

## Architecture
- **CLI** (`kpx`): Click-based, thin HTTP client that talks to the server
- **Server**: FastAPI on `127.0.0.1:19455`, pairing-based auth, thread-safe multi-DB manager
- **Extension**: Firefox Manifest V3, inline badge on login fields, dropdown autofill
- **Client library**: `kpx.client.KPXClient` for use in scripts/automation

## Using KPX credentials in other projects

```python
from kpx.client import KPXClient

kpx = KPXClient()

# Get username + password for a URL (one call)
creds = kpx.get_credentials("https://www.target.com")
username = creds["username"]
password = creds["password"]

# Search by keyword
results = kpx.search("amazon")

# Check if server is running and token is valid
if kpx.is_available():
    ...
```

**Prerequisites**: KPX server must be running (`kpx serve --daemon`) with at least one database unlocked (`kpx unlock /path/to.kdbx`). Token at `~/.kpx/session.token` must be valid (24h TTL, created via `kpx pair`).

**No extra dependencies** — KPXClient uses only stdlib (`urllib`). Any Python project can import it as long as `kpx` is installed (`pip install -e ~/develop/kpx`).

## CLI commands
- `kpx serve [--daemon]` — start the server
- `kpx pair` — pair CLI with server (generates session token)
- `kpx unlock <path.kdbx>` — unlock a database (prompts for password)
- `kpx lock <path> | --all` — lock database(s)
- `kpx status` — show server status and open databases
- `kpx search <query>` — search entries across all open DBs
- `kpx get <query>` — search, pick, copy password to clipboard
- `kpx generate` — generate secure password (`--length`, `--no-symbols`, etc.)
- `kpx config [--auto-lock <minutes>]` — view/set auto-lock timeout (default 15min, 0 to disable)

## Server API endpoints
All on `http://127.0.0.1:19455`. Auth via `Authorization: Bearer <token>` header.

| Endpoint | Auth | Description |
|---|---|---|
| `GET /health` | No | Server status |
| `POST /pair` | No | Pairing flow (generate code / validate code) |
| `GET /generate` | No | Password generator |
| `POST /unlock` | Yes | Unlock a .kdbx file |
| `POST /lock` | Yes | Lock database(s) |
| `GET /databases` | Yes | List open databases |
| `GET /search?q=<query>` | Yes | Search entries |
| `GET /entry/<uuid>?db=<path>` | Yes | Full entry with password |
| `GET /autofill?url=<url>` | Yes | Best match for URL |
| `GET /config` | Yes | View config |
| `POST /config` | Yes | Update config |

## Key files
- `src/kpx/cli.py` — Click CLI entry point
- `src/kpx/server.py` — FastAPI app
- `src/kpx/db_manager.py` — Multi-database manager (singleton, thread-safe)
- `src/kpx/auth.py` — Pairing codes + session tokens
- `src/kpx/models.py` — Pydantic schemas
- `src/kpx/client.py` — Lightweight client for scripts/automation
- `extension/` — Firefox/Chrome browser extension

## Important notes
- Server binds `127.0.0.1` only — never exposed to network
- Runs on WSL2, browser on Windows — localhost forwarding works
- Server restart invalidates all tokens (CLI + extension must re-pair)
- Firefox extension loaded as temporary add-on via `about:debugging`
- CORS accepts both `chrome-extension://` and `moz-extension://` origins
