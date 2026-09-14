"""Unit 34 E2E fixture seeder: creates one fully-completed persona thread
(scenario -> approved -> active -> thread -> one Builder + one Analyst
message -> evaluation) for the evaluation/human-review/portfolio-export
and reflection-form specs to exercise against.

Two things this project's own bootstrap seeds/scheduler don't provide and
no API route can create directly, so this script fills the gap the same
way tests/support/qa_harness.py's `complete_thread` does (script the
result, don't depend on a live Claude call):

1. An open ExceptionFlag — scenario creation requires one
   (app.schemas.scenario.ScenarioCreate.exception_flag_id), and the
   scheduler that would normally generate one is disabled by default
   locally (Settings.scheduler_enabled=False) and, even enabled, has no
   guaranteed timing. Inserted directly via the ORM.
2. A real Evaluation row — POST .../complete now works against a real,
   live Claude API (Phase 4 blocker B3, closed 2026-09-14 -
   app.domain.claude_client_anthropic.AnthropicClaudeClient), but a
   committed E2E spec run in CI shouldn't depend on a live, billed API
   call for its own determinism and cost - so this script still inserts
   the Evaluation row directly via the ORM, replicating exactly what
   app.services.evaluation.complete_thread_and_generate_evaluation itself
   writes (Evaluation row + ChatThread.status -> COMPLETED) minus the
   actual Claude call.

Everything else (scenario/thread/messages) goes through the real HTTP API
against the already-running backend, same as a Builder/Analyst session
would produce.

Prints one line of JSON to stdout: {"scenario_id", "thread_id",
"evaluation_id"}. Every other diagnostic goes to stderr, so a caller can
shell out and safely `json.loads`/`JSON.parse` stdout alone.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.chat import ChatThread
from app.db.dimensions import Product, Warehouse
from app.db.enums import ChatThreadStatus
from app.db.evaluation import Evaluation
from app.db.exception_flags import ExceptionFlag
from app.db.exception_rules import ExceptionRuleThreshold

BASE_URL = "http://localhost:8000"


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def login(email: str, password: str) -> str:
    response = httpx.post(f"{BASE_URL}/api/v1/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser()
    # Defaults to a persona no other spec's fixture uses, so a spec that
    # selects its own thread by persona label (e.g. the reflection-form
    # spec, which has no other stable per-thread selector available in
    # thread-list.tsx's markup) doesn't collide with one seeded by another
    # spec/run sharing the same long-lived local dev database.
    parser.add_argument("--persona", default="operations_director")
    args = parser.parse_args()

    settings = Settings()
    engine = create_engine(settings.database_url)

    with Session(engine) as session:
        threshold = session.execute(select(ExceptionRuleThreshold)).scalars().first()
        product = session.execute(select(Product)).scalars().first()
        warehouse = session.execute(select(Warehouse)).scalars().first()
        assert threshold and product and warehouse, "baseline master data must be seeded first"

        flag = ExceptionFlag(
            category=threshold.id,
            product_id=product.id,
            warehouse_id=warehouse.id,
            simulation_date=date.today(),
            first_detected_simulation_date=date.today(),
            measured_value="2.50",
            threshold_value="5.00",
        )
        session.add(flag)
        session.commit()
        flag_id = str(flag.id)
        log(f"seeded ExceptionFlag {flag_id}")

    admin_token = login(settings.initial_admin_email, settings.initial_admin_password)
    analyst_token = login(settings.initial_analyst_email, settings.initial_analyst_password)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    analyst_headers = {"Authorization": f"Bearer {analyst_token}"}

    created = httpx.post(
        f"{BASE_URL}/api/v1/admin/scenarios",
        headers=admin_headers,
        json={
            "exception_flag_id": flag_id,
            "scenario_type": "root_cause_investigation",
            "competency_cluster": "analysis_diagnosis",
            "difficulty_tier": "standard",
            "title": f"E2E fixture {uuid.uuid4().hex[:8]}",
        },
    )
    created.raise_for_status()
    scenario_id = created.json()["id"]
    log(f"created scenario {scenario_id}")

    # Resolved now, not left open: live.exception_flag's own
    # ux_exception_flag_open_entity partial unique index (migration 0012)
    # allows only one *open* row per (category, product, warehouse, PO,
    # shipment) combination, and scenario creation
    # (app.services.scenario_service) never resolves the flag it was built
    # from — must happen only after creation succeeds, since creation
    # itself requires the flag to still be open.
    with Session(engine) as session:
        flag_row = session.get(ExceptionFlag, uuid.UUID(flag_id))
        assert flag_row is not None
        flag_row.resolved_at = datetime.now(timezone.utc)
        session.commit()

    gt = httpx.patch(
        f"{BASE_URL}/api/v1/admin/scenarios/{scenario_id}/ground-truth",
        headers=admin_headers,
        json={
            "supporting_signals": ["East fill rate has dropped"],
            "distractors": ["Warehouse claims shipments were on time"],
            "expected_considerations": ["Check supplier S-004 lead time"],
            "acceptable_conclusions": ["Raise safety stock and monitor"],
            "unacceptable_conclusions": ["Blame the warehouse without checking the PO"],
            "uncertainty": "moderate confidence pending one more data point",
        },
    )
    gt.raise_for_status()

    httpx.post(f"{BASE_URL}/api/v1/admin/scenarios/{scenario_id}/approve", headers=admin_headers).raise_for_status()
    httpx.post(f"{BASE_URL}/api/v1/admin/scenarios/{scenario_id}/activate", headers=admin_headers).raise_for_status()
    log("scenario approved + activated")

    thread = httpx.post(
        f"{BASE_URL}/api/v1/chat/threads",
        headers=admin_headers,
        json={"scenario_id": scenario_id, "persona": args.persona},
    )
    thread.raise_for_status()
    thread_id = thread.json()["id"]
    log(f"opened thread {thread_id}")

    httpx.post(
        f"{BASE_URL}/api/v1/chat/threads/{thread_id}/messages",
        headers=admin_headers,
        json={"body": "East's service is getting worse. What's happening and what should we do?"},
    ).raise_for_status()
    httpx.post(
        f"{BASE_URL}/api/v1/chat/threads/{thread_id}/messages",
        headers=analyst_headers,
        json={
            "body": "Fill rate at East has dropped and a SKU keeps stocking out. "
            "Checking supplier S-004's lead time next."
        },
    ).raise_for_status()
    log("posted Builder + Analyst messages")

    with Session(engine) as session:
        thread_row = session.get(ChatThread, uuid.UUID(thread_id))
        assert thread_row is not None
        evaluation = Evaluation(
            thread_id=uuid.UUID(thread_id),
            prompt_version="e2e-seed-v1",
            strengths="Correctly identified the East fill-rate drop and the stockout pattern.",
            gaps="Did not yet confirm whether reporting lag was contributing.",
            evidence="Fill rate trend, stockout frequency, Supplier S-004 lead-time drift.",
            senior_analyst_pushback="The warehouse claims shipments were on time — have you ruled that out?",
            final_verdict="Solid root-cause reasoning; recommend a safety-stock increase and a 4-week monitor.",
            suggested_next_skill_focus="Cross-checking a stakeholder claim against a second data source.",
            difficulty_recommendation="standard",
            raw_response=json.dumps({"seeded": "for E2E testing, not a real Claude response"}),
        )
        session.add(evaluation)
        thread_row.status = ChatThreadStatus.COMPLETED
        session.commit()
        evaluation_id = str(evaluation.id)
    log(f"seeded Evaluation {evaluation_id}, thread marked completed")

    print(json.dumps({"scenario_id": scenario_id, "thread_id": thread_id, "evaluation_id": evaluation_id}))


if __name__ == "__main__":
    main()
