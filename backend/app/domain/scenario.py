"""Unit 18 (MEADOWOPS-DOM-011, business id MEADOWOPS-DOMAIN-009, PRD 6.4):
pure scenario-builder domain logic — the draft/approved/active/cancelled
state machine, approve-time validation, and the deterministic ground-truth
snapshot builder. No DB or Claude API access here (same layering as
app.domain.ledger/app.domain.reporting_sync) — app.services.scenario_service
is the only caller, and owns the ORM/session/AI-boundary concerns this
module deliberately stays free of.

`regenerate` (6.4) had no AI to be non-deterministic about at this unit -
it just re-ran build_ground_truth_from_exception_flag against the source
flag's current data. Unit 22 (app.services.scenario_service.
regenerate_scenario) now also calls Claude for the four narrative fields
and uncertainty on every regenerate call; build_ground_truth_from_
exception_flag below still owns only the mechanically-derived known_cause/
evidence half of that package.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

# (from, to) — every valid scenario_status transition (matches the
# stateMachines block registered on MEADOWOPS-DOM-011). Anything not listed
# here is invalid by omission, including every self-transition and every
# transition out of the terminal "cancelled" state or the terminal-for-this-
# unit "active" state (activation is the end of this unit's own lifecycle —
# no further status change ships until U21/U21a's delivery infrastructure
# exists to act on it).
VALID_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("draft", "approved"),
        ("draft", "cancelled"),
        ("approved", "active"),
        ("approved", "cancelled"),
    }
)


def can_transition(from_status: str, to_status: str) -> bool:
    return (from_status, to_status) in VALID_TRANSITIONS


REQUIRED_GROUND_TRUTH_FIELDS: tuple[str, ...] = (
    "known_cause",
    "evidence",
    "supporting_signals",
    "distractors",
    "expected_considerations",
    "acceptable_conclusions",
    "unacceptable_conclusions",
    "uncertainty",
)


@dataclass(frozen=True)
class ExceptionFlagSnapshot:
    """The subset of app.db.exception_flags.ExceptionFlag's columns this
    module needs, decoupled from the ORM row itself (app.services.
    scenario_service converts one to the other) — same reason
    app.domain.ledger keeps DecisionEventStatus free of any db import."""

    id: str
    category: str
    product_id: str | None
    warehouse_id: str | None
    purchase_order_id: str | None
    shipment_id: str | None
    simulation_date: date
    first_detected_simulation_date: date
    measured_value: Decimal | None
    threshold_value: Decimal
    resolved_at: datetime | None


class ExceptionFlagNotOpenError(ValueError):
    """Raised when a scenario is created or regenerated against a flag that
    is no longer open (DD-24 point 2 requires a *real open* flag — one
    that has since auto-resolved is no longer the imperfection it claimed
    to snapshot, so it can't seed a new/refreshed scenario)."""


def build_ground_truth_from_exception_flag(flag: ExceptionFlagSnapshot) -> dict:
    """Deterministic skeleton, not an AI-generated package - `known_cause`
    and `evidence` are mechanically derivable straight from the flag's own
    columns, so this function fills those in; the four narrative fields a
    real evidence package needs (supporting_signals, distractors,
    expected_considerations, both conclusion lists) start empty here, since
    this function alone has no way to generate them. Two different callers
    fill them in afterward: app.services.scenario_service.
    create_scenario_from_exception_flag leaves them for the Builder's own
    "edit" step (6.4); regenerate_scenario (Unit 22) instead calls Claude
    (app.domain.scenario_generation) to (re)generate them on every call.
    Either way the scenario must pass validate_for_approval below before
    approval. `uncertainty` likewise starts as a placeholder here, replaced
    by whichever of those two paths ran.

    Raises ExceptionFlagNotOpenError if the flag has already resolved —
    security/data-integrity review of this unit: a scenario silently built
    from stale, no-longer-true evidence is exactly the failure U17's own
    frozen-artifact design was built to avoid elsewhere.
    """
    if flag.resolved_at is not None:
        raise ExceptionFlagNotOpenError(
            f"exception flag {flag.id} is no longer open (resolved at {flag.resolved_at})"
        )

    entity_bits = [
        f"{name}={value}"
        for name, value in (
            ("product_id", flag.product_id),
            ("warehouse_id", flag.warehouse_id),
            ("purchase_order_id", flag.purchase_order_id),
            ("shipment_id", flag.shipment_id),
        )
        if value is not None
    ]
    entity_desc = ", ".join(entity_bits) if entity_bits else "no linked entity"

    known_cause = (
        f"A '{flag.category}' exception was detected ({entity_desc}): measured "
        f"value {flag.measured_value} against threshold {flag.threshold_value}, "
        f"first observed {flag.first_detected_simulation_date}, still open as of "
        f"{flag.simulation_date}."
    )
    evidence = {
        "source_exception_flag_id": flag.id,
        "category": flag.category,
        "product_id": flag.product_id,
        "warehouse_id": flag.warehouse_id,
        "purchase_order_id": flag.purchase_order_id,
        "shipment_id": flag.shipment_id,
        "simulation_date": flag.simulation_date.isoformat(),
        "first_detected_simulation_date": flag.first_detected_simulation_date.isoformat(),
        "measured_value": str(flag.measured_value) if flag.measured_value is not None else None,
        "threshold_value": str(flag.threshold_value),
    }
    return {
        "known_cause": known_cause,
        "evidence": evidence,
        "supporting_signals": [],
        "distractors": [],
        "expected_considerations": [],
        "acceptable_conclusions": [],
        "unacceptable_conclusions": [],
        "uncertainty": "",
    }


def validate_for_approval(
    *, ground_truth: dict, difficulty_tier: str | None, competency_cluster: str | None
) -> list[str]:
    """The slice of PRD 6.4's approve-time validation checklist checked
    mechanically here (DD-24 point 3): the ground-truth package is complete
    (all seven named fields present and non-empty) and difficulty/
    competency targeting is set. Unit 22 gave this package real
    AI-generated narrative text to evaluate, but 6.4's KPI-claim-correctness
    and no-world-state-contradiction checks are still not implemented here
    - by the same U17 precedent that put SR-1/SR-3 out of scope of their
    own unit (see app.domain.reporting_sync's docstring), those two checks
    are deferred to Phase 3's "full edge case catalog" unit (U30), not
    folded into this unit's own scope.

    Returns the list of validation errors (empty means valid) rather than
    raising, so the Draft-stays-in-Draft rejection path (PRD 9.2's own
    required test case) is a plain data result the API layer can surface
    verbatim, not an exception it has to unpack.
    """
    errors: list[str] = []

    for field_name in REQUIRED_GROUND_TRUTH_FIELDS:
        value = ground_truth.get(field_name)
        if field_name == "evidence":
            if not isinstance(value, dict) or not value:
                errors.append(f"ground_truth.{field_name} must be a non-empty object")
        elif field_name in ("known_cause", "uncertainty"):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"ground_truth.{field_name} must be a non-empty string")
        else:
            if not isinstance(value, list) or not value:
                errors.append(f"ground_truth.{field_name} must be a non-empty list")

    if not difficulty_tier:
        errors.append("difficulty_tier is required")
    if not competency_cluster:
        errors.append("competency_cluster is required")

    return errors
