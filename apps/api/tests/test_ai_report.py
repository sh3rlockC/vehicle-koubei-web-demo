from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.ai_report import generate_report_payload

SUMMARY_PATH = "/Users/xyc/Documents/codexwork/data/26.4.7/风云X3 PLUS/风云X3 PLUS_双平台口碑摘要.xlsx"


class StaticReportClient:
    def __init__(self, payload: dict | None) -> None:
        self.payload = payload

    def generate_report(self, context: dict) -> dict | None:
        return self.payload


VALID_LLM_REPORT = {
    "headline": "LLM headline",
    "executive_summary": "LLM summary",
    "strength_blocks": [],
    "weakness_blocks": [],
    "platform_difference_blocks": [],
    "action_blocks": [],
    "boss_brief": ["one", "two", "three"],
}


def test_generate_report_payload_falls_back_to_deterministic_report() -> None:
    context, payload, version = generate_report_payload(
        summary_path=SUMMARY_PATH,
        model_name="风云X3 PLUS",
        client=StaticReportClient(None),
    )

    assert context["sample_summary"] == {"autohome_count": 169, "dcd_count": 20}
    assert context["requested_report_schema"] == {
        "headline": "string",
        "executive_summary": "string",
        "strength_blocks": "list of objects with title, summary, evidence_ids",
        "weakness_blocks": "list of objects with title, summary, evidence_ids",
        "platform_difference_blocks": "list of objects with title, summary, evidence_ids",
        "action_blocks": "list of objects with title, summary, evidence_ids",
        "boss_brief": "list of exactly 3 strings",
    }
    assert payload["headline"]
    assert len(payload["boss_brief"]) == 3
    assert payload["strength_blocks"]
    assert version == "deterministic-v1"


def test_generate_report_payload_uses_valid_llm_report() -> None:
    _context, payload, version = generate_report_payload(
        summary_path=SUMMARY_PATH,
        model_name="风云X3 PLUS",
        client=StaticReportClient(VALID_LLM_REPORT),
    )

    assert payload == VALID_LLM_REPORT
    assert version == "llm-v1"


def test_generate_report_payload_falls_back_when_llm_report_is_invalid() -> None:
    _context, payload, version = generate_report_payload(
        summary_path=SUMMARY_PATH,
        model_name="风云X3 PLUS",
        client=StaticReportClient({"headline": "missing required lists"}),
    )

    assert payload != {"headline": "missing required lists"}
    assert payload["strength_blocks"]
    assert version == "deterministic-v1"
