# Tender Extract API

FastAPI microservice that extracts structured tender data from South African government procurement documents using deterministic extraction. Supports PDF, DOCX, DOC, XLSX, XLS, PPTX, ODT, RTF, CSV, TXT, and ZIP archives.

---

## About Tenders-SA

[Tenders-SA.org](https://www.tenders-sa.org) is an **AI-powered tender matching and application platform** for South African businesses. It aggregates tenders from national, provincial, and municipal government departments, SOEs (Eskom, Transnet, SANRAL), and public entities — sourced directly from official OCDS (Open Contracting Data Standard) feeds.

### Role of This Microservice

Government tender documents are the raw source of truth for procurement opportunities. The **Tender Extract API** converts unstructured documents into structured, queryable data fields such as:

- Description and scope of work
- Requirements and eligibility criteria
- Tender reference numbers and titles
- Closing dates and times
- Issuing organizations and departments
- Estimated values and bid bond requirements
- B-BBEE level requirements and preference points
- Contact information and briefing session details
- Evaluation criteria and returnable documents
- Confidence scores for extraction quality

This service is intentionally **fast and deterministic** — it uses regex-based extraction and format-specific parsers, not AI/LLM processing. When extraction confidence is low, the main application decides whether to run AI fallback enrichment.

### Pipeline Architecture

```mermaid
graph LR
    A[Cloudflare Worker] -->|Raw OCDS + Document URL| B[Main App<br/>Ingestion Service]
    B -->|URL| C[Tender Extract API]
    C -->|Structured JSON| B
    B -->|Mapped Data| D[(Main Database)]
    D --> E[AI Enrichment<br/>(if confidence low)]
```

---

## Features

- **Multi-format extraction** — PDF, DOCX, DOC, XLSX, XLS, PPTX, ODT, RTF, CSV, TXT
- **ZIP archive support** — Recursive extraction of mixed-format bid packs with result merging
- **Plugin architecture** — Each format is a self-contained extractor module implementing `BaseExtractor`
- **Content-type detection** — Magic byte sniffing > file extension > MIME type priority chain
- **Regex-first extraction** — Deterministic pattern matching tuned for South African government tender formats
- **SA tender optimized** — Patterns cover CIDB gradings, B-BBEE levels, 80/20 and 90/10 preference systems, MBD/SBD returnable document forms, and SA procurement terminology
- **Comprehensive field extraction** — 20+ structured fields including description, requirements, dates, organization, financials, B-BBEE, contact, briefing sessions, evaluation criteria, and returnable documents
- **Multiple input modes** — File upload (multipart) or URL fetch (JSON)
- **Confidence scoring** — Weighted quality indicator (0.0–1.0) for extraction reliability
- **Full text passthrough** — Always returns raw extracted text for AI fallback in the main application
- **URL validation** — Enforced allowlist for trusted document hosts
- **Zero AI dependencies** — No LLM, no OCR, no external APIs.

---

## Quick Start

### Local Development

```bash
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Linux/Mac

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Visit [http://localhost:8000/docs](http://localhost:8000/docs) for interactive Swagger UI.

### Docker

```bash
docker build -t tender-extract .
docker run -p 8080:8080 tender-extract
```

---

## API Reference

### Health Check

```
GET /health
```

```json
{
  "status": "healthy",
  "version": "0.1.0"
}
```

### Readiness Probe

```
GET /ready
```

Returns `200` when the extractor is initialized and ready for traffic, `503` during startup.

### Extract Tender Data

```
POST /v1/extract
```

Extracts structured tender information from a document. Accepts either a file upload or a URL. Supports all formats: PDF, DOCX, DOC, XLSX, XLS, PPTX, ODT, RTF, CSV, TXT, ZIP.

#### Mode A: File Upload

```bash
curl -X POST http://localhost:8000/v1/extract \
  -F "file=@tender.pdf"
```

#### Mode B: URL Fetch

```bash
curl -X POST http://localhost:8000/v1/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.tenders-sa.org/tenders/abc123/specification.pdf"}'
```

#### Response

The response shape is identical regardless of input format:

```json
{
  "description": "Supply and delivery of office stationery and consumables...",
  "requirements": [
    "Valid tax clearance certificate required",
    "B-BBEE Level 1 or 2 contributor preferred"
  ],
  "tender_number": "SCM/2026/001",
  "title": "Supply and Delivery of Office Stationery",
  "closing_date": "31 March 2026",
  "closing_time": "11:00",
  "issuing_organization": "Department of Public Works",
  "department": "Supply Chain Management",
  "estimated_value": "R 5,000,000.00",
  "confidence": 0.87,
  "full_text": "DEPARTMENT OF PUBLIC WORKS...",
  ...
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | `string` | Cleaned plain-text description / scope of work |
| `requirements` | `list[string]` | Extracted requirements and eligibility criteria |
| `tender_number` | `string` | Tender/bid reference number |
| `title` | `string` | Tender title or name |
| `closing_date` | `string` | Submission deadline date |
| `closing_time` | `string` | Submission deadline time |
| `publication_date` | `string` | Date tender was published |
| `validity_period` | `string` | Bid validity period |
| `contract_period` | `string` | Contract duration |
| `issuing_organization` | `string` | Organization issuing the tender |
| `department` | `string` | Department within the organization |
| `delivery_location` | `string` | Delivery location for goods/services |
| `submission_address` | `string` | Physical address for bid submission |
| `estimated_value` | `string` | Estimated contract value |
| `bid_bond_required` | `string` | Bid bond / guarantee requirements |
| `payment_terms` | `string` | Payment terms |
| `bbbee` | `BBBEEInfo` | B-BBEE requirements and scoring |
| `contact` | `ContactInfo` | Contact person details |
| `briefing_session` | `BriefingSession` | Briefing/site inspection details |
| `evaluation_criteria` | `string` | Evaluation and scoring criteria |
| `special_conditions` | `string` | Special conditions of contract |
| `returnable_documents` | `list[string]` | Documents to be submitted |
| `document_type` | `string` | Classified document type (RFQ, TENDER, EOI, RFP) |
| `province` | `string` | Province extracted from document |
| `contract_type` | `string` | Contract framework (NEC3, JBCC, GCC, FIDIC) |
| `procurement_threshold` | `string` | NT threshold classification |
| `evaluation_structured` | `object` | Structured evaluation sub-criteria |
| `confidence` | `float` | Extraction confidence (0.0–1.0) |
| `pages_used` | `list[int]` | 0-indexed pages/sheets analyzed |
| `raw_text_preview` | `string` | First 500 chars of extracted text |
| `full_text` | `string` | Complete extracted text (up to 50KB) |

### Error Codes

| Status | Code | Description |
|--------|------|-------------|
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Unsupported document format (wrong magic bytes, extension, or MIME type) |
| 422 | `UNPROCESSABLE_ENTITY` | Validation error — file too large, invalid URL, URL fetch failure |
| 501 | `NOT_IMPLEMENTED` | Scanned/image-only PDF detected (OCR not supported) |
| 504 | `GATEWAY_TIMEOUT` | URL fetch timed out (configurable, default 90s) |
| 500 | `INTERNAL_ERROR` | Unexpected extraction failure |
| 503 | `SERVICE_UNAVAILABLE` | Extractor not yet initialized |

---

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `MAX_FILE_SIZE_BYTES` | `104857600` (100MB) | Maximum document file size |
| `URL_FETCH_TIMEOUT_SECONDS` | `90.0` | Timeout for URL fetching |
| `URL_FETCH_MAX_REDIRECTS` | `5` | Maximum redirects to follow |
| `ALLOWED_URL_HOSTS` | `etenders-api.tenders-sa.org, docs.tenders-sa.org, www.etenders.gov.za, etenders.gov.za` | Comma-separated trusted document URL hosts |
| `GUNICORN_WORKERS` | `2` | Gunicorn worker processes |
| `GUNICORN_TIMEOUT` | `120` | Gunicorn worker timeout (seconds) |
| `LOG_LEVEL` | `info` | Logging level |
| `PORT` | `8080` | HTTP port |

---

## Deployment

Deployed on **AWS EC2**. See the main project deployment documentation for infrastructure details.

### Docker

```bash
docker build -t tender-extract .
docker run -p 8080:8080 tender-extract
```

---

## Project Structure

```
tender-extract/
├── app/
│   ├── __init__.py           # Package info
│   ├── main.py               # FastAPI app, routes, URL validation, multi-format routing
│   ├── extractor.py          # Shared data types (ExtractionResult, etc.)
│   ├── schemas.py            # Pydantic request/response models
│   └── extractors/           # Plugin-based extractor modules
│       ├── __init__.py       # ExtractorRegistry — maps extensions/MIME/magic bytes
│       ├── base.py           # BaseExtractor abstract class
│       ├── pdf_extractor.py  # PDF (PyMuPDF)
│       ├── docx_extractor.py # DOCX (python-docx)
│       ├── legacy_doc_extractor.py  # Legacy .doc (antiword/catdoc + binary fallback)
│       ├── xlsx_extractor.py # XLSX (openpyxl)
│       ├── xls_extractor.py  # XLS (xlrd)
│       ├── pptx_extractor.py # PPTX (python-pptx)
│       ├── odt_extractor.py  # ODT (odfpy)
│       ├── rtf_extractor.py  # RTF (striprtf)
│       ├── text_extractor.py # CSV/TXT (stdlib)
│       └── zip_extractor.py  # ZIP (zipfile + recursive dispatch + result merging)
├── docs/
│   ├── API_REFERENCE.md      # Detailed API reference
│   ├── INTEGRATION_GUIDE.md  # Ingestion pipeline integration docs
│   └── openapi.json          # OpenAPI 3.0 specification
├── tests/
│   ├── __init__.py
│   ├── test_extractors.py    # 108 tests covering all extractors + registry
│   ├── test_zip_merge.py     # ZIP merger/reconciliation tests
│   └── test_url_policy.py    # URL allowlist + fetch policy tests
├── Dockerfile                # Multi-stage build for deployment
├── gunicorn.conf.py          # Gunicorn server config
├── requirements.txt          # Python dependencies
└── README.md
```

---

## Development

### Testing

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

Currently **108 tests** covering all extractors, registry dispatch, ZIP merging, and URL policy.

### Adding a New Extractor

1. Create a new file in `app/extractors/` implementing `BaseExtractor`
2. Register it in `ExtractorRegistry` in `__init__.py` (extension, MIME, and/or magic bytes)
3. All existing tests must still pass

### Design Principles

1. **No AI in the extraction path** — Deterministic extraction only. AI enrichment is a separate concern handled by the main application when confidence is low.
2. **SA-specific patterns** — All regex patterns are designed and tuned for South African government tender formats.
3. **Plugin architecture** — Each format is a self-contained module. Adding a new format never modifies existing extractors.
4. **Graceful degradation** — Always returns a result, even for poorly formatted documents. Low-confidence results signal the main app to run AI fallback.

---

## Links

- [Tenders-SA Platform](https://www.tenders-sa.org) — Main website
- [Developer Portal](https://tenders-sa.org/developers) — API keys, docs, and pricing
- [GitHub](https://github.com/Tenders-SA/tender-extract) — Source code & issues
- [Support](mailto:support@tenders-sa.org) — Email support

---

## License

MIT
