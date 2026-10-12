#!/usr/bin/env python3
"""Zip the browser extension for the Chrome Web Store / GitHub Releases.

    python3 scripts/package_extension.py   ->  dist/pregame-extension-<version>.zip
"""
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
SKIP_DIRS = {"test", "node_modules"}
SKIP_FILES = {"package.json", ".DS_Store"}

version = json.loads((EXT / "manifest.json").read_text())["version"]
out = ROOT / "dist" / f"pregame-extension-{version}.zip"
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for path in sorted(EXT.rglob("*")):
        rel = path.relative_to(EXT)
        if path.is_dir() or rel.parts[0] in SKIP_DIRS or path.name in SKIP_FILES:
            continue
        z.write(path, rel.as_posix())
print(out)
