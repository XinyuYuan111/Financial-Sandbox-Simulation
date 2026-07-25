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
    signal_direction: object = None,
    signal_confidence_milli: object = None,
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
    if channel != "PrivateChannel" and targets:
        raise ValidationError("public information channels cannot declare target_ids")
    if (signal_direction is None) != (signal_confidence_milli is None):
        raise ValidationError("information signal direction and confidence must be supplied together")
    if signal_direction is not None and signal_direction not in {"bullish", "bearish", "neutral"}:
        raise ValidationError("unsupported information signal direction")
    if signal_confidence_milli is not None and (
        type(signal_confidence_milli) is not int or not 0 <= signal_confidence_milli <= 1_000
    ):
        raise ValidationError("information signal confidence must be within 0..1000")
    item = {
        "information_id": information_id or new_id("info"),
        "source_id": source_id,
        "channel": channel,
        "rendered_content": content[:4_000],
        "sim_time_us": sim_time_us,
        "target_ids": targets,
        "visibility": "agent_private" if channel == "PrivateChannel" else "public",
        "derived_from_info_id": derived_from_info_id,
    }
    if signal_direction is not None:
        item["signal_direction"] = signal_direction
        item["signal_confidence_milli"] = signal_confidence_milli
    return item
