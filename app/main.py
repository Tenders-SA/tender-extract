"""FastAPI application for tender PDF extraction with Cloud Run optimizations.

Features:
- Lifespan management for proper startup/shutdown
- Lazy loading of heavy dependencies
- Health, readiness, and startup probes
- Global exception handling to prevent worker crashes
"""

import os
import sys
import re
import hashlib
import logging
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, unquote

from fastapi import FastAPI, File, HTTPException, UploadFile, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx

# Configure logging before imports
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

from . import __version__
from .schemas import (
    ExtractRequest,
    ExtractResponse,
    HealthResponse,
    ContactInfo,
    BriefingSession,
    BBBEEInfo,
    EvaluationSubCriterion,
    EvaluationCriteria,
)

# Configuration
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_BYTES", str(100 * 1024 * 1024)))  # default 50 MB
URL_FETCH_TIMEOUT = float(os.getenv("URL_FETCH_TIMEOUT_SECONDS", "90.0"))
MAX_REDIRECTS = int(os.getenv("URL_FETCH_MAX_REDIRECTS", "5"))

CORE_ALLOWED_HOSTS: set[str] = {
    "etenders-api.tenders-sa.org",
    "docs.tenders-sa.org",
    "www.etenders.gov.za",
    "etenders.gov.za",
    "ocpo.treasury.gov.za",
    "secure.csd.gov.za",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
}

env_hosts_raw = os.getenv("ALLOWED_URL_HOSTS", "").strip()
if env_hosts_raw:
    env_hosts = {h.strip().lower() for h in env_hosts_raw.split(",") if h.strip()}
    ALLOWED_URL_HOSTS = CORE_ALLOWED_HOSTS | env_hosts
    logger.info("url_allowlist_init", {"core_hosts": list(CORE_ALLOWED_HOSTS), "env_added": list(env_hosts - CORE_ALLOWED_HOSTS)})
else:
    ALLOWED_URL_HOSTS = CORE_ALLOWED_HOSTS
from urllib.parse import urlparse, urlunparse

def normalize(url: str) -> str | None:
    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url  # or reject, depending on strictness

        parsed = urlparse(url)

        if not parsed.hostname:
            return None

        return urlunparse(parsed)
    except Exception:
        return None
    
def _is_allowed_url(url: str) -> bool:
    """Allow only trusted HTTP(S) document sources."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False

    if hostname in ALLOWED_URL_HOSTS:
        return True

    # Allow direct Cloudflare R2 object URLs when explicitly passed by the main app.
    if hostname.endswith(".r2.cloudflarestorage.com"):
        return True

    # Allow subdomains of docs.tenders-sa.org (e.g. service-1.docs.tenders-sa.org)
    if hostname == "docs.tenders-sa.org" or hostname.endswith(".docs.tenders-sa.org"):
        return True

    return False


async def _fetch_document_from_url(url: str) -> bytes:
    """Fetch document bytes from a trusted URL with safer limits and diagnostics."""
    if not _is_allowed_url(url):
        logger.warning("Blocked extraction fetch for untrusted URL", {"url": url[:200]})
        raise HTTPException(status_code=422, detail="URL host is not allowed for extraction")

    timeout = httpx.Timeout(
        timeout=URL_FETCH_TIMEOUT,
        connect=min(10.0, URL_FETCH_TIMEOUT),
        read=URL_FETCH_TIMEOUT,
        write=10.0,
        pool=10.0,
    )

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, max_redirects=MAX_REDIRECTS) as client:
            async with client.stream("GET", url, headers={"Accept": "*/*"}) as response:
                response.raise_for_status()

                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > MAX_FILE_SIZE:
                            raise HTTPException(
                                status_code=422,
                                detail=f"Fetched file exceeds maximum size of {MAX_FILE_SIZE // (1024 * 1024)}MB"
                            )
                    except ValueError:
                        logger.warning("Invalid content-length header", {"url": url[:200], "content_length": content_length})

                chunks: list[bytes] = []
                total_size = 0

                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue

                    chunks.append(chunk)
                    total_size += len(chunk)

                    if total_size > MAX_FILE_SIZE:
                        raise HTTPException(
                            status_code=422,
                            detail=f"Fetched file exceeds maximum size of {MAX_FILE_SIZE // (1024 * 1024)}MB"
                        )

                document_bytes = b"".join(chunks)

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"URL fetch timeout (>{URL_FETCH_TIMEOUT}s)")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=422, detail=f"Failed to fetch URL: HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=422, detail=f"Failed to fetch URL: {str(e)}")

    if not document_bytes:
        raise HTTPException(status_code=422, detail="Fetched file is empty")

    return document_bytes


# ============= LIFESPAN MANAGEMENT =============
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle with proper startup/shutdown."""
    logger.info(f"Application startup - version {__version__}")
    logger.info(f"Python version: {sys.version}")

    logger.info("Loading document extraction dependencies...")
    try:
        # Pre-load all extractor modules so imports are warmed up
        from .extractors import ExtractorRegistry  # noqa: F401
        from .extractor import TenderExtractor

        # Keep TenderExtractor for backward-compatible readiness probes
        app.state.extractor = TenderExtractor()
        logger.info("Document extractors initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize extractors: {e}", exc_info=True)
        app.state.extractor = None

    yield

    logger.info("Application shutdown")


app = FastAPI(
    title="Tender Extract API",
    description=(
        "Extract comprehensive information from South African government tender "
        "PDF documents including description, requirements, B-BBEE details, "
        "contact information, dates, and more."
    ),
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> HealthResponse:
    """Liveness probe - checks if container is alive."""
    return HealthResponse(status="healthy", version=__version__)


@app.get("/ready", tags=["System"])
async def readiness_check(request: Request):
    """Readiness probe - checks if app can handle traffic."""
    if not hasattr(request.app.state, 'extractor') or request.app.state.extractor is None:
        logger.warning("Readiness check failed - extractor not initialized")
        return JSONResponse(status_code=503, content={"status": "not_ready", "version": __version__})
    return {"status": "ready", "version": __version__}


@app.get("/startup", tags=["System"])
async def startup_check(request: Request):
    """Startup probe - checks if app finished initialization."""
    if not hasattr(request.app.state, 'extractor') or request.app.state.extractor is None:
        return JSONResponse(status_code=503, content={"status": "starting", "message": "Still initializing"})
    return {"status": "started", "version": __version__}


@app.post("/v1/extract", response_model=ExtractResponse, tags=["Extraction"])
async def extract_tender(
    request: Request,
    file: Optional[UploadFile] = File(None),
) -> ExtractResponse:
    """Extract comprehensive tender information from a document.

    Accepts either:
    - A document file via multipart/form-data upload (any supported format)
    - A JSON body with a URL to fetch the document from

    Supported formats are detected automatically via ExtractorRegistry
    (magic bytes > file extension > MIME type).
    """
    if not hasattr(request.app.state, 'extractor') or request.app.state.extractor is None:
        logger.error("Extract called but extractor not initialized")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable - extractor not initialized")

    from .extractor import UnsearchablePDF
    from .extractors import ExtractorRegistry

    document_bytes: bytes
    url_filename: Optional[str] = None

    if file is not None:
        document_bytes = await file.read()

        if len(document_bytes) > MAX_FILE_SIZE:
            raise HTTPException(status_code=422, detail=f"File exceeds maximum size of {MAX_FILE_SIZE // (1024 * 1024)}MB")

        # Detect extractor from file bytes, filename, and content type
        extractor = ExtractorRegistry.get_extractor(
            document_bytes,
            filename=file.filename,
            mime_type=file.content_type,
        )
        if extractor is None:
            raise HTTPException(
                status_code=415,
                detail="Unsupported file type. Supported formats: PDF, DOCX, DOC, XLSX, XLS, PPTX, ODT, RTF, CSV, TXT, ZIP"
            )

    else:
        try:
            body = await request.json()
            parsed_request = ExtractRequest(**body)
            url = str(parsed_request.url) if parsed_request.url else None
            if not url:
                raise HTTPException(status_code=422, detail="Provide either a file upload or a URL in the request body")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=422, detail="Provide either a file upload or a URL in the request body")

        document_bytes = await _fetch_document_from_url(url)

        # Extract filename from URL for extension-based type disambiguation
        parsed_url = urlparse(url)
        url_filename = os.path.basename(unquote(parsed_url.path)) or None

        # Detect extractor from document bytes and URL filename
        extractor = ExtractorRegistry.get_extractor(
            document_bytes,
            filename=url_filename,
        )
        if extractor is None:
            raise HTTPException(
                status_code=415,
                detail="Unsupported document type. Supported formats: PDF, DOCX, DOC, XLSX, XLS, PPTX, ODT, RTF, CSV, TXT, ZIP"
            )

    try:
        result = extractor.extract(document_bytes, filename=url_filename or (file.filename if file else None))
    except UnsearchablePDF as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        logger.error(f"Extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")

    contact_info = None
    if result.contact:
        contact_info = ContactInfo(
            name=result.contact.name,
            email=result.contact.email,
            phone=result.contact.phone,
            department=result.contact.department,
            address=result.contact.address,
        )

    briefing_info = None
    if result.briefing_session:
        briefing_info = BriefingSession(
            date=result.briefing_session.date,
            time=result.briefing_session.time,
            venue=result.briefing_session.venue,
            is_compulsory=result.briefing_session.is_compulsory,
        )

    bbbee_info = None
    if result.bbbee:
        bbbee_info = BBBEEInfo(
            minimum_level=result.bbbee.minimum_level,
            points_allocation=result.bbbee.points_allocation,
            details=result.bbbee.details,
            local_content_requirement=result.bbbee.local_content_requirement,
            hdi_requirement=result.bbbee.hdi_requirement,
        )

    eval_structured = None
    if result.evaluation_structured:
        sub_criteria = [
            EvaluationSubCriterion(
                criterion=s.criterion,
                weight=s.weight,
            )
            for s in result.evaluation_structured.sub_criteria
        ]
        eval_structured = EvaluationCriteria(
            system=result.evaluation_structured.system,
            functionality_threshold=result.evaluation_structured.functionality_threshold,
            sub_criteria=sub_criteria,
            details=result.evaluation_structured.details,
        )

    return ExtractResponse(
        description=result.description,
        requirements=result.requirements or ["No specific requirements found"],
        tender_number=result.tender_number,
        title=result.title,
        closing_date=result.closing_date,
        closing_time=result.closing_time,
        publication_date=result.publication_date,
        validity_period=result.validity_period,
        contract_period=result.contract_period,
        issuing_organization=result.issuing_organization,
        department=result.department,
        delivery_location=result.delivery_location,
        submission_address=result.submission_address,
        estimated_value=result.estimated_value,
        bid_bond_required=result.bid_bond_required,
        payment_terms=result.payment_terms,
        bbbee=bbbee_info,
        contact=contact_info,
        briefing_session=briefing_info,
        evaluation_criteria=result.evaluation_criteria,
        special_conditions=result.special_conditions,
        returnable_documents=result.returnable_documents,
        # Phase 2 extended taxonomy
        contractual_terms=result.contractual_terms or None,
        quality_management=result.quality_management or None,
        health_safety=result.health_safety or None,
        environmental=result.environmental or None,
        methodology=result.methodology or None,
        experience_qualifications=result.experience_qualifications or None,
        pricing_schedule=result.pricing_schedule or None,
        extended_sections=result.extended_sections if result.extended_sections else None,
        unclassified_content=result.unclassified_content or None,
        extraction_version=result.extraction_version,
        # Phase 1 extraction enhancements
        document_type=result.document_type,
        province=result.province,
        contract_type=result.contract_type,
        procurement_threshold=result.procurement_threshold,
        evaluation_structured=eval_structured,
        confidence=result.confidence,
        pages_used=result.pages_used,
        raw_text_preview=result.raw_text_preview,
        full_text=result.full_text,
    )


@app.post("/v1/extract/ocpo-suppliers", tags=["OCPO"])
async def extract_ocpo_suppliers(
    request: Request,
    file: Optional[UploadFile] = File(None),
):
    """Extract structured supplier entries from the OCPO restricted supplier PDF.

    Accepts either:
      - A PDF file via multipart upload (backward compatible)
      - A JSON body with `url` and optional `lastPdfHash`:
          { "url": "https://...", "lastPdfHash": "abc123..." }

    When `url` is provided, this service downloads the PDF itself.
    When `lastPdfHash` is provided and matches the downloaded PDF's hash,
    extraction is skipped and `{ success: true, changed: false, pdf_hash }` is returned.

    Returns structured entries with pdf_hash, parser metadata.
    """
    pdf_bytes: bytes | None = None

    # Determine source: file upload or URL
    if file is not None:
        pdf_bytes = await file.read()
    else:
        try:
            body = await request.json()
            url = body.get("url") if isinstance(body, dict) else None
            if not url:
                raise HTTPException(status_code=422, detail="Provide either a file upload or a 'url' field in the request body")
            last_pdf_hash = body.get("lastPdfHash") if isinstance(body, dict) else None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=422, detail="Provide either a file upload or a 'url' field in the request body")

        pdf_bytes = await _fetch_document_from_url(url)

        # Compute hash before extraction — allows early skip if PDF unchanged
        current_hash = hashlib.sha256(pdf_bytes).hexdigest()
        if last_pdf_hash and last_pdf_hash == current_hash:
            logger.info("ocpo_pdf_unchanged", {"pdf_hash": current_hash})
            return {"success": True, "changed": False, "pdf_hash": current_hash}

    # Compute hash for file upload path too
    current_hash = hashlib.sha256(pdf_bytes).hexdigest()

    # Write to temp file for Camelot
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp_path = tmp.name
    try:
        tmp.write(pdf_bytes)
        tmp.close()

        entries = []

        # Primary: Camelot for tabular extraction
        try:
            import camelot
            tables = camelot.read_pdf(tmp_path, pages="all", flavor="lattice")
            if not tables or tables.n == 0:
                tables = camelot.read_pdf(tmp_path, pages="all", flavor="stream")

            if tables and tables.n > 0:
                for table in tables:
                    col_map = None
                    for row_idx in range(table.df.shape[0]):
                        row_values = table.df.iloc[row_idx].tolist()

                        if col_map is None:
                            col_map = _detect_column_map(row_values)
                            if col_map:
                                logger.info(f"Detected OCPO column map: {col_map}")
                                continue

                        entry = _parse_ocpo_row(row_values, col_map)
                        if entry:
                            entries.append(entry)

                return {
                    "success": True,
                    "changed": True,
                    "entries": entries,
                    "parser": "camelot",
                    "entry_count": len(entries),
                    "pdf_hash": current_hash,
                }
        except Exception:
            logger.info("Camelot extraction failed, falling back to PyMuPDF", exc_info=True)

        # Fallback: PyMuPDF text extraction + regex
        entries = _extract_ocpo_with_fitz(tmp_path)
        return {
            "success": True,
            "changed": True,
            "entries": entries,
            "parser": "fitz_fallback",
            "entry_count": len(entries),
            "pdf_hash": current_hash,
        }

    except Exception as e:
        logger.error(f"OCPO extraction failed: {e}", exc_info=True)
        return {"success": False, "entries": [], "parser": "error", "error": str(e), "pdf_hash": current_hash}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _parse_ocpo_row(row_values: list, col_map: dict | None = None) -> dict | None:
    """Parse a single row from the OCPO PDF table into a structured entry.

    Supports two modes:
      - col_map provided: use explicit column index mapping (auto-detected from header).
      - col_map=None: fall back to positional heuristic (legacy 7-column layout).

    Returns None if the row doesn't contain valid data.
    """
    if not row_values or len(row_values) < 4:
        return None

    vals = [str(v).strip() if v else "" for v in row_values]

    first = vals[0]
    if not first:
        return None

    first_lower = first.lower().strip(". ")

    header_indicators = {
        "supplier name", "suppliername", "name", "no.", "no", "#",
        "nr", "nr.", "num", "num.", "number", "s/n", "seq",
        "restricted supplier", "supplier", "entity",
    }
    if first_lower in header_indicators:
        return None

    if all(not v or v == "-" for v in vals):
        return None

    def get_col(key: str, fallback_idx: int) -> str:
        if col_map and key in col_map:
            idx = col_map[key]
            if idx < len(vals):
                return vals[idx]
        if fallback_idx < len(vals):
            return vals[fallback_idx]
        return ""

    supplier_name = get_col("supplier_name", 0)
    registration_num = get_col("registration_number", 1)
    restriction_type = get_col("restriction_type", 2)
    restriction_reason = get_col("restriction_reason", 3)
    period_from = get_col("period_from", 4)
    period_to = get_col("period_to", 5)
    authorized_by = get_col("authorized_by", 6)

    if not supplier_name or len(supplier_name) < 2:
        return None

    if not restriction_type and not restriction_reason:
        return None

    def parse_date(date_str: str) -> str | None:
        if not date_str or date_str == "-":
            return None
        date_str = date_str.strip()
        for fmt in (
            "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
            "%d %b %Y", "%d %B %Y", "%Y/%m/%d",
            "%d-%b-%Y", "%d-%B-%Y", "%Y.%m.%d",
            "%d.%m.%Y",
        ):
            try:
                return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return date_str

    parsed_from = parse_date(period_from)
    parsed_to = parse_date(period_to)

    return {
        "supplierName": supplier_name,
        "registrationNumber": registration_num if registration_num and registration_num != "-" else None,
        "restrictionType": restriction_type or "Restricted",
        "restrictionReason": restriction_reason or "Not specified",
        "periodFrom": parsed_from,
        "periodTo": parsed_to,
        "authorizedBy": authorized_by if authorized_by else "OCPO",
        "reportGeneratedOn": None,
    }


def _detect_column_map(header_row: list) -> dict | None:
    """Detect column mapping from a header row.

    Returns a dict like {"supplier_name": 1, "registration_number": 2, ...}
    or None if the header cannot be reliably mapped.
    """
    if not header_row:
        return None

    vals = [str(v).strip().lower().strip(".") for v in header_row if v]

    col_map = {}
    patterns = {
        "supplier_name": ["supplier name", "suppliername", "supplier", "name", "entity", "company name", "company"],
        "registration_number": ["registration number", "reg number", "reg no", "reg.no", "registration no",
                                "company reg", "entity reg", "company registration"],
        "restriction_type": ["restriction type", "type", "category", "status", "classification"],
        "restriction_reason": ["restriction reason", "reason", "grounds", "description", "details"],
        "period_from": ["period from", "from date", "start date", "date from", "from"],
        "period_to": ["period to", "to date", "end date", "date to", "to", "expiry"],
        "authorized_by": ["authorized by", "authorised by", "authority", "issued by", "approved by"],
    }

    for col_key, keywords in patterns.items():
        for idx, val in enumerate(vals):
            val_clean = val.strip().lower()
            if val_clean in keywords:
                col_map[col_key] = idx
                break

    if "supplier_name" in col_map:
        return col_map
    return None


def _extract_ocpo_with_fitz(pdf_path: str) -> list:
    """Fallback OCR-less extraction using PyMuPDF text + regex patterns.

    Attempts to extract tabular data from the OCPO PDF when Camelot fails.
    Uses line-by-line text extraction with heuristic column detection.
    """
    entries = []
    try:
        import fitz

        doc = fitz.open(pdf_path)
        full_text = ""
        for page_num in range(len(doc)):
            page = doc[page_num]
            full_text += page.get_text()

        doc.close()

        lines = full_text.split("\n")
        in_table = False
        current_row = []
        col_map = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_table and current_row:
                    entry = _parse_ocpo_row(current_row, col_map)
                    if entry:
                        entries.append(entry)
                    current_row = []
                in_table = False
                continue

            if "|" in stripped:
                parts = [p.strip() for p in stripped.split("|") if p.strip()]
                if len(parts) >= 4:
                    if col_map is None:
                        detected = _detect_column_map(parts)
                        if detected:
                            col_map = detected
                            logger.info(f"Fitz detected column map: {col_map}")
                            in_table = True
                            continue
                    current_row = parts
                    in_table = True
                    continue

            parts = re.split(r"\s{2,}", stripped)
            if len(parts) >= 4:
                if col_map is None:
                    detected = _detect_column_map(parts)
                    if detected:
                        col_map = detected
                        logger.info(f"Fitz detected column map: {col_map}")
                        in_table = True
                        continue
                current_row = parts
                in_table = True
            elif in_table and current_row:
                current_row[-1] = current_row[-1] + " " + stripped

        if in_table and current_row:
            entry = _parse_ocpo_row(current_row, col_map)
            if entry:
                entries.append(entry)

    except Exception:
        logger.warning("PyMuPDF fallback extraction failed", exc_info=True)

    return entries


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler to prevent worker crashes."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error", "detail": str(exc)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
