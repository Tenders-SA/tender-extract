import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import _is_allowed_url


def test_allows_platform_document_hosts():
    assert _is_allowed_url("https://etenders-api.tenders-sa.org/api/document?id=155529/file.pdf")
    assert _is_allowed_url("https://docs.tenders-sa.org/docs/155529/file.pdf")


def test_allows_government_etenders_source_urls():
    assert _is_allowed_url(
        "https://www.etenders.gov.za/home/Download/?blobName=abc.pdf&downloadedFileName=bid.pdf"
    )
    assert _is_allowed_url(
        "https://etenders.gov.za/home/Download/?blobName=abc.pdf&downloadedFileName=bid.pdf"
    )


def test_allows_direct_cloudflare_r2_urls():
    assert _is_allowed_url("https://bucket.account.r2.cloudflarestorage.com/docs/155529/file.pdf")


def test_rejects_untrusted_hosts_and_schemes():
    assert not _is_allowed_url("https://example.com/file.pdf")
    assert not _is_allowed_url("file:///tmp/file.pdf")
