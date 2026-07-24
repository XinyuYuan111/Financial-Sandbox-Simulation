from __future__ import annotations

from sandbox.core.errors import ValidationError
from sandbox.core.ids import new_id


SUPPORTED_CHANNELS = {"PublicFeed", "OfficialAnnouncement", "TradingTerminal", "PrivateChannel"}


def publish_information(
    *,
    source_id: str,
    channel: str,
    content: str,
    sim_time_us: int,
    target_ids: list[str] | None = None,
    derived_from_info_id: str | None = None,
    information_id: str | None = None,
) -> dict[str, object]:
    if channel not in SUPPORTED_CHANNELS:
        raise ValidationError(f"unsupported information channel '{channel}'")
    if not content.strip():
        raise ValidationError("information content cannot be empty")
    targets = target_ids or []
    if channel == "PrivateChannel" and not targets:
        raise ValidationError("private information requires target_ids")
    return {
        "information_id": information_id or new_id("info"),
        "source_id": source_id,
        "channel": channel,
        "rendered_content": content[:4_000],
        "sim_time_us": sim_time_us,
        "target_ids": targets,
        "visibility": "agent_private" if channel == "PrivateChannel" else "public",
        "derived_from_info_id": derived_from_info_id,
    }
