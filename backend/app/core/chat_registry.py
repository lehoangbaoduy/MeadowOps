"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13/§7): in-memory registry of live
WebSocket connections, keyed by role — a message send broadcasts to every
currently-connected socket regardless of role, since both the Builder
(Subsystem 2) and the Analyst (Subsystem 1) need live delivery of any
thread's new message (PRD 6.13's chat is not scoped per-connection to "only
the other side").

Single-process, in-memory only, no Redis/pub-sub — deliberate, matching PRD
8.2's one-host/one-environment deployment model and 8.3's cost target, same
already-accepted tradeoff as build_scheduler's own max_instances=1 comment.
A future multi-worker deployment would need a real pub/sub layer; not
attempted here.

No explicit lock: register/unregister/broadcast never `await` in the
middle of a dict/set mutation, and Starlette runs WebSocket route
coroutines on the single asyncio event loop (unlike sync `def` HTTP routes,
which anyio dispatches to a threadpool — see app.core.rate_limit's own
docstring for that distinction) — cooperative scheduling means a mutation
with no `await` inside it is already atomic with respect to every other
coroutine on this registry.
"""

from __future__ import annotations

from fastapi import WebSocket


class ChatConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    def register(self, role: str, websocket: WebSocket) -> None:
        self._connections.setdefault(role, set()).add(websocket)

    def unregister(self, role: str, websocket: WebSocket) -> None:
        self._connections.get(role, set()).discard(websocket)

    async def broadcast(self, payload: dict) -> None:
        """Best-effort: a socket that fails mid-send (a client that
        vanished between accept and this call, before its own disconnect
        was noticed) is dropped from the registry rather than aborting the
        whole broadcast for every other live connection."""
        for role, sockets in list(self._connections.items()):
            for websocket in list(sockets):
                try:
                    await websocket.send_json(payload)
                except Exception:  # noqa: BLE001 - best-effort push, see docstring
                    self._connections.get(role, set()).discard(websocket)
