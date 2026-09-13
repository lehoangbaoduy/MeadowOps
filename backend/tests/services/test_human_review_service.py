"""Unit 26 (MEADOWOPS-DOM-020, business id MEADOWOPS-DOMAIN-015, PRD 6.6
step 11, ER-3/ER-4): transactional-layer tests for recording a human
review against an existing Evaluation. Same non-autocommit discipline as
tests/services/test_evaluation_service.py: runs inside an uncommitted
transaction per test, rolled back at fixture teardown."""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.db.auth import User
from app.db.chat import ChatThread
from app.db.enums import (
    CompetencyCluster,
    DifficultyRecommendation,
    DifficultyTier,
    HumanReviewVerdict,
    ScenarioStatus,
    ScenarioType,
    StakeholderPersona,
    UserRole,
)
from app.db.evaluation import Evaluation
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.domain.claude_client import ClaudeResponse, MockClaudeClient
from app.services.baseline_data import seed_master_data
from app.services.chat import send_message
from app.services.evaluation import complete_thread_and_generate_evaluation
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.human_review import (
    EvaluationNotFoundError,
    HumanReviewAlreadyExistsError,
    InvalidVerdictPairingError,
    get_human_review_for_evaluation,
    record_human_review,
)
from app.services.scenario_service import create_scenario_from_exception_flag

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ADMIN_EMAIL = "zztest-human-review-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-human-review-analyst@meadowops.local"

_VALID_PAYLOAD = {
    "strengths": "Correctly identified the reorder point issue.",
    "gaps": "Did not quantify the cost impact.",
    "evidence": "Cited the on-hand count and lead time signal.",
    "senior_analyst_pushback": "What would you check next if wrong?",
    "final_verdict": "Solid investigation, minor gaps.",
    "suggested_next_skill_focus": "Quantifying financial impact.",
    "difficulty_recommendation": "standard",
}


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        session.execute(delete(User).where(User.email.in_([_ADMIN_EMAIL, _ANALYST_EMAIL])))
        session.commit()
        seed_master_data(session)
        seed_exception_rule_thresholds(session)
        session.commit()
        yield session
        session.rollback()
        session.execute(delete(User).where(User.email.in_([_ADMIN_EMAIL, _ANALYST_EMAIL])))
        session.commit()
    engine.dispose()


@pytest.fixture
def admin_id(session: Session) -> uuid.UUID:
    user = User(email=_ADMIN_EMAIL, password_hash="x", role=UserRole.ADMIN, is_active=True)
    session.add(user)
    session.flush()
    return user.id


@pytest.fixture
def analyst_id(session: Session) -> uuid.UUID:
    user = User(email=_ANALYST_EMAIL, password_hash="x", role=UserRole.ANALYST, is_active=True)
    session.add(user)
    session.flush()
    return user.id


def _make_active_scenario(session: Session, *, admin_id: uuid.UUID) -> Scenario:
    flag = ExceptionFlag(
        category="low_stock_days_of_supply",
        product_id=_PRODUCT_ID,
        warehouse_id=_WAREHOUSE_ID,
        simulation_date=date(2026, 6, 1),
        first_detected_simulation_date=date(2026, 5, 20),
        measured_value=Decimal("4.00"),
        threshold_value=Decimal("10.00"),
    )
    session.add(flag)
    session.flush()
    scenario = create_scenario_from_exception_flag(
        session,
        exception_flag_id=flag.id,
        scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
        competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
        difficulty_tier=DifficultyTier.STANDARD,
        title="zztest human review scenario",
        created_by=admin_id,
    )
    scenario.status = ScenarioStatus.ACTIVE
    flag.resolved_at = datetime.now(timezone.utc)
    session.flush()
    return scenario


@pytest.fixture
def scenario(session: Session, admin_id: uuid.UUID) -> Scenario:
    return _make_active_scenario(session, admin_id=admin_id)


@pytest.fixture
def thread(session: Session, scenario: Scenario) -> ChatThread:
    thread = ChatThread(scenario_id=scenario.id, persona=StakeholderPersona.CFO)
    session.add(thread)
    session.flush()
    return thread


@pytest.fixture
def evaluation(
    session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
) -> Evaluation:
    send_message(
        session, thread_id=thread.id, sender_user_id=admin_id, sender_role=UserRole.ADMIN,
        body="What's the status?",
    )
    send_message(
        session, thread_id=thread.id, sender_user_id=analyst_id, sender_role=UserRole.ANALYST,
        body="Reorder point looks misconfigured.",
    )
    client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])
    return complete_thread_and_generate_evaluation(session, thread_id=thread.id, claude_client=client)


class TestRecordHumanReview:
    def test_records_an_agree_verdict(
        self, session: Session, evaluation: Evaluation, admin_id: uuid.UUID
    ) -> None:
        review = record_human_review(
            session,
            evaluation_id=evaluation.id,
            submitted_by_user_id=admin_id,
            reviewer_name="Prof. Rivera",
            verdict=HumanReviewVerdict.AGREE,
            tier_assessment_notes="Standard tier matches demonstrated level.",
        )

        assert review.evaluation_id == evaluation.id
        assert review.submitted_by_user_id == admin_id
        assert review.verdict == HumanReviewVerdict.AGREE
        assert review.overridden_recommendation is None

    def test_records_an_override_verdict_with_its_own_recommendation(
        self, session: Session, evaluation: Evaluation, admin_id: uuid.UUID
    ) -> None:
        review = record_human_review(
            session,
            evaluation_id=evaluation.id,
            submitted_by_user_id=admin_id,
            reviewer_name="Prof. Rivera",
            verdict=HumanReviewVerdict.OVERRIDE,
            tier_assessment_notes="Evidence actually supports a stretch call.",
            overridden_recommendation=DifficultyRecommendation.STRETCH,
        )

        assert review.verdict == HumanReviewVerdict.OVERRIDE
        assert review.overridden_recommendation == DifficultyRecommendation.STRETCH

    def test_raises_when_the_evaluation_does_not_exist(
        self, session: Session, admin_id: uuid.UUID
    ) -> None:
        with pytest.raises(EvaluationNotFoundError):
            record_human_review(
                session,
                evaluation_id=uuid.uuid4(),
                submitted_by_user_id=admin_id,
                reviewer_name="Prof. Rivera",
                verdict=HumanReviewVerdict.AGREE,
                tier_assessment_notes="n/a",
            )

    def test_raises_when_the_evaluation_already_has_a_review(
        self, session: Session, evaluation: Evaluation, admin_id: uuid.UUID
    ) -> None:
        record_human_review(
            session,
            evaluation_id=evaluation.id,
            submitted_by_user_id=admin_id,
            reviewer_name="Prof. Rivera",
            verdict=HumanReviewVerdict.AGREE,
            tier_assessment_notes="Fine.",
        )

        with pytest.raises(HumanReviewAlreadyExistsError):
            record_human_review(
                session,
                evaluation_id=evaluation.id,
                submitted_by_user_id=admin_id,
                reviewer_name="Someone Else",
                verdict=HumanReviewVerdict.AGREE,
                tier_assessment_notes="Also fine.",
            )

    def test_raises_when_agree_carries_an_overridden_recommendation(
        self, session: Session, evaluation: Evaluation, admin_id: uuid.UUID
    ) -> None:
        with pytest.raises(InvalidVerdictPairingError):
            record_human_review(
                session,
                evaluation_id=evaluation.id,
                submitted_by_user_id=admin_id,
                reviewer_name="Prof. Rivera",
                verdict=HumanReviewVerdict.AGREE,
                tier_assessment_notes="n/a",
                overridden_recommendation=DifficultyRecommendation.STRETCH,
            )

    def test_raises_when_override_has_no_overridden_recommendation(
        self, session: Session, evaluation: Evaluation, admin_id: uuid.UUID
    ) -> None:
        with pytest.raises(InvalidVerdictPairingError):
            record_human_review(
                session,
                evaluation_id=evaluation.id,
                submitted_by_user_id=admin_id,
                reviewer_name="Prof. Rivera",
                verdict=HumanReviewVerdict.OVERRIDE,
                tier_assessment_notes="n/a",
            )


class TestGetHumanReviewForEvaluation:
    def test_returns_none_when_no_review_exists(self, session: Session, evaluation: Evaluation) -> None:
        assert get_human_review_for_evaluation(session, evaluation.id) is None

    def test_returns_the_review_once_recorded(
        self, session: Session, evaluation: Evaluation, admin_id: uuid.UUID
    ) -> None:
        created = record_human_review(
            session,
            evaluation_id=evaluation.id,
            submitted_by_user_id=admin_id,
            reviewer_name="Prof. Rivera",
            verdict=HumanReviewVerdict.AGREE,
            tier_assessment_notes="Fine.",
        )

        found = get_human_review_for_evaluation(session, evaluation.id)

        assert found is not None
        assert found.id == created.id
