# Tender Extract API

FastAPI microservice that extracts structured tender data from South African government PDF documents using deterministic regex-based pattern matching.

---

## About Tenders-SA

[Tenders-SA.org](https://www.tenders-sa.org) is an **AI-powered tender matching and application platform** for South African businesses. It aggregates tenders from national, provincial, and municipal government departments, SOEs (Eskom, Transnet, SANRAL), and public entities — sourced directly from official OCDS (Open Contracting Data Standard) feeds.

The platform goes beyond simple aggregation: AI enrichment extracts key requirements, generates summaries, estimates tender values, classifies categories, and calculates compatibility scores between your company profile and each opportunity.

### Role of This Microservice

Government tender PDFs are the raw source of truth for procurement opportunities. The **Tender Extract API** sits in the ingestion pipeline between the Cloudflare Worker (which fetches raw OCDS data and PDF documents) and the main application database. It converts unstructured PDF documents into structured, queryable data fields such as:

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

This service is intentionally **fast and deterministic** — it uses regex-based extraction with PyMuPDF, not AI/LLM processing. When extraction confidence is low, the main application decides whether to run AI fallback enrichment. This keeps the extraction layer cheap, fast, and reliable.

### Pipeline Architecture

```mermaid
graph LR
    A[Cloudflare Worker] -->|Raw OCDS + PDF URL| B[Tender Ingestion Service]
    B -->|PDF URL / File| C[Tender Extract API]
    C -->|Structured JSON| B
    B -->|Mapped Data| D[(Main Database)]
    D --> E[AI Enrichment<br/>(if confidence low)]
```

---

## Features

- **Regex-first extraction** — Deterministic pattern matching tuned for South African government tender formats
- **SA tender optimized** — Patterns cover CIDB gradings, B-BBEE levels, 80/20 and 90/10 preference systems, MBD/SBD returnable document forms, and SA procurement terminology
- **Comprehensive field extraction** — 20+ structured fields including description, requirements, dates, organization, financials, B-BBEE, contact, briefing sessions, evaluation criteria, and returnable documents
- **Multiple input modes** — File upload (multipart) or URL fetch (JSON)
- **Confidence scoring** — Weighted quality indicator (0.0–1.0) for extraction reliability
- **Scanned PDF detection** — Explicit detection of image-only pages, returns 501 rather than producing garbage output
- **Full text passthrough** — Always returns raw extracted text for AI fallback in the main application
- **Cloud-native** — Docker multi-stage build, health/readiness/startup probes, optimized for Cloud Run
- **Zero AI dependencies** — No LLM, no OCR, no external APIs. Pure Python + PyMuPDF

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

Returns service health status.

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

Extracts structured tender information from a PDF. Accepts either a file upload or a URL.

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
  "bbbee": {
    "minimum_level": "1",
    "points_allocation": "80/20"
  },
  "contact": {
    "name": "Mr. John Doe",
    "email": "john.doe@dpw.gov.za",
    "phone": "012 345 6789",
    "department": "Supply Chain Management"
  },
  "briefing_session": {
    "date": "15 March 2026",
    "time": "10:00",
    "venue": "DPW Boardroom, Pretoria",
    "is_compulsory": true
  },
  "evaluation_criteria": "80/20 preference point system will apply...",
  "returnable_documents": [
    "SBD 1 - Invitation to Bid",
    "SBD 4 - Declaration of Interest",
    "Tax Clearance Certificate"
  ],
  "confidence": 0.87,
  "pages_used": [0, 1, 2, 3],
  "full_text": "DEPARTMENT OF PUBLIC WORKS...",
  "raw_text_preview": "DEPARTMENT OF PUBLIC WORKS..."
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
| `confidence` | `float` | Extraction confidence (0.0–1.0) |
| `pages_used` | `list[int]` | 0-indexed pages analyzed |
| `raw_text_preview` | `string` | First 500 chars of extracted text |
| `full_text` | `string` | Complete extracted text (up to 50KB) |

### Error Codes

| Status | Code | Description |
|--------|------|-------------|
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Not a PDF file (wrong Content-Type or magic bytes) |
| 422 | `UNPROCESSABLE_ENTITY` | Validation error — file too large, invalid URL, URL fetch failure |
| 501 | `NOT_IMPLEMENTED` | Scanned/image-only PDF detected (OCR not supported) |
| 504 | `GATEWAY_TIMEOUT` | URL fetch timed out (configurable, default 90s) |
| 500 | `INTERNAL_ERROR` | Unexpected extraction failure |
| 503 | `SERVICE_UNAVAILABLE` | Extractor not yet initialized |

---

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `MAX_FILE_SIZE_BYTES` | `104857600` (100MB) | Maximum PDF file size |
| `MAX_PAGES` | `30` | Maximum pages to analyze |
| `URL_FETCH_TIMEOUT_SECONDS` | `90.0` | Timeout for URL fetching |
| `URL_FETCH_MAX_REDIRECTS` | `5` | Maximum redirects to follow |
| `ALLOWED_URL_HOSTS` | `etenders-api.tenders-sa.org, docs.tenders-sa.org, www.etenders.gov.za, etenders.gov.za` | Comma-separated trusted document URL hosts |
| `GUNICORN_WORKERS` | `2` | Gunicorn worker processes |
| `GUNICORN_TIMEOUT` | `120` | Gunicorn worker timeout (seconds) |
| `LOG_LEVEL` | `info` | Logging level |
| `PORT` | `8080` | HTTP port (Cloud Run default) |

---

## Deployment

### Cloud Run (Google)

```bash
# Build and push
gcloud builds submit --tag gcr.io/YOUR_PROJECT/tender-extract

# Deploy
gcloud run deploy tender-extract \
  --image gcr.io/YOUR_PROJECT/tender-extract \
  --platform managed \
  --memory 512Mi \
  --timeout 180
```

### Render.com

```bash
render blueprints apply
```

Uses the included `render.yaml` blueprint definition.

### Fly.io

```bash
fly launch
fly deploy
```

Uses the included `fly.toml` configuration.

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
│   ├── __init__.py        # Package info
│   ├── main.py            # FastAPI app, routes, lifespan
│   ├── extractor.py       # Core extraction logic (1495 lines)
│   └── schemas.py         # Pydantic models for request/response
├── docs/
│   ├── API_REFERENCE.md   # Detailed API reference
│   ├── INTEGRATION_GUIDE.md # Ingestion pipeline integration docs
│   └── openapi.json       # OpenAPI 3.0 specification
├── tests/
│   └── fixtures/          # Sample PDFs for testing
├── Dockerfile             # Multi-stage build for Cloud Run
├── render.yaml            # Render.com blueprint
├── fly.toml               # Fly.io configuration
├── gunicorn.conf.py       # Gunicorn server config
├── requirements.txt       # Python dependencies
└── README.md
```

---

## Development

### Type Checking

```bash
pip install mypy
mypy --python-version 3.13 app/
```

### Testing

```bash
pip install pytest pytest-asyncio
pytest tests/
```

### Design Principles

1. **No AI in the extraction path** — This service uses deterministic regex matching only. AI enrichment is a separate concern handled by the main application when confidence is low (`confidence < 0.55` or missing critical fields)
2. **SA-specific patterns** — All regex patterns are designed and tuned for South African government tender formats, including CIDB grading, B-BBEE scoring, MBD/SBD returnable forms, and SA procurement language
3. **Fast and stateless** — Designed for horizontal scaling. Each request is independent with no shared state
4. **Graceful degradation** — Always returns a result, even for poorly formatted PDFs. Low-confidence results signal the main app to run AI fallback

---

## Links

- [Tenders-SA Platform](https://www.tenders-sa.org) — Main website
- [Developer Portal](https://tenders-sa.org/developers) — API keys, docs, and pricing
- [GitHub](https://github.com/Tenders-SA/tender-extract) — Source code & issues
- [Support](mailto:support@tenders-sa.org) — Email support

---

## License

MIT
