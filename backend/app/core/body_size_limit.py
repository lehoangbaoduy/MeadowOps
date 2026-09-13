"""Unit 30c (MEADOWOPS-UI-005, security review): a hard cap on request body
size, enforced ahead of routing and form parsing entirely.

Why this can't live in app.api.chat.upload_attachment_route alone: that
route's own `await file.read(max_size_bytes + 1)` only bounds how much of
the *already-parsed* UploadFile the route copies into a `bytes` object. By
the time route code runs, FastAPI has already resolved the `File(...)`
dependency, which means Starlette's MultiPartParser has already streamed
the entire file part into a SpooledTemporaryFile first (confirmed directly
against the installed Starlette version, formparsers.py's `on_part_data`:
`max_part_size` is only checked for the `self._current_part.file is None`
branch - ordinary form fields - never for an actual file part, which is
unconditionally appended with no size check at all). A single authenticated
Analyst request with a multi-gigabyte file part would be fully received and
spooled to disk before `max_attachment_size_bytes` ever gets a chance to
reject it.

This middleware sits outside all of that. It rejects an oversized body
before any parsing starts, closing the gap regardless of which route or
body format (JSON, multipart, anything else) receives it - not routed
per-endpoint, since every other route on this API is small JSON and a
generous global cap costs them nothing.

Verified directly, two ways (advisor review, this unit - don't just assert
a mitigation works, check it): (1) a request with a declared Content-Length
over the cap is rejected by the header check below before receive() is
ever called, confirmed via a real oversized multipart POST against a
running app instance. (2) a request with NO Content-Length (real chunked
transfer, confirmed by inspecting the outgoing request's own headers - no
`content-length` key) still gets interrupted early by the raise inside
`limited_receive` once the running total crosses the cap - but the
resulting response is FastAPI's own generic `400 "There was an error
parsing the body"`, not this module's 413. Read directly in
fastapi/routing.py: request-body/form dependency resolution wraps every
exception except `HTTPException` and `json.JSONDecodeError` into that
fixed 400 before it can propagate to any exception handler this app
registers - `request_body_too_large_handler` below is therefore dead code
for every route on this API today (all of them resolve their body through
that same FastAPI machinery), kept registered only as a harmless defensive
no-op in case a future route ever raises this outside that path. The
security property that actually matters - the oversized body is never
fully received or spooled to disk - holds in both cases; only the
response's status code and message differ between them, and only for the
uncommon case of a client omitting Content-Length altogether (real browser
and curl file uploads always set it for a file of known size, which is
every realistic attachment upload)."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# Multipart boundary/header overhead (field names, Content-Disposition/
# Content-Type lines per part, the boundary string itself) on top of the
# raw file bytes - a few hundred bytes in practice, this is a deliberately
# generous margin so a legitimate max-size upload is never rejected purely
# for the encoding overhead around it.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


class RequestBodyTooLargeError(Exception):
    """Raised mid-stream, from inside the wrapped `receive()`, once the
    running total of received body bytes exceeds the configured cap -
    covers chunked-transfer or any other request with no (or a lying)
    Content-Length header, which the upfront header check below can't
    catch. Stops that oversized body from ever being fully received - the
    protection that actually matters - regardless of what status code the
    client ends up seeing (see this module's own docstring: on this app's
    routes today, that's FastAPI's generic 400, not the 413
    `request_body_too_large_handler` below is registered to produce,
    because FastAPI's own body-parsing dependency resolution intercepts
    this exception first)."""


async def _send_too_large_response(scope: Scope, receive: Receive, send: Send) -> None:
    # JSON body, not plain text (code review, this unit): both Next.js
    # attachment proxy routes do `await response.json()` on a non-ok
    # response - a plain-text body would make the proxy itself throw,
    # trading a clean 413 for an opaque Next.js 500 with no indication of
    # the real cause. Reuses the same JSONResponse the exception-handler
    # path returns, rather than hand-rolling ASGI messages twice.
    response = JSONResponse(
        status_code=413,
        content={"detail": "request body exceeds the maximum allowed size"},
    )
    await response(scope, receive, send)


class MaxBodySizeMiddleware:
    """Pure ASGI middleware (not BaseHTTPMiddleware) so it never buffers a
    request body itself - it only counts bytes as they stream past."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = None
            if declared is not None and declared > self.max_bytes:
                # Fast path: reject before ever calling receive() at all -
                # covers the overwhelming majority of real uploads (browsers
                # and curl both set Content-Length for a multipart file
                # upload of known size).
                await _send_too_large_response(scope, receive, send)
                return

        total = 0

        async def limited_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    raise RequestBodyTooLargeError()
            return message

        await self.app(scope, limited_receive, send)


async def request_body_too_large_handler(
    _request: Request, _exc: RequestBodyTooLargeError
) -> Response:
    return JSONResponse(
        status_code=413,
        content={"detail": "request body exceeds the maximum allowed size"},
    )
