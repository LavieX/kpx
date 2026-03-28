#!/usr/bin/env python3
"""
Build script for the KPX browser extension.

Usage:
    python3 extension/build.py

Generates two output directories from the source files in extension/:
    extension/chrome/   — Chrome-compatible (background.service_worker)
    extension/firefox/  — Firefox-compatible (background.scripts)

All JS/CSS/HTML/icons are identical; only manifest.json differs.
"""

import json
import os
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# Files and dirs to copy into both browser builds
COPY_ITEMS = [
    "background.js",
    "content.js",
    "popup.html",
    "popup.css",
    "popup.js",
    "icons",
]

# Items to skip when copying (build artifacts and this script)
SKIP = {"chrome", "firefox", "build.py", "__pycache__", "manifest.json"}


def load_source_manifest():
    manifest_path = SCRIPT_DIR / "manifest.json"
    with open(manifest_path) as f:
        return json.load(f)


def make_chrome_manifest(source):
    """Derive Chrome manifest: service_worker background, no gecko settings."""
    m = dict(source)
    m.pop("browser_specific_settings", None)
    m["background"] = {"service_worker": "background.js"}
    return m


def make_firefox_manifest(source):
    """Derive Firefox manifest: scripts background, keep gecko settings."""
    m = dict(source)
    m["background"] = {"scripts": ["background.js"]}
    return m


def copy_shared_files(dest: Path):
    """Copy all shared extension files into dest directory."""
    for item in COPY_ITEMS:
        src = SCRIPT_DIR / item
        dst = dest / item
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        elif src.is_file():
            shutil.copy2(src, dst)
        else:
            print(f"  WARNING: {item} not found, skipping")


def write_manifest(dest: Path, manifest: dict):
    manifest_path = dest / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def build():
    source = load_source_manifest()

    for browser, make_manifest in [("chrome", make_chrome_manifest), ("firefox", make_firefox_manifest)]:
        dest = SCRIPT_DIR / browser
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir()

        print(f"Building {browser}/ ...")
        copy_shared_files(dest)
        write_manifest(dest, make_manifest(source))
        print(f"  -> {dest}")

    print("\nDone. Load the extensions from:")
    print(f"  Chrome:  chrome://extensions -> Load unpacked -> {SCRIPT_DIR / 'chrome'}")
    print(f"  Firefox: about:debugging -> Load Temporary Add-on -> {SCRIPT_DIR / 'firefox' / 'manifest.json'}")


if __name__ == "__main__":
    build()
