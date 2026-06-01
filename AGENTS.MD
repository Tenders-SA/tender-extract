# tender-extract — Agent Instructions

**Path**: `pdf-processor/tender-extract/` | **Repo**: [github.com/Tenders-SA/tender-extract](https://github.com/Tenders-SA/tender-extract)

## What It Is
Python microservice for deterministic text extraction from South African government procurement documents. Supports PDF, DOCX, DOC, XLSX, XLS, PPTX, ODT, RTF, CSV, TXT, and ZIP archives. No AI, no OCR. Returns structured text for downstream AI enrichment.

## Quick Start
```bash
pip install -r requirements.txt
pytest -v                     # run 108+ tests
gunicorn app.main:app -c gunicorn.conf.py  # local dev
# Deploy: docker build -t tender-extract . && docker run -p 8080:8080 tender-extract
```

## Key Files
| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app: `POST /v1/extract`, health probes, URL validation, multi-format routing |
| `app/extractor.py` | Shared data types (ExtractionResult dataclass, etc.) |
| `app/schemas.py` | Pydantic models: request/response types |
| `app/extractors/` | Plugin-based extractor modules (11 formats) |
| `app/extractors/__init__.py` | ExtractorRegistry — extension/MIME/magic byte dispatch |
| `gunicorn.conf.py` | Optimized config (workers=2, timeout=120s) |
| `Dockerfile` | Multi-stage build for deployment |
| `tests/test_extractors.py` | 108 tests: all extractors + registry dispatch |
| `tests/test_url_policy.py` | URL allowlist validation tests |

## API
- `POST /v1/extract` — Receives `{ url: string }`, returns extracted text and structured fields (all formats)
- `GET /health` — Liveness probe
- `GET /ready` — Readiness probe
- `GET /startup` — Startup probe

## Architecture Notes
- **No AI/LLM** — deterministic extraction only. Returns `full_text` and `raw_text_preview` for the main app to do AI enrichment
- **No OCR** — detects scanned/image-only pages but does not perform OCR
- **Plugin architecture**: Each format is a self-contained `BaseExtractor` subclass, registered by extension/MIME/magic bytes
- **Content detection priority**: magic bytes > file extension > MIME type
- **URL allowlist**: enforced via `ALLOWED_URL_HOSTS` env var — trusted hosts only
- **ZIP support**: recursive in-memory extraction with result merging (highest-confidence fields, deduplicated lists)
- **Deployment**: AWS EC2
