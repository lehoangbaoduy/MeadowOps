"""Unit 18 (MEADOWOPS-DOM-011, business id MEADOWOPS-DOMAIN-009, PRD 6.4):
scenario builder — the transactional layer. Pure decision logic lives in
app.domain.scenario, same split as app.domain.exception_engine /
app.services.exception_engine.

Does not commit — caller-owns-the-transaction, same convention as every
other service module in this project (app.api.admin_scenarios commits
after each call, the same way app.api.master_data does).

`source_exception_flag_id` is read fresh from live.exception_flag on every
create/regenerate call, never cached — the flag's own resolution state is
exactly what app.domain.scenario.build_ground_truth_from_exception_flag
checks before snapshotting it (ExceptionFlagNotOpenError propagates
straight through both entry points here, unwrapped, since the domain
error message is already specific enough for the API layer to surface).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import CompetencyCluster, DifficultyTier, ScenarioSource, ScenarioStatus, ScenarioType
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.domain.scenario import (
    ExceptionFlagSnapshot,
    build_ground_truth_from_exception_flag,
    can_transition,
    validate_for_approval,
)


class ScenarioNotFoundError(ValueError):
    pass


class ExceptionFlagNotFoundError(ValueError):
    pass


class ScenarioTransitionError(ValueError):
    """Raised when the requested status change isn't a valid transition
    from the scenario's current status (app.domain.scenario.can_transition)."""


class ScenarioValidationError(ValueError):
    """Raised by approve_scenario when app.domain.scenario.
    validate_for_approval returns a non-empty error list — carries that
    list on `.errors` so the API layer can return it verbatim (PRD 9.2's
    required rejection-path test case) rather than a single flattened
    message."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _snapshot_from_flag(flag: ExceptionFlag) -> ExceptionFlagSnapshot:
    return ExceptionFlagSnapshot(
        id=str(flag.id),
        category=flag.category,
        product_id=flag.product_id,
        warehouse_id=flag.warehouse_id,
        purchase_order_id=str(flag.purchase_order_id) if flag.purchase_order_id else None,
        shipment_id=str(flag.shipment_id) if flag.shipment_id else None,
        simulation_date=flag.simulation_date,
        first_detected_simulation_date=flag.first_detected_simulation_date,
        measured_value=flag.measured_value,
        threshold_value=flag.threshold_value,
        resolved_at=flag.resolved_at,
    )


def _get_scenario(session: Session, scenario_id: uuid.UUID) -> Scenario:
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise ScenarioNotFoundError(f"scenario {scenario_id} not found")
    return scenario


def _require_transition(scenario: Scenario, to_status: ScenarioStatus) -> None:
    if not can_transition(scenario.status.value, to_status.value):
        raise ScenarioTransitionError(
            f"cannot move scenario {scenario.id} from {scenario.status.value} to {to_status.value}"
        )


def create_scenario_from_exception_flag(
    session: Session,
    *,
    exception_flag_id: uuid.UUID,
    scenario_type: ScenarioType,
    competency_cluster: CompetencyCluster,
    difficulty_tier: DifficultyTier,
    title: str,
    created_by: uuid.UUID,
) -> Scenario:
    flag = session.get(ExceptionFlag, exception_flag_id)
    if flag is None:
        raise ExceptionFlagNotFoundError(f"exception flag {exception_flag_id} not found")

    ground_truth = build_ground_truth_from_exception_flag(_snapshot_from_flag(flag))

    scenario = Scenario(
        title=title,
        scenario_type=scenario_type,
        competency_cluster=competency_cluster,
        difficulty_tier=difficulty_tier,
        source=ScenarioSource.EXCEPTION_FLAG,
        source_exception_flag_id=flag.id,
        ground_truth=ground_truth,
        status=ScenarioStatus.DRAFT,
        created_by=created_by,
    )
    session.add(scenario)
    session.flush()
    return scenario


def regenerate_scenario(session: Session, scenario_id: uuid.UUID) -> Scenario:
    scenario = _get_scenario(session, scenario_id)
    if scenario.status != ScenarioStatus.DRAFT:
        raise ScenarioTransitionError(
            f"scenario {scenario_id} can only be regenerated while in draft "
            f"(currently {scenario.status.value})"
        )
    if scenario.source != ScenarioSource.EXCEPTION_FLAG or scenario.source_exception_flag_id is None:
        raise ScenarioTransitionError(
            f"scenario {scenario_id} has no source exception flag to regenerate from"
        )

    flag = session.get(ExceptionFlag, scenario.source_exception_flag_id)
    if flag is None:
        raise ExceptionFlagNotFoundError(
            f"exception flag {scenario.source_exception_flag_id} not found"
        )

    # Merge, not replace (code review, MEDIUM): only known_cause/evidence are
    # mechanically re-derivable from the flag's current data — the four
    # narrative fields and uncertainty are the Builder's own hand-authored
    # "edit" step (6.4), and a full overwrite would silently destroy that
    # work with no warning every time the flag's underlying numbers move.
    fresh = build_ground_truth_from_exception_flag(_snapshot_from_flag(flag))
    scenario.ground_truth = {
        **scenario.ground_truth,
        "known_cause": fresh["known_cause"],
        "evidence": fresh["evidence"],
    }
    session.flush()
    return scenario


def update_ground_truth(session: Session, scenario_id: uuid.UUID, updates: dict) -> Scenario:
    """Merges `updates` into the scenario's ground_truth (6.4's "edit"
    control). Draft-only (code review, HIGH): without this guard, editing
    ground_truth after approve_scenario has already validated it lets an
    Approved/Active scenario silently end up with an incomplete or invalid
    package, with no re-validation and no status reversion — nothing
    downstream would know the approval gate had been bypassed after the
    fact."""
    scenario = _get_scenario(session, scenario_id)
    if scenario.status != ScenarioStatus.DRAFT:
        raise ScenarioTransitionError(
            f"scenario {scenario_id} ground_truth can only be edited while in "
            f"draft (currently {scenario.status.value})"
        )
    scenario.ground_truth = {**scenario.ground_truth, **updates}
    session.flush()
    return scenario


def approve_scenario(session: Session, scenario_id: uuid.UUID) -> Scenario:
    scenario = _get_scenario(session, scenario_id)
    _require_transition(scenario, ScenarioStatus.APPROVED)

    errors = validate_for_approval(
        ground_truth=scenario.ground_truth,
        difficulty_tier=scenario.difficulty_tier.value if scenario.difficulty_tier else None,
        competency_cluster=scenario.competency_cluster.value
        if scenario.competency_cluster
        else None,
    )
    if errors:
        raise ScenarioValidationError(errors)

    scenario.status = ScenarioStatus.APPROVED
    scenario.approved_at = datetime.now(timezone.utc)
    session.flush()
    return scenario


def activate_scenario(session: Session, scenario_id: uuid.UUID) -> Scenario:
    scenario = _get_scenario(session, scenario_id)
    _require_transition(scenario, ScenarioStatus.ACTIVE)

    scenario.status = ScenarioStatus.ACTIVE
    scenario.activated_at = datetime.now(timezone.utc)
    session.flush()
    return scenario


def cancel_scenario(session: Session, scenario_id: uuid.UUID) -> Scenario:
    scenario = _get_scenario(session, scenario_id)
    _require_transition(scenario, ScenarioStatus.CANCELLED)

    scenario.status = ScenarioStatus.CANCELLED
    session.flush()
    return scenario


def get_scenario(session: Session, scenario_id: uuid.UUID) -> Scenario:
    return _get_scenario(session, scenario_id)


def list_scenarios(session: Session, *, status: ScenarioStatus | None = None) -> list[Scenario]:
    query = select(Scenario).order_by(Scenario.created_at.desc())
    if status is not None:
        query = query.where(Scenario.status == status)
    return list(session.scalars(query))
