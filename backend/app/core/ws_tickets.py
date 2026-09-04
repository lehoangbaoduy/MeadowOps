"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13): short-lived, single-use
WebSocket connection tickets — see tests/core/test_ws_tickets.py's module
docstring for why this exists at all (the browser WebSocket API can't set
an Authorization header, and the session lives in an httpOnly cookie
neither frontend's JS can read).

Mirrors app.core.rate_limit.LoginRateLimiter's shape exactly: a single
in-process instance per app.state (constructed in create_app, never a
module-level global — same reasoning as that module and
app.core.internal_client), an injectable clock for deterministic tests, a
threading.Lock around the store since FastAPI dispatches sync callers from
its anyio threadpool (single-worker does not mean single-threaded), and a
probabilistic sweep-on-mint to bound memory for tickets that are minted but
never redeemed.

`session_exp` (the *session JWT's* own `exp` claim, a Unix timestamp) rides
along on the ticket and is carried into the live WebSocket connection by
the caller (app.api.chat) — pre-implementation security review of this
unit, MEDIUM: the 20s ticket TTL alone only protects the handshake; without
this, an already-accepted WS connection would be the first credential in
this project able to outlive its own session's verification with no
re-check (app.core.security's own docstring conditions the whole
no-server-side-revocation posture on `exp` staying short specifically
because every other credential path re-verifies naturally on its next use).
"""

from __future__ import annotations

import random
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

_SWEEP_PROBABILITY = 0.01


@dataclass(frozen=True)
class WsTicketClaims:
    user_id: str
    role: str
    session_exp: float


@dataclass(frozen=True)
class _Entry:
    claims: WsTicketClaims
    expires_at: float


class WsTicketStore:
    def __init__(
        self,
        *,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._tickets: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def mint(self, *, user_id: str, role: str, session_exp: float) -> str:
        ticket = secrets.token_urlsafe(32)
        now = self._clock()
        entry = _Entry(
            claims=WsTicketClaims(user_id=user_id, role=role, session_exp=session_exp),
            expires_at=now + self._ttl_seconds,
        )
        with self._lock:
            self._tickets[ticket] = entry
            self._sweep_stale(now)
        return ticket

    def redeem(self, ticket: str) -> WsTicketClaims | None:
        """Single-use: a ticket is popped whether or not it turns out to be
        expired, so a redeem attempt on an expired-but-still-present ticket
        can never succeed on a later retry either."""
        now = self._clock()
        with self._lock:
            entry = self._tickets.pop(ticket, None)
        if entry is None:
            return None
        if entry.expires_at < now:
            return None
        return entry.claims

    def outstanding_count(self) -> int:
        with self._lock:
            return len(self._tickets)

    def _sweep_stale(self, now: float) -> None:
        """Caller already holds `self._lock`. Probabilistic so this stays a
        rare O(n) sweep rather than running on every mint — same tradeoff
        LoginRateLimiter._sweep_stale already makes."""
        if random.random() >= _SWEEP_PROBABILITY:
            return
        stale = [t for t, entry in self._tickets.items() if entry.expires_at < now]
        for t in stale:
            del self._tickets[t]
