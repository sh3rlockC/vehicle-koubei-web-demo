from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
from pathlib import Path
import re
from typing import Any

from openpyxl import Workbook


@dataclass(frozen=True)
class VehicleSnapshot:
    model_name: str
    source_job_id: str
    final_report_path: Path
    analysis_facts_path: Path
    llm_metrics_path: Path | None = None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", str(value or ""))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _count_jsonl(path: Path, *, start_date: str | None = None, end_date: str | None = None) -> int:
    start = _parse_date(start_date) if start_date else None
    end = _parse_date(end_date) if end_date else None
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                if start or end:
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    parsed = _parse_date(payload.get("date") if isinstance(payload, dict) else None)
                    if parsed is None:
                        continue
                    if start and parsed < start:
                        continue
                    if end and parsed > end:
                        continue
                count += 1
    except OSError:
        return 0
    return count


def _vehicle_summary(snapshot: VehicleSnapshot, *, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    report = _read_json(snapshot.final_report_path)
    total_count = _count_jsonl(snapshot.analysis_facts_path)
    selected_count = _count_jsonl(snapshot.analysis_facts_path, start_date=start_date, end_date=end_date) if start_date or end_date else total_count
    return {
        "model_name": snapshot.model_name,
        "source_job_id": snapshot.source_job_id,
        "comment_fact_count": selected_count,
        "total_comment_fact_count": total_count,
        "headline": report.get("headline") or report.get("summary") or f"{snapshot.model_name} 口碑摘要",
        "structured_sections": report.get("structured_sections") or report.get("sections") or {},
        "source_report_path": str(snapshot.final_report_path),
        "source_facts_path": str(snapshot.analysis_facts_path),
    }


def _write_summary_workbook(path: Path, vehicles: list[dict[str, Any]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "竞品对比"
    sheet.append(["车型", "评论事实数", "摘要"])
    for vehicle in vehicles:
        sheet.append([vehicle["model_name"], vehicle["comment_fact_count"], str(vehicle["headline"])])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def generate_comparison_outputs(
    *,
    snapshots: list[VehicleSnapshot],
    output_dir: Path,
    start_date: str | None = None,
    end_date: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    vehicles = [_vehicle_summary(snapshot, start_date=start_date, end_date=end_date) for snapshot in snapshots]
    generated_at = datetime.now(UTC).isoformat()
    date_range = {"start_date": start_date, "end_date": end_date} if start_date or end_date else None
    report_json = {
        "headline": "竞品口碑对比",
        "generated_at": generated_at,
        "source": "hermes_comparison",
        "date_range": date_range,
        "vehicle_count": len(vehicles),
        "vehicles": vehicles,
        "comparison": {
            "summary": "已基于各车型脱敏 JSON 产物生成横向对比。",
            "dimensions": ["口碑摘要", "评论事实数", "结构化结论"],
        },
    }

    final_json = output_dir / "final_comparison.json"
    summary_xlsx = output_dir / "comparison_summary.xlsx"
    metrics_json = output_dir / "llm_metrics.json"
    final_json.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_summary_workbook(summary_xlsx, vehicles)
    metrics_json.write_text(
        json.dumps(
            {
                "source": "hermes_comparison",
                "generated_at": generated_at,
                "provider": (env or {}).get("LLM_PROVIDER"),
                "model_report": (env or {}).get("LLM_MODEL_REPORT"),
                "vehicle_count": len(vehicles),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "report_json": report_json,
        "artifact_paths": [str(final_json), str(summary_xlsx), str(metrics_json)],
    }
