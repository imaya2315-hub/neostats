# Solution Presentation — Outline (turn into PPT)

A `solution_presentation.pdf`/pptx is a mandatory deliverable. This is a
ready-to-fill outline; the diagram in `architecture.png` can be dropped
in directly.

1. **Problem & objective** — one slide restating section 1 of the brief.
2. **Architecture** — `architecture.png`.
3. **Pipeline walkthrough** — validation → OCR → extraction → financial
   validation → persistence → API/dashboard, one line each.
4. **Tech stack & why** — FastAPI, SQLAlchemy/SQLite, Tesseract/pdfplumber,
   Anthropic Claude, plain HTML/JS frontend — one reason each (see README §2).
5. **Sample result walkthrough** — screenshot of the dashboard + one
   `sample_outputs/*.json` shown side by side.
6. **Financial validation logic** — one example formula + PASS/FAIL/
   NOT_APPLICABLE definition.
7. **Testing & reliability** — test suite summary, graceful-failure design.
8. **Known limitations & what's next for production** — README §11.
9. **Deployment** — live URLs (fill in after deploying).
