"""Unit 23 (MEADOWOPS-DOM-017, business id MEADOWOPS-DOMAIN-012, PRD 6.5/
6.6/6.13): transactional-layer tests for the persona-roleplay pushback
suggestion and AI sufficiency check. Both are read-only (no DB writes) - see
app.services.persona_chat's own docstring. Same non-autocommit discipline as
tests/services/test_chat_service.py: runs inside an uncommitted transaction
per test, rolled back at fixture teardown.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.db.auth import User
from app.db.chat import ChatThread
from app.db.enums import (
    CompetencyCluster,
    DifficultyTier,
    ScenarioStatus,
    ScenarioType,
    StakeholderPersona,
    UserRole,
)
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.domain.claude_client import ClaudeResponse, MockClaudeClient
from app.domain.persona_chat import Attitude
from app.services.baseline_data import seed_master_data
from app.services.chat import list_messages, send_message
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.persona_chat import (
    MAX_PUSHBACK_ROUNDS,
    MaxPushbackRoundsExceededError,
    NoAnalystMessageYetError,
    ScenarioCancelledError,
    check_thread_sufficiency,
    suggest_thread_pushback,
)
from app.services.scenario_service import create_scenario_from_exception_flag

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ADMIN_EMAIL = "zztest-persona-chat-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-persona-chat-analyst@meadowops.local"

_GRADING_ONLY_MARKERS = (
    "SECRET-SIGNAL",
    "SECRET-DISTRACTOR",
    "SECRET-CONSIDERATION",
    "SECRET-CONCLUSION",
    "SECRET-UNCERTAINTY",
)


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


def _make_active_scenario_with_full_ground_truth(session: Session, *, admin_id: uuid.UUID) -> Scenario:
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
        title="zztest persona chat scenario",
        created_by=admin_id,
    )
    # Test setup shortcut, same convention as tests/services/
    # test_scenario_service.py's _complete_ground_truth: directly completing
    # the AI-narrative fields and activating status, rather than driving
    # regenerate_scenario/approve_scenario/activate_scenario's full state
    # machine - this module's own tests are about persona_chat's read-only
    # logic, not scenario_service's transition rules.
    scenario.ground_truth = {
        **scenario.ground_truth,
        "supporting_signals": ["SECRET-SIGNAL"],
        "distractors": ["SECRET-DISTRACTOR"],
        "expected_considerations": ["SECRET-CONSIDERATION"],
        "acceptable_conclusions": ["SECRET-CONCLUSION-ok"],
        "unacceptable_conclusions": ["SECRET-CONCLUSION-bad"],
        "uncertainty": "SECRET-UNCERTAINTY",
    }
    scenario.status = ScenarioStatus.ACTIVE
    session.flush()
    return scenario


@pytest.fixture
def scenario(session: Session, admin_id: uuid.UUID) -> Scenario:
    return _make_active_scenario_with_full_ground_truth(session, admin_id=admin_id)


@pytest.fixture
def thread(session: Session, scenario: Scenario) -> ChatThread:
    thread = ChatThread(scenario_id=scenario.id, persona=StakeholderPersona.CFO)
    session.add(thread)
    session.flush()
    return thread


class TestSuggestThreadPushback:
    def test_raises_when_no_analyst_message_exists_yet(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID
    ) -> None:
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="Opening message from the persona.",
        )
        client = MockClaudeClient(script=[ClaudeResponse(content="unused")])

        with pytest.raises(NoAnalystMessageYetError):
            suggest_thread_pushback(
                session, thread_id=thread.id, attitude=Attitude.NEUTRAL, claude_client=client
            )

    def test_suggests_a_message_once_an_analyst_has_replied(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="What's the status on SKU-COR-001?",
        )
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="I think the reorder point is fine as-is.",
        )
        client = MockClaudeClient(script=[ClaudeResponse(content="That doesn't add up to me.")])

        suggestion = suggest_thread_pushback(
            session, thread_id=thread.id, attitude=Attitude.SKEPTICAL, claude_client=client
        )

        assert suggestion == "That doesn't add up to me."

    def test_raises_once_the_analyst_has_already_replied_the_maximum_number_of_rounds(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        """PRD 9.2 catalog row 17: the pushback loop must conclude
        gracefully (proceed to evaluation) rather than hang indefinitely -
        no more AI-suggested pushback once the Analyst has already replied
        MAX_PUSHBACK_ROUNDS times."""
        for round_number in range(MAX_PUSHBACK_ROUNDS):
            send_message(
                session, thread_id=thread.id, sender_user_id=admin_id, sender_role=UserRole.ADMIN,
                body=f"Pushback round {round_number}.",
            )
            send_message(
                session, thread_id=thread.id, sender_user_id=analyst_id, sender_role=UserRole.ANALYST,
                body=f"Analyst reply {round_number}.",
            )
        client = MockClaudeClient(script=[ClaudeResponse(content="unused")])

        with pytest.raises(MaxPushbackRoundsExceededError):
            suggest_thread_pushback(
                session, thread_id=thread.id, attitude=Attitude.NEUTRAL, claude_client=client
            )

    def test_does_not_raise_one_round_before_the_maximum(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        for round_number in range(MAX_PUSHBACK_ROUNDS - 1):
            send_message(
                session, thread_id=thread.id, sender_user_id=admin_id, sender_role=UserRole.ADMIN,
                body=f"Pushback round {round_number}.",
            )
            send_message(
                session, thread_id=thread.id, sender_user_id=analyst_id, sender_role=UserRole.ANALYST,
                body=f"Analyst reply {round_number}.",
            )
        client = MockClaudeClient(script=[ClaudeResponse(content="Still not convinced.")])

        suggestion = suggest_thread_pushback(
            session, thread_id=thread.id, attitude=Attitude.NEUTRAL, claude_client=client
        )

        assert suggestion == "Still not convinced."

    def test_the_latest_analyst_message_appears_exactly_once_in_the_prompt(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        # Code review finding: STAKEHOLDER_ROLEPLAY_TEMPLATE has two
        # distinct sections - "Conversation so far" (history) and "The
        # Analyst just said" (the current turn) - conversation_history must
        # stop *before* the message being reacted to, or that message's
        # body appears twice in the rendered prompt.
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="Opening.",
        )
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="UNIQUE-ANALYST-BODY-MARKER",
        )
        client = MockClaudeClient(script=[ClaudeResponse(content="Suggestion.")])

        suggest_thread_pushback(
            session, thread_id=thread.id, attitude=Attitude.NEUTRAL, claude_client=client
        )

        sent_prompt = client.call_log[0]["messages"][0]["content"]
        assert sent_prompt.count("UNIQUE-ANALYST-BODY-MARKER") == 1

    def test_does_not_write_any_message_or_change_message_count(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="What's the status?",
        )
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="Looks fine to me.",
        )
        before = len(list_messages(session, thread.id))
        client = MockClaudeClient(script=[ClaudeResponse(content="Suggestion text.")])

        suggest_thread_pushback(
            session, thread_id=thread.id, attitude=Attitude.URGENT, claude_client=client
        )

        after = len(list_messages(session, thread.id))
        assert after == before

    def test_excludes_grading_fields_from_the_prompt(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="What's going on?",
        )
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="Seems okay.",
        )
        client = MockClaudeClient(script=[ClaudeResponse(content="Suggestion text.")])

        suggest_thread_pushback(
            session, thread_id=thread.id, attitude=Attitude.NEUTRAL, claude_client=client
        )

        sent_prompt = client.call_log[0]["messages"][0]["content"]
        for marker in _GRADING_ONLY_MARKERS:
            assert marker not in sent_prompt

    def test_raises_when_the_scenario_is_cancelled(
        self, session: Session, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        cancelled_scenario = _make_active_scenario_with_full_ground_truth(session, admin_id=admin_id)
        cancelled_scenario.status = ScenarioStatus.CANCELLED
        session.flush()
        thread = ChatThread(scenario_id=cancelled_scenario.id, persona=StakeholderPersona.CFO)
        session.add(thread)
        session.flush()
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="Opening.",
        )
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="Reply.",
        )
        client = MockClaudeClient(script=[ClaudeResponse(content="unused")])

        with pytest.raises(ScenarioCancelledError):
            suggest_thread_pushback(
                session, thread_id=thread.id, attitude=Attitude.NEUTRAL, claude_client=client
            )


class TestCheckThreadSufficiency:
    def test_raises_when_no_analyst_message_exists_yet(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID
    ) -> None:
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="Opening message.",
        )
        client = MockClaudeClient(script=[ClaudeResponse(content="unused")])

        with pytest.raises(NoAnalystMessageYetError):
            check_thread_sufficiency(session, thread_id=thread.id, claude_client=client)

    def test_returns_a_verdict_once_an_analyst_has_replied(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="What's the status?",
        )
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="I think the reorder point is fine.",
        )
        payload = {"verdict": "insufficient", "suggested_pushback": "But what about lead time?"}
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(payload))])

        verdict = check_thread_sufficiency(session, thread_id=thread.id, claude_client=client)

        assert verdict.verdict == "insufficient"
        assert verdict.suggested_pushback == "But what about lead time?"

    def test_uses_the_full_ground_truth_package_not_a_redacted_one(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="What's the status?",
        )
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="I think the reorder point is fine.",
        )
        payload = {"verdict": "sufficient", "suggested_pushback": None}
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(payload))])

        check_thread_sufficiency(session, thread_id=thread.id, claude_client=client)

        sent_prompt = client.call_log[0]["messages"][0]["content"]
        assert "SECRET-SIGNAL" in sent_prompt

    def test_does_not_write_any_message_or_change_message_count(
        self, session: Session, thread: ChatThread, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="What's the status?",
        )
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="Looks fine.",
        )
        before = len(list_messages(session, thread.id))
        payload = {"verdict": "sufficient", "suggested_pushback": None}
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(payload))])

        check_thread_sufficiency(session, thread_id=thread.id, claude_client=client)

        after = len(list_messages(session, thread.id))
        assert after == before

    def test_raises_when_the_scenario_is_cancelled(
        self, session: Session, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        cancelled_scenario = _make_active_scenario_with_full_ground_truth(session, admin_id=admin_id)
        cancelled_scenario.status = ScenarioStatus.CANCELLED
        session.flush()
        thread = ChatThread(scenario_id=cancelled_scenario.id, persona=StakeholderPersona.CFO)
        session.add(thread)
        session.flush()
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="Opening.",
        )
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="Reply.",
        )
        client = MockClaudeClient(script=[ClaudeResponse(content="unused")])

        with pytest.raises(ScenarioCancelledError):
            check_thread_sufficiency(session, thread_id=thread.id, claude_client=client)
