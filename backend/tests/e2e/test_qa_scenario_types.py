"""Unit 29 (MEADOWOPS-QA-001, harness-os spec MEADOWOPS-API-029, PRD
6.2/6.6/9.1): the QA test-analyst harness's main run — one full pass of
PRD 6.6's interaction loop (steps 1-10) for each of PRD 6.2's six scenario
types, via tests.support.qa_harness's real-route driver. No production
code changes: this is the "end-to-end tests via a QA test-analyst harness"
unit PRD 9.1 calls for, not a new feature.

Each test asserts real state left behind at every step (scenario reaches
`active`, the evaluation row is fetchable independently of the /complete
response, the Ledger decision reaches `accepted`) rather than trusting a
single response body, the same "containment, not a single response"
discipline tests/api/test_evaluation_api.py's own assertions already use.

The simulated callback scenario (PRD 6.6/9.1/Appendix C) is a separate run
- tests/e2e/test_qa_callback_scenario.py - since it needs a first decision
already advanced to `outcome_observed` before it can even start.
"""

import os
from collections.abc import Generator
from datetime import date
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.auth import User
from app.db.enums import UserRole
from app.db.exception_flags import ExceptionFlag
from app.main import create_app
from tests.support.auth import TEST_SESSION_SECRET, make_token
from tests.support.qa_harness import (
    complete_thread,
    create_and_activate_scenario,
    ground_truth_updates_for,
    open_persona_thread,
    propose_and_accept_decision,
    run_pushback_round,
)

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ADMIN_EMAIL = "zztest-qa-harness-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-qa-harness-analyst@meadowops.local"
_SERVICE_TOKEN = "test-internal-service-token-value-at-least-32-bytes-long"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "session_secret_key": TEST_SESSION_SECRET,
        "internal_service_token": _SERVICE_TOKEN,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(create_app(settings=_settings())) as c:
        yield c


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def admin_user_id(db_session: Session) -> Generator[str, None, None]:
    db_session.execute(delete(User).where(User.email == _ADMIN_EMAIL))
    db_session.commit()
    user = User(email=_ADMIN_EMAIL, password_hash="x", role=UserRole.ADMIN, is_active=True)
    db_session.add(user)
    db_session.commit()
    yield str(user.id)
    db_session.execute(delete(User).where(User.email == _ADMIN_EMAIL))
    db_session.commit()


@pytest.fixture
def analyst_user_id(db_session: Session) -> Generator[str, None, None]:
    db_session.execute(delete(User).where(User.email == _ANALYST_EMAIL))
    db_session.commit()
    user = User(email=_ANALYST_EMAIL, password_hash="x", role=UserRole.ANALYST, is_active=True)
    db_session.add(user)
    db_session.commit()
    yield str(user.id)
    db_session.execute(delete(User).where(User.email == _ANALYST_EMAIL))
    db_session.commit()


@pytest.fixture
def admin_auth(admin_user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token('admin', user_id=admin_user_id)}"}


@pytest.fixture
def analyst_auth(analyst_user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token('analyst', user_id=analyst_user_id)}"}


@pytest.fixture
def exception_flag_id(
    db_session: Session, owner_dsn: str
) -> Generator[str, None, None]:
    flag = ExceptionFlag(
        category="low_stock_days_of_supply",
        product_id=_PRODUCT_ID,
        warehouse_id=_WAREHOUSE_ID,
        simulation_date=date(2026, 6, 1),
        first_detected_simulation_date=date(2026, 5, 20),
        measured_value=Decimal("4.00"),
        threshold_value=Decimal("10.00"),
    )
    db_session.add(flag)
    db_session.commit()
    flag_id = str(flag.id)
    yield flag_id
    # Teardown mirrors tests/api/test_evaluation_api.py's own scenario_id
    # fixture - duplicated rather than imported, this project's established
    # per-test-file convention (tests/support/auth.py's own docstring).
    # decision_event carries no no-delete trigger (only chat_message,
    # evaluation, human_review, and portfolio_artifact do - confirmed
    # against alembic/versions/0018, 0020, 0021), so it's a plain delete.
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "select id from engine.scenario where source_exception_flag_id = %s", (flag_id,)
        )
        scenario_ids = [row[0] for row in cur.fetchall()]
        for scenario_id in scenario_ids:
            cur.execute("delete from live.decision_event where scenario_id = %s", (scenario_id,))
            cur.execute(
                "delete from chat.chat_thread_read_state where thread_id in "
                "(select id from chat.chat_thread where scenario_id = %s)",
                (scenario_id,),
            )
            cur.execute("alter table engine.evaluation disable trigger evaluation_no_delete")
            try:
                cur.execute(
                    "delete from engine.evaluation where thread_id in "
                    "(select id from chat.chat_thread where scenario_id = %s)",
                    (scenario_id,),
                )
            finally:
                cur.execute("alter table engine.evaluation enable trigger evaluation_no_delete")
            cur.execute("alter table chat.chat_message disable trigger chat_message_no_delete")
            try:
                cur.execute(
                    "delete from chat.chat_message where thread_id in "
                    "(select id from chat.chat_thread where scenario_id = %s)",
                    (scenario_id,),
                )
            finally:
                cur.execute("alter table chat.chat_message enable trigger chat_message_no_delete")
            cur.execute("delete from chat.chat_thread where scenario_id = %s", (scenario_id,))
            cur.execute("delete from engine.scenario where id = %s", (scenario_id,))
        cur.execute("delete from live.exception_flag where id = %s", (flag_id,))


def _evaluation_payload(recommendation: str) -> dict:
    return {
        "strengths": "Correctly identified the driving signal.",
        "gaps": "Did not fully quantify the downstream cost impact.",
        "evidence": "Cited the relevant measured value against its threshold.",
        "senior_analyst_pushback": "What would change your recommendation?",
        "final_verdict": "Solid investigation for this scenario type.",
        "suggested_next_skill_focus": "Quantifying financial impact.",
        "difficulty_recommendation": recommendation,
    }


class TestScenarioTypeLoops:
    """One test per PRD 6.2 scenario type (all 6, per PRD 9.1/9.3/10's
    "each of the 6... at least once" - the more specific and more
    frequently repeated framing than 6.2's own heading, which this unit
    treats as the controlling requirement)."""

    def _run_full_loop(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        exception_flag_id: str,
        *,
        scenario_type: str,
        competency_cluster: str,
        persona: str,
        narrative: str,
    ) -> None:
        scenario_id = create_and_activate_scenario(
            client,
            admin_auth,
            exception_flag_id=exception_flag_id,
            scenario_type=scenario_type,
            competency_cluster=competency_cluster,
            difficulty_tier="standard",
            title=f"zztest qa harness - {scenario_type}",
            ground_truth_updates=ground_truth_updates_for(narrative),
        )

        thread_id = open_persona_thread(
            client, admin_auth, scenario_id=scenario_id, persona=persona
        )

        run_pushback_round(
            client,
            thread_id,
            admin_auth=admin_auth,
            analyst_auth=analyst_auth,
            opening_message=f"{narrative} - can you look into this?",
            initial_response="Here is my initial read of the situation.",
            pushback_message="What about the alternative explanation?",
            revision_message="Good point - here is my revised conclusion accounting for that.",
        )

        complete_thread(
            client, thread_id, admin_auth, _evaluation_payload("standard")
        )

        # Provable state, not just the /complete response - a fresh GET
        # proves the Evaluation row was actually persisted.
        response = client.get(f"/api/v1/evaluations/threads/{thread_id}", headers=admin_auth)
        assert response.status_code == 200
        evaluation = response.json()
        assert evaluation["thread_id"] == thread_id
        assert evaluation["difficulty_recommendation"] == "standard"

        decision_id = propose_and_accept_decision(
            client,
            admin_auth,
            entity_type="warehouse",
            entity_id=_WAREHOUSE_ID,
            scenario_id=scenario_id,
            title=f"zztest qa harness decision - {scenario_type}",
            summary=f"Recommendation from the {scenario_type} scenario's evaluation.",
        )

        response = client.get(f"/api/v1/ledger/decisions/{decision_id}", headers=admin_auth)
        assert response.status_code == 200
        decision = response.json()
        assert decision["scenario_id"] == scenario_id
        assert decision["status"] == "accepted"

    def test_stakeholder_request(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        exception_flag_id: str,
    ) -> None:
        self._run_full_loop(
            client,
            admin_auth,
            analyst_auth,
            exception_flag_id,
            scenario_type="stakeholder_request",
            competency_cluster="communication",
            persona="operations_manager",
            narrative="Service levels are dropping in the East region",
        )

    def test_data_quality_issue(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        exception_flag_id: str,
    ) -> None:
        self._run_full_loop(
            client,
            admin_auth,
            analyst_auth,
            exception_flag_id,
            scenario_type="data_quality_issue",
            competency_cluster="analysis_diagnosis",
            persona="it_manager",
            narrative="WMS and Reporting disagree on the same SKU's on-hand count",
        )

    def test_root_cause_investigation(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        exception_flag_id: str,
    ) -> None:
        self._run_full_loop(
            client,
            admin_auth,
            analyst_auth,
            exception_flag_id,
            scenario_type="root_cause_investigation",
            competency_cluster="analysis_diagnosis",
            persona="warehouse_manager",
            narrative="A SKU keeps stocking out despite normal reorder points",
        )

    def test_supplier_vendor_decision(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        exception_flag_id: str,
    ) -> None:
        self._run_full_loop(
            client,
            admin_auth,
            analyst_auth,
            exception_flag_id,
            scenario_type="supplier_vendor_decision",
            competency_cluster="judgment_delivery",
            persona="procurement_manager",
            narrative="A supplier's lead time has crept up over the last quarter",
        )

    def test_process_breakdown(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        exception_flag_id: str,
    ) -> None:
        self._run_full_loop(
            client,
            admin_auth,
            analyst_auth,
            exception_flag_id,
            scenario_type="process_breakdown",
            competency_cluster="judgment_delivery",
            persona="operations_director",
            narrative="PO approvals are timing out before receiving, causing a backlog",
        )

    def test_executive_reporting(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        exception_flag_id: str,
    ) -> None:
        self._run_full_loop(
            client,
            admin_auth,
            analyst_auth,
            exception_flag_id,
            scenario_type="executive_reporting",
            competency_cluster="communication",
            persona="cfo",
            narrative="Leadership wants a one-page summary of inventory carrying cost trend",
        )
