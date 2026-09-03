"""Unit 18 (MEADOWOPS-DOM-011): scenario builder service layer — the
transactional glue between app.domain.scenario's pure logic and the real
`engine.scenario` / `live.exception_flag` / `live.user` tables. Same
non-autocommit discipline as tests/services/test_exception_engine.py: runs
against the real seeded baseline data inside an uncommitted transaction per
test, rolled back via Session.close()'s implicit rollback (services never
commit — caller-owns-the-transaction, same convention as every other
service module in this project).
"""

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
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.domain.scenario import ExceptionFlagNotOpenError
from app.services.baseline_data import seed_master_data
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.scenario_service import (
    ExceptionFlagNotFoundError,
    ScenarioNotFoundError,
    ScenarioTransitionError,
    ScenarioValidationError,
    activate_scenario,
    approve_scenario,
    cancel_scenario,
    create_scenario_from_exception_flag,
    regenerate_scenario,
    update_ground_truth,
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


class TestRegenerateScenario:
    def test_rebuilds_ground_truth_from_the_flags_current_data(
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

        regenerated = regenerate_scenario(session, scenario.id)

        assert regenerated.ground_truth["evidence"]["measured_value"] == "1.00"

    def test_preserves_already_edited_narrative_fields(
        self, session: Session, builder_id: uuid.UUID
    ) -> None:
        # Code review, MEDIUM: an earlier version overwrote ground_truth
        # wholesale, silently destroying any narrative fields the Builder
        # had already hand-edited (6.4's "edit" control). Regenerate should
        # only refresh the mechanically-derived known_cause/evidence.
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
        flag.measured_value = Decimal("1.00")
        session.flush()

        regenerated = regenerate_scenario(session, scenario.id)

        assert regenerated.ground_truth["uncertainty"] == "already edited by builder"
        assert regenerated.ground_truth["evidence"]["measured_value"] == "1.00"

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
            regenerate_scenario(session, scenario.id)

    def test_raises_when_scenario_does_not_exist(self, session: Session) -> None:
        with pytest.raises(ScenarioNotFoundError):
            regenerate_scenario(session, uuid.uuid4())


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
