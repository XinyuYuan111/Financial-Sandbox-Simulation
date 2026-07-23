from __future__ import annotations

from decimal import Decimal

from sandbox.core.errors import ValidationError


def require_int(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be an integer smallest-unit value", field_path=field)
    if value < minimum:
        raise ValidationError(f"{field} must be at least {minimum}", field_path=field)
    return value


def ceil_basis_points(amount: int, basis_points: int) -> int:
    require_int(amount, "amount")
    require_int(basis_points, "basis_points")
    return (amount * basis_points + 9_999) // 10_000


def reject_float(value: object, field: str) -> None:
    if isinstance(value, (float, Decimal)):
        raise ValidationError(f"binary or decimal floating point is forbidden for {field}", field_path=field)

