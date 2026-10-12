"""State transitions for a scheduled care occurrence."""

from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum

from rest_framework.exceptions import ValidationError

from ..models import Occurrence


class OccurrenceAction(StrEnum):
    ACKNOWLEDGE = "acknowledge"
    COMPLETE = "complete"
    SKIP = "skip"
    SNOOZE = "snooze"


def _acknowledge(occurrence: Occurrence, _until: datetime | None, now: datetime) -> None:
    if occurrence.state in (Occurrence.State.COMPLETED, Occurrence.State.SKIPPED):
        raise ValidationError({"action": "Occurrence is closed"})
    if occurrence.state == Occurrence.State.PENDING:
        occurrence.state = Occurrence.State.ACKNOWLEDGED
        occurrence.acknowledged_at = now


def _complete(occurrence: Occurrence, _until: datetime | None, now: datetime) -> None:
    if occurrence.state == Occurrence.State.SKIPPED:
        raise ValidationError({"action": "Occurrence was skipped"})
    if occurrence.state != Occurrence.State.COMPLETED:
        occurrence.state = Occurrence.State.COMPLETED
        occurrence.completed_at = now
        occurrence.acknowledged_at = occurrence.acknowledged_at or now


def _skip(occurrence: Occurrence, _until: datetime | None, now: datetime) -> None:
    if occurrence.state == Occurrence.State.COMPLETED:
        raise ValidationError({"action": "Occurrence was completed"})
    if occurrence.state != Occurrence.State.SKIPPED:
        occurrence.state = Occurrence.State.SKIPPED
        occurrence.acknowledged_at = occurrence.acknowledged_at or now


def _snooze(occurrence: Occurrence, until: datetime | None, now: datetime) -> None:
    if occurrence.state not in (Occurrence.State.PENDING, Occurrence.State.ACKNOWLEDGED):
        raise ValidationError({"action": "Cannot snooze a closed occurrence"})
    if until is None or not now < until <= now + timedelta(hours=24):
        raise ValidationError({"snoozed_until": "Must be within the next 24 hours"})
    occurrence.snoozed_until = until
    occurrence.state = Occurrence.State.PENDING
    occurrence.acknowledged_at = None


_HANDLERS: dict[OccurrenceAction, Callable[[Occurrence, datetime | None, datetime], None]] = {
    OccurrenceAction.ACKNOWLEDGE: _acknowledge,
    OccurrenceAction.COMPLETE: _complete,
    OccurrenceAction.SKIP: _skip,
    OccurrenceAction.SNOOZE: _snooze,
}


def apply_occurrence_action(
    occurrence: Occurrence, action: str, snoozed_until: datetime | None, now: datetime
) -> OccurrenceAction:
    try:
        selected = OccurrenceAction(action)
    except ValueError as exc:
        raise ValidationError({"action": "Unknown action"}) from exc
    _HANDLERS[selected](occurrence, snoozed_until, now)
    return selected
