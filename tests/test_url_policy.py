"""Tests for URL validation policy.

These tests verify that _is_allowed_url() correctly validates document
source URLs before fetching, ensuring only trusted hosts and schemes
are allowed for document extraction.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import _is_allowed_url


# =========================================================================
# Trusted Hosts
# =========================================================================


def test_allows_platform_document_hosts():
    """Internal platform APIs and document hosts are allowed."""
    assert _is_allowed_url("https://etenders-api.tenders-sa.org/api/document?id=155529/file.pdf")
    assert _is_allowed_url("https://docs.tenders-sa.org/docs/155529/file.pdf")


def test_allows_government_etenders_source_urls():
    """South African government eTenders portal is allowed."""
    assert _is_allowed_url(
        "https://www.etenders.gov.za/home/Download/?blobName=abc.pdf&downloadedFileName=bid.pdf"
    )
    assert _is_allowed_url(
        "https://etenders.gov.za/home/Download/?blobName=abc.pdf&downloadedFileName=bid.pdf"
    )


def test_allows_direct_cloudflare_r2_urls():
    """Direct Cloudflare R2 object URLs are allowed."""
    assert _is_allowed_url("https://bucket.account.r2.cloudflarestorage.com/docs/155529/file.pdf")


def test_allows_r2_subdomain_urls():
    """Subdomains of docs.tenders-sa.org (R2 proxied) are allowed."""
    assert _is_allowed_url("https://service-1.docs.tenders-sa.org/docs/155529/file.docx")
    assert _is_allowed_url("https://cdn.docs.tenders-sa.org/bidpacks/archive.xlsx")


def test_allows_localhost_for_development():
    """Localhost is allowed for development/testing."""
    assert _is_allowed_url("http://localhost:8000/test/document.docx")
    assert _is_allowed_url("http://127.0.0.1:8000/test/document.xlsx")
    assert _is_allowed_url("http://0.0.0.0:8080/test/document.pdf")


# =========================================================================
# Document Type URLs from Trusted Hosts
# =========================================================================


def test_all_document_types_from_trusted_host():
    """All supported document types from trusted hosts are allowed."""
    base = "https://docs.tenders-sa.org/tenders/"
    assert _is_allowed_url(f"{base}tender.pdf")
    assert _is_allowed_url(f"{base}tender.docx")
    assert _is_allowed_url(f"{base}tender.doc")
    assert _is_allowed_url(f"{base}pricing.xlsx")
    assert _is_allowed_url(f"{base}pricing.xls")
    assert _is_allowed_url(f"{base}briefing.pptx")
    assert _is_allowed_url(f"{base}municipal.odt")
    assert _is_allowed_url(f"{base}document.rtf")
    assert _is_allowed_url(f"{base}data.csv")
    assert _is_allowed_url(f"{base}notes.txt")
    assert _is_allowed_url(f"{base}bidpack.zip")


# =========================================================================
# Rejected URLs
# =========================================================================


def test_rejects_untrusted_hosts():
    """Arbitrary external hosts are not allowed."""
    assert not _is_allowed_url("https://example.com/file.pdf")
    assert not _is_allowed_url("https://drive.google.com/file/doc.docx")
    assert not _is_allowed_url("https://dropbox.com/s/abc/tender.xlsx")
    assert not _is_allowed_url("https://s3.amazonaws.com/tenders/doc.pdf")


def test_rejects_file_scheme():
    """file:// URLs are not allowed (can't access local filesystem)."""
    assert not _is_allowed_url("file:///tmp/tender.pdf")
    assert not _is_allowed_url("file:///C:/Documents/tender.docx")


def test_rejects_ftp_and_other_schemes():
    """Only HTTP/HTTPS schemes are allowed."""
    assert not _is_allowed_url("ftp://files.etenders.gov.za/tender.pdf")
    assert not _is_allowed_url("sftp://host/tender.pdf")
    assert not _is_allowed_url("data:application/pdf;base64,dGVzdA==")


def test_rejects_malformed_urls():
    """Malformed or empty URLs are rejected."""
    assert not _is_allowed_url("")
    assert not _is_allowed_url("not-a-url")
    assert not _is_allowed_url("http://")
    assert not _is_allowed_url("https://")


def test_rejects_http_on_trusted_scheme_only():
    """HTTPS-only hosts reject HTTP."""
    # Government eTenders still works with HTTP
    assert _is_allowed_url("http://www.etenders.gov.za/home/Download/?blobName=abc.pdf")
    # But arbitrary hosts still fail
    assert not _is_allowed_url("http://malicious.com/tender.pdf")


# =========================================================================
# Edge Cases
# =========================================================================


def test_url_with_query_params():
    """URLs with query parameters from trusted hosts are allowed."""
    assert _is_allowed_url(
        "https://docs.tenders-sa.org/tender.pdf?token=abc&expires=1234567890"
    )


def test_url_with_fragment():
    """URLs with fragments from trusted hosts are allowed."""
    assert _is_allowed_url("https://docs.tenders-sa.org/tender.pdf#page=5")


def test_url_with_port():
    """Trusted hosts with non-standard ports are allowed (dev mode)."""
    assert _is_allowed_url("http://localhost:3000/api/tender.pdf")
    assert _is_allowed_url("https://docs.tenders-sa.org:8443/tender.pdf")


def test_case_insensitive_hostname():
    """Hostname matching is case-insensitive."""
    assert _is_allowed_url("https://DOCS.TENDERS-SA.ORG/tender.pdf")
    assert _is_allowed_url("https://WWW.ETENDERS.GOV.ZA/tender.pdf")


def test_trailing_dot_in_hostname():
    """Trailing dot in hostname is handled correctly."""
    # URLs ending in a dot won't match our allowlist — that's fine
    assert not _is_allowed_url("https://docs.tenders-sa.org./tender.pdf")
