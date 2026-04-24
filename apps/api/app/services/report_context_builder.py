from __future__ import annotations

from pathlib import Path

from app.services.result_reader import read_summary_workbook


def build_report_context(summary_path: str | Path, *, model_name: str) -> dict:
    summary = read_summary_workbook(summary_path)
    overview_map = {row.get("模块", ""): row.get("内容", "") for row in summary["overview_rows"]}
    business_map = {row.get("模块", ""): row.get("内容", "") for row in summary["business_rows"]}

    compare_rows = summary["compare_rows"][:5]
    opportunity_rows = summary["opportunity_rows"][:5]

    return {
        "model_name": model_name,
        "sample_summary": summary["sample_counts"],
        "overview": overview_map,
        "business": business_map,
        "compare_rows": compare_rows,
        "opportunity_rows": opportunity_rows,
        "one_pager_lines": summary["one_pager_lines"],
        "requested_report_schema": {
            "headline": "string",
            "executive_summary": "string",
            "strength_blocks": "list of objects with title, summary, evidence_ids",
            "weakness_blocks": "list of objects with title, summary, evidence_ids",
            "platform_difference_blocks": "list of objects with title, summary, evidence_ids",
            "action_blocks": "list of objects with title, summary, evidence_ids",
            "boss_brief": "list of exactly 3 strings",
        },
    }
