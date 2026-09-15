# NeoStats Document Intelligence Platform

NeoStats is an end-to-end document intelligence application for extracting structured information from financial documents and validating financial calculations.

The system accepts invoices, balance sheets, profit and loss statements, and cash flow statements in PDF, JPG, and PNG formats. It validates the uploaded file, performs OCR and text extraction, uses an LLM for structured field extraction, applies deterministic financial validation rules, calculates an overall processing status and confidence score, stores the result, and displays the result through a web dashboard and REST API.

## Live Application

- Frontend: https://neostats-1.onrender.com/
- Backend API and Swagger UI: https://neostats-1.onrender.com/docs
- OpenAPI specification: https://neostats-1.onrender.com/openapi.json
- Health endpoint: https://neostats-1.onrender.com/api/v1/health
- GitHub repository: https://github.com/imaya2315-hub/neostats
- Development approach presentation: https://drive.google.com/drive/u/0/folders/10GXJywvI-5pO9TWwhS8iuPZ6Hr4eUzXb
- Deployment platform: Render

The frontend and backend are deployed as a single FastAPI service. The Swagger page is the interactive API documentation and testing interface.

## Features

### Document processing

- PDF, JPG, and PNG upload support
- File type, readability, size, and page-count validation
- OCR for scanned documents and images
- Native PDF text extraction where available
- Page-level source text tracking
- Structured extraction of document-specific fields
- Line-item extraction for invoices
- Comparative-period extraction for financial statements

### Supported document types

- `invoice`
- `balance_sheet`
- `profit_and_loss`
- `cash_flow_statement`

### Financial validation

The financial validation layer performs deterministic calculations using only values extracted from the document. Missing source values are not invented. When the required values are unavailable, the corresponding check is marked `NOT_APPLICABLE`.

Invoice validation includes:

- Quantity multiplied by unit price checks
- Line-item totals against subtotal or total
- Tax-inclusive and tax-exclusive total handling
- Shipping and discount handling
- Cash paid minus total equals change

Balance sheet validation includes:

- Total assets compared with total liabilities plus equity
- Comparative-period validation when multiple periods are available

Profit and loss validation includes support for both standard and bank-style statements, including:

- Revenue and cost of sales to gross profit
- Gross profit and operating expenses to operating profit
- Operating profit and tax to net profit
- Interest earned and other income to total income for bank-style statements
- Interest expended, operating expenses, and provisions to total expenditure
- Profit before and after minority interest where available
- Appropriation checks where the required values are available

Cash flow validation includes:

- Operating, investing, and financing cash flows to net change in cash
- Foreign exchange translation adjustments when present
- Opening cash plus net change to closing cash
- Additional cash adjustments such as cash acquired on amalgamation when applicable

## Processing pipeline

```text
Upload
  |
  v
Document Validation
  |
  v
OCR / PDF Text Extraction
  |
  v
AI Field and Table Extraction
  |
  v
Normalization
  |
  v
Financial Validation
  |
  v
Confidence and PASS / FAILED Status
  |
  v
Database Persistence
  |
  +------------------+
  |                  |
  v                  v
REST API          Web Dashboard
```

Each major processing stage is separated into its own service or utility module. The main orchestration is handled by `document_service.py`.

## Technology stack

### Backend

- Python 3.11
- FastAPI
- Uvicorn
- Pydantic
- SQLAlchemy
- SQLite by default
- Jinja2

### OCR and document processing

- `pdfplumber` for native PDF text extraction
- `pdf2image` and Poppler for PDF rendering
- `pytesseract` and Tesseract OCR
- RapidOCR runtime support
- `pypdfium2`
- Pillow
- NumPy
- Custom table OCR utilities for structured financial statement tables

### AI extraction

- Groq API
- Configurable Groq model
- Current configured model: `qwen/qwen3.8-27b`

The LLM integration is isolated in `backend/app/services/extraction_service.py`, allowing the extraction layer to be changed without redesigning the rest of the pipeline.

### Frontend

- HTML
- CSS
- Vanilla JavaScript
- Jinja2 templates

The frontend is served directly by the FastAPI application, so no separate frontend deployment is required.

## Repository structure

```text
neostats/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/
│   │   ├── core/
│   │   ├── models/
│   │   ├── repositories/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── utils/
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── templates/
│   └── static/
├── docs/
│   ├── architecture.png
│   └── solution_presentation_outline.md
├── sample_outputs/
├── uploads/
├── data/
├── evaluate_all.py
├── evaluation_report.json
├── render.yaml
├── Dockerfile
├── Document_Intelligence_Development_Approach.pptx
└── README.md
```

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Web dashboard |
| GET | `/documents/{document_name}` | Web page showing a processed document |
| GET | `/api/v1/health` | Service health check |
| POST | `/api/v1/documents/process` | Upload and process a document |
| GET | `/api/v1/documents` | List processed documents |
| GET | `/api/v1/documents/{document_name}` | Retrieve the latest processed result for a document |
| GET | `/docs` | Swagger UI |
| GET | `/openapi.json` | OpenAPI specification |

### Processing request

`POST /api/v1/documents/process` accepts a multipart form request containing:

- `file`: PDF, JPG, or PNG document
- `document_type`: one of the supported document types

Example:

```bash
curl -X POST "https://neostats-1.onrender.com/api/v1/documents/process" \
  -F "file=@sample_invoice.jpg" \
  -F "document_type=invoice"
```

Example response structure:

```json
{
  "document_name": "sample_invoice.jpg",
  "document_type": "invoice",
  "processing_status": "PASS",
  "overall_confidence": 0.88,
  "file_validation": {},
  "extracted_data": {},
  "validation": {},
  "processing_metadata": {}
}
```

## Environment variables

The application reads configuration from environment variables. Important variables include:

| Variable | Purpose |
|---|---|
| `APP_NAME` | Application name |
| `ENVIRONMENT` | Runtime environment |
| `LOG_LEVEL` | Logging level |
| `CORS_ORIGINS` | Allowed CORS origins |
| `UPLOAD_DIR` | Uploaded document directory |
| `MAX_PAGES` | Maximum pages processed per document |
| `MAX_UPLOAD_SIZE_MB` | Maximum upload size |
| `DATABASE_URL` | Database connection URL |
| `GROQ_API_KEY` | Groq API authentication key |
| `GROQ_MODEL` | LLM model used for extraction |
| `LLM_MAX_TOKENS` | Maximum LLM output tokens |
| `LLM_TIMEOUT_SECONDS` | LLM request timeout |
| `VALIDATION_ABS_TOLERANCE` | Absolute financial validation tolerance |
| `VALIDATION_PCT_TOLERANCE` | Percentage financial validation tolerance |

The Groq API key is supplied through the deployment environment and should not be committed to GitHub.

## Financial validation tolerance

A calculated value is considered within tolerance when its absolute difference from the reported value is no greater than the larger of:

```text
VALIDATION_ABS_TOLERANCE

or

VALIDATION_PCT_TOLERANCE × absolute(reported value)
```

The deployed configuration uses:

```text
VALIDATION_ABS_TOLERANCE=1.0
VALIDATION_PCT_TOLERANCE=0.01
```

This allows small rounding differences while still identifying larger reconciliation errors.

## Database and persistence

SQLite is used by default through SQLAlchemy. The default database is stored at:

```text
data/documents.db
```

The database stores the latest processing result for each document name, including:

- Document name and type
- Processing status
- Overall confidence
- File validation result
- Extracted data
- Financial validation result
- Processing metadata
- Processing timestamps

A different SQLAlchemy-compatible database can be configured through `DATABASE_URL`.

## Testing and evaluation

The repository contains automated tests under `backend/tests/` covering validation, extraction helpers, and API behavior.

The repository also contains `evaluate_all.py` and `evaluation_report.json` for evaluation against the provided document dataset.

The recorded evaluation in `evaluation_report.json` contains 50 documents:

| Document type | Documents | Passed | Failed | Pass rate |
|---|---:|---:|---:|---:|
| Balance sheet | 10 | 10 | 0 | 100% |
| Cash flow statement | 10 | 9 | 1 | 90% |
| Invoice | 20 | 18 | 2 | 90% |
| Profit and loss | 10 | 10 | 0 | 100% |
| Total | 50 | 47 | 3 | 94% |

Recorded average confidence: `0.8981`

Recorded average processing time: approximately `54.99 seconds` per document.

Financial validation checks in the recorded evaluation:

- PASS: 155
- FAIL: 5
- NOT_APPLICABLE: 42

The evaluation report is included in the repository so the evaluator can inspect the recorded results without having to reproduce the entire evaluation locally.

To run the automated test suite locally:

```bash
cd backend
pytest
```

To run the evaluation script:

```bash
python evaluate_all.py
```

The evaluation requires the configured application dependencies and an available Groq API key for live LLM extraction.

## Local installation

### Requirements

- Python 3.11
- Tesseract OCR
- Poppler utilities for PDF rendering

### Setup

```bash
git clone https://github.com/imaya2315-hub/neostats.git
cd neostats
python -m venv .venv
```

Activate the virtual environment.

Windows:

```bash
.venv\Scripts\activate
```

Linux or macOS:

```bash
source .venv/bin/activate
```

Install Python dependencies:

```bash
pip install -r backend/requirements.txt
```

Configure the required environment variables, especially `GROQ_API_KEY`.

Start the application from the project root:

```bash
uvicorn app.main:app --reload --app-dir backend
```

The local application will be available at:

```text
http://localhost:8000/
```

Swagger UI:

```text
http://localhost:8000/docs
```

## Docker and Render deployment

The repository includes a `Dockerfile` and `render.yaml`.

The Render service is configured as a Python web service with:

```text
Build command:
pip install -r backend/requirements.txt

Start command:
uvicorn app.main:app --host 0.0.0.0 --port $PORT --app-dir backend
```

The application binds to Render's `$PORT` environment variable and listens on `0.0.0.0`, allowing the deployed service to receive external traffic.

The deployment uses the `main` branch with automatic deployment enabled.

## Error handling

API errors use a consistent structure:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message"
  }
}
```

Internal stack traces are logged by the server but are not returned to API clients.

## Confidence and processing status

The application reports an overall confidence score together with the processing status.

The processing status represents the outcome of the validation pipeline:

- `PASS`: the document passed the applicable validation checks
- `FAILED`: one or more applicable financial validation checks failed

Individual financial validation checks can have one of three states:

- `PASS`: the calculated value is within tolerance of the reported value
- `FAIL`: the calculated value is outside the configured tolerance
- `NOT_APPLICABLE`: a required source value was not available for deterministic validation

This distinction prevents missing information from automatically being treated as a successful validation.

## Source traceability

Extracted fields can include:

- `value`
- `source_text`
- `page_number`

This provides a link between structured extraction results and the OCR or PDF text from which the value was extracted.

## Known limitations

- OCR quality depends on the quality and layout of the source document.
- Table detection uses deterministic heuristics and can be affected by complex or low-quality table layouts.
- LLM extraction depends on the availability and quality of the configured Groq model.
- The current application is synchronous, so large documents can take longer to process.
- The default deployment is intended as an evaluation application and does not include production authentication or multi-tenant access control.
- SQLite is suitable for the current deployment model but a managed database is preferable for a larger production workload.
- Confidence is an application-level score and should not be interpreted as a calibrated probability.

## Development approach

The project separates document processing into validation, OCR, extraction, normalization, financial validation, persistence, and presentation layers. Deterministic calculations are kept separate from LLM extraction so that financial reconciliation does not depend solely on generated model output.

The repository includes the development approach presentation at:

https://drive.google.com/drive/u/0/folders/10GXJywvI-5pO9TWwhS8iuPZ6Hr4eUzXb

## Project links

- Live application: https://neostats-1.onrender.com/
- API documentation: https://neostats-1.onrender.com/docs
- GitHub: https://github.com/imaya2315-hub/neostats
- Development approach presentation: https://drive.google.com/drive/u/0/folders/10GXJywvI-5pO9TWwhS8iuPZ6Hr4eUzXb
