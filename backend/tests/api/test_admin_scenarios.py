"""Unit 18 (MEADOWOPS-DOM-011): admin scenario-builder API — every route is
require_admin-only (DD-24 point 4, no Analyst read path at all, unlike
every other Subsystem-1-facing resource in this codebase). Auth migrated
the same way test_master_data.py's own file describes: signed session
tokens minted via tests/support/auth.py, not a shared bearer token.

`created_by` on a created scenario must FK to a real `live.user.id` row
(app/db/scenario.py), so — unlike test_master_data.py's own `_AUTH`,
which is fine using the token helper's placeholder "test-user" subject
since master data never reads it — the admin token here is minted against
a real seeded `live.user` row's id.
"""

import json
import os
import uuid
from collections.abc import Generator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.auth import User
from app.db.enums import UserRole
from app.db.exception_flags import ExceptionFlag
from app.db.query_log import QueryLog
from app.db.scenario import Scenario
from app.domain.claude_client import ClaudeAPIError, ClaudeResponse, MockClaudeClient
from app.main import create_app
from app.services.baseline_data import seed_master_data
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from tests.support.auth import TEST_SESSION_SECRET, make_token

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ADMIN_EMAIL = "zztest-scenario-api-admin@meadowops.local"

_ANALYST_AUTH = {"Authorization": f"Bearer {make_token('analyst')}"}


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
    seed_master_data(db_session)
    seed_exception_rule_thresholds(db_session)
    user = User(
        email=_ADMIN_EMAIL, password_hash="not-a-real-hash", role=UserRole.ADMIN, is_active=True
    )
    db_session.add(user)
    db_session.commit()
    yield str(user.id)
    db_session.execute(delete(Scenario).where(Scenario.created_by == user.id))
    db_session.execute(delete(User).where(User.email == _ADMIN_EMAIL))
    db_session.commit()


@pytest.fixture
def admin_auth(admin_user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token('admin', user_id=admin_user_id)}"}


@pytest.fixture
def open_flag_id(db_session: Session) -> Generator[str, None, None]:
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
    yield str(flag.id)
    db_session.execute(delete(ExceptionFlag).where(ExceptionFlag.id == flag.id))
    db_session.commit()


@pytest.fixture
def second_flag_id(db_session: Session) -> Generator[str, None, None]:
    # Distinct product_id (SKU-COR-002, seeded baseline data - same
    # precedent as tests/e2e/test_qa_callback_scenario.py) so this flag
    # never collides with open_flag_id's own ux_exception_flag_open_entity
    # partial unique index.
    flag = ExceptionFlag(
        category="low_stock_days_of_supply",
        product_id="SKU-COR-002",
        warehouse_id=_WAREHOUSE_ID,
        simulation_date=date(2026, 6, 1),
        first_detected_simulation_date=date(2026, 5, 20),
        measured_value=Decimal("4.00"),
        threshold_value=Decimal("10.00"),
    )
    db_session.add(flag)
    db_session.commit()
    yield str(flag.id)
    db_session.execute(delete(ExceptionFlag).where(ExceptionFlag.id == flag.id))
    db_session.commit()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(create_app(settings=Settings(session_secret_key=TEST_SESSION_SECRET))) as c:
        yield c


def _create_payload(exception_flag_id: str) -> dict:
    return {
        "exception_flag_id": exception_flag_id,
        "scenario_type": "data_quality_issue",
        "competency_cluster": "analysis_diagnosis",
        "difficulty_tier": "standard",
        "title": "Low stock at WH-EAST",
    }


def _complete_ground_truth_payload() -> dict:
    return {
        "supporting_signals": ["signal"],
        "distractors": ["distractor"],
        "expected_considerations": ["consideration"],
        "acceptable_conclusions": ["ok"],
        "unacceptable_conclusions": ["bad"],
        "uncertainty": "moderate",
    }


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


class TestAuth:
    def test_list_requires_auth(self, client: TestClient) -> None:
        assert client.get("/api/v1/admin/scenarios").status_code == 401

    def test_list_is_forbidden_for_the_analyst_role(self, client: TestClient) -> None:
        response = client.get("/api/v1/admin/scenarios", headers=_ANALYST_AUTH)
        assert response.status_code == 403

    def test_create_is_forbidden_for_the_analyst_role(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/admin/scenarios",
            json=_create_payload(str(uuid.uuid4())),
            headers=_ANALYST_AUTH,
        )
        assert response.status_code == 403

    # DD-24 point 4's design claim is "no Analyst path at all" on this
    # resource, distinct from every other Subsystem-1-facing resource in
    # this codebase (which is Analyst-readable). A missing
    # Depends(require_admin) on any one of these five action routes would
    # pass the two tests above silently — parametrized the same way
    # test_master_data.py's own _ENTITY_PATHS covers every entity path.
    @pytest.mark.parametrize(
        "method,path_suffix",
        [
            ("get", "/{id}"),
            ("patch", "/{id}/ground-truth"),
            ("post", "/{id}/regenerate"),
            ("post", "/{id}/expected-query/run"),
            ("post", "/{id}/approve"),
            ("post", "/{id}/activate"),
            ("post", "/{id}/cancel"),
        ],
    )
    def test_every_scenario_action_route_is_forbidden_for_the_analyst_role(
        self, client: TestClient, method: str, path_suffix: str
    ) -> None:
        path = f"/api/v1/admin/scenarios{path_suffix.format(id=uuid.uuid4())}"
        kwargs = {"headers": _ANALYST_AUTH}
        if method in ("post", "patch"):
            kwargs["json"] = {}
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 403


class TestListScenarios:
    def test_an_invalid_status_filter_returns_422_not_500(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.get(
            "/api/v1/admin/scenarios?status_filter=not-a-real-status", headers=admin_auth
        )
        assert response.status_code == 422


class TestCreateScenario:
    def test_creates_a_draft_scenario_from_an_open_exception_flag(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        response = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=admin_auth
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "draft"
        assert body["source_exception_flag_id"] == open_flag_id

    def test_unknown_exception_flag_id_returns_404(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/admin/scenarios",
            json=_create_payload(str(uuid.uuid4())),
            headers=admin_auth,
        )
        assert response.status_code == 404

    def test_a_malformed_token_subject_returns_401_not_500(
        self, client: TestClient, open_flag_id: str
    ) -> None:
        # Security review, LOW: uuid.UUID(identity["user_id"]) must not be
        # an unhandled ValueError -> 500 on a non-UUID `sub` claim.
        bad_auth = {"Authorization": f"Bearer {make_token('admin', user_id='not-a-uuid')}"}
        response = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=bad_auth
        )
        assert response.status_code == 401

    def test_a_deleted_users_still_valid_token_returns_409_not_500(
        self, client: TestClient, open_flag_id: str
    ) -> None:
        # Code review, MEDIUM: created_by's hard FK to live.user.id must
        # surface as a clean 409, not an unhandled IntegrityError -> 500,
        # when a still-valid token's subject no longer exists as a real row.
        orphan_auth = {
            "Authorization": f"Bearer {make_token('admin', user_id=str(uuid.uuid4()))}"
        }
        response = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=orphan_auth
        )
        assert response.status_code == 409


class TestApproveScenario:
    def test_rejects_incomplete_ground_truth_with_error_details(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=admin_auth
        ).json()

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/approve", headers=admin_auth
        )

        assert response.status_code == 422
        assert response.json()["detail"]["errors"] != []

    def test_approves_after_the_builder_completes_ground_truth(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=admin_auth
        ).json()
        client.patch(
            f"/api/v1/admin/scenarios/{created['id']}/ground-truth",
            json=_complete_ground_truth_payload(),
            headers=admin_auth,
        )

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/approve", headers=admin_auth
        )

        assert response.status_code == 200
        assert response.json()["status"] == "approved"


class TestRegenerateScenario:
    def test_returns_503_when_no_claude_client_is_configured(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        # app.state.claude_client is None until a real Anthropic adapter is
        # wired in (Phase 4, blocker B3) — the route must fail clearly, not
        # crash, when the Builder hits Regenerate before then.
        created = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=admin_auth
        ).json()

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/regenerate", headers=admin_auth
        )

        assert response.status_code == 503

    def test_regenerates_with_an_ai_generated_narrative_when_configured(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=admin_auth
        ).json()
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content=json.dumps(_narrative_payload()))]
        )

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/regenerate", headers=admin_auth
        )

        assert response.status_code == 200
        assert response.json()["ground_truth"]["uncertainty"] == "moderate"
        assert response.json()["ground_truth"]["supporting_signals"] == ["signal"]

    def test_returns_422_with_error_details_when_referenced_ids_are_unknown(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=admin_auth
        ).json()
        client.app.state.claude_client = MockClaudeClient(
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

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/regenerate", headers=admin_auth
        )

        assert response.status_code == 422
        assert response.json()["detail"]["errors"] != []

    def test_returns_502_when_claude_generation_fails_after_retry(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=admin_auth
        ).json()
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeAPIError("boom"), ClaudeAPIError("boom again")]
        )

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/regenerate", headers=admin_auth
        )

        assert response.status_code == 502


class TestUpdateGroundTruth:
    def test_returns_404_for_an_unknown_scenario(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.patch(
            f"/api/v1/admin/scenarios/{uuid.uuid4()}/ground-truth",
            json={"uncertainty": "x"},
            headers=admin_auth,
        )
        assert response.status_code == 404

    def test_rejects_edits_to_an_approved_scenario(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        # Code review + security review, HIGH: this is the exact gap both
        # reviews found — approve_scenario's validation must not be
        # bypassable by a later PATCH once the scenario is no longer draft.
        created = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=admin_auth
        ).json()
        client.patch(
            f"/api/v1/admin/scenarios/{created['id']}/ground-truth",
            json=_complete_ground_truth_payload(),
            headers=admin_auth,
        )
        client.post(f"/api/v1/admin/scenarios/{created['id']}/approve", headers=admin_auth)

        response = client.patch(
            f"/api/v1/admin/scenarios/{created['id']}/ground-truth",
            json={"uncertainty": "tampered after approval"},
            headers=admin_auth,
        )

        assert response.status_code == 409
        unchanged = client.get(
            f"/api/v1/admin/scenarios/{created['id']}", headers=admin_auth
        ).json()
        assert unchanged["ground_truth"]["uncertainty"] == "moderate"


class TestNarrativeAndExpectedQuery:
    """Unit 38 (MEADOWOPS-DOM-026): the Builder-only narrative + suggested
    query, so the Builder can check the work and help a stuck Analyst. Both
    live in ground_truth, which no Analyst or persona path ever reads."""

    _SELECT = "SELECT 1 AS one, 'x' AS label"

    def _create_draft(self, client: TestClient, admin_auth: dict[str, str], flag_id: str) -> dict:
        response = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(flag_id), headers=admin_auth
        )
        assert response.status_code == 201
        return response.json()

    def _patch(self, client: TestClient, admin_auth: dict[str, str], scenario_id: str, body: dict):
        return client.patch(
            f"/api/v1/admin/scenarios/{scenario_id}/ground-truth", json=body, headers=admin_auth
        )

    def test_the_builder_can_edit_the_narrative_and_expected_query(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = self._create_draft(client, admin_auth, open_flag_id)

        response = self._patch(
            client,
            admin_auth,
            created["id"],
            {"narrative": "Stock is low at WH-EAST.", "expected_query": f"{self._SELECT};"},
        )

        assert response.status_code == 200
        truth = response.json()["ground_truth"]
        assert truth["narrative"] == "Stock is low at WH-EAST."
        assert truth["expected_query"] == self._SELECT  # trailing ; normalised away

    @pytest.mark.parametrize(
        "bad_query",
        ["DELETE FROM sandbox.product", "SELECT 1; SELECT 2", "DROP TABLE sandbox.product"],
    )
    def test_a_non_select_expected_query_is_rejected_with_422(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str, bad_query: str
    ) -> None:
        created = self._create_draft(client, admin_auth, open_flag_id)

        response = self._patch(client, admin_auth, created["id"], {"expected_query": bad_query})

        assert response.status_code == 422
        stored = client.get(f"/api/v1/admin/scenarios/{created['id']}", headers=admin_auth).json()
        assert "expected_query" not in stored["ground_truth"]

    def test_an_empty_expected_query_clears_it(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = self._create_draft(client, admin_auth, open_flag_id)
        self._patch(client, admin_auth, created["id"], {"expected_query": self._SELECT})

        response = self._patch(client, admin_auth, created["id"], {"expected_query": ""})

        assert response.status_code == 200
        assert response.json()["ground_truth"]["expected_query"] == ""

    def test_running_the_expected_query_returns_its_rows(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = self._create_draft(client, admin_auth, open_flag_id)
        self._patch(client, admin_auth, created["id"], {"expected_query": self._SELECT})

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/expected-query/run", headers=admin_auth
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["columns"] == ["one", "label"]
        assert body["rows"] == [{"one": 1, "label": "x"}]

    def test_a_failing_expected_query_reports_the_error_instead_of_a_500(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = self._create_draft(client, admin_auth, open_flag_id)
        self._patch(
            client,
            admin_auth,
            created["id"],
            {"expected_query": "SELECT * FROM sandbox.no_such_table_zz"},
        )

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/expected-query/run", headers=admin_auth
        )

        assert response.status_code == 200
        assert response.json()["status"] == "error"
        assert response.json()["error_message"]

    def test_running_without_an_expected_query_returns_422(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = self._create_draft(client, admin_auth, open_flag_id)

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/expected-query/run", headers=admin_auth
        )

        assert response.status_code == 422

    def test_running_an_unknown_scenario_returns_404(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.post(
            f"/api/v1/admin/scenarios/{uuid.uuid4()}/expected-query/run", headers=admin_auth
        )
        assert response.status_code == 404

    def test_a_stored_write_query_is_refused_at_run_time_too(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        db_session: Session,
        open_flag_id: str,
    ) -> None:
        # Defence in depth: ground_truth is a free-form JSON column, so a
        # row written around the API (a migration, a script) must still
        # never be executed as a write.
        created = self._create_draft(client, admin_auth, open_flag_id)
        scenario = db_session.get(Scenario, uuid.UUID(created["id"]))
        scenario.ground_truth = {**scenario.ground_truth, "expected_query": "DELETE FROM sandbox.product"}
        db_session.commit()

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/expected-query/run", headers=admin_auth
        )

        assert response.status_code == 422

    def test_a_query_that_hides_a_second_statement_from_the_classifier_cannot_write(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        db_session: Session,
        open_flag_id: str,
    ) -> None:
        # Unit 38 security review: sqlparse and Postgres disagree about
        # backslash-escaped quotes, so this passes the text-level checks as
        # one SELECT while the server sees a second, CREATE TABLE, statement.
        bypass = r"SELECT '\'; CREATE TABLE sandbox.zz_scenario_probe (x int); --'"
        created = self._create_draft(client, admin_auth, open_flag_id)
        self._patch(client, admin_auth, created["id"], {"expected_query": bypass})
        try:
            response = client.post(
                f"/api/v1/admin/scenarios/{created['id']}/expected-query/run", headers=admin_auth
            )

            assert response.status_code == 200
            assert response.json()["status"] == "error"
            exists = db_session.scalar(text("select to_regclass('sandbox.zz_scenario_probe')"))
            assert exists is None
        finally:
            db_session.rollback()
            db_session.execute(text("drop table if exists sandbox.zz_scenario_probe"))
            db_session.commit()

    def test_running_the_expected_query_leaves_no_query_log_entry(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        db_session: Session,
        open_flag_id: str,
    ) -> None:
        # The Builder's check is not Analyst work: it must not appear in the
        # query history the Analyst's own activity is read from.
        created = self._create_draft(client, admin_auth, open_flag_id)
        self._patch(client, admin_auth, created["id"], {"expected_query": self._SELECT})
        before = db_session.scalar(select(func.count()).select_from(QueryLog))

        client.post(
            f"/api/v1/admin/scenarios/{created['id']}/expected-query/run", headers=admin_auth
        )

        db_session.expire_all()
        assert db_session.scalar(select(func.count()).select_from(QueryLog)) == before

    def test_a_regenerated_scenario_gets_the_narrative_and_query_from_claude(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = self._create_draft(client, admin_auth, open_flag_id)
        client.app.state.claude_client = MockClaudeClient(
            script=[
                ClaudeResponse(
                    content=json.dumps(
                        _narrative_payload(narrative="What happened.", expected_query=self._SELECT)
                    )
                )
            ]
        )

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/regenerate", headers=admin_auth
        )

        assert response.status_code == 200
        truth = response.json()["ground_truth"]
        assert truth["narrative"] == "What happened."
        assert truth["expected_query"] == self._SELECT


class TestActivateScenario:
    def test_activate_before_approve_returns_409(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=admin_auth
        ).json()

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/activate", headers=admin_auth
        )

        assert response.status_code == 409

    def test_full_lifecycle_reaches_active_with_no_delivery_side_effects(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=admin_auth
        ).json()
        client.patch(
            f"/api/v1/admin/scenarios/{created['id']}/ground-truth",
            json=_complete_ground_truth_payload(),
            headers=admin_auth,
        )
        client.post(f"/api/v1/admin/scenarios/{created['id']}/approve", headers=admin_auth)

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/activate", headers=admin_auth
        )

        assert response.status_code == 200
        assert response.json()["status"] == "active"
        assert response.json()["activated_at"] is not None

    def test_activating_a_second_scenario_while_one_is_already_active_returns_409(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        open_flag_id: str,
        second_flag_id: str,
    ) -> None:
        """PRD 9.2 catalog row 19: only one scenario active at a time."""

        def _create_and_approve(flag_id: str) -> str:
            created = client.post(
                "/api/v1/admin/scenarios", json=_create_payload(flag_id), headers=admin_auth
            ).json()
            client.patch(
                f"/api/v1/admin/scenarios/{created['id']}/ground-truth",
                json=_complete_ground_truth_payload(),
                headers=admin_auth,
            )
            client.post(f"/api/v1/admin/scenarios/{created['id']}/approve", headers=admin_auth)
            return created["id"]

        first_id = _create_and_approve(open_flag_id)
        second_id = _create_and_approve(second_flag_id)

        first_response = client.post(
            f"/api/v1/admin/scenarios/{first_id}/activate", headers=admin_auth
        )
        assert first_response.status_code == 200

        second_response = client.post(
            f"/api/v1/admin/scenarios/{second_id}/activate", headers=admin_auth
        )
        assert second_response.status_code == 409
        unchanged = client.get(
            f"/api/v1/admin/scenarios/{second_id}", headers=admin_auth
        ).json()
        assert unchanged["status"] == "approved"


class TestCancelScenario:
    def test_cancel_from_draft(
        self, client: TestClient, admin_auth: dict[str, str], open_flag_id: str
    ) -> None:
        created = client.post(
            "/api/v1/admin/scenarios", json=_create_payload(open_flag_id), headers=admin_auth
        ).json()

        response = client.post(
            f"/api/v1/admin/scenarios/{created['id']}/cancel", headers=admin_auth
        )

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
