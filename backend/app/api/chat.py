"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13, §7, DD-25): chat delivery
infrastructure's REST + WebSocket surface. No UI (U21), no AI sufficiency
check (U23), no thread work-state lifecycle (U23/U24) — this unit only
builds the persistent thread+message substrate and real-time delivery.

Every REST route is `reject_service_role`-gated except thread creation
(`require_admin` — DD-25: the Builder picks which thread to open) — the
internal-service credential (Subsystem 2's `Settings.internal_service_
token`, app.core.internal_client) has no legitimate reason to touch chat at
all, mirroring the Query Playground's own routes exactly (pre-
implementation security review of this unit).

`sender_user_id`/`sender_role` on every sent message are derived here, from
the caller's own verified identity, never from the request body — the
exact class of forgery bug Unit 20a's pre-implementation review caught
(client-side role trust), not repeated here.

`create_message_route` stays a plain sync `def`, matching every other
route in this project's sync-SQLAlchemy stack (app.api.admin_scenarios's
own docstring) — an earlier version made it `async def` so it could
`await` ChatConnectionRegistry.broadcast directly, but that ran the
synchronous DB write inline on the asyncio event loop instead of in
FastAPI's threadpool, stalling every other live WebSocket connection and
in-flight request for the duration of each message send (code review of
this unit). `BackgroundTasks` schedules the broadcast after the response
is returned instead — Starlette awaits an async background task on the
event loop at that point, which is exactly where an awaited coroutine
belongs, not inline in a sync route's threadpool-dispatched body.
"""

import asyncio
import time
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    WebSocket,
    status,
)
from psycopg import errors as pg_errors
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import reject_service_role, require_admin
from app.core.chat_registry import ChatConnectionRegistry
from app.core.security import InvalidSessionToken, decode_session_token
from app.core.ws_tickets import WsTicketStore
from app.db.chat import ChatThread
from app.db.enums import StakeholderPersona, UserRole
from app.db.session import get_session
from app.schemas.chat import (
    MessageCreate,
    MessageRead,
    ThreadCreate,
    ThreadRead,
    ThreadReadWithUnread,
    WsTicketRead,
)
from app.services.chat import (
    MessageBodyTooLongError,
    ThreadNotFoundError,
    get_or_create_thread,
    list_messages,
    list_threads_with_unread,
    mark_thread_read,
    send_message,
)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("/ws-ticket", response_model=WsTicketRead)
def mint_ws_ticket_route(
    request: Request,
    authorization: str | None = Header(default=None),
    identity: dict[str, str] = Depends(reject_service_role),
) -> WsTicketRead:
    settings = request.app.state.settings
    # reject_service_role already guarantees this token decoded as a real
    # signed session JWT (the internal-service credential short-circuits
    # require_authenticated before ever reaching decode_session_token, and
    # is rejected before this route body runs) — decoding it again here is
    # redundant verification work, not a new trust decision, purely to
    # recover the `exp` claim require_authenticated's identity dict doesn't
    # carry (app.core.ws_tickets' own docstring has the full reasoning).
    token = (authorization or "").removeprefix("Bearer ")
    try:
        claims = decode_session_token(token, secret=settings.session_secret_key)
    except InvalidSessionToken as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc
    store: WsTicketStore = request.app.state.chat_ws_tickets
    ticket = store.mint(
        user_id=identity["user_id"], role=identity["role"], session_exp=float(claims["exp"])
    )
    return WsTicketRead(ticket=ticket)


@router.post("/threads", response_model=ThreadRead, status_code=status.HTTP_201_CREATED)
def create_thread_route(
    payload: ThreadCreate,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> ChatThread:
    try:
        thread = get_or_create_thread(
            session,
            scenario_id=payload.scenario_id,
            persona=StakeholderPersona(payload.persona),
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if isinstance(exc.orig, pg_errors.ForeignKeyViolation):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="scenario not found"
            ) from exc
        # UniqueViolation: a concurrent create won the (scenario_id,
        # persona) race between this call's own select and insert — DD-25
        # makes this idempotent by contract, so re-fetch and return the
        # winner rather than surfacing a 409 for a request that was, in
        # spirit, satisfied.
        existing = session.scalar(
            select(ChatThread).where(
                ChatThread.scenario_id == payload.scenario_id,
                ChatThread.persona == StakeholderPersona(payload.persona),
            )
        )
        if existing is None:
            raise
        return existing
    session.refresh(thread)
    return thread


@router.get("/threads", response_model=list[ThreadReadWithUnread])
def list_threads_route(
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(reject_service_role),
) -> list[ThreadReadWithUnread]:
    try:
        # Same guard, same precedent as create_message_route below: a
        # validly-signed token's `sub` is always a real UUID today, guarded
        # anyway so a malformed/future claim shape 401s instead of an
        # unhandled ValueError -> 500.
        viewer_id = uuid.UUID(identity["user_id"])
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc
    return [
        ThreadReadWithUnread(
            id=item.thread.id,
            scenario_id=item.thread.scenario_id,
            persona=item.thread.persona,
            created_at=item.thread.created_at,
            unread_count=item.unread_count,
        )
        for item in list_threads_with_unread(session, user_id=viewer_id)
    ]


@router.post("/threads/{thread_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_thread_read_route(
    thread_id: uuid.UUID,
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(reject_service_role),
) -> None:
    try:
        viewer_id = uuid.UUID(identity["user_id"])
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc
    try:
        mark_thread_read(session, thread_id=thread_id, user_id=viewer_id)
        session.commit()
    except ThreadNotFoundError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/threads/{thread_id}/messages", response_model=list[MessageRead])
def list_messages_route(
    thread_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(reject_service_role),
):
    try:
        return list_messages(session, thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/threads/{thread_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
def create_message_route(
    thread_id: uuid.UUID,
    payload: MessageCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(reject_service_role),
):
    try:
        # Code review precedent (app.api.admin_scenarios.create_scenario_
        # route): a validly-signed token's `sub` is always a real UUID
        # today, guarded anyway so a malformed/future claim shape 401s
        # instead of an unhandled ValueError -> 500.
        sender_user_id = uuid.UUID(identity["user_id"])
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc
    try:
        message = send_message(
            session,
            thread_id=thread_id,
            sender_user_id=sender_user_id,
            sender_role=UserRole(identity["role"]),
            body=payload.body,
        )
        session.commit()
    except ThreadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MessageBodyTooLongError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    session.refresh(message)

    registry: ChatConnectionRegistry = request.app.state.chat_connections
    background_tasks.add_task(
        registry.broadcast,
        {
            "type": "chat.message",
            "thread_id": str(message.thread_id),
            "message_id": str(message.id),
            "sender_role": message.sender_role.value,
            "body": message.body,
            "sent_at": message.sent_at.isoformat(),
        },
    )
    return message


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    """Code review of this unit: the low-level `websocket.receive()` used
    here never raises `WebSocketDisconnect` (only the `receive_text`/
    `receive_bytes`/`receive_json` convenience wrappers do, per Starlette's
    own source) — disconnect shows up as a `{"type":
    "websocket.disconnect"}` message instead, which is what this actually
    checks. An earlier version also caught `WebSocketDisconnect` here,
    dead code that implied a safety net which didn't exist."""
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            return


@router.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    """Server->client push only (see module docstring) — no FastAPI
    `Depends` is possible on a websocket route at all, so auth is entirely
    the ticket redemption below: only a ticket minted by /ws-ticket (which
    is reject_service_role-gated) can ever reach `accept()`, closing off
    the internal-service credential transitively rather than needing its
    own check here."""
    ticket = websocket.query_params.get("ticket")
    store: WsTicketStore = websocket.app.state.chat_ws_tickets
    claims = store.redeem(ticket) if ticket else None
    if claims is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    registry: ChatConnectionRegistry = websocket.app.state.chat_connections
    registry.register(claims.role, websocket)

    remaining = max(claims.session_exp - time.time(), 0.0)
    receive_task = asyncio.create_task(_wait_for_disconnect(websocket))
    expiry_task = asyncio.create_task(asyncio.sleep(remaining))
    try:
        done, _pending = await asyncio.wait(
            {receive_task, expiry_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if expiry_task in done:
            # Session that authorized this connection has expired (MEDIUM
            # finding, pre-implementation security review of this unit) —
            # the 20s ticket TTL only protects the handshake, this is what
            # keeps the live connection itself from outliving the session.
            try:
                await websocket.close(code=4401)
            except Exception:  # noqa: BLE001 - best-effort; the client may
                # already be gone (send() surfaces that as an OSError-
                # derived WebSocketDisconnect per Starlette's own source,
                # code review of this unit) — nothing left to do about it,
                # unregister below still runs either way.
                pass
    finally:
        # Cancellation and awaiting both belong here, not in the try body
        # above (code review of this unit, MEDIUM): if the outer coroutine
        # itself gets cancelled while awaiting `asyncio.wait` (server
        # shutdown, an ASGI-level handler cancellation — a real trigger for
        # a long-lived WS route, not hypothetical), control jumps straight
        # to `finally` and skips any cleanup that isn't here. `gather(...,
        # return_exceptions=True)` also surfaces (by discarding safely,
        # rather than losing as an untracked "exception never retrieved"
        # GC warning) whatever `receive_task` raised if it wasn't the one
        # that already completed normally.
        receive_task.cancel()
        expiry_task.cancel()
        await asyncio.gather(receive_task, expiry_task, return_exceptions=True)
        registry.unregister(claims.role, websocket)
