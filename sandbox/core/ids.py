from __future__ import annotations

import uuid


def new_id(namespace: str) -> str:
    return f"{namespace}_{uuid.uuid4().hex}"


def deterministic_id(namespace: str, *parts: object) -> str:
    value = "|".join(str(part) for part in parts)
    return f"{namespace}_{uuid.uuid5(uuid.NAMESPACE_URL, value).hex}"

