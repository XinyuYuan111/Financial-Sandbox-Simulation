from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SandboxError(Exception):
    error_code: str
    message: str
    field_path: str | None = None
    retryable: bool = False
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


class ConflictError(SandboxError):
    def __init__(self, message: str, *, error_code: str = "STATE_CONFLICT") -> None:
        super().__init__(error_code=error_code, message=message)


class NotFoundError(SandboxError):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            error_code="NOT_FOUND",
            message=f"{resource} '{resource_id}' was not found",
        )


class ValidationError(SandboxError):
    def __init__(self, message: str, *, field_path: str | None = None) -> None:
        super().__init__(
            error_code="VALIDATION_FAILED",
            message=message,
            field_path=field_path,
        )


class MissingCausalStateError(SandboxError):
    def __init__(self, message: str, *, field_path: str | None = None) -> None:
        super().__init__(
            error_code="MISSING_CAUSAL_STATE",
            message=message,
            field_path=field_path,
        )
