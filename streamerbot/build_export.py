#!/usr/bin/env python3
"""Build streamerbot/KinkajouBridge.sb from KinkajouBridgeRouter.cs."""

from __future__ import annotations

import base64
import gzip
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "KinkajouBridgeRouter.cs"
OUTPUT = ROOT / "KinkajouBridge.sb"

ACTION_ID = "a7c3e1f2-9b4d-4e6a-8c1f-2d5e7a9b0c3d"
COMMENT_IDS = [
    "b1c2d3e4-f5a6-4789-8abc-def012345601",
    "b1c2d3e4-f5a6-4789-8abc-def012345602",
    "b1c2d3e4-f5a6-4789-8abc-def012345603",
]
CODE_ID = "c0de0001-2345-4678-9abc-def012345678"


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    byte_code = base64.b64encode(source.encode("utf-8")).decode("ascii")

    payload = {
        "meta": {
            "name": "Kinkajou Bridge",
            "author": "Phai Ting",
            "version": "1.0.0",
            "description": (
                "Router action for Kinkajou Bridge. Bridge calls this action with "
                "event_name; it runs your matching Kinkajou - … user action when present."
            ),
            "autoRunAction": None,
            "minimumVersion": None,
        },
        "data": {
            "actions": [
                {
                    "id": ACTION_ID,
                    "queue": "00000000-0000-0000-0000-000000000000",
                    "enabled": True,
                    "excludeFromHistory": False,
                    "excludeFromPending": False,
                    "name": "Kinkajou Bridge",
                    "group": "Kinkajou",
                    "alwaysRun": False,
                    "randomAction": False,
                    "concurrent": False,
                    "triggers": [],
                    "subActions": [
                        {
                            "value": "Kinkajou Bridge — event router",
                            "color": "",
                            "id": COMMENT_IDS[0],
                            "weight": 0.0,
                            "type": 1009,
                            "parentId": None,
                            "enabled": True,
                            "index": 0,
                        },
                        {
                            "value": (
                                "Called by Kinkajou Bridge with event_name "
                                "(for example Kinkajou - Print Started). "
                                "Runs that user action when it exists."
                            ),
                            "color": "",
                            "id": COMMENT_IDS[1],
                            "weight": 0.0,
                            "type": 1009,
                            "parentId": None,
                            "enabled": True,
                            "index": 1,
                        },
                        {
                            "value": (
                                "Source: https://github.com/phai-ting/kinkajou-bridge/"
                                "tree/main/streamerbot"
                            ),
                            "color": "",
                            "id": COMMENT_IDS[2],
                            "weight": 0.0,
                            "type": 1009,
                            "parentId": None,
                            "enabled": True,
                            "index": 2,
                        },
                        {
                            "name": "Kinkajou Bridge Router",
                            "description": (
                                "Route Bridge events to user actions named like "
                                "Kinkajou - Print Started."
                            ),
                            "references": [
                                r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\mscorlib.dll"
                            ],
                            "byteCode": byte_code,
                            "precompile": False,
                            "delayStart": False,
                            "saveResultToVariable": False,
                            "saveToVariable": None,
                            "id": CODE_ID,
                            "weight": 0.0,
                            "type": 99999,
                            "parentId": None,
                            "enabled": True,
                            "index": 3,
                        },
                    ],
                    "collapsedGroups": [],
                }
            ],
            "queues": [],
            "commands": [],
            "websocketServers": [],
            "websocketClients": [],
            "timers": [],
        },
        "version": 23,
        "exportedFrom": "1.0.4",
        "minimumVersion": "1.0.0-alpha.1",
    }

    raw = json.dumps(payload, indent=2).encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    encoded = base64.b64encode(b"SBAE" + compressed).decode("ascii")
    OUTPUT.write_text(encoded + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(encoded)} chars)")


if __name__ == "__main__":
    # uuid imported for possible future use; keep IDs stable across rebuilds.
    _ = uuid
    main()
