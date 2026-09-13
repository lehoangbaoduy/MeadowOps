"""Unit 25 (MEADOWOPS-DOM-019, business id MEADOWOPS-DOMAIN-014, PRD 6.6
steps 8-9, 6.7): transactional-layer tests for completing a thread +
generating its evaluation, and the adaptive difficulty engine's DB-backed
lookup. Same non-autocommit discipline as tests/services/test_persona_chat_
service.py: runs inside an uncommitted transaction per test, rolled back at
fixture teardown."""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.db.auth import User
from app.db.chat import ChatThread
from app.db.enums import (
    ChatThreadStatus,
    CompetencyCluster,
    DifficultyRecommendation,
    DifficultyTier,
    ScenarioStatus,
    ScenarioType,
    StakeholderPersona,
    UserRole,
)
from app.db.evaluation import Evaluation
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.domain.claude_client import ClaudeAPIError, ClaudeResponse, MockClaudeClient
from app.domain.evaluation import EvaluationGenerationFailedError
from app.services.baseline_data import seed_master_data
from app.services.chat import send_message
from app.services.evaluation import (
    LatestMessageNotFromAnalystError,
    ThreadAlreadyCompletedError,
    complete_thread_and_generate_evaluation,
    get_evaluation_for_thread,
    resolve_difficulty_for_cluster,
)
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.persona_chat import ScenarioCancelledError
from app.services.scenario_service import (
    ScenarioTransitionError,
    activate_scenario,
    approve_scenario,
    create_scenario_from_exception_flag,
)

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ADMIN_EMAIL = "zztest-evaluation-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-evaluation-analyst@meadowops.local"

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


def _make_active_scenario(
    session: Session, *, admin_id: uuid.UUID, cluster: CompetencyCluster = CompetencyCluster.ANALYSIS_DIAGNOSIS
) -> Scenario:
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
        competency_cluster=cluster,
        difficulty_tier=DifficultyTier.STANDARD,
        title="zztest evaluation scenario",
        created_by=admin_id,
    )
    scenario.ground_truth = {
        **scenario.ground_truth,
        "supporting_signals": ["signal"],
        "distractors": ["distractor"],
        "expected_considerations": ["consideration"],
        "acceptable_conclusions": ["raise the reorder point"],
        "unacceptable_conclusions": ["blame the supplier"],
        "uncertainty": "moderate confidence",
    }
    scenario.status = ScenarioStatus.ACTIVE
    # live.exception_flag's own ux_exception_flag_open_entity partial
    # unique index (migration 0012) is scoped to (category, product_id,
    # warehouse_id, ...) WHERE resolved_at IS NULL -
    # TestResolveDifficultyForCluster below creates several scenarios in
    # the same uncommitted transaction, which would otherwise collide on
    # the identical tuple.
    flag.resolved_at = datetime.now(timezone.utc)
    session.flush()
    return scenario


def _make_thread(session: Session, scenario: Scenario) -> ChatThread:
    thread = ChatThread(scenario_id=scenario.id, persona=StakeholderPersona.CFO)
    session.add(thread)
    session.flush()
    return thread


def _send_opening_and_analyst_reply(
    session: Session, thread: ChatThread, *, admin_id: uuid.UUID, analyst_id: uuid.UUID
) -> None:
    send_message(
        session, thread_id=thread.id, sender_user_id=admin_id, sender_role=UserRole.ADMIN,
        body="What's the status on SKU-COR-001?",
    )
    send_message(
        session, thread_id=thread.id, sender_user_id=analyst_id, sender_role=UserRole.ANALYST,
        body="The reorder point looks misconfigured.",
    )


@pytest.fixture
def scenario(session: Session, admin_id: uuid.UUID) -> Scenario:
    return _make_active_scenario(session, admin_id=admin_id)


@pytest.fixture
def thread(session: Session, scenario: Scenario) -> ChatThread:
    return _make_thread(session, scenario)


class TestCompleteThreadAndGenerateEvaluation:
    def test_raises_when_the_latest_message_is_not_from_the_analyst(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID
    ) -> None:
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id, sender_role=UserRole.ADMIN,
            body="Opening only, no Analyst reply yet.",
        )
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])

        with pytest.raises(LatestMessageNotFromAnalystError):
            complete_thread_and_generate_evaluation(session, thread_id=thread.id, claude_client=client)

    def test_raises_when_the_thread_has_no_messages_at_all(
        self, session: Session, thread: ChatThread
    ) -> None:
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])

        with pytest.raises(LatestMessageNotFromAnalystError):
            complete_thread_and_generate_evaluation(session, thread_id=thread.id, claude_client=client)

    def test_succeeds_and_marks_the_thread_completed(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        _send_opening_and_analyst_reply(session, thread, admin_id=admin_id, analyst_id=analyst_id)
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])

        evaluation = complete_thread_and_generate_evaluation(
            session, thread_id=thread.id, claude_client=client
        )

        assert evaluation.difficulty_recommendation == DifficultyRecommendation.STANDARD
        assert thread.status == ChatThreadStatus.COMPLETED

    def test_raises_when_the_thread_is_already_completed(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        _send_opening_and_analyst_reply(session, thread, admin_id=admin_id, analyst_id=analyst_id)
        first_client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])
        complete_thread_and_generate_evaluation(session, thread_id=thread.id, claude_client=first_client)

        second_client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])
        with pytest.raises(ThreadAlreadyCompletedError):
            complete_thread_and_generate_evaluation(
                session, thread_id=thread.id, claude_client=second_client
            )

    def test_generation_failure_leaves_the_thread_open_and_writes_no_evaluation(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        _send_opening_and_analyst_reply(session, thread, admin_id=admin_id, analyst_id=analyst_id)
        client = MockClaudeClient(
            script=[ClaudeAPIError("rate limited"), ClaudeAPIError("rate limited again")]
        )

        with pytest.raises(EvaluationGenerationFailedError):
            complete_thread_and_generate_evaluation(session, thread_id=thread.id, claude_client=client)

        assert thread.status == ChatThreadStatus.OPEN
        assert get_evaluation_for_thread(session, thread.id) is None

    def test_the_analyst_response_reaches_the_prompt(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        _send_opening_and_analyst_reply(session, thread, admin_id=admin_id, analyst_id=analyst_id)
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])

        complete_thread_and_generate_evaluation(session, thread_id=thread.id, claude_client=client)

        sent_prompt = client.call_log[0]["messages"][0]["content"]
        assert "reorder point looks misconfigured" in sent_prompt

    def test_stores_the_prompt_version(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        _send_opening_and_analyst_reply(session, thread, admin_id=admin_id, analyst_id=analyst_id)
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])

        evaluation = complete_thread_and_generate_evaluation(
            session, thread_id=thread.id, claude_client=client
        )

        assert evaluation.prompt_version == "draft_evaluation/v1"

    def test_raises_when_the_scenario_is_cancelled(
        self, session: Session, thread: ChatThread, scenario: Scenario,
        admin_id: uuid.UUID, analyst_id: uuid.UUID,
    ) -> None:
        # Advisor review (post-implementation, before this unit was closed):
        # generate_evaluation writes an Evaluation row the migration-0020
        # trigger makes permanently immutable, so a cancelled scenario's
        # thread must be refused here rather than left to the caller - once
        # written, it can never be retracted (unlike app.services.
        # persona_chat's read-only calls, which just waste a Claude call on
        # a stale scenario).
        _send_opening_and_analyst_reply(session, thread, admin_id=admin_id, analyst_id=analyst_id)
        scenario.status = ScenarioStatus.CANCELLED
        session.flush()
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])

        with pytest.raises(ScenarioCancelledError):
            complete_thread_and_generate_evaluation(session, thread_id=thread.id, claude_client=client)

        assert thread.status == ChatThreadStatus.OPEN
        assert get_evaluation_for_thread(session, thread.id) is None


class TestActivateScenarioSingleActiveGuard:
    """Unit 30 (MEADOWOPS-DOM-030, PRD 9.2 catalog row 19): only one
    scenario active *at a time* - not one scenario active across this
    system's entire history. ScenarioStatus has no active->completed
    transition (app.domain.scenario.VALID_TRANSITIONS), so a scenario
    whose work is actually finished (its chat thread completed) must not
    permanently block every future activation - unlike the still-open-
    thread case, which correctly still blocks."""

    def _approved_scenario(self, session: Session, *, admin_id: uuid.UUID, product_id: str) -> Scenario:
        flag = ExceptionFlag(
            category="low_stock_days_of_supply",
            product_id=product_id,
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
            title="zztest single-active-guard scenario",
            created_by=admin_id,
        )
        scenario.ground_truth = {
            **scenario.ground_truth,
            "supporting_signals": ["signal"],
            "distractors": ["distractor"],
            "expected_considerations": ["consideration"],
            "acceptable_conclusions": ["raise the reorder point"],
            "unacceptable_conclusions": ["blame the supplier"],
            "uncertainty": "moderate confidence",
        }
        session.flush()
        approve_scenario(session, scenario.id)
        return scenario

    def test_blocks_activating_a_second_scenario_while_the_first_s_thread_is_still_open(
        self, session: Session, admin_id: uuid.UUID
    ) -> None:
        first = self._approved_scenario(session, admin_id=admin_id, product_id=_PRODUCT_ID)
        second = self._approved_scenario(session, admin_id=admin_id, product_id="SKU-COR-002")
        activate_scenario(session, first.id)

        with pytest.raises(ScenarioTransitionError):
            activate_scenario(session, second.id)

    def test_allows_activating_a_second_scenario_once_the_first_s_thread_is_completed(
        self, session: Session, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        first = self._approved_scenario(session, admin_id=admin_id, product_id=_PRODUCT_ID)
        second = self._approved_scenario(session, admin_id=admin_id, product_id="SKU-COR-002")
        activate_scenario(session, first.id)

        thread = ChatThread(scenario_id=first.id, persona=StakeholderPersona.CFO)
        session.add(thread)
        session.flush()
        _send_opening_and_analyst_reply(session, thread, admin_id=admin_id, analyst_id=analyst_id)
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])
        complete_thread_and_generate_evaluation(session, thread_id=thread.id, claude_client=client)

        activate_scenario(session, second.id)

        assert second.status == ScenarioStatus.ACTIVE


class TestGetEvaluationForThread:
    def test_returns_none_when_no_evaluation_exists(self, session: Session, thread: ChatThread) -> None:
        assert get_evaluation_for_thread(session, thread.id) is None

    def test_returns_the_evaluation_once_generated(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        _send_opening_and_analyst_reply(session, thread, admin_id=admin_id, analyst_id=analyst_id)
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])
        created = complete_thread_and_generate_evaluation(
            session, thread_id=thread.id, claude_client=client
        )

        found = get_evaluation_for_thread(session, thread.id)

        assert found is not None
        assert found.id == created.id


def _complete_with_recommendation(
    session: Session,
    *,
    admin_id: uuid.UUID,
    analyst_id: uuid.UUID,
    cluster: CompetencyCluster,
    recommendation: str,
    created_at: datetime,
) -> Evaluation:
    # Inserts an Evaluation row directly rather than going through
    # complete_thread_and_generate_evaluation - these tests are about
    # resolve_difficulty_for_cluster's own query/ordering behavior (that
    # full pipeline is TestCompleteThreadAndGenerateEvaluation's job
    # above), and engine.evaluation's immutability trigger (migration
    # 0020, ER-6) blocks an UPDATE of created_at after the fact - func.
    # now() is transaction-time (frozen per transaction, same gotcha
    # app.services.chat.mark_thread_read's own docstring documents), so
    # every row inserted through the real service in one test's
    # uncommitted transaction would otherwise share the exact same
    # created_at, making ordering nondeterministic. Setting it explicitly
    # at INSERT time is unaffected by the trigger (UPDATE/DELETE/
    # TRUNCATE only).
    scenario = _make_active_scenario(session, admin_id=admin_id, cluster=cluster)
    thread = _make_thread(session, scenario)
    evaluation = Evaluation(
        thread_id=thread.id,
        prompt_version="draft_evaluation/v1",
        strengths="s", gaps="g", evidence="e",
        senior_analyst_pushback="p", final_verdict="v", suggested_next_skill_focus="f",
        difficulty_recommendation=DifficultyRecommendation(recommendation),
        raw_response="{}",
        created_at=created_at,
    )
    session.add(evaluation)
    session.flush()
    return evaluation


class TestResolveDifficultyForCluster:
    def test_holds_with_no_evaluations(self, session: Session) -> None:
        result = resolve_difficulty_for_cluster(session, CompetencyCluster.ANALYSIS_DIAGNOSIS)
        assert result == DifficultyRecommendation.HOLD

    def test_holds_with_only_one_evaluation(
        self, session: Session, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        now = datetime.now(timezone.utc)
        _complete_with_recommendation(
            session, admin_id=admin_id, analyst_id=analyst_id,
            cluster=CompetencyCluster.COMMUNICATION, recommendation="stretch", created_at=now,
        )
        result = resolve_difficulty_for_cluster(session, CompetencyCluster.COMMUNICATION)
        assert result == DifficultyRecommendation.HOLD

    def test_resolves_to_the_tier_when_the_two_most_recent_agree(
        self, session: Session, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        now = datetime.now(timezone.utc)
        _complete_with_recommendation(
            session, admin_id=admin_id, analyst_id=analyst_id,
            cluster=CompetencyCluster.JUDGMENT_DELIVERY, recommendation="stretch",
            created_at=now - timedelta(days=2),
        )
        _complete_with_recommendation(
            session, admin_id=admin_id, analyst_id=analyst_id,
            cluster=CompetencyCluster.JUDGMENT_DELIVERY, recommendation="stretch",
            created_at=now - timedelta(days=1),
        )
        result = resolve_difficulty_for_cluster(session, CompetencyCluster.JUDGMENT_DELIVERY)
        assert result == DifficultyRecommendation.STRETCH

    def test_holds_when_the_two_most_recent_disagree(
        self, session: Session, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        now = datetime.now(timezone.utc)
        _complete_with_recommendation(
            session, admin_id=admin_id, analyst_id=analyst_id,
            cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS, recommendation="foundational",
            created_at=now - timedelta(days=2),
        )
        _complete_with_recommendation(
            session, admin_id=admin_id, analyst_id=analyst_id,
            cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS, recommendation="standard",
            created_at=now - timedelta(days=1),
        )
        result = resolve_difficulty_for_cluster(session, CompetencyCluster.ANALYSIS_DIAGNOSIS)
        assert result == DifficultyRecommendation.HOLD

    def test_ignores_evaluations_from_a_different_cluster(
        self, session: Session, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        now = datetime.now(timezone.utc)
        _complete_with_recommendation(
            session, admin_id=admin_id, analyst_id=analyst_id,
            cluster=CompetencyCluster.COMMUNICATION, recommendation="stretch",
            created_at=now - timedelta(days=2),
        )
        _complete_with_recommendation(
            session, admin_id=admin_id, analyst_id=analyst_id,
            cluster=CompetencyCluster.COMMUNICATION, recommendation="stretch",
            created_at=now - timedelta(days=1),
        )
        result = resolve_difficulty_for_cluster(session, CompetencyCluster.JUDGMENT_DELIVERY)
        assert result == DifficultyRecommendation.HOLD

    def test_only_the_two_most_recent_matter_even_with_an_older_disagreement(
        self, session: Session, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        now = datetime.now(timezone.utc)
        _complete_with_recommendation(
            session, admin_id=admin_id, analyst_id=analyst_id,
            cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS, recommendation="foundational",
            created_at=now - timedelta(days=3),
        )
        _complete_with_recommendation(
            session, admin_id=admin_id, analyst_id=analyst_id,
            cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS, recommendation="stretch",
            created_at=now - timedelta(days=2),
        )
        _complete_with_recommendation(
            session, admin_id=admin_id, analyst_id=analyst_id,
            cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS, recommendation="stretch",
            created_at=now - timedelta(days=1),
        )
        result = resolve_difficulty_for_cluster(session, CompetencyCluster.ANALYSIS_DIAGNOSIS)
        assert result == DifficultyRecommendation.STRETCH
