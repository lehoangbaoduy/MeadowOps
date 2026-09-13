"""Unit 30c (MEADOWOPS-UI-005, PRD 380): pure content-type validation for
uploaded chat attachments - no I/O, no DB, so it's testable without any
fixture beyond raw bytes (same "domain module has no side effects" shape as
app.domain.query_classifier).

PRD 380's allowlist is "images, PDF, CSV." The client-declared Content-Type
header and the filename extension are both attacker-controlled and never
trusted (advisor-review finding, this unit) - every upload is sniffed from
its actual bytes instead, and the *sniffed* type (never the client's claim)
is what gets stored and later served back. A `.csv` that is actually HTML
is the textbook bypass this guards against: CSV has no magic-byte signature
of its own, so it's accepted only by first ruling out every other known
binary signature, then requiring the content to actually decode as text and
not look like markup.
"""

ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "application/pdf", "text/csv"}
)

# Hard cap - PRD 380 requires one, gives no specific number. Chosen as a
# sane default for the "images, PDF, CSV" allowlist at this project's scale;
# a Settings field (Unit 30c, app.core.config) so ops can retune without a
# redeploy, same convention as query_timeout_seconds/reporting_lag_days.
DEFAULT_MAX_ATTACHMENT_SIZE_BYTES = 5_000_000

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_GIF_MAGICS = (b"GIF87a", b"GIF89a")
_PDF_MAGIC = b"%PDF-"


class UnsupportedAttachmentTypeError(ValueError):
    """Raised when the uploaded bytes don't sniff as one of
    ALLOWED_CONTENT_TYPES, or the sniffed type disagrees with the client's
    declared Content-Type."""


def sniff_content_type(content: bytes) -> str | None:
    """Returns the sniffed content type if `content`'s own bytes match a
    known signature in ALLOWED_CONTENT_TYPES, else None. Checked in a fixed
    order (binary signatures first) so a CSV that happens to start with
    bytes resembling another format is never misclassified as CSV by
    default - CSV is the fallback, not the first guess."""
    if content.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if content.startswith(_PNG_MAGIC):
        return "image/png"
    if content.startswith(_GIF_MAGICS):
        return "image/gif"
    if content.startswith(_PDF_MAGIC):
        return "application/pdf"
    return _sniff_csv(content)


def _sniff_csv(content: bytes) -> str | None:
    """No magic-byte signature exists for CSV - text is text. Accepted only
    when the content is NOT empty, decodes cleanly as UTF-8, contains no
    NUL byte (a strong binary-content signal no legitimate CSV would ever
    have), and doesn't open with markup (`<` after stripping a UTF-8 BOM
    and leading whitespace) - the classic "HTML saved with a .csv name"
    bypass advisor review flagged for this unit."""
    if not content:
        return None
    if b"\x00" in content:
        return None
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    stripped = text.lstrip("﻿ \t\r\n")
    if stripped.startswith("<"):
        return None
    return "text/csv"


def validate_attachment_content(claimed_content_type: str, content: bytes) -> str:
    """Returns the trusted (sniffed) content type on success. Raises
    UnsupportedAttachmentTypeError if the bytes don't sniff as any allowed
    type, or if the sniffed type disagrees with what the client declared -
    a mismatch is treated as suspicious rather than silently corrected,
    since a client that mislabels its own upload has no legitimate reason
    to."""
    sniffed = sniff_content_type(content)
    if sniffed is None or sniffed not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedAttachmentTypeError(
            "file content does not match an allowed attachment type "
            "(images, PDF, CSV)"
        )
    if claimed_content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedAttachmentTypeError(
            f"declared content type {claimed_content_type!r} is not allowed"
        )
    if sniffed != claimed_content_type:
        raise UnsupportedAttachmentTypeError(
            "declared content type does not match the file's actual content"
        )
    return sniffed
