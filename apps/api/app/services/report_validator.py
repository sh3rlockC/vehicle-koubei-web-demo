from __future__ import annotations


REQUIRED_REPORT_KEYS = {
    "headline",
    "executive_summary",
    "strength_blocks",
    "weakness_blocks",
    "platform_difference_blocks",
    "action_blocks",
    "boss_brief",
}


def validate_report_payload(payload: dict) -> tuple[bool, list[str]]:
    missing = [key for key in REQUIRED_REPORT_KEYS if key not in payload]
    errors = [f"missing field: {key}" for key in missing]

    boss_brief = payload.get("boss_brief")
    if boss_brief is not None and not isinstance(boss_brief, list):
        errors.append("boss_brief must be a list")

    for list_key in [
        "strength_blocks",
        "weakness_blocks",
        "platform_difference_blocks",
        "action_blocks",
    ]:
        if list_key in payload and not isinstance(payload[list_key], list):
            errors.append(f"{list_key} must be a list")

    return (not errors, errors)
