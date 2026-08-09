"""Streamer.bot action naming for the Kinkajou Bridge integration."""

from __future__ import annotations

from kinkajou_bridge.models import EventType

# Single entry action shipped in the Kinkajou Streamer.bot export.
# It looks up a user-owned action by `event_name` so re-importing the export
# does not overwrite user automation.
ROUTER_ACTION_NAME = "Kinkajou Bridge"

# Prefix for user-created handlers, e.g. "Kinkajou - Print Started".
USER_ACTION_PREFIX = "Kinkajou - "


def user_action_name(event_type: EventType | str) -> str:
    """Map a Bridge event type to the expected user Streamer.bot action name."""
    token = event_type.value if isinstance(event_type, EventType) else str(event_type)
    words = token.replace(".", " ").replace("_", " ").split()
    title = " ".join(part.capitalize() for part in words)
    return f"{USER_ACTION_PREFIX}{title}"
