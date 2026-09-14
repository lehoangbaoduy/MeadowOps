"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13, §7, DD-25): chat delivery
infrastructure's REST + WebSocket surface. No UI (U21) — this unit only
builds the persistent thread+message substrate and real-time delivery.

Unit 25 (MEADOWOPS-DOM-019) adds complete_thread_route below — marking a
thread Completed (PRD 6.6 step 8, flagged as unowned in DD-34, now closed)
synchronously triggers step 9's AI evaluation. admin_only, same reasoning
as suggest_pushback_route/sufficiency_check_route.

Unit 23 (MEADOWOPS-DOM-017) adds suggest_pushback_route/
sufficiency_check_route below — both require_admin (Builder-only), unlike
every route above them, since both read the scenario's ground truth (one
redacted, one in full) and the Analyst must never see it.

Code review of this unit: neither new route catches PromptRenderError —
unreachable today (both call sites always supply full required_context, and
test_prompt_templates.py's placeholder-consistency test pins that), so
adding a handler for it would be error handling for a case that can't
happen, not defense in depth for one that can.

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
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    status,
)
from psycopg import errors as pg_errors
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.auth import reject_service_role, require_admin, require_analyst
from app.core.chat_registry import ChatConnectionRegistry
from app.core.claude import get_claude_client
from app.core.security import InvalidSessionToken, decode_session_token
from app.core.storage import AttachmentStorage, get_attachment_storage
from app.core.ws_tickets import WsTicketStore
from app.db.chat import ChatThread, Notification
from app.db.enums import StakeholderPersona, UserRole
from app.db.session import get_session
from app.domain.attachment_validation import UnsupportedAttachmentTypeError
from app.domain.claude_client import ClaudeClient
from app.domain.evaluation import EvaluationGenerationFailedError
from app.domain.persona_chat import (
    Attitude,
    PersonaMessageGenerationFailedError,
    SufficiencyCheckFailedError,
)
from app.schemas.chat import (
    AttachmentRead,
    DraftUpdate,
    MessageCreate,
    MessageRead,
    NotificationRead,
    SufficiencyCheckResponse,
    SuggestPushbackRequest,
    SuggestPushbackResponse,
    ThreadCreate,
    ThreadRead,
    ThreadReadWithUnread,
    WsTicketRead,
)
from app.schemas.evaluation import EvaluationRead
from app.services.chat import (
    AttachmentAlreadyLinkedError,
    AttachmentOwnershipError,
    MessageBodyTooLongError,
    ThreadCompletedError,
    ThreadNotFoundError,
    get_or_create_thread,
    list_messages,
    list_threads_with_unread,
    mark_thread_read,
    save_draft,
    send_message,
)
from app.services.chat import AttachmentNotFoundError as SendAttachmentNotFoundError
from app.services.chat_attachments import (
    AttachmentTooLargeError,
    get_attachment_for_message,
    upload_attachment,
)
from app.services.evaluation import (
    LatestMessageNotFromAnalystError,
    ThreadAlreadyCompletedError,
    complete_thread_and_generate_evaluation,
)
from app.services.notifications import (
    NotificationNotFoundError,
    list_notifications_for_user,
    mark_notification_read,
)
from app.services.persona_chat import (
    MaxPushbackRoundsExceededError,
    NoAnalystMessageYetError,
    ScenarioCancelledError,
    check_thread_sufficiency,
    suggest_thread_pushback,
)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def _is_overdue(deadline_at: datetime | None) -> bool:
    """Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12): a moment-of-response
    computation, not a stored attribute - see ChatThread.deadline_at's own
    docstring (app.db.chat) for why "overdue" isn't a persisted status."""
    return deadline_at is not None and deadline_at <= datetime.now(timezone.utc)


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


def _thread_read(thread: ChatThread) -> ThreadRead:
    return ThreadRead(
        id=thread.id,
        scenario_id=thread.scenario_id,
        persona=thread.persona,
        status=thread.status,
        created_at=thread.created_at,
        deadline_at=thread.deadline_at,
        is_overdue=_is_overdue(thread.deadline_at),
    )


@router.post("/threads", response_model=ThreadRead, status_code=status.HTTP_201_CREATED)
def create_thread_route(
    payload: ThreadCreate,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> ThreadRead:
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
        return _thread_read(existing)
    session.refresh(thread)
    return _thread_read(thread)


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
            status=item.thread.status,
            created_at=item.thread.created_at,
            deadline_at=item.thread.deadline_at,
            is_overdue=_is_overdue(item.thread.deadline_at),
            unread_count=item.unread_count,
            draft_body=item.draft_body,
        )
        for item in list_threads_with_unread(session, user_id=viewer_id)
    ]


@router.put("/threads/{thread_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
def save_draft_route(
    thread_id: uuid.UUID,
    payload: DraftUpdate,
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(reject_service_role),
) -> None:
    """Unit 30b (MEADOWOPS-UI-004, PRD 6.1 'Drafting' bullet, catalog row
    31, B12 follow-on to U30)."""
    try:
        viewer_id = uuid.UUID(identity["user_id"])
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc
    try:
        save_draft(session, thread_id=thread_id, user_id=viewer_id, body=payload.body)
        session.commit()
    except ThreadNotFoundError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MessageBodyTooLongError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


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


@router.get("/notifications", response_model=list[NotificationRead])
def list_notifications_route(
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(reject_service_role),
) -> list[Notification]:
    try:
        viewer_id = uuid.UUID(identity["user_id"])
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc
    return list_notifications_for_user(session, user_id=viewer_id)


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_notification_read_route(
    notification_id: uuid.UUID,
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
        # Ownership-scoped lookup (id AND user_id together) - a wrong-owner
        # id 404s exactly like an unknown one (app.services.notifications.
        # mark_notification_read's own docstring).
        mark_notification_read(session, notification_id=notification_id, user_id=viewer_id)
        session.commit()
    except NotificationNotFoundError as exc:
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
            response_window_days=request.app.state.settings.chat_response_window_days,
            attachment_id=payload.attachment_id,
        )
        session.commit()
    except ThreadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MessageBodyTooLongError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ThreadCompletedError as exc:
        # Unit 25 (MEADOWOPS-DOM-019, security review, LOW).
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SendAttachmentNotFoundError as exc:
        # Unit 30c (MEADOWOPS-UI-005): the given attachment_id doesn't
        # exist at all.
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AttachmentOwnershipError as exc:
        # Unit 30c: exists, but wasn't uploaded by this sender on this
        # thread - 403, not 404, since the credential itself is fine (same
        # require_admin-vs-401 distinction elsewhere in this module).
        session.rollback()
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AttachmentAlreadyLinkedError as exc:
        # Unit 30c: already claimed by a different message - 409, matching
        # ThreadCompletedError's own conflict-not-validation-error framing.
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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
            "attachment_ref": message.attachment_ref,
            "sent_at": message.sent_at.isoformat(),
        },
    )
    return message


def _content_disposition_header_value(original_filename: str) -> str:
    """Builds a full `Content-Disposition` header value safe to hand to
    Starlette's `Response`, which encodes header values as Latin-1
    (`Response.init_headers`) — a plain `filename="…"` echo of an
    untrusted, user-supplied name (S1-FR-15: the Analyst names the file at
    upload time) crashes with an unhandled `UnicodeEncodeError` the moment
    that name contains anything outside Latin-1 (any CJK/Cyrillic/emoji
    filename), permanently 500ing that attachment's download route forever
    afterward, since the name is stored once, immutably, at upload time
    (dual review, this unit — caught independently by both reviewers).

    Two parameters, per RFC 6266: an ASCII-only `filename=` fallback (an
    allow-list of printable ASCII minus the characters that could break out
    of the quoted value or a filesystem path — not the previous 4-character
    deny-list, which passed non-Latin-1 characters straight through) for
    clients that don't parse `filename*`, plus a `filename*=UTF-8''…`
    percent-encoded parameter (guaranteed ASCII output via urllib.quote, so
    it can never itself trip the Latin-1 encode) carrying the real name for
    every modern browser. storage_key, not this filename, is what actually
    picks the filesystem path (always a server-generated uuid4().hex — see
    app.core.storage's own docstring), so this value is never used for path
    resolution — only ever echoed into a response header.

    Truncated once, up front (advisor review, this unit), and both
    parameters derived from that same truncated value — truncating only
    ascii_fallback, as an earlier version of this function did, left
    filename* unbounded, so an unbounded original_filename (Text column,
    no length constraint) still produced an unbounded header value through
    that parameter alone."""
    truncated = original_filename[:255]
    ascii_fallback = "".join(
        ch
        for ch in truncated
        if " " <= ch <= "~" and ch not in '"\\/'
    )
    ascii_fallback = ascii_fallback or "attachment"
    encoded = quote(truncated, safe="")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


@router.post(
    "/threads/{thread_id}/attachments",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment_route(
    thread_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    storage: AttachmentStorage = Depends(get_attachment_storage),
    identity: dict[str, str] = Depends(require_analyst),
):
    """Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380): phase one of the
    two-phase upload-then-send flow (see migration 0026's docstring for why
    a message can't be attached-to after the fact). require_analyst, not
    reject_service_role like every other write in this router — PRD 380
    frames attachments as Analyst-side specifically, and app.core.auth.
    AttachmentOwnershipError's own docstring explains why send_message's
    ownership check is what actually makes this structural, not just this
    dependency alone."""
    try:
        uploaded_by_user_id = uuid.UUID(identity["user_id"])
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc
    max_size = request.app.state.settings.max_attachment_size_bytes
    # Bounded read: reads at most one byte past the cap so an oversized
    # upload is rejected without copying the rest of the already-parsed
    # file into a second, larger `bytes` object. This does NOT bound what
    # gets buffered before this line runs, though — a Starlette version
    # note, corrected from an earlier, inaccurate claim here (dual review,
    # this unit): FastAPI has already fully parsed `file` via Starlette's
    # MultiPartParser by the time this route body executes, and that parser
    # applies no size limit at all to file parts (only to plain form
    # fields — see app.core.body_size_limit's own module docstring for the
    # exact trace). app.main's MaxBodySizeMiddleware, not this read, is
    # what actually stops an oversized body from being received in the
    # first place.
    content = await file.read(max_size + 1)
    try:
        # run_in_threadpool (Unit 32, pre-implementation security review,
        # decision 1627): upload_attachment's storage.save() call can now be
        # a real R2 network round-trip, not just a local disk write - this
        # route is `async def`, so calling it directly on the event loop
        # would block every other coroutine on this worker for the duration
        # of that upload. get_message_attachment_route needs no equivalent
        # change - it's already a plain `def`, which FastAPI/Starlette runs
        # in the same threadpool this call now uses explicitly.
        attachment = await run_in_threadpool(
            upload_attachment,
            session,
            storage,
            thread_id=thread_id,
            uploaded_by_user_id=uploaded_by_user_id,
            original_filename=file.filename or "attachment",
            claimed_content_type=file.content_type or "application/octet-stream",
            content=content,
            max_size_bytes=max_size,
        )
        session.commit()
    except ThreadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ThreadCompletedError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AttachmentTooLargeError as exc:
        session.rollback()
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)
        ) from exc
    except UnsupportedAttachmentTypeError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    session.refresh(attachment)
    return attachment


@router.get("/messages/{message_id}/attachment")
def get_message_attachment_route(
    message_id: uuid.UUID,
    session: Session = Depends(get_session),
    storage: AttachmentStorage = Depends(get_attachment_storage),
    _identity: dict[str, str] = Depends(reject_service_role),
):
    """Unit 30c (MEADOWOPS-UI-005, PRD 380): "served only to the two
    authenticated roles on the owning thread." reject_service_role (both
    human roles, either Admin or Analyst) matches this project's existing
    scale precedent for that phrase — DD-41's own accepted LOW finding
    documents that nothing in this chat feature is thread-participant-
    scoped beyond "any authenticated human role," harmless at the current
    single-Builder/single-Analyst scale, so this route doesn't invent a
    stricter boundary than every other message-reading route in this file
    already has.

    Content-Disposition: attachment + X-Content-Type-Options: nosniff
    (advisor review, this unit): "never executed or interpreted
    server-side" (PRD 380) is about this server, but the realistic exploit
    is the *browser* rendering an uploaded file inline from this origin -
    these two headers are what actually close that, not the content-type
    allowlist alone."""
    attachment = get_attachment_for_message(session, message_id)
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no attachment on this message")
    content = storage.load(attachment.storage_key)
    return Response(
        content=content,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": _content_disposition_header_value(attachment.original_filename),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/threads/{thread_id}/suggest-pushback", response_model=SuggestPushbackResponse)
def suggest_pushback_route(
    thread_id: uuid.UUID,
    payload: SuggestPushbackRequest,
    session: Session = Depends(get_session),
    claude_client: ClaudeClient | None = Depends(get_claude_client),
    _identity: dict[str, str] = Depends(require_admin),
) -> SuggestPushbackResponse:
    """Builder-only (require_admin, not reject_service_role, unlike every
    other route above) - the ground truth this suggestion is built from
    (redacted, but still real scenario evidence) must never reach the
    Analyst role."""
    if claude_client is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Persona pushback suggestion is not configured (no Claude client)",
        )
    try:
        suggestion = suggest_thread_pushback(
            session,
            thread_id=thread_id,
            attitude=Attitude(payload.attitude),
            claude_client=claude_client,
        )
    except ThreadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (
        NoAnalystMessageYetError,
        ScenarioCancelledError,
        MaxPushbackRoundsExceededError,
    ) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PersonaMessageGenerationFailedError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return SuggestPushbackResponse(suggested_message=suggestion)


@router.post("/threads/{thread_id}/sufficiency-check", response_model=SufficiencyCheckResponse)
def sufficiency_check_route(
    thread_id: uuid.UUID,
    session: Session = Depends(get_session),
    claude_client: ClaudeClient | None = Depends(get_claude_client),
    _identity: dict[str, str] = Depends(require_admin),
) -> SufficiencyCheckResponse:
    """Builder-only, same reasoning as suggest_pushback_route above - this
    one gets the *full* ground_truth package (it grades against it), so the
    access-control boundary matters even more here."""
    if claude_client is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI sufficiency check is not configured (no Claude client)",
        )
    try:
        verdict = check_thread_sufficiency(session, thread_id=thread_id, claude_client=claude_client)
    except ThreadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (NoAnalystMessageYetError, ScenarioCancelledError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SufficiencyCheckFailedError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return SufficiencyCheckResponse(
        verdict=verdict.verdict, suggested_pushback=verdict.suggested_pushback
    )


@router.post("/threads/{thread_id}/complete", response_model=EvaluationRead)
def complete_thread_route(
    thread_id: uuid.UUID,
    session: Session = Depends(get_session),
    claude_client: ClaudeClient | None = Depends(get_claude_client),
    _identity: dict[str, str] = Depends(require_admin),
) -> EvaluationRead:
    """Builder-only, same reasoning as suggest_pushback_route/
    sufficiency_check_route - generates a draft evaluation from the
    scenario's ground truth. On failure (after the one automatic retry),
    neither the thread's status nor an Evaluation row changes - see
    app.services.evaluation's own docstring for why that's deliberate."""
    if claude_client is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI evaluation is not configured (no Claude client)",
        )
    try:
        evaluation = complete_thread_and_generate_evaluation(
            session, thread_id=thread_id, claude_client=claude_client
        )
        session.commit()
    except ThreadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (
        ThreadAlreadyCompletedError,
        LatestMessageNotFromAnalystError,
        ScenarioCancelledError,
    ) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except EvaluationGenerationFailedError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except IntegrityError as exc:
        # Code review, HIGH: Evaluation.thread_id's unique constraint
        # (app.db.evaluation's own "DB-level backstop" comment) is the
        # only thing that actually closes the race between two concurrent
        # /complete calls for the same still-OPEN thread - both can pass
        # the in-memory ThreadAlreadyCompletedError check before either
        # commits. Same IntegrityError-to-409 translation as
        # create_thread_route's own (scenario_id, persona) race above.
        session.rollback()
        if isinstance(exc.orig, pg_errors.UniqueViolation):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="chat thread is already completed"
            ) from exc
        raise
    session.refresh(evaluation)
    return evaluation


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
