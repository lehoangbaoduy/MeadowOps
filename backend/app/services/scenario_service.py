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

from app.db.chat import ChatThread
from app.db.dimensions import Product, Supplier, Warehouse
from app.db.enums import (
    ChatThreadStatus,
    CompetencyCluster,
    DifficultyTier,
    ScenarioSource,
    ScenarioStatus,
    ScenarioType,
)
from app.db.exception_flags import ExceptionFlag
from app.db.facts import PurchaseOrder, Shipment
from app.db.scenario import Scenario
from app.db.world_state import SimulationClock
from app.domain.claude_client import ClaudeClient
from app.domain.scenario import (
    ExceptionFlagSnapshot,
    build_ground_truth_from_exception_flag,
    can_transition,
    validate_for_approval,
)
from app.domain.scenario_generation import generate_scenario_narrative

# Keyed by the app.domain.scenario_generation.ScenarioNarrative.
# referenced_entity_ids field a Claude response carries. String-PK entity
# types (Product/Warehouse/Supplier) are checked by session.get() directly;
# UUID-PK types (PurchaseOrder/Shipment) need uuid.UUID() parsing first -
# split into two maps below so a malformed id string is a validation error,
# not an unhandled ValueError.
_STRING_ID_ENTITY_TYPES: dict[str, tuple[type, str]] = {
    "product_ids": (Product, "product"),
    "warehouse_ids": (Warehouse, "warehouse"),
    "supplier_ids": (Supplier, "supplier"),
}
_UUID_ID_ENTITY_TYPES: dict[str, tuple[type, str]] = {
    "purchase_order_ids": (PurchaseOrder, "purchase order"),
    "shipment_ids": (Shipment, "shipment"),
}


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


class ScenarioGenerationValidationError(ValueError):
    """Raised by regenerate_scenario when the AI-generated narrative
    references an entity id that doesn't exist in the live database (PRD
    9.2: "Caught by scenario validation... rejected before reaching any
    user, Builder notified"). Unlike a ClaudeAPIError/schema failure inside
    app.domain.scenario_generation, this is never automatically retried -
    the Builder decides whether to regenerate again or edit manually.
    Carries the error list on `.errors`, same convention as
    ScenarioValidationError above."""

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

    # PRD 4.2 line 130 / catalog row 7: pin the scenario to whatever
    # world_state is current right now. A soft reference (see
    # app.db.scenario.Scenario.world_state_id's own docstring) - the
    # simulation_clock singleton may not be seeded yet in every environment
    # (e.g. a fresh test DB that never calls seed_initial_world_state_and_
    # clock), so this stays None rather than raising in that case.
    clock = session.get(SimulationClock, 1)
    world_state_id = clock.current_world_state_id if clock is not None else None

    scenario = Scenario(
        title=title,
        scenario_type=scenario_type,
        competency_cluster=competency_cluster,
        difficulty_tier=difficulty_tier,
        source=ScenarioSource.EXCEPTION_FLAG,
        source_exception_flag_id=flag.id,
        world_state_id=world_state_id,
        ground_truth=ground_truth,
        status=ScenarioStatus.DRAFT,
        created_by=created_by,
    )
    session.add(scenario)
    session.flush()
    return scenario


def validate_referenced_entity_ids(
    session: Session, referenced_entity_ids: dict[str, list[str]]
) -> list[str]:
    """Mechanically checks every id an AI-generated narrative *declares* in
    its own referenced_entity_ids manifest actually exists in the live
    database (PRD 9.2's "AI generates a scenario referencing non-existent or
    stale IDs" edge case). Returns the list of validation errors (empty
    means valid) rather than raising, same non-raising convention
    app.domain.scenario.validate_for_approval already uses - the caller
    (regenerate_scenario) decides what to do.

    Security review (2026-09-04): this is existence-only and manifest-only -
    two gaps deliberately left to Phase 3's U30 "full edge case catalog"
    unit, the same precedent that put SR-1/SR-3 out of U17's own scope (see
    app.domain.reporting_sync's docstring). (1) An id only used inside the
    narrative's free-text fields (supporting_signals, distractors, etc.)
    rather than declared in referenced_entity_ids is never checked at all.
    (2) A declared id that is real but unrelated to this scenario's own
    evidence package (GENERATION_TEMPLATE's "reference only ... identifiers
    that exist in the evidence package" instruction) passes this check
    anyway - it is global-existence, not evidence-package-membership."""
    errors: list[str] = []
    for key, ids in referenced_entity_ids.items():
        if key in _STRING_ID_ENTITY_TYPES:
            model, label = _STRING_ID_ENTITY_TYPES[key]
            for entity_id in ids:
                if session.get(model, entity_id) is None:
                    errors.append(f"referenced_entity_ids.{key}: unknown {label} id {entity_id!r}")
        elif key in _UUID_ID_ENTITY_TYPES:
            model, label = _UUID_ID_ENTITY_TYPES[key]
            for raw_id in ids:
                try:
                    parsed_id = uuid.UUID(raw_id)
                except ValueError:
                    errors.append(f"referenced_entity_ids.{key}: {raw_id!r} is not a valid id")
                    continue
                if session.get(model, parsed_id) is None:
                    errors.append(f"referenced_entity_ids.{key}: unknown {label} id {raw_id}")
    return errors


def regenerate_scenario(
    session: Session, scenario_id: uuid.UUID, claude_client: ClaudeClient
) -> Scenario:
    """Unit 22 (MEADOWOPS-DOM-016): now a full overwrite of both the
    mechanical facts (known_cause/evidence) and an AI-generated narrative -
    the user's explicit "extend regenerate" scoping decision, superseding
    U18's own merge-not-replace code-review fix (that fix predated any AI
    call existing to run here at all; the Builder's edit path for a
    narrative they want to keep is update_ground_truth, not skipping
    regenerate).

    scenario.ground_truth is only reassigned after generation AND
    referenced-id validation both succeed - a failure at either step
    (ScenarioGenerationFailedError, ScenarioGenerationValidationError)
    leaves the scenario's existing ground_truth completely untouched.
    """
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

    fresh = build_ground_truth_from_exception_flag(_snapshot_from_flag(flag))

    # Propagates ScenarioGenerationFailedError unwrapped on a Claude API/
    # schema failure that survives the one automatic retry - ground_truth
    # is not touched below in that case.
    narrative = generate_scenario_narrative(
        claude_client,
        scenario_type=scenario.scenario_type.value,
        difficulty_tier=scenario.difficulty_tier.value,
        competency_cluster=scenario.competency_cluster.value,
        evidence_package=fresh["evidence"],
    )

    errors = validate_referenced_entity_ids(session, narrative.referenced_entity_ids)
    if errors:
        raise ScenarioGenerationValidationError(errors)

    scenario.ground_truth = {
        "known_cause": fresh["known_cause"],
        "evidence": fresh["evidence"],
        "supporting_signals": narrative.supporting_signals,
        "distractors": narrative.distractors,
        "expected_considerations": narrative.expected_considerations,
        "acceptable_conclusions": narrative.acceptable_conclusions,
        "unacceptable_conclusions": narrative.unacceptable_conclusions,
        "uncertainty": narrative.uncertainty,
        "referenced_entity_ids": narrative.referenced_entity_ids,
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
    """PRD 9.2 catalog row 19: only one scenario may be active *at a time*
    - not "only one scenario active across this system's entire history".
    That distinction matters here because ScenarioStatus has no
    active->completed transition (app.domain.scenario.VALID_TRANSITIONS):
    activation was deliberately left as this unit's own lifecycle terminus,
    so every scenario that has ever been activated stays status=ACTIVE
    forever (see B13 in prd/MeadowOps_progress.md for the deferred "real"
    terminal-status fix this punts on). A DB-level "at most one row with
    status=active, ever" constraint was tried first (migration 0023) and
    reverted - it broke real, correct multi-scenario history
    (app.services.evaluation_service's difficulty-tier lookups, the QA
    harness's callback scenario both rely on many past scenarios coexisting
    at status=active).

    So "still active" here means "another scenario is ACTIVE and its work
    isn't done yet" - approximated as: has no chat.chat_thread with
    status=COMPLETED. A scenario with zero threads, or only open ones, is
    still in flight and blocks; one with *at least one* completed thread
    (deliberate - a scenario with a CFO thread completed and an Ops thread
    still open already counts as "done" for this guard) has had its work
    wrapped up and no longer does, even though its own status column never
    moves off ACTIVE.

    Not race-safe: this is a check-then-write with no DB constraint
    underneath it (migration 0023 dropped ux_scenario_single_active - see
    that migration's own docstring), so two concurrent activation requests
    can both pass the check and both flush. Acceptable for now under this
    project's single-Analyst-seat assumption everywhere else; a real fix
    needs the terminal-status column B13 already tracks, not a index that
    breaks multi-scenario history."""
    scenario = _get_scenario(session, scenario_id)
    _require_transition(scenario, ScenarioStatus.ACTIVE)

    completed_thread_scenario_ids = select(ChatThread.scenario_id).where(
        ChatThread.status == ChatThreadStatus.COMPLETED
    )
    blocking_scenario_id = session.execute(
        select(Scenario.id)
        .where(Scenario.status == ScenarioStatus.ACTIVE)
        .where(Scenario.id != scenario_id)
        .where(Scenario.id.not_in(completed_thread_scenario_ids))
    ).scalars().first()
    if blocking_scenario_id is not None:
        raise ScenarioTransitionError(
            f"cannot activate {scenario_id}: scenario {blocking_scenario_id} is still active"
        )

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
