from __future__ import annotations

from pathlib import Path

# Visible in Explorer when users open the custom overlays folder.
INSTRUCTIONS_FILENAME = "Put custom overlays here.txt"

_INSTRUCTIONS = """\
Kinkajou Bridge — custom overlays
=================================

Drop your own OBS overlay folders in this directory. Bridge serves them at:

  http://127.0.0.1:29067/bridge/custom/<folder-name>/

Example
-------
Create a folder named "my-overlay" next to this file:

  my-overlay/
    index.html
    overlay.css      (optional)
    overlay.js       (optional)

Then open in OBS as a Browser Source:

  http://127.0.0.1:29067/bridge/custom/my-overlay/?printer=YOUR_PRINTER_ID

Optional query params: theme=dark|light, token=…, interval=2000

Shared helper
-------------
Built-in overlays use Bridge's helper script. From a custom page, load it with
an absolute path (do not use ../_shared — that path is for built-ins only):

  <script src="/bridge/_shared/bridge-client.js"></script>

Then call KinkajouBridge.watchPrinter({ onUpdate, onError }) or use fetch /
WebSocket against the local API yourself.

Docs
----
  https://kinkajou.dev/bridge/overlay-developer/custom/
  https://kinkajou.dev/bridge/overlay-developer/api/

Notes
-----
- This folder lives under your Bridge data directory so updates do not wipe it.
- Each overlay needs its own subfolder with an index.html.
- Do not put secrets in overlay files; use the token= query param if you enable
  an API token.
"""


def ensure_custom_overlays_dir(root: Path) -> Path:
    """Create the custom overlays directory and seed the instructions file."""
    root.mkdir(parents=True, exist_ok=True)
    instructions = root / INSTRUCTIONS_FILENAME
    if not instructions.exists():
        instructions.write_text(_INSTRUCTIONS, encoding="utf-8", newline="\n")
    return root
