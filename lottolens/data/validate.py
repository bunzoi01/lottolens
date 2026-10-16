"""Validation for a single draw record."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .dates import is_valid_draw_date, now_sydney

MIN_NUMBER = 1
MAX_NUMBER = 45
PICK = 6


class DrawValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Draw:
    draw_date: date
    numbers: tuple[int, ...]
    supps: tuple[int, ...] | None = None
    draw_number: int | None = None
    source: str = "unknown"

    @property
    def key(self) -> str:
        return self.draw_date.isoformat()


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def check_draw(draw: Draw, *, allow_future: bool = False) -> ValidationResult:
    res = ValidationResult()
    nums = draw.numbers
    if len(nums) != PICK:
        res.errors.append(f"expected {PICK} winning numbers, got {len(nums)}")
    if len(set(nums)) != len(nums):
        res.errors.append("winning numbers are not unique")
    if any(not (MIN_NUMBER <= n <= MAX_NUMBER) for n in nums):
        res.errors.append(f"winning numbers must be within {MIN_NUMBER}-{MAX_NUMBER}")
    if draw.supps is not None:
        supps = draw.supps
        if len(supps) != 2:
            res.errors.append(f"expected 2 supplementary numbers, got {len(supps)}")
        if len(set(supps)) != len(supps):
            res.errors.append("supplementary numbers are not unique")
        if any(not (MIN_NUMBER <= n <= MAX_NUMBER) for n in supps):
            res.errors.append(f"supplementary numbers must be within {MIN_NUMBER}-{MAX_NUMBER}")
        if set(supps) & set(nums):
            res.errors.append("supplementary numbers must differ from the winning numbers")
    if not is_valid_draw_date(draw.draw_date):
        res.errors.append(
            f"{draw.draw_date} ({draw.draw_date:%A}) is not a Saturday or New Year draw date"
        )
    if not allow_future and draw.draw_date > now_sydney().date():
        res.errors.append(f"{draw.draw_date} is in the future")
    if draw.draw_number is not None and draw.draw_number <= 0:
        res.errors.append("draw number must be positive")
    return res


def make_draw(
    draw_date: date | str,
    numbers,
    supps=None,
    draw_number: int | None = None,
    source: str = "unknown",
) -> Draw:
    """Build a normalised (sorted) Draw and raise DrawValidationError if it's invalid."""
    if isinstance(draw_date, str):
        try:
            draw_date = date.fromisoformat(draw_date.strip())
        except ValueError as exc:
            raise DrawValidationError(f"invalid date {draw_date!r}") from exc
    try:
        nums = tuple(sorted(int(n) for n in numbers))
        sup = tuple(int(n) for n in supps) if supps else None
    except (TypeError, ValueError) as exc:
        raise DrawValidationError(f"non-integer number in draw {draw_date}") from exc
    draw = Draw(draw_date, nums, sup, int(draw_number) if draw_number else None, source)
    result = check_draw(draw)
    if not result.ok:
        raise DrawValidationError(f"{draw_date}: " + "; ".join(result.errors))
    return draw
