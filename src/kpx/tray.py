"""KPX system tray application — wraps the FastAPI server for desktop use."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

import uvicorn
from PIL import Image, ImageDraw

from kpx import __version__
from kpx.auth import AuthManager
from kpx.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOST = "127.0.0.1"
PORT = 19455
TOOLTIP = "KPX \u2014 KeePass Bridge"
ICON_SIZE = 64
ICON_COLOR = "#89b4fa"
ICON_BG = "#1e1e2e"


# ---------------------------------------------------------------------------
# Icon generation
# ---------------------------------------------------------------------------

def _create_icon_image() -> Image.Image:
    """Generate a key icon with Pillow."""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), ICON_BG)
    draw = ImageDraw.Draw(img)

    # Key head (circle)
    cx, cy = 20, 20
    r = 12
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        outline=ICON_COLOR, width=3,
    )
    # Inner hole
    draw.ellipse(
        [cx - 4, cy - 4, cx + 4, cy + 4],
        outline=ICON_COLOR, width=2,
    )
    # Key shaft
    draw.line([(cx + r - 2, cy + r - 2), (52, 52)], fill=ICON_COLOR, width=3)
    # Key teeth
    draw.line([(44, 44), (44, 52)], fill=ICON_COLOR, width=3)
    draw.line([(50, 50), (50, 58)], fill=ICON_COLOR, width=3)

    return img


# ---------------------------------------------------------------------------
# Server thread
# ---------------------------------------------------------------------------

class _ServerThread(threading.Thread):
    """Runs uvicorn in a daemon thread."""

    def __init__(self) -> None:
        super().__init__(daemon=True, name="kpx-server")
        self._server: Optional[uvicorn.Server] = None

    def run(self) -> None:
        from kpx.server import app

        config = uvicorn.Config(
            app, host=HOST, port=PORT, log_level="info",
        )
        self._server = uvicorn.Server(config)
        self._server.run()

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.should_exit = True


# ---------------------------------------------------------------------------
# Tkinter dialogs (run on demand)
# ---------------------------------------------------------------------------

def _tk_open_file() -> Optional[str]:
    """Show a file-open dialog for .kdbx files. Returns path or None."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title="Select KeePass Database",
        filetypes=[("KeePass Database", "*.kdbx"), ("All Files", "*.*")],
    )
    root.destroy()
    return path if path else None


def _tk_ask_password(db_name: str) -> Optional[str]:
    """Prompt for a password using tkinter."""
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    password = simpledialog.askstring(
        "KPX \u2014 Unlock Database",
        f"Password for {db_name}:",
        show="*",
        parent=root,
    )
    root.destroy()
    return password


def _tk_show_message(title: str, message: str) -> None:
    """Show a simple message box."""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    messagebox.showinfo(title, message, parent=root)
    root.destroy()


# ---------------------------------------------------------------------------
# Tray application
# ---------------------------------------------------------------------------

class KPXTray:
    """System tray application for KPX."""

    def __init__(self) -> None:
        self._server_thread = _ServerThread()
        self._db = DatabaseManager()
        self._auth = AuthManager()
        self._icon: Any = None  # pystray.Icon, typed as Any to avoid import

    # -- Actions -----------------------------------------------------------

    def _unlock_database(self, icon: Any, item: Any) -> None:
        """Open file dialog, prompt for password, unlock."""
        db_path = _tk_open_file()
        if not db_path:
            return

        db_name = Path(db_path).stem
        password = _tk_ask_password(db_name)
        if not password:
            return

        try:
            info = self._db.unlock(db_path=db_path, password=password)
            count = info.entry_count if hasattr(info, "entry_count") else "?"
            icon.notify(f"Unlocked {db_name} \u2014 {count} entries", "KPX")
        except Exception as exc:
            _tk_show_message("KPX \u2014 Unlock Failed", str(exc))

        icon.update_menu()

    def _lock_database(self, db_path: str) -> Any:
        """Return a callback that locks a specific database."""
        def _do_lock(icon: Any, item: Any) -> None:
            name = Path(db_path).stem
            self._db.lock(db_path)
            icon.notify(f"Locked {name}", "KPX")
            icon.update_menu()
        return _do_lock

    def _show_pairing_code(self, icon: Any, item: Any) -> None:
        """Generate and display a pairing code."""
        code = self._auth.generate_pairing_code()
        _tk_show_message(
            "KPX \u2014 Pairing Code",
            f"Pairing code:\n\n{code}\n\nEnter this in your CLI or browser extension.",
        )

    def _quit(self, icon: Any, item: Any) -> None:
        """Stop everything and exit."""
        self._db.lock_all()
        self._server_thread.shutdown()
        icon.stop()

    # -- Menu building -----------------------------------------------------

    def _build_open_dbs_submenu(self) -> list:
        """Build submenu items for currently open databases."""
        import pystray

        databases = self._db.get_databases()
        if not databases:
            return [pystray.MenuItem("(none)", None, enabled=False)]

        items = []
        for db_info in databases:
            name = db_info.name if hasattr(db_info, "name") else Path(db_info.path).stem
            count = db_info.entry_count if hasattr(db_info, "entry_count") else "?"
            db_path = db_info.path if hasattr(db_info, "path") else str(db_info)
            items.append(
                pystray.MenuItem(
                    f"{name} ({count} entries) \u2014 Lock",
                    self._lock_database(db_path),
                )
            )
        return items

    def _get_auto_lock_label(self) -> str:
        timeout_sec = self._db.get_auto_lock_timeout()
        if timeout_sec <= 0:
            return "Auto-lock: disabled"
        minutes = timeout_sec / 60
        if minutes == int(minutes):
            return f"Auto-lock: {int(minutes)} min"
        return f"Auto-lock: {minutes:.1f} min"

    def _build_menu(self) -> Any:
        import pystray

        return pystray.Menu(
            pystray.MenuItem(
                f"Server: running on :{PORT}",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Unlock Database...",
                self._unlock_database,
            ),
            pystray.MenuItem(
                "Open Databases",
                pystray.Menu(lambda: self._build_open_dbs_submenu()),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Pairing Code",
                self._show_pairing_code,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: self._get_auto_lock_label(),
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    # -- Auto-lock monitor -------------------------------------------------

    def _auto_lock_monitor(self) -> None:
        """Background thread that checks for idle timeout."""
        while True:
            time.sleep(60)
            locked = self._db.check_idle()
            if locked and self._icon is not None:
                self._icon.notify(
                    "All databases locked due to inactivity", "KPX"
                )
                self._icon.update_menu()

    # -- Entry point -------------------------------------------------------

    def run(self) -> None:
        """Start the server and display the tray icon."""
        import pystray

        # Start the FastAPI server in background
        self._server_thread.start()

        # Start idle-lock monitor
        monitor = threading.Thread(
            target=self._auto_lock_monitor, daemon=True, name="kpx-idle-monitor",
        )
        monitor.start()

        # Wait briefly for server to come up
        time.sleep(0.5)

        # Create and run the tray icon (blocks on the main thread)
        self._icon = pystray.Icon(
            name="kpx",
            icon=_create_icon_image(),
            title=TOOLTIP,
            menu=self._build_menu(),
        )
        self._icon.run()


def main() -> None:
    """Entry point for ``kpx-tray`` script and ``kpx tray`` command."""
    tray = KPXTray()
    tray.run()


if __name__ == "__main__":
    main()
