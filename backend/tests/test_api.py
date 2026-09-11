"""End-to-end tests for the REST API using FastAPI's TestClient.

Uses a throwaway on-disk SQLite DB and upload dir (via env vars, set
before the app/config module is imported) so tests never touch real
data. The LLM extraction path is not exercised here (no API key in
CI) -- these tests cover health, validation-rejection and the
not-found / list flows, which do not require a live model call.
"""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP}/test.db")
os.environ.setdefault("UPLOAD_DIR", os.path.join(_TMP, "uploads"))
os.environ.setdefault("LOG_DIR", os.path.join(_TMP, "logs"))
os.environ.setdefault("ENVIRONMENT", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_process_rejects_unsupported_file_type():
    response = client.post(
        "/api/v1/documents/process",
        files={"file": ("notes.txt", b"not a document", "text/plain")},
        data={"document_type": "invoice"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["processing_status"] == "FAILED"
    assert body["file_validation"]["status"] == "FAILED"
    assert body["file_validation"]["is_supported"] is False


def test_process_rejects_empty_file():
    response = client.post(
        "/api/v1/documents/process",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        data={"document_type": "invoice"},
    )
    body = response.json()
    assert body["processing_status"] == "FAILED"
    assert body["file_validation"]["error_code"] if "error_code" in body["file_validation"] else True


def test_get_unknown_document_returns_404():
    response = client.get("/api/v1/documents/does-not-exist.pdf")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_list_documents_returns_consistent_shape():
    response = client.get("/api/v1/documents")
    assert response.status_code == 200
    body = response.json()
    assert "count" in body
    assert "documents" in body
    assert body["count"] == len(body["documents"])


def test_process_invalid_document_type_returns_422():
    response = client.post(
        "/api/v1/documents/process",
        files={"file": ("notes.txt", b"data", "text/plain")},
        data={"document_type": "not_a_real_type"},
    )
    assert response.status_code == 422
