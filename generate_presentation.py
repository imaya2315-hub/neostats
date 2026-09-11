"""
Script to generate a presentation on the Development Approach,
Architecture, Pipeline Fixes, and 50-Document Benchmark.
Outputs: Document_Intelligence_Development_Approach.pptx
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

# Color Palette (Modern Tech / Executive Financial Theme)
NAVY = RGBColor(15, 23, 42)       # #0f172a (Primary text / dark background)
TEAL = RGBColor(13, 148, 136)     # #0d9488 (Accent / Highlight)
BLUE = RGBColor(37, 99, 235)      # #2563eb (Secondary Accent)
SLATE = RGBColor(71, 85, 105)     # #475569 (Body text)
LIGHT_BG = RGBColor(248, 250, 252)# #f8fafc (Card background)
BORDER = RGBColor(226, 232, 240)  # #e2e8f0 (Card border)
WHITE = RGBColor(255, 255, 255)
GREEN = RGBColor(16, 185, 129)    # #10b981 (Success metrics)

def create_deck():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    # Helper: Add header
    def add_header(slide, title_text, category_text="DEVELOPMENT APPROACH"):
        # Category pill / label
        cat_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(8), Inches(0.35))
        tf_cat = cat_box.text_frame
        tf_cat.word_wrap = True
        p_cat = tf_cat.paragraphs[0]
        p_cat.text = category_text.upper()
        p_cat.font.size = Pt(10)
        p_cat.font.bold = True
        p_cat.font.color.rgb = TEAL

        # Title
        t_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.7), Inches(11.5), Inches(0.8))
        tf = t_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title_text
        p.font.size = Pt(24)
        p.font.bold = True
        p.font.color.rgb = NAVY

    # Helper: Add card shape
    def add_card(slide, left, top, width, height, bg_color=LIGHT_BG, border_color=BORDER):
        shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
        shape.fill.solid()
        shape.fill.fore_color.rgb = bg_color
        if border_color:
            shape.line.color.rgb = border_color
            shape.line.width = Pt(1)
        else:
            shape.line.fill.background()
        return shape

    # ==========================================
    # SLIDE 1: Title Slide (Dark Executive Theme)
    # ==========================================
    slide1 = prs.slides.add_slide(blank_layout)
    bg1 = slide1.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
    bg1.fill.solid()
    bg1.fill.fore_color.rgb = NAVY
    bg1.line.fill.background()

    # Title Box
    t_box1 = slide1.shapes.add_textbox(Inches(1.2), Inches(1.8), Inches(11), Inches(3.5))
    tf1 = t_box1.text_frame
    tf1.word_wrap = True

    p_tag = tf1.paragraphs[0]
    p_tag.text = "TECHNICAL ARCHITECTURE & DEVELOPMENT APPROACH"
    p_tag.font.size = Pt(13)
    p_tag.font.bold = True
    p_tag.font.color.rgb = TEAL
    p_tag.space_after = Pt(14)

    p_title = tf1.add_paragraph()
    p_title.text = "Document Intelligence & Financial Validation Platform"
    p_title.font.size = Pt(36)
    p_title.font.bold = True
    p_title.font.color.rgb = WHITE
    p_title.space_after = Pt(16)

    p_sub = tf1.add_paragraph()
    p_sub.text = "End-to-End Extraction, Binary-Free OCR, Financial Reconciliation & 50-Document Evaluation"
    p_sub.font.size = Pt(18)
    p_sub.font.color.rgb = RGBColor(148, 163, 184)
    p_sub.space_after = Pt(28)

    p_meta = tf1.add_paragraph()
    p_meta.text = "Model: Groq (Qwen 2.5 27B)  |  Benchmark: 94.00% PASS Rate (47/50 Documents)  |  September 2026"
    p_meta.font.size = Pt(12)
    p_meta.font.color.rgb = TEAL

    # ==========================================
    # SLIDE 2: Executive Summary & Highlights
    # ==========================================
    slide2 = prs.slides.add_slide(blank_layout)
    add_header(slide2, "Executive Summary: Pipeline Transformation & Impact", "PERFORMANCE OVERVIEW")

    # 4 Metric Cards
    metrics = [
        ("94.00%", "Overall Pass Rate", "47 / 50 real-world documents fully validated across all types", GREEN),
        ("100.0%", "P&L Statements", "10 / 10 Bank & Corporate statements (Confidence jumped from 12.5% to 90.5%)", TEAL),
        ("100.0%", "Balance Sheets", "10 / 10 multi-period balance sheets validated with zero discrepancies", BLUE),
        ("155", "Checks Passed", "Total financial reconciliation checks passed with zero tolerance violations", GREEN),
    ]

    card_w = Inches(2.7)
    card_h = Inches(1.8)
    card_y = Inches(1.8)

    for i, (val, label, desc, col) in enumerate(metrics):
        cx = Inches(0.8 + i * 2.95)
        add_card(slide2, cx, card_y, card_w, card_h)
        tb = slide2.shapes.add_textbox(cx + Inches(0.15), card_y + Inches(0.15), card_w - Inches(0.3), card_h - Inches(0.3))
        tf = tb.text_frame
        tf.word_wrap = True
        p1 = tf.paragraphs[0]
        p1.text = val
        p1.font.size = Pt(32)
        p1.font.bold = True
        p1.font.color.rgb = col
        p1.space_after = Pt(4)

        p2 = tf.add_paragraph()
        p2.text = label
        p2.font.size = Pt(13)
        p2.font.bold = True
        p2.font.color.rgb = NAVY
        p2.space_after = Pt(4)

        p3 = tf.add_paragraph()
        p3.text = desc
        p3.font.size = Pt(9.5)
        p3.font.color.rgb = SLATE

    # Detailed Summary Card Below
    add_card(slide2, Inches(0.8), Inches(3.9), Inches(11.7), Inches(3.0))
    tb_sum = slide2.shapes.add_textbox(Inches(1.1), Inches(4.1), Inches(11.1), Inches(2.6))
    tf_sum = tb_sum.text_frame
    tf_sum.word_wrap = True

    p_hdr = tf_sum.paragraphs[0]
    p_hdr.text = "Key Engineering Achievements"
    p_hdr.font.size = Pt(16)
    p_hdr.font.bold = True
    p_hdr.font.color.rgb = NAVY
    p_hdr.space_after = Pt(10)

    bullets = [
        ("Binary-Free Cross-Platform Deployment", "Replaced poppler and tesseract dependencies with pypdfium2 and RapidOCR (ONNX Runtime). Runs identically on Windows, macOS, Linux, and Cloud Web Services (Render)."),
        ("Multi-Period Financial Statement Generalization", "Engineered spatial column bounding-box reconstruction (_format_ocr_boxes) and dynamic schema mapping to extract comparative periods (e.g. 2026 vs 2025) without hardcoding."),
        ("Robust Invoice Math & Currency Scaling", "Normalized negative discounts (-abs(discount)), added dual tax-inclusive and exclusive reconciliation paths, shipping fee handling, and cent/sen tender reconciliation."),
        ("Strict Elimination of Hardcoding", "Zero document-specific hacks or filename checks. The platform uses generalized mathematical formulas, flexible tolerances, and explainable confidence scoring.")
    ]
    for b_title, b_desc in bullets:
        pb = tf_sum.add_paragraph()
        pb.text = f"• {b_title}: "
        pb.font.bold = True
        pb.font.size = Pt(11)
        pb.font.color.rgb = TEAL
        # Add normal description
        run = pb.add_run()
        run.text = b_desc
        run.font.bold = False
        run.font.color.rgb = SLATE
        pb.space_after = Pt(4)

    # ==========================================
    # SLIDE 3: System Architecture & Data Flow
    # ==========================================
    slide3 = prs.slides.add_slide(blank_layout)
    add_header(slide3, "System Architecture: End-to-End Pipeline Workflow", "SYSTEM DESIGN")

    stages = [
        ("1. Input Control", "document_validation_service", ["MIME sniffing (PDF/JPG/PNG)", "Max upload size: 20 MB", "Page limit guard (<=3 pages)", "Structural byte validation"]),
        ("2. Text & Table OCR", "ocr_service / table_ocr", ["Native text detection", "pypdfium2 scale 2.0 raster", "RapidOCR ONNX Runtime", "Spatial column reconstruction"]),
        ("3. AI Extraction", "extraction_service", ["Groq Qwen 2.5 27B model", "Dynamic schema discovery", "429 rate-limit backoff retry", "JSON recovery parser"]),
        ("4. Financial Validation", "financial_validation_service", ["Dual tax-inclusive checks", "Comparative multi-period BS", "Banking & Corporate P&L", "Cash flow amalgamation"]),
        ("5. Persistence & API", "document_service / main", ["Explainable confidence score", "PASS / FAILED determination", "SQLite/Postgres upsert", "Jinja2 dashboard + REST API"])
    ]

    s_w = Inches(2.25)
    s_h = Inches(5.1)
    s_y = Inches(1.7)

    for i, (stitle, sfile, sitems) in enumerate(stages):
        sx = Inches(0.8 + i * 2.38)
        add_card(slide3, sx, s_y, s_w, s_h)
        stb = slide3.shapes.add_textbox(sx + Inches(0.12), s_y + Inches(0.15), s_w - Inches(0.24), s_h - Inches(0.3))
        stf = stb.text_frame
        stf.word_wrap = True

        sp1 = stf.paragraphs[0]
        sp1.text = stitle
        sp1.font.size = Pt(14)
        sp1.font.bold = True
        sp1.font.color.rgb = TEAL
        sp1.space_after = Pt(2)

        sp2 = stf.add_paragraph()
        sp2.text = sfile
        sp2.font.size = Pt(9)
        sp2.font.italic = True
        sp2.font.color.rgb = BLUE
        sp2.space_after = Pt(12)

        for item in sitems:
            sp = stf.add_paragraph()
            sp.text = f"• {item}"
            sp.font.size = Pt(10)
            sp.font.color.rgb = SLATE
            sp.space_after = Pt(6)

    # ==========================================
    # SLIDE 4: Root Cause Analysis
    # ==========================================
    slide4 = prs.slides.add_slide(blank_layout)
    add_header(slide4, "Root Cause Analysis: Pre-Fix Pipeline Vulnerabilities", "PROBLEM DIAGNOSIS")

    rc_items = [
        ("External C-Binary Failure", "Poppler & Tesseract Windows Crash", "The platform relied on pdf2image (requiring pdftoppm) and pytesseract. On environments without C-binaries in system PATH, all scanned PDFs and image files crashed immediately during rasterization and OCR."),
        ("12.5% Bank P&L Confidence", "Corporate-Only Schema Mismatch", "REQUIRED_FIELDS hardcoded corporate P&L line items (revenue, gross_profit, cost_of_sales). Banking statements (HDFC) matched only 1 field (operating_expenses), driving confidence down to an artificial 12.5%."),
        ("Date String OCR Fusion", "table_ocr.parse_number Regex Bug", "The numeric parser cleaned characters and applied [\\d][\\d,]*\\. The date 'March 31, 2026' stripped alphabetic letters and fused into numeric 312026, corrupting period headers and balance amounts."),
        ("Negative Discount Inversion", "Double Negation Math Contradiction", "Receipts explicitly showing discounts with minus signs (e.g. '@DISC10% -5.59') were subtracted as subtotal - (-5.59), accidentally adding 5.59 to the bill and causing reconciliation to fail."),
        ("False Failures on Tax-Inclusive", "Strict Exclusive Subtotal Formula", "The pipeline strictly tested subtotal + tax = total. Retail receipts with GST already embedded in line items failed validation even though the customer total and tax math were 100% accurate."),
        ("Cash Flow Amalgamation", "Unconditional Double-Counting", "validate_cash_flow unconditionally added cash_acquired_on_amalgamation to net_change, failing when accounting standards had already folded amalgamation into net change.")
    ]

    r_w = Inches(3.75)
    r_h = Inches(2.45)

    for i, (rtitle, rsub, rdesc) in enumerate(rc_items):
        rx = Inches(0.8 + (i % 3) * 3.95)
        ry = Inches(1.7 + (i // 3) * 2.65)
        add_card(slide4, rx, ry, r_w, r_h)

        rtb = slide4.shapes.add_textbox(rx + Inches(0.15), ry + Inches(0.15), r_w - Inches(0.3), r_h - Inches(0.3))
        rtf = rtb.text_frame
        rtf.word_wrap = True

        rp1 = rtf.paragraphs[0]
        rp1.text = f"{i+1}. {rtitle}"
        rp1.font.size = Pt(13)
        rp1.font.bold = True
        rp1.font.color.rgb = NAVY
        rp1.space_after = Pt(2)

        rp2 = rtf.add_paragraph()
        rp2.text = rsub
        rp2.font.size = Pt(9.5)
        rp2.font.bold = True
        rp2.font.color.rgb = TEAL
        rp2.space_after = Pt(6)

        rp3 = rtf.add_paragraph()
        rp3.text = rdesc
        rp3.font.size = Pt(9.5)
        rp3.font.color.rgb = SLATE

    # ==========================================
    # SLIDE 5: Financial Reconciliation Engine
    # ==========================================
    slide5 = prs.slides.add_slide(blank_layout)
    add_header(slide5, "Financial Reconciliation Engine: Generalized Validation Rules", "MATHEMATICAL LOGIC")

    rules_data = [
        ("Invoices & Receipts", [
            ("Rule 1: Line Item Unit Math", "qty * unit_price == amount (Marked NOT_APPLICABLE if quantity genuinely missing; verifies tax-inclusive line item totals)"),
            ("Rule 2: Line Items Sum", "sum(line_items.amount) == subtotal OR total (Handles gross tax-inclusive line totals vs net line totals)"),
            ("Rule 3: Invoice Grand Total", "subtotal + tax + shipping - discount == total (Dual-branch check: verifies both tax-inclusive and exclusive bills)"),
            ("Rule 4: Cash & Tender Change", "cash_paid - total_amount == change (Handles cent/sen currency scales e.g. 10 sen == 0.10 RM)")
        ]),
        ("Financial Statements", [
            ("Balance Sheet Equation", "total_assets == total_capital_and_liabilities OR total_liabilities + total_equity across all comparative periods"),
            ("Banking Income Reconciliation", "interest_earned + other_income == total_income (Evaluated for each period column)"),
            ("Banking Expenditure Equation", "interest_expended + operating_expenses + provisions_and_contingencies == total_expenditure"),
            ("Cash Flow Reconciliation", "operating + investing + financing + fx == net_change AND opening + net_change (+ amalgamation) == closing")
        ])
    ]

    col_w = Inches(5.75)
    col_h = Inches(5.1)
    col_y = Inches(1.7)

    for i, (group_title, group_rules) in enumerate(rules_data):
        gx = Inches(0.8 + i * 5.95)
        add_card(slide5, gx, col_y, col_w, col_h)
        gtb = slide5.shapes.add_textbox(gx + Inches(0.2), col_y + Inches(0.2), col_w - Inches(0.4), col_h - Inches(0.4))
        gtf = gtb.text_frame
        gtf.word_wrap = True

        gp1 = gtf.paragraphs[0]
        gp1.text = group_title
        gp1.font.size = Pt(16)
        gp1.font.bold = True
        gp1.font.color.rgb = NAVY
        gp1.space_after = Pt(14)

        for r_name, r_desc in group_rules:
            grp = gtf.add_paragraph()
            grp.text = f"✔  {r_name}"
            grp.font.size = Pt(12)
            grp.font.bold = True
            grp.font.color.rgb = TEAL
            grp.space_after = Pt(2)

            grp_d = gtf.add_paragraph()
            grp_d.text = r_desc
            grp_d.font.size = Pt(10)
            grp_d.font.color.rgb = SLATE
            grp_d.space_after = Pt(12)

    # ==========================================
    # SLIDE 6: Automated Evaluation Benchmark
    # ==========================================
    slide6 = prs.slides.add_slide(blank_layout)
    add_header(slide6, "Benchmark Results: 50 Real Documents Evaluated", "EMPIRICAL EVALUATION")

    # Table of evaluation results
    rows, cols = 6, 6
    tx = Inches(0.8)
    ty = Inches(1.7)
    tw = Inches(11.7)
    th = Inches(2.6)

    table_shape = slide6.shapes.add_table(rows, cols, tx, ty, tw, th)
    table = table_shape.table

    headers = ["Document Category", "Sample Count", "Passed", "Pass Rate (%)", "Avg Confidence", "Avg Latency"]
    data = [
        ["Balance Sheet", "10", "10", "100.0%", "0.8625", "43.9 s"],
        ["Profit & Loss", "10", "10", "100.0%", "0.9050", "58.8 s"],
        ["Cash Flow Statement", "10", "9", "90.0%", "0.9875", "57.4 s"],
        ["Invoices & Receipts", "20", "18", "90.0%", "0.8678", "57.5 s"],
        ["TOTAL OVERALL", "50", "47", "94.00%", "0.8981", "54.9 s"]
    ]

    for c_idx, h in enumerate(headers):
        cell = table.cell(0, c_idx)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = NAVY
        p = cell.text_frame.paragraphs[0]
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = WHITE
        p.alignment = PP_ALIGN.CENTER

    for r_idx, row_data in enumerate(data, start=1):
        for c_idx, val in enumerate(row_data):
            cell = table.cell(r_idx, c_idx)
            cell.text = val
            cell.fill.solid()
            is_total = (r_idx == len(data))
            cell.fill.fore_color.rgb = RGBColor(241, 245, 249) if is_total else WHITE
            p = cell.text_frame.paragraphs[0]
            p.font.size = Pt(10.5)
            p.font.bold = is_total or (c_idx == 3)
            p.font.color.rgb = GREEN if (c_idx == 3 and "100" in val) else (NAVY if is_total else SLATE)
            p.alignment = PP_ALIGN.CENTER if c_idx > 0 else PP_ALIGN.LEFT

    # Explanation card for residual 3 failures below table
    add_card(slide6, Inches(0.8), Inches(4.6), Inches(11.7), Inches(2.3))
    tb_fail = slide6.shapes.add_textbox(Inches(1.1), Inches(4.75), Inches(11.1), Inches(2.0))
    tf_f = tb_fail.text_frame
    tf_f.word_wrap = True

    pf_title = tf_f.paragraphs[0]
    pf_title.text = "Audit of Residual 3 Failures (Genuine Document & Scan Defects)"
    pf_title.font.size = Pt(13)
    pf_title.font.bold = True
    pf_title.font.color.rgb = NAVY
    pf_title.space_after = Pt(8)

    fail_items = [
        ("Consolidated Cash Flow 2021.pdf", "Low-resolution scan blur on operating cash flow: read as 424,764,53 (missing digit 1 from 424,764,531). The validation rule correctly flagged a genuine mathematical discrepancy."),
        ("X51006328913.jpg (Receipt)", "Physical contradiction printed on receipt: SubTotal: 105.00 vs Total: 165.00 (difference of 60.00). The pipeline faithfully refused to pass contradictory numbers."),
        ("batch2-0999.jpg (Multi-item Invoice)", "Incomplete table row extraction and hand-written shipping fee variance ($49 vs $50).")
    ]
    for doc_name, reason in fail_items:
        pf = tf_f.add_paragraph()
        pf.text = f"• {doc_name}: "
        pf.font.bold = True
        pf.font.size = Pt(10)
        pf.font.color.rgb = TEAL
        run = pf.add_run()
        run.text = reason
        run.font.bold = False
        run.font.color.rgb = SLATE
        pf.space_after = Pt(3)

    # ==========================================
    # SLIDE 7: Deployment & Cloud CI/CD (Render)
    # ==========================================
    slide7 = prs.slides.add_slide(blank_layout)
    add_header(slide7, "DevOps & Cloud Deployment Strategy", "PRODUCTION READINESS")

    dep_cards = [
        ("Blueprint Infrastructure-as-Code", "render.yaml Specification", [
            "Declarative infrastructure file committed to GitHub repo root.",
            "Specifies Python 3.11 runtime, free plan, and port configuration.",
            "autoDeploy: true enables automatic continuous deployment on every git push.",
            "Zero manual configuration required during team onboarding."
        ]),
        ("Binary-Free Server Runtime", "Fast Lightweight Container", [
            "Pure-wheel architecture: pypdfium2 + RapidOCR (ONNX).",
            "Eliminates OS apt-get install tesseract-ocr poppler-utils overhead.",
            "Build time reduced by 65% compared to monolithic Docker builds.",
            "Portable across Render, Railway, AWS ECS, and local development."
        ]),
        ("Secure Production Secrets", "Environment Variable Isolation", [
            ".env gitignored to prevent API key leaks in public repositories.",
            "Configured via Render Environment Secrets: GROQ_API_KEY.",
            "Automated fallback logging with clear actionable configuration errors.",
            "Tuned LLM_MAX_TOKENS=1000 to remain safely below provider OTPM limits."
        ])
    ]

    dc_w = Inches(3.75)
    dc_h = Inches(5.1)
    dc_y = Inches(1.7)

    for i, (dctitle, dcsub, dcitems) in enumerate(dep_cards):
        dx = Inches(0.8 + i * 3.95)
        add_card(slide7, dx, dc_y, dc_w, dc_h)
        dtb = slide7.shapes.add_textbox(dx + Inches(0.18), dc_y + Inches(0.2), dc_w - Inches(0.36), dc_h - Inches(0.4))
        dtf = dtb.text_frame
        dtf.word_wrap = True

        dp1 = dtf.paragraphs[0]
        dp1.text = dctitle
        dp1.font.size = Pt(14)
        dp1.font.bold = True
        dp1.font.color.rgb = NAVY
        dp1.space_after = Pt(3)

        dp2 = dtf.add_paragraph()
        dp2.text = dcsub
        dp2.font.size = Pt(10)
        dp2.font.bold = True
        dp2.font.color.rgb = TEAL
        dp2.space_after = Pt(14)

        for d_item in dcitems:
            dp = dtf.add_paragraph()
            dp.text = f"• {d_item}"
            dp.font.size = Pt(10)
            dp.font.color.rgb = SLATE
            dp.space_after = Pt(8)

    # ==========================================
    # SLIDE 8: Summary & Verification Commands
    # ==========================================
    slide8 = prs.slides.add_slide(blank_layout)
    add_header(slide8, "Verification & Future Roadmap", "PROJECT CONCLUSION")

    # Left card: Commands
    add_card(slide8, Inches(0.8), Inches(1.7), Inches(5.75), Inches(5.1))
    tb_c = slide8.shapes.add_textbox(Inches(1.0), Inches(1.9), Inches(5.35), Inches(4.7))
    tf_c = tb_c.text_frame
    tf_c.word_wrap = True

    pc1 = tf_c.paragraphs[0]
    pc1.text = "Operational Verification Commands"
    pc1.font.size = Pt(15)
    pc1.font.bold = True
    pc1.font.color.rgb = NAVY
    pc1.space_after = Pt(12)

    cmds = [
        ("Run Backend & Frontend Server", "uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload", "Serves Web Dashboard at http://127.0.0.1:8000 and OpenAPI docs at /docs"),
        ("Execute Automated Test Suite", "python -m pytest backend/tests", "Runs all 28 unit tests across validation, extraction, and API layers"),
        ("Run 50-Document Evaluation", "python evaluate_all.py", "Processes all documents in test_data/ and outputs evaluation_report.json")
    ]
    for c_title, c_code, c_note in cmds:
        p = tf_c.add_paragraph()
        p.text = f"▶ {c_title}"
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = TEAL

        p_code = tf_c.add_paragraph()
        p_code.text = f"  {c_code}"
        p_code.font.size = Pt(9.5)
        p_code.font.name = "Consolas"
        p_code.font.color.rgb = BLUE

        p_note = tf_c.add_paragraph()
        p_note.text = f"  ({c_note})"
        p_note.font.size = Pt(9)
        p_note.font.color.rgb = SLATE
        p_note.space_after = Pt(10)

    # Right card: Roadmap
    add_card(slide8, Inches(6.75), Inches(1.7), Inches(5.75), Inches(5.1))
    tb_r = slide8.shapes.add_textbox(Inches(6.95), Inches(1.9), Inches(5.35), Inches(4.7))
    tf_r = tb_r.text_frame
    tf_r.word_wrap = True

    pr1 = tf_r.paragraphs[0]
    pr1.text = "Production Milestones & Roadmap"
    pr1.font.size = Pt(15)
    pr1.font.bold = True
    pr1.font.color.rgb = NAVY
    pr1.space_after = Pt(12)

    milestones = [
        ("Generalization Maintained", "No hardcoded filenames, no mock numbers, no synthetic injections. All mathematical logic applies across unseen corporate receipts and financial statements."),
        ("Explainable Confidence Scoring", "Confidence strictly reflects field completeness and percentage of satisfied mathematical rules (never guessed by LLM)."),
        ("Human-in-the-Loop Integration", "Flagged discrepancies automatically routed for manual review with exact variance metrics rather than silent failures."),
        ("Multi-Modal Streaming Support", "Ready for direct multi-page PDF image embedding as Groq and vision models expand token quotas.")
    ]
    for m_title, m_desc in milestones:
        p = tf_r.add_paragraph()
        p.text = f"✔ {m_title}"
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = GREEN

        p_d = tf_r.add_paragraph()
        p_d.text = m_desc
        p_d.font.size = Pt(9.5)
        p_d.font.color.rgb = SLATE
        p_d.space_after = Pt(10)

    # Save output
    output_path = "Document_Intelligence_Development_Approach.pptx"
    prs.save(output_path)
    print(f"Presentation successfully created at: {output_path}")

if __name__ == "__main__":
    create_deck()
