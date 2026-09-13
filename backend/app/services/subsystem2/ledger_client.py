"""Unit 24 (MEADOWOPS-DOM-018, PRD 4.4 callback mechanism): the first real
consumer of app.core.internal_client's Subsystem 2 boundary (Unit 20,
DD-2). `app.db.ledger` is in app.domain.subsystem_boundary.
FORBIDDEN_MODULES, so this module reaches Subsystem 1's ledger data only
through an HTTP round trip on the shared `httpx.AsyncClient`
(request.app.state.subsystem2_client in a real request, a bare
httpx.AsyncClient in tests) — never a direct ORM import. Proven against the
real running app in tests/integration/test_subsystem2_boundary.py; this
module's own tests only exercise its request-shaping/error-handling against
a fake client.

Deliberately not wired into app.domain.scenario_generation's
GENERATION_TEMPLATE yet (PRD 6.11 ER-6: that template is frozen v1, never
silently rewritten) — this unit only builds the lookup capability PRD 9.2's
callback-scenario edge case needs. Injecting the result into a real
scenario-generation prompt has no way to be end-to-end verified until
U25's draft-evaluation pipeline exists to produce real decisions worth
calling back to; that wiring is a later unit's job, not a drive-by here.
"""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote

import httpx


class LedgerClientError(RuntimeError):
    """Raised when the ledger's callback-candidates route returns anything
    other than 200 — the caller decides whether that's fatal or just means
    "generate without a callback this time"."""


class _AsyncHttpClient(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


async def fetch_callback_candidates(
    client: _AsyncHttpClient, *, entity_type: str, entity_id: str
) -> list[dict[str, Any]]:
    # Code review, MEDIUM: entity_id is a plain, client-supplied String on
    # DecisionEvent/master-data rows (no format constraint beyond
    # min_length=1) - raw f-string interpolation would let a value
    # containing "/" split across the route's single {entity_id} path
    # segment, 404ing instead of returning "no candidates" for a valid id.
    # quote(..., safe="") percent-encodes every reserved character
    # (entity_type is already a closed Literal enum on the API side, but
    # quoted too for defense-in-depth against this function ever being
    # called with a raw string from elsewhere).
    path = (
        f"/api/v1/ledger/entities/{quote(entity_type, safe='')}"
        f"/{quote(entity_id, safe='')}/callback-candidates"
    )
    response = await client.get(path)
    if response.status_code != 200:
        raise LedgerClientError(
            f"ledger callback lookup for {entity_type}/{entity_id} failed: "
            f"{response.status_code} {response.text}"
        )
    return response.json()
