from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OutputPaths:
    raw: Path
    postprocess: Path
    summary: Path
    wordcloud: Path
    ai: Path


@dataclass(frozen=True)
class JobPaths:
    root: Path
    meta: Path
    progress: Path
    logs: Path
    inputs: Path
    outputs: OutputPaths


def ensure_job_dirs(artifact_root: str | Path, job_id: str) -> JobPaths:
    root = Path(artifact_root).expanduser().resolve() / job_id
    meta = root / "meta"
    progress = root / "progress"
    logs = root / "logs"
    inputs = root / "inputs"
    outputs_root = root / "outputs"
    raw = outputs_root / "raw"
    postprocess = outputs_root / "postprocess"
    summary = outputs_root / "summary"
    wordcloud = outputs_root / "wordcloud"
    ai = outputs_root / "ai"

    for path in [meta, progress, logs, inputs, raw, postprocess, summary, wordcloud, ai]:
        path.mkdir(parents=True, exist_ok=True)

    return JobPaths(
        root=root,
        meta=meta,
        progress=progress,
        logs=logs,
        inputs=inputs,
        outputs=OutputPaths(
            raw=raw,
            postprocess=postprocess,
            summary=summary,
            wordcloud=wordcloud,
            ai=ai,
        ),
    )
