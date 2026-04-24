from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass
class ProgressSink:
    job_id: str
    progress_path: Path
    stages: list[str]
    snapshots: list[dict] = field(default_factory=list)

    def update(self, *, stage: str, status: str, message: str, overall_percent: int, degraded: bool = False) -> dict:
        payload = {
            "job_id": self.job_id,
            "stage": stage,
            "status": status,
            "message": message,
            "overall_percent": overall_percent,
            "degraded": degraded,
            "updated_at": utc_now_iso(),
            "stages": self.stages,
        }
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self.progress_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.snapshots.append(payload)
        return payload
