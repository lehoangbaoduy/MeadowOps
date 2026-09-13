"""Unit 18 (MEADOWOPS-DOM-011): scenario builder service layer — the
transactional glue between app.domain.scenario's pure logic and the real
`engine.scenario` / `live.exception_flag` / `live.user` tables. Same
non-autocommit discipline as tests/services/test_exception_engine.py: runs
against the real seeded baseline data inside an uncommitted transaction per
test, rolled back via Session.close()'s implicit rollback (services never
commit — caller-owns-the-transaction, same convention as every other
service module in this project).
"""

import json
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.db.auth import User
from app.db.enums import (
    CompetencyCluster,
    DifficultyTier,
    ScenarioStatus,
    ScenarioType,
    UserRole,
)
from app.db.dimensions import Warehouse
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.db.world_state import SimulationClock
from app.domain.claude_client import ClaudeAPIError, ClaudeResponse, MockClaudeClient
from app.domain.scenario import ExceptionFlagNotOpenError
from app.domain.scenario_generation import ScenarioGenerationFailedError
from app.services.baseline_data import seed_master_data
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.simulation_clock_ops import reset_simulation, seed_initial_world_state_and_clock
from app.services.scenario_service import (
    ExceptionFlagNotFoundError,
    ScenarioGenerationValidationError,
    ScenarioNotFoundError,
    ScenarioTransitionError,
    ScenarioValidationError,
    activate_scenario,
    approve_scenario,
    cancel_scenario,
    create_scenario_from_exception_flag,
    regenerate_scenario,
    update_ground_truth,
    validate_referenced_entity_ids,
)

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_BUILDER_EMAIL = "zztest-scenario-builder@meadowops.local"


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        session.execute(delete(User).where(User.email == _BUILDER_EMAIL))
        session.commit()
        seed_master_data(session)
        seed_exception_rule_thresholds(session)
        session.commit()
        yield session
        session.rollback()
        session.execute(delete(User).where(User.email == _BUILDER_EMAIL))
        session.commit()
    engine.dispose()


@pytest.fixture
def builder_id(session: Session) -> uuid.UUID:
    user = User(
        email=_BUILDER_EMAIL,
        password_hash="not-a-real-hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user.id


def _open_flag(session: Session, **overrides) -> ExceptionFlag:
    kwargs = dict(
        category="low_stock_days_of_supply",
        product_id=_PRODUCT_ID,
        warehouse_id=_WAREHOUSE_ID,
        simulation_date=date(2026, 6, 1),
        first_detected_simulation_date=date(2026, 5, 20),
        measured_value=Decimal("4.00"),
        threshold_value=Decimal("10.00"),
    )
    kwargs.update(overrides)
    flag = ExceptionFlag(**kwargs)
    session.add(flag)
    session.flush()
    return flag


def _complete_ground_truth(scenario: Scenario) -> None:
    scenario.ground_truth = {
        **scenario.ground_truth,
        "supporting_signals": ["signal"],
        "distractors": ["distractor"],
        "expected_considerations": ["consideration"],
        "acceptable_conclusions": ["ok"],
        "unacceptable_conclusions": ["bad"],
        "uncertainty": "moderate",
    }


class TestCreateScenarioFromExceptionFlag:
    def test_builds_a_draft_scenario_with_snapshotted_ground_truth(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)

        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="Low stock at WH-EAST",
            created_by=builder_id,
        )

        assert scenario.id is not None
        assert scenario.status == ScenarioStatus.DRAFT
        assert scenario.source_exception_flag_id == flag.id
        assert scenario.ground_truth["evidence"]["source_exception_flag_id"] == str(flag.id)
        assert scenario.created_by == builder_id

    def test_raises_when_the_exception_flag_does_not_exist(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        with pytest.raises(ExceptionFlagNotFoundError):
            create_scenario_from_exception_flag(
                session,
                exception_flag_id=uuid.uuid4(),
                scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
                competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
                difficulty_tier=DifficultyTier.STANDARD,
                title="x",
                created_by=builder_id,
            )

    def test_raises_when_the_exception_flag_has_already_resolved(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session, resolved_at=None)
        flag.resolved_at = flag.detected_at
        session.flush()

        with pytest.raises(ExceptionFlagNotOpenError):
            create_scenario_from_exception_flag(
                session,
                exception_flag_id=flag.id,
                scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
                competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
                difficulty_tier=DifficultyTier.STANDARD,
                title="x",
                created_by=builder_id,
            )


def _narrative_payload(**overrides) -> dict:
    payload = {
        "supporting_signals": ["signal"],
        "distractors": ["distractor"],
        "expected_considerations": ["consideration"],
        "acceptable_conclusions": ["ok"],
        "unacceptable_conclusions": ["bad"],
        "uncertainty": "moderate",
        "referenced_entity_ids": {"product_ids": [_PRODUCT_ID], "warehouse_ids": [_WAREHOUSE_ID]},
    }
    payload.update(overrides)
    return payload


class TestRegenerateScenario:
    def test_produces_a_fresh_narrative_and_refreshed_mechanical_facts(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        flag.measured_value = Decimal("1.00")
        session.flush()
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_narrative_payload()))])

        regenerated = regenerate_scenario(session, scenario.id, client)

        assert regenerated.ground_truth["evidence"]["measured_value"] == "1.00"
        assert regenerated.ground_truth["supporting_signals"] == ["signal"]
        assert regenerated.ground_truth["uncertainty"] == "moderate"

    def test_full_overwrite_replaces_a_previously_hand_edited_narrative(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        # U22 (the user's explicit "extend regenerate" scoping decision)
        # supersedes U18's merge-not-replace code-review fix: regenerate now
        # means "produce a fresh AI narrative", not just refresh the
        # mechanical facts. The Builder's edit path for a narrative they
        # want to keep is update_ground_truth, not skipping regenerate.
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        update_ground_truth(session, scenario.id, {"uncertainty": "already edited by builder"})
        client = MockClaudeClient(
            script=[
                ClaudeResponse(content=json.dumps(_narrative_payload(uncertainty="ai-generated")))
            ]
        )

        regenerated = regenerate_scenario(session, scenario.id, client)

        assert regenerated.ground_truth["uncertainty"] == "ai-generated"

    def test_retries_once_on_a_claude_failure_before_succeeding(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        client = MockClaudeClient(
            script=[ClaudeAPIError("boom"), ClaudeResponse(content=json.dumps(_narrative_payload()))]
        )

        regenerated = regenerate_scenario(session, scenario.id, client)

        assert len(client.call_log) == 2
        assert regenerated.ground_truth["uncertainty"] == "moderate"

    def test_a_regenerated_scenario_passes_approval(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        # Code review, MEDIUM: regenerate_scenario now builds ground_truth
        # from a 9-key literal instead of merging into the existing dict
        # (scenario_service.py) - this must exactly satisfy
        # REQUIRED_GROUND_TRUTH_FIELDS for approve_scenario to accept it, or
        # every AI-regenerated scenario would be permanently unapprovable.
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_narrative_payload()))])
        regenerate_scenario(session, scenario.id, client)

        approved = approve_scenario(session, scenario.id)

        assert approved.status == ScenarioStatus.APPROVED

    def test_raises_scenario_generation_failed_after_the_retry_is_exhausted_and_leaves_ground_truth_untouched(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        original_ground_truth = dict(scenario.ground_truth)
        client = MockClaudeClient(script=[ClaudeAPIError("boom"), ClaudeAPIError("boom again")])

        with pytest.raises(ScenarioGenerationFailedError):
            regenerate_scenario(session, scenario.id, client)
        assert scenario.ground_truth == original_ground_truth

    def test_raises_scenario_generation_validation_error_on_an_unknown_referenced_id_with_no_retry(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        # PRD 9.2: a bad referenced-id is caught by scenario validation and
        # rejected before reaching any user — no automatic retry, unlike a
        # Claude API/schema failure above (the Builder decides whether to
        # regenerate or edit manually).
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        original_ground_truth = dict(scenario.ground_truth)
        client = MockClaudeClient(
            script=[
                ClaudeResponse(
                    content=json.dumps(
                        _narrative_payload(
                            referenced_entity_ids={"product_ids": ["SKU-DOES-NOT-EXIST"]}
                        )
                    )
                )
            ]
        )

        with pytest.raises(ScenarioGenerationValidationError) as exc_info:
            regenerate_scenario(session, scenario.id, client)
        assert exc_info.value.errors != []
        assert len(client.call_log) == 1
        assert scenario.ground_truth == original_ground_truth

    def test_raises_when_scenario_is_not_in_draft(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        _complete_ground_truth(scenario)
        approve_scenario(session, scenario.id)
        client = MockClaudeClient(script=[])

        with pytest.raises(ScenarioTransitionError):
            regenerate_scenario(session, scenario.id, client)
        assert client.call_log == []

    def test_raises_when_scenario_does_not_exist(self, session: Session) -> None:
        client = MockClaudeClient(script=[])
        with pytest.raises(ScenarioNotFoundError):
            regenerate_scenario(session, uuid.uuid4(), client)


class TestValidateReferencedEntityIds:
    def test_empty_dict_is_valid(self, session: Session) -> None:
        assert validate_referenced_entity_ids(session, {}) == []

    def test_known_product_and_warehouse_ids_are_valid(self, session: Session) -> None:
        errors = validate_referenced_entity_ids(
            session, {"product_ids": [_PRODUCT_ID], "warehouse_ids": [_WAREHOUSE_ID]}
        )
        assert errors == []

    def test_unknown_product_id_is_an_error(self, session: Session) -> None:
        errors = validate_referenced_entity_ids(session, {"product_ids": ["SKU-DOES-NOT-EXIST"]})
        assert errors != []

    def test_unknown_warehouse_id_is_an_error(self, session: Session) -> None:
        errors = validate_referenced_entity_ids(session, {"warehouse_ids": ["WH-DOES-NOT-EXIST"]})
        assert errors != []

    def test_malformed_purchase_order_id_is_an_error_not_a_crash(self, session: Session) -> None:
        errors = validate_referenced_entity_ids(session, {"purchase_order_ids": ["not-a-uuid"]})
        assert errors != []

    def test_unknown_purchase_order_id_is_an_error(self, session: Session) -> None:
        errors = validate_referenced_entity_ids(
            session, {"purchase_order_ids": [str(uuid.uuid4())]}
        )
        assert errors != []

    def test_unknown_shipment_id_is_an_error(self, session: Session) -> None:
        errors = validate_referenced_entity_ids(session, {"shipment_ids": [str(uuid.uuid4())]})
        assert errors != []


class TestApproveScenario:
    def test_rejects_a_freshly_created_scenario_missing_builder_edits(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )

        with pytest.raises(ScenarioValidationError) as exc_info:
            approve_scenario(session, scenario.id)
        assert exc_info.value.errors != []
        assert scenario.status == ScenarioStatus.DRAFT

    def test_approves_a_complete_scenario(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        _complete_ground_truth(scenario)

        approved = approve_scenario(session, scenario.id)

        assert approved.status == ScenarioStatus.APPROVED
        assert approved.approved_at is not None

    def test_raises_when_scenario_is_not_in_draft(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        _complete_ground_truth(scenario)
        approve_scenario(session, scenario.id)

        with pytest.raises(ScenarioTransitionError):
            approve_scenario(session, scenario.id)


class TestActivateScenario:
    def test_activates_an_approved_scenario(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        _complete_ground_truth(scenario)
        approve_scenario(session, scenario.id)

        activated = activate_scenario(session, scenario.id)

        assert activated.status == ScenarioStatus.ACTIVE
        assert activated.activated_at is not None

    def test_raises_when_scenario_is_still_a_draft(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )

        with pytest.raises(ScenarioTransitionError):
            activate_scenario(session, scenario.id)


class TestCancelScenario:
    def test_cancels_a_draft_scenario(self, session: Session, builder_id: uuid.UUID) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )

        cancelled = cancel_scenario(session, scenario.id)

        assert cancelled.status == ScenarioStatus.CANCELLED

    def test_raises_when_scenario_is_already_active(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        _complete_ground_truth(scenario)
        approve_scenario(session, scenario.id)
        activate_scenario(session, scenario.id)

        with pytest.raises(ScenarioTransitionError):
            cancel_scenario(session, scenario.id)


class TestUpdateGroundTruth:
    def test_merges_edits_into_a_draft_scenario(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )

        updated = update_ground_truth(session, scenario.id, {"uncertainty": "medium"})

        assert updated.ground_truth["uncertainty"] == "medium"

    def test_raises_once_the_scenario_is_no_longer_a_draft(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        # Code review + security review, HIGH: editing ground_truth after
        # approve_scenario has already validated it must not be possible —
        # otherwise an Approved/Active scenario can silently end up with an
        # incomplete package with no re-validation and no status reversion.
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="x",
            created_by=builder_id,
        )
        _complete_ground_truth(scenario)
        approve_scenario(session, scenario.id)

        with pytest.raises(ScenarioTransitionError):
            update_ground_truth(session, scenario.id, {"uncertainty": "tampered"})
        assert scenario.ground_truth["uncertainty"] == "moderate"

    def test_raises_when_scenario_does_not_exist(self, session: Session) -> None:
        with pytest.raises(ScenarioNotFoundError):
            update_ground_truth(session, uuid.uuid4(), {"uncertainty": "x"})


class TestWorldStatePinning:
    """PRD 9.2 catalog row 7 / PRD 4.2 line 130: every scenario stores its
    own world_state_id at creation, and a later global reset (which always
    inserts a *new* world_state row, per app.services.simulation_clock_ops.
    reset_simulation) must never affect an already-pinned scenario's own
    reference. Unit 4's own tests already proved this at the world_state-row
    level ("rows are append-only"); this is the first test that proves it
    against a real Scenario row, now that the table exists (Phase 3)."""

    def test_a_scenario_s_world_state_id_survives_a_later_reset(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        seed_initial_world_state_and_clock(session)
        clock = session.get(SimulationClock, 1)
        pinned_world_state_id = clock.current_world_state_id

        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="zztest world-state pin",
            created_by=builder_id,
        )
        assert scenario.world_state_id == pinned_world_state_id

        reset_simulation(session)
        reset_simulation(session)

        session.refresh(scenario)
        assert scenario.world_state_id == pinned_world_state_id


class TestGroundTruthImmuneToLaterMasterDataEdits:
    """Unit 30 (MEADOWOPS-DOM-030, PRD 9.2 catalog row 9): a master-data
    edit (Warehouse/Supplier/Carrier) applied mid-scenario must not change
    the historical scenario's own data. Confirmatory only, no new
    production logic - app.domain.scenario.build_ground_truth_from_
    exception_flag already snapshots the flag's own column values into
    Scenario.ground_truth (a static JSONB blob) at creation time, and
    nothing ever re-joins that blob against the live `live.warehouse`/
    `live.supplier` rows afterward, so this is a structural guarantee this
    test simply proves against a real edit."""

    def test_editing_the_warehouse_after_scenario_creation_leaves_its_ground_truth_unchanged(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        flag = _open_flag(session)
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=flag.id,
            scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
            competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
            difficulty_tier=DifficultyTier.STANDARD,
            title="zztest master-data-edit immunity",
            created_by=builder_id,
        )
        original_ground_truth = dict(scenario.ground_truth)

        warehouse = session.get(Warehouse, _WAREHOUSE_ID)
        warehouse.name = "Renamed Mid-Scenario Warehouse"
        warehouse.region = "renamed-region"
        session.flush()

        session.refresh(scenario)
        assert scenario.ground_truth == original_ground_truth
