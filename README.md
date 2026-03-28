# KPX

**KeePass credentials, everywhere — without the browser extension pain.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/LavieX/kpx/pulls)

---

## The Problem

KeePassXC's browser integration relies on **native messaging** — a fragile protocol where the browser launches a helper binary through a JSON manifest registered in the OS.

It breaks. A lot.

- **Snap/Flatpak browsers** can't see the native host (sandbox boundary)
- **WSL2 users** run KeePass on Linux but browse on Windows (OS boundary)
- **Browser updates** silently break the manifest path
- **Startup order** matters — open the browser before KeePassXC and nothing works
- **179+ open issues** on `keepassxc-browser` and counting

If you've ever stared at "Cannot connect to KeePassXC" after a routine update, KPX is for you.

## The Solution

KPX replaces native messaging with a **localhost HTTP server**. Your `.kdbx` files stay where they are. The browser extension talks to `127.0.0.1:19455` instead of a flaky native messaging pipe.

- Works across **OS boundaries** (KPX on WSL2, browser on Windows)
- Works across **sandbox boundaries** (Snap, Flatpak, containers)
- **Never breaks** on browser updates — it's just HTTP
- Supports **multiple `.kdbx` databases** open simultaneously
- Full **CLI** for terminal workflows and scripting

## Quick Start

```bash
# 1. Install
pip install git+https://github.com/LavieX/kpx.git

# 2. Start the server
kpx serve --daemon

# 3. Pair your CLI and unlock a database
kpx pair
kpx unlock ~/passwords.kdbx

# 4. Load the browser extension (see Browser Extension section below)
```

That's it. Your credentials are now available in the browser and on the command line.

## Features

- **Multi-database support** — unlock multiple `.kdbx` files at once, search across all of them
- **CLI + Server + Extension** — use whichever interface fits the moment
- **Chrome + Firefox** — Manifest V3 extension works in both browsers
- **Inline autofill badge** — small icon appears in login fields, click to fill
- **Password generator** — configurable length, symbols, clipboard copy
- **Auto-lock** — databases lock after 15 minutes of inactivity (configurable)
- **Scriptable API** — `KPXClient` class for Python automation (Playwright, CI, etc.)
- **System tray app** — `kpx-tray` for quick status and lock/unlock from the taskbar

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  Browser     │     │   CLI            │     │   Python Scripts    │
│  Extension   │     │   (kpx)          │     │   (KPXClient)       │
└──────┬───────┘     └────────┬─────────┘     └──────────┬──────────┘
       │                      │                          │
       │    HTTP requests to 127.0.0.1:19455             │
       └──────────────────────┼──────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  FastAPI Server     │
                    │  (auth + routing)   │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  DatabaseManager   │
                    │  (thread-safe,     │
                    │   multi-DB)        │
                    └─────────┬──────────┘
                              │
                 ┌────────────┼────────────┐
                 ▼            ▼            ▼
            work.kdbx   personal.kdbx  shared.kdbx
```

## Security

KPX takes security seriously. It is **not** a revival of the deprecated KeePassHTTP — the architecture is designed from scratch with modern threat modeling.

| Layer | Protection |
|---|---|
| **Network** | Server binds to `127.0.0.1` only — never exposed to the network |
| **Authentication** | Pairing-based auth: 6-digit code exchange generates a bearer token (24h TTL) |
| **Authorization** | All credential endpoints require `Authorization: Bearer <token>` |
| **DNS rebinding** | `Host` header validation rejects requests not addressed to `127.0.0.1` or `localhost` |
| **CORS** | Only `chrome-extension://` and `moz-extension://` origins accepted |
| **Rate limiting** | Per-endpoint sliding-window rate limiter; pairing capped at 5 attempts per minute |
| **Token lifecycle** | Server restart invalidates all tokens — clients must re-pair |
| **Log hygiene** | Sensitive endpoints (entry lookups, autofill) are redacted from access logs |

## CLI Reference

| Command | Description |
|---|---|
| `kpx serve [--daemon]` | Start the server (optionally in background) |
| `kpx pair` | Pair CLI with the server, generates session token |
| `kpx unlock <path.kdbx>` | Unlock a database (prompts for password) |
| `kpx lock <path> \| --all` | Lock a database or all databases |
| `kpx status` | Show server status and open databases |
| `kpx search <query>` | Search entries across all open databases |
| `kpx get <query>` | Search, pick an entry, copy password to clipboard |
| `kpx generate` | Generate a password (`--length`, `--no-symbols`, etc.) |
| `kpx config` | View or set configuration (`--auto-lock <minutes>`) |

## API Reference

All endpoints are on `http://127.0.0.1:19455`.

| Endpoint | Auth | Description |
|---|---|---|
| `GET /health` | No | Server health check |
| `POST /pair` | No | Pairing flow (generate/validate code) |
| `GET /generate` | No | Password generator |
| `POST /unlock` | Yes | Unlock a `.kdbx` file |
| `POST /lock` | Yes | Lock database(s) |
| `GET /databases` | Yes | List open databases |
| `GET /search?q=<query>` | Yes | Search entries |
| `GET /entry/<uuid>?db=<path>` | Yes | Get full entry with password |
| `GET /autofill?url=<url>` | Yes | Best credential match for a URL |
| `GET /config` | Yes | View configuration |
| `POST /config` | Yes | Update configuration |

See [CLAUDE.md](CLAUDE.md) for detailed API documentation.

## Using KPX in Scripts

`KPXClient` is a zero-dependency client (stdlib `urllib` only) for using KPX credentials in automation — test suites, scrapers, CI pipelines.

```python
from kpx.client import KPXClient

kpx = KPXClient()

# One-call credential lookup by URL
creds = kpx.get_credentials("https://www.example.com")
username = creds["username"]
password = creds["password"]

# Search by keyword
results = kpx.search("staging-db")

# Check server availability
if kpx.is_available():
    print("KPX is ready")
```

**Example: Playwright login automation**

```python
from playwright.sync_api import sync_playwright
from kpx.client import KPXClient

kpx = KPXClient()
creds = kpx.get_credentials("https://app.example.com")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://app.example.com/login")
    page.fill("#username", creds["username"])
    page.fill("#password", creds["password"])
    page.click("button[type=submit]")
```

**Prerequisites**: The KPX server must be running (`kpx serve --daemon`) with at least one database unlocked. A valid session token must exist at `~/.kpx/session.token` (created via `kpx pair`, 24h TTL).

## Browser Extension

### Chrome

1. Open `chrome://extensions/`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `extension/` directory from this repo

### Firefox

1. Open `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on**
3. Select `extension/manifest.json`

Once loaded, the extension adds an autofill badge to login fields. Click the badge or use the popup to search and fill credentials.

## System Tray

Run the tray app for quick access to server status and database management from the taskbar:

```bash
kpx-tray
```

Requires `pystray` and `Pillow` (included in dependencies).

## Contributing

Contributions are welcome! Here's how to get started:

```bash
# Clone and install in development mode
git clone https://github.com/LavieX/kpx.git
cd kpx
pip install -e ".[dev]"

# Run the test suite
pytest
```

Please open an issue before starting work on large changes. For bugs and feature requests, use the [issue templates](https://github.com/LavieX/kpx/issues/new/choose).

## License

[MIT](LICENSE) -- 2026 LavieX
