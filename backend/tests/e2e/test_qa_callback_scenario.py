"""Unit 29 (MEADOWOPS-QA-001, harness-os spec MEADOWOPS-API-029, PRD
6.6/9.1/Appendix C): the harness's simulated callback run - "your changes
helped, but X. Should we keep the new policy?"

No dedicated callback API exists on Scenario (confirmed: no callback/
referenced_decision/continuity field anywhere on app.db.scenario.Scenario,
and app.services.subsystem2.ledger_client's own docstring says wiring
find_callback_candidates into scenario generation was deliberately
deferred to "a later unit's job"). This unit is that later unit's *test*
job, not the wiring itself - MEADOWOPS-QA-001 stays test-only, so this
test assembles the callback narrative by hand: it advances a first
decision to `outcome_observed`, confirms the callback-candidates route
actually surfaces it, and only then builds a second scenario whose
hand-authored ground truth references that observed outcome.

Same entity (a supplier) both times - PRD 4.4's own callback example is
always keyed on one entity across two decisions, and Appendix C's S-004
storyline is exactly this shape (a supplier's lead-time recommendation,
revisited once).
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
    advance_decision_to_outcome_observed,
    complete_thread,
    create_and_activate_scenario,
    ground_truth_updates_for,
    open_persona_thread,
    propose_and_accept_decision,
    run_pushback_round,
)

_PRODUCT_ID = "SKU-COR-001"
_CALLBACK_PRODUCT_ID = "SKU-COR-002"
_WAREHOUSE_ID = "WH-EAST"
_SUPPLIER_ID = "S-004"
_ADMIN_EMAIL = "zztest-qa-callback-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-qa-callback-analyst@meadowops.local"
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
def two_exception_flag_ids(
    db_session: Session, owner_dsn: str
) -> Generator[tuple[str, str], None, None]:
    """Two open flags on the same product/warehouse - the original
    decision's scenario and the callback scenario each get their own, same
    reasoning as create_scenario_from_exception_flag's per-scenario
    snapshot (a single flag isn't reused across two separate scenarios
    anywhere else in this codebase either)."""
    flags = [
        ExceptionFlag(
            category="low_stock_days_of_supply",
            product_id=_PRODUCT_ID,
            warehouse_id=_WAREHOUSE_ID,
            simulation_date=date(2026, 6, 1),
            first_detected_simulation_date=date(2026, 5, 20),
            measured_value=Decimal("4.00"),
            threshold_value=Decimal("10.00"),
        ),
        ExceptionFlag(
            category="low_stock_days_of_supply",
            product_id=_CALLBACK_PRODUCT_ID,
            warehouse_id=_WAREHOUSE_ID,
            simulation_date=date(2026, 7, 1),
            first_detected_simulation_date=date(2026, 6, 20),
            measured_value=Decimal("3.00"),
            threshold_value=Decimal("10.00"),
        ),
    ]
    for flag in flags:
        db_session.add(flag)
    db_session.commit()
    flag_ids = [str(flag.id) for flag in flags]
    yield flag_ids[0], flag_ids[1]

    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        for flag_id in flag_ids:
            cur.execute(
                "select id from engine.scenario where source_exception_flag_id = %s", (flag_id,)
            )
            scenario_ids = [row[0] for row in cur.fetchall()]
            for scenario_id in scenario_ids:
                cur.execute(
                    "delete from live.decision_event where scenario_id = %s", (scenario_id,)
                )
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
                    cur.execute(
                        "alter table engine.evaluation enable trigger evaluation_no_delete"
                    )
                cur.execute(
                    "alter table chat.chat_message disable trigger chat_message_no_delete"
                )
                try:
                    cur.execute(
                        "delete from chat.chat_message where thread_id in "
                        "(select id from chat.chat_thread where scenario_id = %s)",
                        (scenario_id,),
                    )
                finally:
                    cur.execute(
                        "alter table chat.chat_message enable trigger chat_message_no_delete"
                    )
                cur.execute("delete from chat.chat_thread where scenario_id = %s", (scenario_id,))
                cur.execute("delete from engine.scenario where id = %s", (scenario_id,))
            cur.execute("delete from live.exception_flag where id = %s", (flag_id,))


def _evaluation_payload() -> dict:
    return {
        "strengths": "Correctly weighed the prior decision's observed outcome.",
        "gaps": "Did not fully quantify the new tradeoff's cost.",
        "evidence": "Referenced the earlier decision's recorded outcome.",
        "senior_analyst_pushback": "How would you balance service against carrying cost?",
        "final_verdict": "Solid continuity reasoning from the prior decision.",
        "suggested_next_skill_focus": "Quantifying tradeoffs across two competing metrics.",
        "difficulty_recommendation": "standard",
    }


class TestSimulatedCallbackScenario:
    def test_callback_scenario_references_a_prior_observed_outcome(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        two_exception_flag_ids: tuple[str, str],
    ) -> None:
        original_flag_id, callback_flag_id = two_exception_flag_ids

        # --- First pass: an ordinary supplier_vendor_decision run, taken
        # all the way to an observed outcome (PRD Appendix C's S-004
        # lead-time storyline).
        original_scenario_id = create_and_activate_scenario(
            client,
            admin_auth,
            exception_flag_id=original_flag_id,
            scenario_type="supplier_vendor_decision",
            competency_cluster="judgment_delivery",
            difficulty_tier="standard",
            title="zztest qa callback - original supplier decision",
            ground_truth_updates=ground_truth_updates_for(
                f"Supplier {_SUPPLIER_ID}'s lead time has crept up this quarter"
            ),
        )
        original_thread_id = open_persona_thread(
            client, admin_auth, scenario_id=original_scenario_id, persona="procurement_manager"
        )
        run_pushback_round(
            client,
            original_thread_id,
            admin_auth=admin_auth,
            analyst_auth=analyst_auth,
            opening_message=(
                f"Supplier {_SUPPLIER_ID}'s lead time keeps creeping up - what should we do?"
            ),
            initial_response="Recommend moving a portion of volume to a backup supplier.",
            pushback_message="What happens to our carrying cost if we do that?",
            revision_message="It rises modestly, but service risk drops more than that costs us.",
        )
        complete_thread(client, original_thread_id, admin_auth, _evaluation_payload())

        original_decision_id = propose_and_accept_decision(
            client,
            admin_auth,
            entity_type="supplier",
            entity_id=_SUPPLIER_ID,
            scenario_id=original_scenario_id,
            title=f"Shift volume away from {_SUPPLIER_ID}",
            summary="Move a portion of volume to a backup supplier to protect service levels.",
        )
        advanced = advance_decision_to_outcome_observed(
            client, admin_auth, original_decision_id, outcome="succeeded"
        )
        # Code review of this unit, MEDIUM: assert the actual transition
        # here rather than only inferring it later from callback-candidates
        # membership - _CALLBACK_ELIGIBLE_STATUSES (app/services/ledger.py)
        # also includes implemented/partially_implemented, so that
        # membership check alone can't distinguish "reached
        # outcome_observed" from "only reached implemented".
        assert advanced["status"] == "outcome_observed"
        assert advanced["outcome"] == "succeeded"

        # The callback mechanism itself (app.services.ledger.
        # find_callback_candidates via GET .../callback-candidates) must
        # actually surface the now-observed decision before the harness
        # hand-authors a scenario around it.
        response = client.get(
            f"/api/v1/ledger/entities/supplier/{_SUPPLIER_ID}/callback-candidates",
            headers=admin_auth,
        )
        assert response.status_code == 200
        candidate_ids = [candidate["id"] for candidate in response.json()]
        assert original_decision_id in candidate_ids

        # --- Second pass: the callback scenario itself - "your changes
        # helped, but inventory carrying cost is now higher. Should we keep
        # the new policy?" (PRD Appendix C).
        callback_scenario_id = create_and_activate_scenario(
            client,
            admin_auth,
            exception_flag_id=callback_flag_id,
            scenario_type="supplier_vendor_decision",
            competency_cluster="judgment_delivery",
            difficulty_tier="standard",
            title="zztest qa callback - carrying cost follow-up",
            ground_truth_updates=ground_truth_updates_for(
                f"Callback: shifting volume away from {_SUPPLIER_ID} improved service but "
                f"raised inventory carrying cost (see decision {original_decision_id}, "
                "outcome: succeeded)"
            ),
        )
        callback_thread_id = open_persona_thread(
            client, admin_auth, scenario_id=callback_scenario_id, persona="cfo"
        )
        run_pushback_round(
            client,
            callback_thread_id,
            admin_auth=admin_auth,
            analyst_auth=analyst_auth,
            opening_message=(
                "Your changes helped East, but inventory carrying cost is now higher. "
                "Should we keep the new policy?"
            ),
            initial_response="Yes - the service improvement outweighs the added carrying cost.",
            pushback_message="How confident are you in that tradeoff, quantitatively?",
            revision_message=(
                "Fairly confident: the carrying cost increase is modest next to the "
                "service-level and stockout-avoidance gains."
            ),
        )
        complete_thread(client, callback_thread_id, admin_auth, _evaluation_payload())

        response = client.get(
            f"/api/v1/evaluations/threads/{callback_thread_id}", headers=admin_auth
        )
        assert response.status_code == 200
        assert response.json()["difficulty_recommendation"] == "standard"

        callback_decision_id = propose_and_accept_decision(
            client,
            admin_auth,
            entity_type="supplier",
            entity_id=_SUPPLIER_ID,
            scenario_id=callback_scenario_id,
            title=f"Keep the {_SUPPLIER_ID} volume-shift policy",
            summary="Confirmed: keep the new sourcing policy despite the higher carrying cost.",
        )

        response = client.get(
            f"/api/v1/ledger/decisions/{callback_decision_id}", headers=admin_auth
        )
        assert response.status_code == 200
        callback_decision = response.json()
        assert callback_decision["scenario_id"] == callback_scenario_id
        assert callback_decision["status"] == "accepted"
        assert callback_decision["entity_id"] == _SUPPLIER_ID
