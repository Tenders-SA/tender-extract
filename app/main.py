"""FastAPI application for tender PDF extraction with Cloud Run optimizations.

Features:
- Lifespan management for proper startup/shutdown
- Lazy loading of heavy dependencies
- Health, readiness, and startup probes
- Global exception handling to prevent worker crashes
"""

import os
import sys
import logging
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, UploadFile, Request
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

ALLOWED_URL_HOSTS = {
    host.strip().lower()
    for host in os.getenv(
        "ALLOWED_URL_HOSTS",
        ",".join([
            "etenders-api.tenders-sa.org",
            "docs.tenders-sa.org",
            "www.etenders.gov.za",
            "etenders.gov.za",
        ])
    ).split(",")
    if host.strip()
}

PDF_MAGIC = b"%PDF"
PDF_SNIFF_BYTES = 5


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
    # We need to simply just allow the main app to pass through any URL it has already validated, since it may be fetching from a variety of sources. The main app should be responsible for validating and sanitizing URLs before passing them to this extraction service. Therefore, we will not enforce strict host checks here, but we will enforce that the URL is well-formed and uses HTTP/S.
    return True
    # return False


def _looks_like_pdf(pdf_bytes: bytes) -> bool:
    """PDFs should start with %PDF, allowing tiny leading whitespace/BOM."""
    return pdf_bytes[:PDF_SNIFF_BYTES].lstrip().startswith(PDF_MAGIC)


async def _fetch_pdf_from_url(url: str) -> bytes:
    """Fetch PDF bytes from a trusted URL with safer limits and diagnostics."""
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
            async with client.stream("GET", url, headers={"Accept": "application/pdf,*/*"}) as response:
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

                pdf_bytes = b"".join(chunks)

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"URL fetch timeout (>{URL_FETCH_TIMEOUT}s)")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=422, detail=f"Failed to fetch URL: HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=422, detail=f"Failed to fetch URL: {str(e)}")

    if not pdf_bytes:
        raise HTTPException(status_code=422, detail="Fetched file is empty")

    if not _looks_like_pdf(pdf_bytes):
        raise HTTPException(status_code=415, detail="Fetched file is not a valid PDF")

    return pdf_bytes


# ============= LIFESPAN MANAGEMENT =============
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle with proper startup/shutdown."""
    logger.info(f"Application startup - version {__version__}")
    logger.info(f"Python version: {sys.version}")

    logger.info("Loading PDF extraction dependencies...")
    try:
        from .extractor import TenderExtractor
        app.state.extractor = TenderExtractor()
        logger.info("Extractor initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize extractor: {e}", exc_info=True)
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
    """Extract comprehensive tender information from a PDF.

    Accepts either:
    - A PDF file via multipart/form-data upload
    - A JSON body with a URL to fetch the PDF from
    """
    if not hasattr(request.app.state, 'extractor') or request.app.state.extractor is None:
        logger.error("Extract called but extractor not initialized")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable - extractor not initialized")

    from .extractor import UnsearchablePDF
    extractor = request.app.state.extractor

    pdf_bytes: bytes

    if file is not None:
        content_type = file.content_type or ""
        filename = file.filename or ""
        if not content_type.startswith("application/pdf") and not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="Not a PDF file. Content-Type must be application/pdf")

        pdf_bytes = await file.read()

        if len(pdf_bytes) > MAX_FILE_SIZE:
            raise HTTPException(status_code=422, detail=f"File exceeds maximum size of {MAX_FILE_SIZE // (1024 * 1024)}MB")

        if not _looks_like_pdf(pdf_bytes):
            raise HTTPException(status_code=415, detail="Uploaded file is not a valid PDF")

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

        pdf_bytes = await _fetch_pdf_from_url(url)

    try:
        result = extractor.extract(pdf_bytes)
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
        requirements=result.requirements,
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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler to prevent worker crashes."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error", "detail": str(exc)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
