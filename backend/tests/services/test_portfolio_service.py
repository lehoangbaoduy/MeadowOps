"""Unit 26 (MEADOWOPS-DOM-020, business id MEADOWOPS-DOMAIN-015, PRD 6.10):
transactional-layer tests for authoring a portfolio reflection and
compiling the full export document. Same non-autocommit discipline as
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
from app.services.human_review import record_human_review
from app.services.portfolio import (
    PortfolioArtifactAlreadyExistsError,
    ThreadNotCompletedError,
    create_portfolio_reflection,
    get_portfolio_artifact_for_thread,
    get_portfolio_export,
)
from app.services.scenario_service import create_scenario_from_exception_flag

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ADMIN_EMAIL = "zztest-portfolio-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-portfolio-analyst@meadowops.local"

_VALID_PAYLOAD = {
    "strengths": "Correctly identified the reorder point issue.",
    "gaps": "Did not quantify the cost impact.",
    "evidence": "Cited the on-hand count and lead time signal.",
    "senior_analyst_pushback": "What would you check next if wrong?",
    "final_verdict": "Solid investigation, minor gaps.",
    "suggested_next_skill_focus": "Quantifying financial impact.",
    "difficulty_recommendation": "standard",
}

_REFLECTION_KWARGS = {
    "reflection_what_happened": "A stockout on SKU-COR-001 at WH-EAST.",
    "reflection_initial_thought": "I assumed the supplier was late.",
    "reflection_evidence_that_mattered": "The reorder point history.",
    "reflection_what_missed": "The lead-time trend at first.",
    "reflection_what_changed_after_pushback": "I checked the reorder point config.",
    "reflection_what_differently": "Check configuration before blaming the supplier.",
    "reflection_skill_improved": "Root-cause analysis.",
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
        title="zztest portfolio scenario",
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


def _send_opening_and_analyst_reply(
    session: Session, thread: ChatThread, *, admin_id: uuid.UUID, analyst_id: uuid.UUID
) -> None:
    send_message(
        session, thread_id=thread.id, sender_user_id=admin_id, sender_role=UserRole.ADMIN,
        body="East's service is getting worse.",
    )
    send_message(
        session, thread_id=thread.id, sender_user_id=analyst_id, sender_role=UserRole.ANALYST,
        body="Reorder point looks misconfigured.",
    )


@pytest.fixture
def completed_thread(
    session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
) -> ChatThread:
    _send_opening_and_analyst_reply(session, thread, admin_id=admin_id, analyst_id=analyst_id)
    client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])
    complete_thread_and_generate_evaluation(session, thread_id=thread.id, claude_client=client)
    return thread


class TestCreatePortfolioReflection:
    def test_raises_when_the_thread_is_not_completed(
        self, session: Session, thread: ChatThread, analyst_id: uuid.UUID
    ) -> None:
        with pytest.raises(ThreadNotCompletedError):
            create_portfolio_reflection(
                session, thread_id=thread.id, submitted_by_user_id=analyst_id, **_REFLECTION_KWARGS
            )

    def test_succeeds_once_the_thread_is_completed(
        self, session: Session, completed_thread: ChatThread, analyst_id: uuid.UUID
    ) -> None:
        artifact = create_portfolio_reflection(
            session,
            thread_id=completed_thread.id,
            submitted_by_user_id=analyst_id,
            **_REFLECTION_KWARGS,
        )

        assert artifact.thread_id == completed_thread.id
        assert artifact.submitted_by_user_id == analyst_id
        assert artifact.reflection_skill_improved == "Root-cause analysis."

    def test_raises_when_a_reflection_already_exists(
        self, session: Session, completed_thread: ChatThread, analyst_id: uuid.UUID
    ) -> None:
        create_portfolio_reflection(
            session,
            thread_id=completed_thread.id,
            submitted_by_user_id=analyst_id,
            **_REFLECTION_KWARGS,
        )

        with pytest.raises(PortfolioArtifactAlreadyExistsError):
            create_portfolio_reflection(
                session,
                thread_id=completed_thread.id,
                submitted_by_user_id=analyst_id,
                **_REFLECTION_KWARGS,
            )


class TestGetPortfolioArtifactForThread:
    def test_returns_none_when_no_reflection_exists(
        self, session: Session, completed_thread: ChatThread
    ) -> None:
        assert get_portfolio_artifact_for_thread(session, completed_thread.id) is None

    def test_returns_the_reflection_once_authored(
        self, session: Session, completed_thread: ChatThread, analyst_id: uuid.UUID
    ) -> None:
        created = create_portfolio_reflection(
            session,
            thread_id=completed_thread.id,
            submitted_by_user_id=analyst_id,
            **_REFLECTION_KWARGS,
        )

        found = get_portfolio_artifact_for_thread(session, completed_thread.id)

        assert found is not None
        assert found.id == created.id


class TestGetPortfolioExport:
    def test_raises_when_the_thread_is_not_completed(
        self, session: Session, thread: ChatThread
    ) -> None:
        with pytest.raises(ThreadNotCompletedError):
            get_portfolio_export(session, thread.id)

    def test_compiles_with_no_human_review_and_no_reflection(
        self, session: Session, completed_thread: ChatThread
    ) -> None:
        export = get_portfolio_export(session, completed_thread.id)

        assert export["scenario"]["title"] == "zztest portfolio scenario"
        assert export["trigger"] == "East's service is getting worse."
        assert len(export["messages"]) == 2
        assert export["evaluation"]["difficulty_recommendation"] == "standard"
        assert export["human_review"] is None
        assert export["reflection"] is None

    def test_compiles_with_a_human_review_and_a_reflection(
        self, session: Session, completed_thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        evaluation = session.query(Evaluation).filter_by(thread_id=completed_thread.id).one()
        record_human_review(
            session,
            evaluation_id=evaluation.id,
            submitted_by_user_id=admin_id,
            reviewer_name="Prof. Rivera",
            verdict=HumanReviewVerdict.OVERRIDE,
            tier_assessment_notes="Evidence supports a stretch call.",
            overridden_recommendation=DifficultyRecommendation.STRETCH,
        )
        create_portfolio_reflection(
            session,
            thread_id=completed_thread.id,
            submitted_by_user_id=analyst_id,
            **_REFLECTION_KWARGS,
        )

        export = get_portfolio_export(session, completed_thread.id)

        assert export["human_review"]["verdict"] == "override"
        assert export["human_review"]["overridden_recommendation"] == "stretch"
        assert export["reflection"]["reflection_skill_improved"] == "Root-cause analysis."

    def test_never_includes_raw_response(
        self, session: Session, completed_thread: ChatThread
    ) -> None:
        export = get_portfolio_export(session, completed_thread.id)

        assert "raw_response" not in export["evaluation"]
