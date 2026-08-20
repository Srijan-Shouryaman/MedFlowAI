from dataclasses import dataclass
from uuid import UUID

from contracts.schemas import ClinicalEvent, ClinicalEventValidationStatus


ALLOWED_ASSERTIONS = {"affirmed", "negated", "possible", "conditional"}
ALLOWED_CLINICAL_STATUSES = {"active", "inactive", "unknown", "resolved"}
ALLOWED_TEMPORAL_CONTEXTS = {"current", "historical", "past", "future", "unknown"}


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str


@dataclass(frozen=True)
class EventValidationResult:
    valid: bool
    event: ClinicalEvent
    issues: tuple[ValidationIssue, ...] = ()


class ClinicalEventValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        super().__init__(
            "; ".join(f"{issue.field}: {issue.message}" for issue in issues)
        )


def validate_event(
    event: ClinicalEvent,
    *,
    expected_source_document_id: UUID | None = None,
) -> EventValidationResult:
    issues: list[ValidationIssue] = []
    if expected_source_document_id and event.source_document_id != expected_source_document_id:
        issues.append(
            ValidationIssue(
                "source_document_id",
                "does not match the Step1Output document.",
            )
        )
    if event.validation_status != ClinicalEventValidationStatus.VALID:
        issues.append(ValidationIssue("validation_status", "event is not valid."))
    if event.source_text_span.end <= event.source_text_span.start:
        issues.append(ValidationIssue("source_text_span", "must contain text."))
    if event.source_text_span.end > len(event.original_text):
        issues.append(
            ValidationIssue(
                "source_text_span",
                "extends beyond original_text.",
            )
        )
    if event.assertion not in ALLOWED_ASSERTIONS:
        issues.append(ValidationIssue("assertion", "is not supported."))
    if event.clinical_status not in ALLOWED_CLINICAL_STATUSES:
        issues.append(ValidationIssue("clinical_status", "is not supported."))
    if event.temporal_context not in ALLOWED_TEMPORAL_CONTEXTS:
        issues.append(ValidationIssue("temporal_context", "is not supported."))
    if not event.normalized_concept.strip():
        issues.append(ValidationIssue("normalized_concept", "cannot be empty."))

    return EventValidationResult(
        valid=not issues,
        event=event,
        issues=tuple(issues),
    )


def validate_events(
    events: list[ClinicalEvent],
    *,
    expected_source_document_id: UUID,
) -> list[ClinicalEvent]:
    if not events:
        raise ClinicalEventValidationError(
            [ValidationIssue("clinical_events", "at least one event is required.")]
        )

    results = [
        validate_event(
            event,
            expected_source_document_id=expected_source_document_id,
        )
        for event in events
    ]
    issues = [issue for result in results for issue in result.issues]
    if issues:
        raise ClinicalEventValidationError(issues)

    return [
        result.event.model_copy(
            update={"validation_status": ClinicalEventValidationStatus.VALID}
        )
        for result in results
    ]
