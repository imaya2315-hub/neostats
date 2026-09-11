"""
Evaluation and benchmarking runner.
Runs the entire pipeline (validation, OCR, extraction, financial validation, storage)
over test documents in `test_data/` and produces `evaluation_report.json` and a console summary.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

# Add backend directory to sys.path so app modules import properly
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import SessionLocal, init_db
from app.services import document_service

FOLDER_TO_TYPE = {
    "invoices": "invoice",
    "profit_and_loss": "profit_and_loss",
    "balance_sheet": "balance_sheet",
    "cash_flow": "cash_flow_statement",
}


def discover_test_files(test_dir: str = "test_data") -> list[dict]:
    files = []
    base = Path(test_dir)
    for folder, doc_type in FOLDER_TO_TYPE.items():
        folder_path = base / folder
        if not folder_path.exists():
            continue
        for p in folder_path.iterdir():
            if p.is_file() and not p.name.startswith("."):
                files.append({
                    "path": str(p),
                    "filename": p.name,
                    "folder": folder,
                    "doc_type": doc_type,
                })
    # Sort files deterministically
    files.sort(key=lambda x: (x["folder"], x["filename"]))
    return files


def run_evaluation(
    test_dir: str = "test_data",
    limit: int | None = None,
    doc_type_filter: str | None = None,
    resume: bool = True,
    report_path: str = "evaluation_report.json",
) -> dict:
    init_db()
    all_files = discover_test_files(test_dir)
    if doc_type_filter:
        all_files = [f for f in all_files if f["folder"] == doc_type_filter or f["doc_type"] == doc_type_filter]
    if limit:
        all_files = all_files[:limit]

    # Load existing report if resume is enabled
    existing_docs: dict[str, dict] = {}
    if resume and os.path.exists(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as rf:
                old_data = json.load(rf)
                for d in old_data.get("documents", []):
                    # Only reuse if it passed and wasn't a configuration failure
                    if d.get("processing_status") == "PASS":
                        existing_docs[d["document_name"]] = d
        except Exception:
            pass

    print(f"\n=======================================================")
    print(f"Starting Evaluation on {len(all_files)} documents from '{test_dir}'")
    if existing_docs:
        print(f"Resuming: {len(existing_docs)} already successfully processed")
    print(f"=======================================================\n")

    results: list[dict] = []
    db = SessionLocal()

    def _save_current_report():
        total_docs = len(results)
        total_pass = sum(1 for r in results if r["processing_status"] == "PASS")
        total_fail = total_docs - total_pass
        pass_rate = (total_pass / total_docs * 100) if total_docs else 0.0

        all_confs = [r["overall_confidence"] for r in results if r.get("overall_confidence") is not None]
        avg_conf = (sum(all_confs) / len(all_confs)) if all_confs else 0.0

        all_times = [r["processing_time_ms"] for r in results if r.get("processing_time_ms")]
        avg_time = (sum(all_times) / len(all_times)) if all_times else 0.0

        type_metrics: dict[str, dict] = {}
        total_checks_count = {"PASS": 0, "FAIL": 0, "NOT_APPLICABLE": 0}
        checks_by_rule: dict[str, dict[str, int]] = {}

        for r in results:
            dtype = r["document_type"]
            if dtype not in type_metrics:
                type_metrics[dtype] = {"total": 0, "pass_count": 0, "fail_count": 0, "confidences": [], "times_ms": []}
            tm = type_metrics[dtype]
            tm["total"] += 1
            if r["processing_status"] == "PASS":
                tm["pass_count"] += 1
            else:
                tm["fail_count"] += 1
            if r.get("overall_confidence") is not None:
                tm["confidences"].append(r["overall_confidence"])
            if r.get("processing_time_ms"):
                tm["times_ms"].append(r["processing_time_ms"])

            for c in r.get("validation_checks", []):
                st = c.get("status", "NOT_APPLICABLE")
                cn = c.get("check_name") or c.get("name", "unknown")
                total_checks_count[st] = total_checks_count.get(st, 0) + 1
                if cn not in checks_by_rule:
                    checks_by_rule[cn] = {"PASS": 0, "FAIL": 0, "NOT_APPLICABLE": 0}
                checks_by_rule[cn][st] = checks_by_rule[cn].get(st, 0) + 1

        summary_types = {}
        for dtype, tm in type_metrics.items():
            t_pass_rate = (tm["pass_count"] / tm["total"] * 100) if tm["total"] else 0.0
            t_avg_conf = (sum(tm["confidences"]) / len(tm["confidences"])) if tm["confidences"] else 0.0
            t_avg_time = (sum(tm["times_ms"]) / len(tm["times_ms"])) if tm["times_ms"] else 0.0
            summary_types[dtype] = {
                "total": tm["total"],
                "pass_count": tm["pass_count"],
                "fail_count": tm["fail_count"],
                "pass_rate_pct": round(t_pass_rate, 2),
                "avg_confidence": round(t_avg_conf, 4),
                "avg_time_ms": round(t_avg_time, 1),
            }

        rep = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "summary": {
                "total_documents": total_docs,
                "pass_count": total_pass,
                "fail_count": total_fail,
                "overall_pass_rate_pct": round(pass_rate, 2),
                "average_confidence": round(avg_conf, 4),
                "average_processing_time_ms": round(avg_time, 1),
                "by_document_type": summary_types,
                "financial_validation_checks_total": total_checks_count,
                "financial_validation_by_rule": checks_by_rule,
            },
            "documents": results,
        }
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=2)
        return rep

    try:
        for idx, item in enumerate(all_files, start=1):
            fname = item["filename"]
            dtype = item["doc_type"]
            fpath = item["path"]

            if fname in existing_docs:
                print(f"[{idx}/{len(all_files)}] (Cached) {fname} ({dtype})... PASS (Conf: {existing_docs[fname].get('overall_confidence')})")
                results.append(existing_docs[fname])
                _save_current_report()
                continue

            print(f"[{idx}/{len(all_files)}] Processing: {fname} ({dtype})... ", end="", flush=True)
            with open(fpath, "rb") as fh:
                content = fh.read()

            t0 = time.monotonic()
            try:
                res = document_service.process_upload(
                    db, original_filename=fname, document_type=dtype, content=content
                )
            except Exception as exc:
                print(f"ERROR: {exc}")
                res = {
                    "document_name": fname,
                    "document_type": dtype,
                    "processing_status": "FAILED",
                    "overall_confidence": None,
                    "file_validation": {"status": "FAILED", "error_message": str(exc)},
                    "extracted_data": None,
                    "validation": None,
                    "processing_metadata": {
                        "ocr_used": False,
                        "processing_time_ms": int((time.monotonic() - t0) * 1000),
                        "warnings": [f"PIPELINE_ERROR: {exc}"],
                    },
                }

            proc_status = res.get("processing_status", "FAILED")
            conf = res.get("overall_confidence")
            file_val = res.get("file_validation", {})
            metadata = res.get("processing_metadata", {})
            val_res = res.get("validation") or {}
            extracted = res.get("extracted_data") or {}
            checks = val_res.get("checks", [])

            time_ms = metadata.get("processing_time_ms", int((time.monotonic() - t0) * 1000))
            ocr_used = metadata.get("ocr_used", False)

            fields_dict = extracted.get("fields", {}) or {}
            found_fields = [k for k, v in fields_dict.items() if isinstance(v, dict) and v.get("value") is not None]

            doc_checks = []
            for c in checks:
                status = c.get("status", "NOT_APPLICABLE")
                cname = c.get("name") or c.get("check_name", "unknown")
                doc_checks.append({
                    "check_name": cname,
                    "status": status,
                    "formula": c.get("formula"),
                    "calculated_value": c.get("calculated_value"),
                    "reported_value": c.get("reported_value"),
                    "variance": c.get("variance"),
                    "operands": c.get("operands"),
                })

            failed_checks = [c["check_name"] for c in doc_checks if c["status"] == "FAIL"]

            print(f"Status: {proc_status} | Conf: {conf} | Checks: {len(checks)} (Fails: {len(failed_checks)}) | Time: {time_ms}ms")

            doc_result = {
                "document_name": fname,
                "document_type": dtype,
                "folder": item["folder"],
                "processing_status": proc_status,
                "overall_confidence": conf,
                "file_validation_status": file_val.get("status"),
                "ocr_used": ocr_used,
                "processing_time_ms": time_ms,
                "extracted_fields_count": len(found_fields),
                "extracted_key_fields": found_fields,
                "line_items_count": len(extracted.get("line_items", []) or extracted.get("statement_line_items", []) or []),
                "validation_checks": doc_checks,
                "failed_rules": failed_checks,
                "warnings": metadata.get("warnings", []),
            }
            results.append(doc_result)
            _save_current_report()

            # Small pause between LLM requests to be gentle on API quotas
            time.sleep(1.0)

    finally:
        db.close()

    report = _save_current_report()

    # Print summary table
    summary = report["summary"]
    print("\n" + "=" * 70)
    print("                      EVALUATION SUMMARY")
    print("=" * 70)
    print(f"Total Documents Evaluated: {summary['total_documents']}")
    print(f"Overall PASS Rate:         {summary['overall_pass_rate_pct']:.2f}% ({summary['pass_count']}/{summary['total_documents']})")
    print(f"Average Confidence:        {summary['average_confidence']:.4f}")
    print(f"Average Processing Time:   {summary['average_processing_time_ms']:.1f} ms")
    print("-" * 70)
    print("Performance by Document Type:")
    for dtype, m in summary["by_document_type"].items():
        print(f"  - {dtype.ljust(22)}: {m['pass_count']}/{m['total']} PASS ({m['pass_rate_pct']}%) | Avg Conf: {m['avg_confidence']:.4f} | Avg Time: {m['avg_time_ms']} ms")
    print("-" * 70)
    print(f"Financial Validation Checks:")
    checks_total = summary["financial_validation_checks_total"]
    print(f"  PASS:           {checks_total.get('PASS', 0)}")
    print(f"  FAIL:           {checks_total.get('FAIL', 0)}")
    print(f"  NOT_APPLICABLE: {checks_total.get('NOT_APPLICABLE', 0)}")
    print("=" * 70)
    print(f"Detailed report written to {report_path}\n")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate pipeline across test_data")
    parser.add_argument("--test-dir", default="test_data", help="Directory with test documents")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of documents to evaluate")
    parser.add_argument("--type", default=None, help="Filter by document type/folder")
    parser.add_argument("--no-resume", action="store_true", help="Do not reuse existing successful results")
    args = parser.parse_args()

    run_evaluation(
        test_dir=args.test_dir,
        limit=args.limit,
        doc_type_filter=args.type,
        resume=not args.no_resume,
    )
