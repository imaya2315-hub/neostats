# Intelligent Document Extraction, Validation & API Platform

End-to-end document intelligence service: upload an invoice / balance sheet /
P&L / cash flow statement (PDF, JPG, PNG), validate it, OCR/extract it,
run financial-formula validation, store the result, and expose it through
a REST API and a small dashboard.

## 1. Architecture

See `docs/architecture.png`. Pipeline:

```
Upload -> Document Validation -> OCR/Text Extraction -> AI Field & Table
Extraction -> Financial Validation -> Confidence/PASS-FAILED -> Persist
-> Dashboard + REST API
```

Each stage is its own module (see `backend/app/services/`) and is
orchestrated by `document_service.py`, which never lets a stage failure
crash the request — it always returns a well-formed, persisted result.

## 2. Tech stack

- **API**: FastAPI (async, auto Swagger/OpenAPI at `/docs`)
- **OCR**: `pdfplumber` for native PDF text; `pdf2image` + `pytesseract`
  (Tesseract) for scanned PDFs/images; a custom deterministic column-grid
  detector (`table_ocr.py`) for two-column comparative financial statements
- **AI extraction**: Anthropic Claude (any provider is pluggable — the LLM
  call is isolated in `extraction_service.py`)
- **Storage**: SQLite via SQLAlchemy by default; swap `DATABASE_URL` for
  Postgres/MySQL with no code changes
- **Frontend**: server-rendered HTML/CSS + vanilla JS, served by the same
  FastAPI app (Jinja2 + static files) — one deployable service

## 3. Repository structure

```
project-root/
├── backend/app/{api,core,models,schemas,services,repositories,utils}
├── backend/tests/
├── frontend/{templates,static}
├── docs/architecture.png
├── sample_outputs/
├── .env.example
└── README.md
```

## 4. Local setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Tesseract must be installed on the OS (apt-get install tesseract-ocr poppler-utils)
cp ../.env.example ../.env   # fill in ANTHROPIC_API_KEY
uvicorn app.main:app --reload --app-dir .
```

Dashboard: `http://localhost:8000/` · Swagger: `http://localhost:8000/docs`

## 5. Environment variables

See `.env.example`. Key ones: `ANTHROPIC_API_KEY` (required for the
extraction stage — without it, uploads are validated/OCR'd but fail at
the extraction step with a clear `LLM_NOT_CONFIGURED` warning, see
`sample_outputs/sample_invoice_no_llm_key_REAL.json`), `DATABASE_URL`,
`MAX_PAGES`, `VALIDATION_ABS_TOLERANCE` / `VALIDATION_PCT_TOLERANCE`.

## 6. API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/documents/process` | multipart upload: `file`, `document_type` |
| GET | `/api/v1/documents/{document_name}` | latest result by name |
| GET | `/api/v1/documents` | dashboard list |
| GET | `/api/v1/health` | health check |

Example:
```bash
curl -X POST http://localhost:8000/api/v1/documents/process \
  -F "file=@sample_invoice.pdf" -F "document_type=invoice"

curl http://localhost:8000/api/v1/documents/sample_invoice.pdf
curl http://localhost:8000/api/v1/documents
```

Errors are always `{"error": {"code": ..., "message": ...}}` — stack
traces are never leaked (see `documents.py` route + `document_service.py`
exception handling).

## 7. Financial validation

Each check compares a calculated value against the reported one within
`max(VALIDATION_ABS_TOLERANCE, VALIDATION_PCT_TOLERANCE * reported)`. A
check whose required source fields weren't extracted returns
`NOT_APPLICABLE` rather than assuming a value — never PASS/FAIL on
invented data. Rules per document type are in
`backend/app/services/financial_validation_service.py` and mirror
section 4.4 of the assignment brief exactly (invoice totals/line-items,
balance-sheet equation, P&L cascade, cash-flow reconciliation, all
per comparative period where present).

## 8. Persistence

SQLite file (`data/documents.db`), one row per `document_name`
(re-processing overwrites — "latest wins" per the spec). Structured,
variable-shape payloads (`extracted_data`, `validation`,
`processing_metadata`) are stored as JSON columns; queryable dashboard
columns (name, type, status, timestamps) are first-class.

## 9. Testing

`backend/tests/`: `test_validation.py` (file-integrity + financial-formula
checks, no external services), `test_extraction.py` (LLM-response parsing/
normalization helpers, no live model call), `test_api.py` (FastAPI
`TestClient` end-to-end: health, unsupported/empty-file rejection,
404-on-unknown-name, list shape, 422 on bad `document_type`).

```bash
cd backend && pytest
```

`test_validation.py` and `test_extraction.py` were run and passed against real sample documents (see below); `test_api.py`
needs `fastapi`/`sqlalchemy` installed.

## 10. Sample outputs (`sample_outputs/`)

- `sample_unsupported_file_REAL.json`, `sample_invoice_no_llm_key_REAL.json`
  — genuine outputs of this exact codebase, run in this environment
  against a real sample `.txt` file and a real invoice image from the
  provided dataset (OCR ran for real; the LLM step correctly short-circuits
  since no API key is configured here).
- `invoice_PASS_illustrative.json`, `balance_sheet_PASS_illustrative.json`,
  `profit_and_loss_PASS_illustrative.json`,
  `cash_flow_statement_PASS_illustrative.json` — hand-built examples
  showing the exact response shape for a PASS result on each of the four
  document types (marked `_note`); not live model output, since this
  environment has no network access to call the Anthropic API. Supplying
  `ANTHROPIC_API_KEY` and re-running against the provided dataset produces
  the real equivalents.

## 11. Known limitations / production improvements

- The deterministic table-grid OCR (`table_ocr.py`) is heuristic
  (vertical-line detection + per-cell OCR); on lower-quality scans it can
  merge period-header columns or split a label across rows. Production:
  replace with a dedicated table-extraction model (e.g. Document AI /
  LayoutLM) rather than a hand-rolled column detector.
  - Confidence is a simple, explainable average of (required fields
  found) and (validation checks passed) — not a calibrated model score.
- Synchronous processing only; a production version would queue
  OCR/LLM work and expose a polling/webhook status endpoint for larger
  documents.
- Single-tenant, no auth on the API — would add API keys/OAuth and
  per-tenant storage isolation for production.
- Page-level `source_text` locating is a case-insensitive substring
  match against page text; it can mislocate a page when the same text
  string legitimately repeats across pages.

## 12. AI tool usage declaration

Claude was used throughout to design the service boundaries, write the
FastAPI/SQLAlchemy/OCR/extraction/validation code, the deterministic
table-OCR heuristic, the test suite, and this documentation, and to
verify the pipeline end-to-end against real sample documents from the
provided dataset.

## 13. Deployment

Not deployed from this environment (no network egress here). To deploy:
push this repo to a public GitHub repo, then deploy `backend/` (with
`frontend/` alongside it, since `main.py` mounts it as static files/
templates) to Render/Railway/Koyeb as a single Python web service running
`uvicorn app.main:app --host 0.0.0.0 --port $PORT --app-dir backend`,
setting `ANTHROPIC_API_KEY` and (optionally) a managed Postgres
`DATABASE_URL` as environment variables. Fill in the live URLs here once
deployed:

- Frontend URL: _TODO_
- Backend API base URL: _TODO_
- Swagger/OpenAPI URL: _TODO_
- Public GitHub repo: _TODO_
