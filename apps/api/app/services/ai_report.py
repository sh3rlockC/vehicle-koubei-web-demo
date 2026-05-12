from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import JobAIReport
from app.services.llm_client import DisabledLLMClient, ReportLLMClient, build_report_llm_client
from app.services.report_context_builder import build_report_context
from app.services.report_validator import validate_report_payload


def build_deterministic_report(context: dict) -> dict:
    overview = context["overview"]
    business = context["business"]
    compare_rows = context["compare_rows"]
    opportunity_rows = context["opportunity_rows"]
    one_pager_lines = context["one_pager_lines"]

    strengths = [
        {
            "title": "核心好评",
            "summary": business.get("核心好评", business.get("核心卖点", "")),
            "evidence_ids": ["business.core_strengths"],
        }
    ]
    weaknesses = [
        {
            "title": "核心槽点",
            "summary": business.get("核心槽点", ""),
            "evidence_ids": ["business.core_weaknesses"],
        }
    ]
    platform_differences = [
        {
            "title": row.get("方向", ""),
            "summary": (
                f"汽车之家优势 {row.get('汽车之家_优势提及', '0')} / 槽点 {row.get('汽车之家_槽点提及', '0')}；"
                f"懂车帝优势 {row.get('懂车帝_优势提及', '0')} / 槽点 {row.get('懂车帝_槽点提及', '0')}。"
            ),
            "evidence_ids": [f"compare.{row.get('方向', 'unknown')}"],
        }
        for row in compare_rows[:3]
    ]
    actions = [
        {
            "title": row.get("方向", row.get("类型", "产品机会点")),
            "summary": row.get("建议", ""),
            "evidence_ids": [f"opportunity.{index + 1}"],
        }
        for index, row in enumerate(opportunity_rows[:3])
    ]

    boss_brief = [line for line in one_pager_lines[1:4] if line][:3]
    if len(boss_brief) < 3:
        boss_brief.extend(
            item
            for item in [
                overview.get("综合一句话", ""),
                business.get("产品建议", ""),
                business.get("适合人群", ""),
            ]
            if item and item not in boss_brief
        )
    boss_brief = boss_brief[:3]

    return {
        "headline": overview.get("综合一句话", one_pager_lines[0] if one_pager_lines else ""),
        "executive_summary": one_pager_lines[1] if len(one_pager_lines) > 1 else overview.get("项目", ""),
        "strength_blocks": strengths,
        "weakness_blocks": weaknesses,
        "platform_difference_blocks": platform_differences,
        "action_blocks": actions,
        "boss_brief": boss_brief,
    }


def generate_report_payload(
    *,
    summary_path: str,
    model_name: str,
    client: ReportLLMClient | None = None,
) -> tuple[dict, dict, str]:
    context = build_report_context(summary_path, model_name=model_name)
    client = client or build_report_llm_client(get_settings())
    payload = client.generate_report(context)
    ok, _errors = validate_report_payload(payload) if payload is not None else (False, ["empty llm payload"])
    if ok and payload is not None and not isinstance(client, DisabledLLMClient):
        return context, payload, "llm-v1"
    if ok and payload is not None:
        return context, payload, "deterministic-v1"
    return context, build_deterministic_report(context), "deterministic-v1"


def ensure_ai_report(
    db: Session,
    *,
    job_id: str,
    summary_path: str,
    model_name: str,
    report_path: str | None = None,
) -> JobAIReport:
    existing = (
        db.query(JobAIReport)
        .filter(JobAIReport.job_id == job_id)
        .order_by(JobAIReport.id.desc())
        .first()
    )
    if existing is not None:
        return existing

    if report_path and Path(report_path).exists():
        try:
            payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        ok, _errors = validate_report_payload(payload) if isinstance(payload, dict) else (False, ["invalid hermes report"])
        if ok and isinstance(payload, dict):
            report = JobAIReport(job_id=job_id, report_version="hermes-v1", report_json=payload)
            db.add(report)
            db.commit()
            db.refresh(report)
            return report

    _context, payload, version = generate_report_payload(summary_path=summary_path, model_name=model_name)
    report = JobAIReport(job_id=job_id, report_version=version, report_json=payload)
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
