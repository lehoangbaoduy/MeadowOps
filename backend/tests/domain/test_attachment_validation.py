"""Unit 30c (MEADOWOPS-UI-005, PRD 380): pure content-sniffing tests for
app.domain.attachment_validation — no DB, no fixture beyond raw bytes, same
shape as tests/domain/test_query_classifier.py.

The HTML-disguised-as-CSV cases are the load-bearing tests here (advisor
review, this unit): PRD 380 requires this boundary "tested directly, not
just asserted" — the same bar the Query Playground's sandbox boundary was
held to.
"""

import pytest

from app.domain.attachment_validation import (
    ALLOWED_CONTENT_TYPES,
    UnsupportedAttachmentTypeError,
    sniff_content_type,
    validate_attachment_content,
)

_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00rest-of-a-fake-jpeg"
_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRrest-of-a-fake-png"
_GIF_BYTES = b"GIF89a\x01\x00\x01\x00rest-of-a-fake-gif"
_PDF_BYTES = b"%PDF-1.7\n%rest-of-a-fake-pdf"
_CSV_BYTES = b"product_id,warehouse_id,on_hand\nSKU-COR-001,WH-EAST,12\n"


class TestSniffContentType:
    def test_detects_jpeg_from_its_magic_bytes(self) -> None:
        assert sniff_content_type(_JPEG_BYTES) == "image/jpeg"

    def test_detects_png_from_its_magic_bytes(self) -> None:
        assert sniff_content_type(_PNG_BYTES) == "image/png"

    def test_detects_gif_from_its_magic_bytes(self) -> None:
        assert sniff_content_type(_GIF_BYTES) == "image/gif"

    def test_detects_pdf_from_its_magic_bytes(self) -> None:
        assert sniff_content_type(_PDF_BYTES) == "application/pdf"

    def test_detects_plain_csv_text(self) -> None:
        assert sniff_content_type(_CSV_BYTES) == "text/csv"

    def test_returns_none_for_unrecognized_binary_content(self) -> None:
        # A Windows PE executable's own magic bytes ("MZ...") - not in the
        # allowlist and not text, so it must sniff as nothing at all, not
        # fall through to a CSV guess.
        assert sniff_content_type(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00") is None

    def test_returns_none_for_empty_content(self) -> None:
        assert sniff_content_type(b"") is None

    def test_rejects_html_disguised_as_csv(self) -> None:
        """The exact bypass advisor review flagged for this unit: a file
        uploaded with a .csv name/claimed content-type whose actual bytes
        are HTML - must NOT sniff as text/csv."""
        html_bytes = b"<html><body><script>alert(1)</script></body></html>"
        assert sniff_content_type(html_bytes) is None

    def test_rejects_html_disguised_as_csv_with_leading_whitespace_or_bom(self) -> None:
        assert sniff_content_type(b"\xef\xbb\xbf   <!DOCTYPE html><html></html>") is None

    def test_rejects_csv_looking_content_containing_a_null_byte(self) -> None:
        # A strong signal of binary content masquerading as text - no
        # legitimate CSV export would ever contain a NUL byte.
        assert sniff_content_type(b"a,b,c\x00\x01\x02\n1,2,3\n") is None

    def test_rejects_content_that_does_not_decode_as_utf8(self) -> None:
        assert sniff_content_type(b"\xff\xfe\x00\x01not valid utf-8") is None


class TestValidateAttachmentContent:
    def test_returns_the_sniffed_type_when_it_matches_the_claim(self) -> None:
        assert validate_attachment_content("image/jpeg", _JPEG_BYTES) == "image/jpeg"
        assert validate_attachment_content("text/csv", _CSV_BYTES) == "text/csv"

    def test_raises_when_content_does_not_sniff_as_any_allowed_type(self) -> None:
        with pytest.raises(UnsupportedAttachmentTypeError):
            validate_attachment_content("image/jpeg", b"not actually a jpeg at all")

    def test_raises_when_claimed_type_is_outside_the_allowlist(self) -> None:
        with pytest.raises(UnsupportedAttachmentTypeError):
            validate_attachment_content("application/x-msdownload", _PDF_BYTES)

    def test_raises_when_sniffed_and_claimed_types_disagree(self) -> None:
        """The declared content-type is never trusted on its own - a PNG
        upload that claims to be text/csv is rejected, not silently
        corrected to image/png."""
        with pytest.raises(UnsupportedAttachmentTypeError):
            validate_attachment_content("text/csv", _PNG_BYTES)

    def test_raises_for_html_claiming_to_be_csv(self) -> None:
        """End-to-end version of the sniff-level HTML-as-CSV test above,
        through the actual function upload_attachment calls."""
        html_bytes = b"<html><body>not a spreadsheet</body></html>"
        with pytest.raises(UnsupportedAttachmentTypeError):
            validate_attachment_content("text/csv", html_bytes)

    def test_allowed_content_types_match_prd_380s_allowlist(self) -> None:
        # images, PDF, CSV (PRD 380) - pinned so a future edit to the
        # allowlist is a deliberate, reviewed change, not an accidental one.
        assert ALLOWED_CONTENT_TYPES == {
            "image/jpeg",
            "image/png",
            "image/gif",
            "application/pdf",
            "text/csv",
        }
