"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13): the WebSocket ticket store — a
short-lived, single-use credential minted via an authenticated REST call
and burned on WS connect, since the browser WebSocket API can't carry an
Authorization header and the session lives in an httpOnly cookie neither
frontend's JS can read (pre-implementation security review of this unit —
see the design doc referenced from the record_decision log).

Mirrors app.core.rate_limit.LoginRateLimiter's own shape (a single
in-process instance per app.state, an injectable clock, a threading.Lock
around the store) for the same reasons that module's docstring gives:
single-worker scale, but not single-threaded — FastAPI dispatches sync
callers from its anyio threadpool.
"""

import threading

import pytest

from app.core.ws_tickets import WsTicketStore


def _clock_factory(start: float = 1000.0):
    state = {"now": start}

    def clock() -> float:
        return state["now"]

    def advance(seconds: float) -> None:
        state["now"] += seconds

    return clock, advance


def test_mint_then_redeem_returns_the_minted_identity() -> None:
    clock, _advance = _clock_factory()
    store = WsTicketStore(ttl_seconds=20, clock=clock)
    ticket = store.mint(user_id="u1", role="admin", session_exp=2000.0)
    claims = store.redeem(ticket)
    assert claims is not None
    assert claims.user_id == "u1"
    assert claims.role == "admin"
    assert claims.session_exp == 2000.0


def test_redeem_is_single_use() -> None:
    clock, _advance = _clock_factory()
    store = WsTicketStore(ttl_seconds=20, clock=clock)
    ticket = store.mint(user_id="u1", role="admin", session_exp=2000.0)
    assert store.redeem(ticket) is not None
    assert store.redeem(ticket) is None


def test_redeem_rejects_an_unknown_ticket() -> None:
    store = WsTicketStore(ttl_seconds=20)
    assert store.redeem("never-minted") is None


def test_redeem_rejects_an_expired_ticket() -> None:
    clock, advance = _clock_factory()
    store = WsTicketStore(ttl_seconds=20, clock=clock)
    ticket = store.mint(user_id="u1", role="admin", session_exp=2000.0)
    advance(21)
    assert store.redeem(ticket) is None


def test_redeem_accepts_a_ticket_right_at_the_ttl_boundary() -> None:
    clock, advance = _clock_factory()
    store = WsTicketStore(ttl_seconds=20, clock=clock)
    ticket = store.mint(user_id="u1", role="admin", session_exp=2000.0)
    advance(19.999)
    assert store.redeem(ticket) is not None


def test_two_mints_produce_different_tickets() -> None:
    store = WsTicketStore(ttl_seconds=20)
    a = store.mint(user_id="u1", role="admin", session_exp=2000.0)
    b = store.mint(user_id="u1", role="admin", session_exp=2000.0)
    assert a != b


def test_concurrent_mints_do_not_corrupt_the_store() -> None:
    """Mirrors LoginRateLimiter's own concurrency-safety proof — a burst of
    parallel mints from FastAPI's anyio threadpool must not lose tickets to
    a lost dict-write race."""
    store = WsTicketStore(ttl_seconds=20)
    tickets: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        ticket = store.mint(user_id="u1", role="admin", session_exp=2000.0)
        with lock:
            tickets.append(ticket)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(tickets) == len(set(tickets)) == 50
    for ticket in tickets:
        assert store.redeem(ticket) is not None


def test_stale_tickets_are_eventually_swept(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bounds memory for mints that are never connected/redeemed (LOW
    finding from this unit's pre-implementation security review, mirroring
    LoginRateLimiter._sweep_stale's own probabilistic-sweep-on-mint
    approach)."""
    monkeypatch.setattr("app.core.ws_tickets._SWEEP_PROBABILITY", 1.0)
    clock, advance = _clock_factory()
    store = WsTicketStore(ttl_seconds=20, clock=clock)
    store.mint(user_id="stale-one", role="admin", session_exp=2000.0)
    advance(21)
    # This mint's own sweep call (probability patched to 1.0) should prune
    # the now-stale entry above before adding itself.
    store.mint(user_id="fresh-one", role="analyst", session_exp=2000.0)
    assert store.outstanding_count() == 1
