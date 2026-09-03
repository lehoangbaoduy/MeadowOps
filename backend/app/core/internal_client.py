"""Unit 20 (MEADOWOPS-API-004, DD-2): the internal HTTP client Subsystem 2's
own future service layer (Phase 3 - the AI-driven scenario/evaluation
engine) must use to read Subsystem 1's data - never a direct
app.db.session/live-schema ORM import (PRD 376, S1-FR-6). Built once, in
app.main's lifespan, against the *same running* FastAPI app instance via
httpx.ASGITransport - real HTTP request/response semantics (routing,
Pydantic validation/serialization, every dependency including auth) execute
exactly as they would for a real network caller, but in-process with zero
network hop and zero extra hosting cost (PRD 8.3). A second `create_app()`
call would spin up a second DB engine/lifespan for no reason - this always
wraps the one already running.

Authenticates as Settings.internal_service_token, the read-only "service"
identity app.core.auth.require_authenticated grants it - never accepted by
require_admin or by the Query Playground's own routes
(app.core.auth.reject_service_role).
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI


def build_subsystem2_client(app: FastAPI, *, service_token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://internal",
        headers={"Authorization": f"Bearer {service_token}"},
    )
