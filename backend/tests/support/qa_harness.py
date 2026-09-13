"""Unit 29 (MEADOWOPS-QA-001, harness-os spec MEADOWOPS-API-029, PRD
6.6/9.1): shared driver for the QA test-analyst harness. Chains the real
scenario/chat/evaluation/ledger REST routes to run one pass of PRD 6.6's
interaction loop end to end, the same way a Builder-operated stand-in
Analyst would.

This is the harness's own compositional driver, not a per-test-file
fixture — tests/support/auth.py's docstring documents this project's
established convention of duplicating *fixtures* (client/db_session/
admin_auth) across test files rather than sharing them; a multi-step REST
driver used by every scenario-type run is the opposite case DRY exists
for, so it lives here once, alongside auth.py, and both
tests/e2e/test_qa_scenario_types.py and tests/e2e/test_qa_callback_scenario.py
import it.

Steps 11-12 of the loop (human review, learning record) are out of scope:
PRD 6.6 calls both "validated structurally... without requiring a real
reviewer or real portfolio content", and tests/api/test_evaluation_api.py's
TestHumanReviewRoutes already exercises the human-review route directly.
This driver stops at step 10 (a decision entering the Ledger).

Ground truth here is hand-authored via PATCH .../ground-truth, not
Claude-regenerated via POST .../regenerate — the harness scripts
MockClaudeClient for chat (pushback/sufficiency) and evaluation, the two
points PRD 6.6 actually requires an AI in the loop; scenario narrative
generation already has its own dedicated test coverage
(tests/api/test_admin_scenarios.py), so re-exercising it here would test
the same code path a second time rather than a new part of the loop.
"""

import json

from fastapi.testclient import TestClient

from app.domain.claude_client import ClaudeResponse, MockClaudeClient


def ground_truth_updates_for(narrative: str) -> dict:
    """Code review of this unit, LOW: this was byte-identical between
    test_qa_scenario_types.py and test_qa_callback_scenario.py - a plain
    data builder with no per-file variation, unlike the fixtures
    tests/support/auth.py's own convention sanctions duplicating, so it
    belongs here alongside the rest of the driver instead."""
    return {
        "supporting_signals": [f"{narrative} - supporting signal A"],
        "distractors": [f"{narrative} - distractor A"],
        "expected_considerations": [f"{narrative} - what a solid analyst checks first"],
        "acceptable_conclusions": [f"{narrative} - an acceptable conclusion"],
        "unacceptable_conclusions": [f"{narrative} - jumping straight to blame"],
        "uncertainty": "moderate confidence pending one more data point",
    }


def create_and_activate_scenario(
    client: TestClient,
    admin_auth: dict[str, str],
    *,
    exception_flag_id: str,
    scenario_type: str,
    competency_cluster: str,
    difficulty_tier: str,
    title: str,
    ground_truth_updates: dict,
) -> str:
    """PRD 6.6 step 1 setup: create -> hand-author the narrative fields ->
    approve -> activate, via the real routes. Returns the new scenario's id.

    Code review of this unit, MEDIUM: asserts scenario_type/competency_cluster
    round-trip on both the create and activate responses, not just the 201/200
    status codes - without this, a route that silently ignored the requested
    scenario_type would still pass every one of tests/e2e/test_qa_scenario_
    types.py's six tests, undercutting the file's own "one test per PRD 6.2
    scenario type" claim."""
    response = client.post(
        "/api/v1/admin/scenarios",
        json={
            "exception_flag_id": exception_flag_id,
            "scenario_type": scenario_type,
            "competency_cluster": competency_cluster,
            "difficulty_tier": difficulty_tier,
            "title": title,
        },
        headers=admin_auth,
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["scenario_type"] == scenario_type
    assert created["competency_cluster"] == competency_cluster
    scenario_id = created["id"]

    response = client.patch(
        f"/api/v1/admin/scenarios/{scenario_id}/ground-truth",
        json=ground_truth_updates,
        headers=admin_auth,
    )
    assert response.status_code == 200, response.text

    response = client.post(
        f"/api/v1/admin/scenarios/{scenario_id}/approve", headers=admin_auth
    )
    assert response.status_code == 200, response.text

    response = client.post(
        f"/api/v1/admin/scenarios/{scenario_id}/activate", headers=admin_auth
    )
    assert response.status_code == 200, response.text
    activated = response.json()
    assert activated["status"] == "active"
    assert activated["scenario_type"] == scenario_type
    assert activated["competency_cluster"] == competency_cluster
    return scenario_id


def open_persona_thread(
    client: TestClient, admin_auth: dict[str, str], *, scenario_id: str, persona: str
) -> str:
    response = client.post(
        "/api/v1/chat/threads",
        json={"scenario_id": scenario_id, "persona": persona},
        headers=admin_auth,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def post_message(
    client: TestClient, thread_id: str, auth: dict[str, str], body: str
) -> dict:
    response = client.post(
        f"/api/v1/chat/threads/{thread_id}/messages", json={"body": body}, headers=auth
    )
    assert response.status_code == 201, response.text
    return response.json()


def run_pushback_round(
    client: TestClient,
    thread_id: str,
    *,
    admin_auth: dict[str, str],
    analyst_auth: dict[str, str],
    opening_message: str,
    initial_response: str,
    pushback_message: str,
    revision_message: str,
) -> None:
    """PRD 6.6 steps 2, 4, 5, 6: opening request, initial response,
    stakeholder pushback, revision - one full multi-round pass."""
    post_message(client, thread_id, admin_auth, opening_message)
    post_message(client, thread_id, analyst_auth, initial_response)
    post_message(client, thread_id, admin_auth, pushback_message)
    post_message(client, thread_id, analyst_auth, revision_message)


def complete_thread(
    client: TestClient, thread_id: str, admin_auth: dict[str, str], evaluation_payload: dict
) -> dict:
    """PRD 6.6 steps 8-9: mark Completed and generate the draft evaluation
    in one atomic call. Scripts MockClaudeClient immediately before the
    call, same convention as tests/api/test_evaluation_api.py's own
    _complete_thread."""
    client.app.state.claude_client = MockClaudeClient(
        script=[ClaudeResponse(content=json.dumps(evaluation_payload))]
    )
    response = client.post(f"/api/v1/chat/threads/{thread_id}/complete", headers=admin_auth)
    assert response.status_code == 200, response.text
    return response.json()


def propose_and_accept_decision(
    client: TestClient,
    admin_auth: dict[str, str],
    *,
    entity_type: str,
    entity_id: str,
    scenario_id: str,
    title: str,
    summary: str,
) -> str:
    """PRD 6.6 step 10: a decision entering the Ledger, immediately
    accepted so a callback run can advance it further. Returns the new
    decision's id."""
    response = client.post(
        "/api/v1/ledger/decisions",
        json={
            "entity_type": entity_type,
            "entity_id": entity_id,
            "title": title,
            "summary": summary,
            "scenario_id": scenario_id,
        },
        headers=admin_auth,
    )
    assert response.status_code == 201, response.text
    decision_id = response.json()["id"]

    response = client.post(
        f"/api/v1/ledger/decisions/{decision_id}/accept", json={}, headers=admin_auth
    )
    assert response.status_code == 200, response.text
    return decision_id


def advance_decision_to_outcome_observed(
    client: TestClient, admin_auth: dict[str, str], decision_id: str, *, outcome: str
) -> dict:
    """accepted -> implemented -> outcome_observed, the path
    app.services.ledger.find_callback_candidates requires
    (_CALLBACK_ELIGIBLE_STATUSES) before a later scenario can reference
    this decision as a callback candidate."""
    response = client.post(
        f"/api/v1/ledger/decisions/{decision_id}/implement", headers=admin_auth
    )
    assert response.status_code == 200, response.text

    response = client.post(
        f"/api/v1/ledger/decisions/{decision_id}/outcome",
        json={"outcome": outcome},
        headers=admin_auth,
    )
    assert response.status_code == 200, response.text
    return response.json()
