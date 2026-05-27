# tender-extract — Agent Instructions

**Path**: `pdf-processor/tender-extract/` | **Repo**: [github.com/Tenders-SA/tender-extract](https://github.com/Tenders-SA/tender-extract)

## What It Is
Python microservice for deterministic PDF text extraction from tender documents. No AI, no OCR. Receives PDF URLs, returns structured text for downstream AI enrichment.

## Quick Start
```bash
pip install -r requirements.txt
pytest                        # run URL policy tests
gunicorn app.main:app -c gunicorn.conf.py  # local dev
# Deploy: docker build -t tender-extract . && docker run -p 8080:8080 tender-extract
```

## Key Files
| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app (345 lines): `POST /v1/extract`, health probes, URL validation |
| `app/extractor.py` | Core extractor (1495 lines): SA-specific regex patterns |
| `app/schemas.py` | Pydantic models (178 lines): request/response types |
| `gunicorn.conf.py` | Optimized config (workers=2, timeout=120s) |
| `Dockerfile` | Multi-stage build for Cloud Run |
| `fly.toml` | Fly.io config (Frankfurt, 512MB) |
| `render.yaml` | Render deployment config |
| `tests/test_url_policy.py` | URL allowlist tests |

## API
- `POST /v1/extract` — Receives `{ url: string }`, returns extracted text and structured fields
- `GET /health` — Liveness probe
- `GET /ready` — Readiness probe
- `GET /startup` — Startup probe

## Architecture Notes
- **No AI/LLM** — deterministic extraction only. Returns `full_text` and `raw_text_preview` for the main app to do AI enrichment
- **No OCR** — detects scanned/image-only pages but does not perform OCR
- **URL allowlist**: PDF fetching restricted to `etenders-api.tenders-sa.org`, `docs.tenders-sa.org`, `www.etenders.gov.za`, `etenders.gov.za`, and `*.r2.cloudflarestorage.com`
- **PDF validation**: magic byte detection (`%PDF` header sniffing)
- **Deployment targets**: Cloud Run (primary), Fly.io, Render
- **Worker monitoring**: psutil in gunicorn hooks for crash diagnostics
