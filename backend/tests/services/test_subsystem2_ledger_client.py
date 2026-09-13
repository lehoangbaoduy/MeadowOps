"""Unit 24 (MEADOWOPS-DOM-018): app.services.subsystem2.ledger_client - the
first real consumer of app.core.internal_client's Subsystem 2 boundary
(Unit 20, DD-2). Unit-level only: exercises fetch_callback_candidates
against a fake httpx.AsyncClient standing in for
request.app.state.subsystem2_client, proving its own request-shaping and
error-handling. The real ASGI round trip through the actual ledger route is
tests/integration/test_subsystem2_boundary.py's job (same split that
module's own docstring describes for app.core.internal_client itself).
"""

import httpx
import pytest

from app.services.subsystem2.ledger_client import (
    LedgerClientError,
    fetch_callback_candidates,
)


class _FakeAsyncClient:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.requested_url: str | None = None

    async def get(self, url: str) -> httpx.Response:
        self.requested_url = url
        return self._response


@pytest.mark.asyncio
async def test_requests_the_expected_url() -> None:
    fake = _FakeAsyncClient(httpx.Response(200, json=[]))
    await fetch_callback_candidates(fake, entity_type="supplier", entity_id="SUP-001")
    assert fake.requested_url == "/api/v1/ledger/entities/supplier/SUP-001/callback-candidates"


@pytest.mark.asyncio
async def test_returns_the_parsed_json_body_on_success() -> None:
    payload = [{"id": "11111111-1111-1111-1111-111111111111", "title": "example"}]
    fake = _FakeAsyncClient(httpx.Response(200, json=payload))
    result = await fetch_callback_candidates(fake, entity_type="supplier", entity_id="SUP-001")
    assert result == payload


@pytest.mark.asyncio
async def test_raises_ledger_client_error_on_a_non_200_response() -> None:
    fake = _FakeAsyncClient(httpx.Response(403, text="forbidden"))
    with pytest.raises(LedgerClientError):
        await fetch_callback_candidates(fake, entity_type="supplier", entity_id="SUP-001")


@pytest.mark.asyncio
async def test_percent_encodes_an_entity_id_containing_a_slash() -> None:
    # Code review, MEDIUM: entity_id is a plain, unconstrained string
    # (min_length=1 only) - a raw f-string interpolation would let "/"
    # split across the route's single {entity_id} path segment.
    fake = _FakeAsyncClient(httpx.Response(200, json=[]))
    await fetch_callback_candidates(fake, entity_type="supplier", entity_id="SUP/2024")
    assert fake.requested_url == "/api/v1/ledger/entities/supplier/SUP%2F2024/callback-candidates"
