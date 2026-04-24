from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import JobAIReport, JobArtifact, JobQAChunk
from app.services.result_reader import read_summary_workbook


SUMMARY_SUFFIX = "_双平台口碑摘要.xlsx"

INTENT_KEYWORDS = {
    "boss": ("老板", "汇报", "三句", "3句", "一句话"),
    "strength": ("优点", "卖点", "满意", "喜欢", "优势"),
    "weakness": ("缺点", "槽点", "不满意", "问题", "吐槽"),
    "comparison": ("差异", "对比", "平台"),
    "action": ("建议", "改进", "优化", "优先", "怎么做"),
}

INTENT_SOURCE_WEIGHTS = {
    "boss": {"one_pager": 5, "business": 3, "overview": 2},
    "strength": {"business": 4, "overview": 3, "compare": 2, "one_pager": 2},
    "weakness": {"business": 4, "opportunity": 4, "overview": 3, "compare": 2, "one_pager": 2},
    "comparison": {"compare": 5, "overview": 2, "one_pager": 1},
    "action": {"opportunity": 5, "business": 4, "one_pager": 2},
}

FOLLOW_UP_SUGGESTIONS = {
    "boss": ["大家最满意什么？", "主要短板是什么？", "产品上优先改什么？"],
    "strength": ["主要短板是什么？", "平台差异在哪里？", "给老板汇报怎么说？"],
    "weakness": ["产品上优先改什么？", "平台差异在哪里？", "这些问题集中在哪些方向？"],
    "comparison": ["大家最满意什么？", "大家最不满意什么？", "产品上优先改什么？"],
    "action": ["这些问题主要集中在哪些方向？", "平台差异在哪里？", "给老板汇报怎么说？"],
    "generic": ["大家最满意什么？", "大家最不满意什么？", "给老板汇报怎么说？"],
}


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _question_tokens(question: str) -> list[str]:
    lowered = question.lower()
    tokens = re.findall(r"[a-z0-9+/.-]+|[\u4e00-\u9fff]{2,}", lowered)
    return list(dict.fromkeys(token for token in tokens if token))


def _detect_intents(question: str) -> list[str]:
    intents = [intent for intent, keywords in INTENT_KEYWORDS.items() if any(keyword in question for keyword in keywords)]
    return intents or ["generic"]


def _append_chunk(
    chunks: list[dict],
    *,
    chunk_id: str,
    source_type: str,
    text: str,
    tags: Iterable[str],
    metadata: dict,
) -> None:
    normalized = _normalize_text(text)
    if not normalized:
        return

    tag_values = [_normalize_text(tag).lower() for tag in tags if _normalize_text(tag)]
    chunks.append(
        {
            "chunk_id": chunk_id,
            "source_type": source_type,
            "text": normalized,
            "tags": list(dict.fromkeys(tag_values)),
            "metadata_json": metadata,
        }
    )


def _build_chunks(summary_path: str | Path, *, model_name: str) -> list[dict]:
    summary_data = read_summary_workbook(summary_path)
    chunks: list[dict] = []

    for index, row in enumerate(summary_data["overview_rows"], start=1):
        module = row.get("模块", "")
        content = row.get("内容", "")
        _append_chunk(
            chunks,
            chunk_id=f"overview_{index}",
            source_type="overview",
            text=f"{module}：{content}" if module and content else content or module,
            tags=("overview", module, model_name),
            metadata={"module": module},
        )

    for index, row in enumerate(summary_data["business_rows"], start=1):
        module = row.get("模块", "")
        content = row.get("内容", "")
        _append_chunk(
            chunks,
            chunk_id=f"business_{index}",
            source_type="business",
            text=f"{module}：{content}" if module and content else content or module,
            tags=("business", module, model_name),
            metadata={"module": module},
        )

    for index, row in enumerate(summary_data["compare_rows"], start=1):
        direction = row.get("方向", "")
        _append_chunk(
            chunks,
            chunk_id=f"compare_{index}",
            source_type="compare",
            text=(
                f"{direction}：汽车之家优势 {row.get('汽车之家_优势提及', '0')}，汽车之家槽点 {row.get('汽车之家_槽点提及', '0')}；"
                f"懂车帝优势 {row.get('懂车帝_优势提及', '0')}，懂车帝槽点 {row.get('懂车帝_槽点提及', '0')}。"
            ),
            tags=("compare", direction, model_name),
            metadata={
                "direction": direction,
                "autohome_positive": row.get("汽车之家_优势提及", "0"),
                "autohome_negative": row.get("汽车之家_槽点提及", "0"),
                "dongchedi_positive": row.get("懂车帝_优势提及", "0"),
                "dongchedi_negative": row.get("懂车帝_槽点提及", "0"),
            },
        )

    for index, row in enumerate(summary_data["opportunity_rows"], start=1):
        direction = row.get("方向", "")
        suggestion = row.get("建议", "")
        _append_chunk(
            chunks,
            chunk_id=f"opportunity_{index}",
            source_type="opportunity",
            text=f"{direction}：{suggestion}" if direction and suggestion else suggestion or direction,
            tags=("opportunity", row.get("类型", ""), direction, model_name),
            metadata={
                "type": row.get("类型", ""),
                "direction": direction,
                "suggestion": suggestion,
            },
        )

    for index, line in enumerate(summary_data["one_pager_lines"], start=1):
        _append_chunk(
            chunks,
            chunk_id=f"one_pager_{index}",
            source_type="one_pager",
            text=line,
            tags=("one_pager", model_name),
            metadata={"line_no": index},
        )

    return chunks


def find_summary_artifact(db: Session, job_id: str) -> JobArtifact | None:
    artifacts = (
        db.query(JobArtifact)
        .filter(JobArtifact.job_id == job_id)
        .order_by(JobArtifact.id.asc())
        .all()
    )
    return next((artifact for artifact in artifacts if artifact.artifact_path.endswith(SUMMARY_SUFFIX)), None)


def ensure_qa_chunks(db: Session, *, job_id: str, summary_path: str | Path, model_name: str) -> list[JobQAChunk]:
    existing = (
        db.query(JobQAChunk)
        .filter(JobQAChunk.job_id == job_id)
        .order_by(JobQAChunk.id.asc())
        .all()
    )
    if existing:
        return existing

    payloads = _build_chunks(summary_path, model_name=model_name)
    for payload in payloads:
        db.add(JobQAChunk(job_id=job_id, **payload))
    db.commit()

    return (
        db.query(JobQAChunk)
        .filter(JobQAChunk.job_id == job_id)
        .order_by(JobQAChunk.id.asc())
        .all()
    )


def _score_chunk(chunk: JobQAChunk, *, intents: list[str], tokens: list[str]) -> int:
    score = 0
    lowered_text = chunk.text.lower()
    lowered_tags = [str(tag).lower() for tag in chunk.tags or []]

    for intent in intents:
        score += INTENT_SOURCE_WEIGHTS.get(intent, {}).get(chunk.source_type, 0)

    for token in tokens:
        if token in lowered_text:
            score += 3
        elif any(token in tag for tag in lowered_tags):
            score += 4

    return score


def _chunk_summary(chunk: JobQAChunk) -> str:
    return _normalize_text(chunk.text.rstrip("。")) + "。"


def _build_answer(question: str, *, intents: list[str], chunks: list[JobQAChunk], ai_report: JobAIReport | None) -> str:
    summaries = list(dict.fromkeys(_chunk_summary(chunk) for chunk in chunks if chunk.text))
    if "boss" in intents and ai_report and isinstance(ai_report.report_json, dict):
        boss_brief = ai_report.report_json.get("boss_brief") or []
        brief_lines = [str(line).strip() for line in boss_brief if str(line).strip()]
        if brief_lines:
            return "给老板汇报可以先讲这 3 点：" + "；".join(brief_lines[:3]) + "。"

    if "boss" in intents:
        return (
            "给老板汇报可以先讲这几句：" + "；".join(summaries[:3]) + "。"
            if summaries
            else "当前证据不足，暂时无法整理老板汇报稿。"
        )
    if "action" in intents:
        return "基于当前结果，优先动作建议是：" + "；".join(summaries[:3]) + "。"
    if "weakness" in intents:
        return "当前最集中的负向反馈主要是：" + "；".join(summaries[:3]) + "。"
    if "strength" in intents:
        return "当前最稳定的正向卖点主要是：" + "；".join(summaries[:3]) + "。"
    if "comparison" in intents:
        return "从平台对比看，当前最相关的差异是：" + "；".join(summaries[:3]) + "。"
    return f"基于当前任务结果，和“{question}”最相关的是：" + "；".join(summaries[:3]) + "。"


def answer_job_question(db: Session, *, job_id: str, question: str, model_name: str | None = None) -> dict:
    summary_artifact = find_summary_artifact(db, job_id)
    if summary_artifact is None:
        raise ValueError("summary artifact missing")

    chunks = ensure_qa_chunks(
        db,
        job_id=job_id,
        summary_path=summary_artifact.artifact_path,
        model_name=model_name or Path(summary_artifact.artifact_path).name.replace(SUMMARY_SUFFIX, ""),
    )

    intents = _detect_intents(question)
    tokens = _question_tokens(question)
    ranked = sorted(
        ((chunk, _score_chunk(chunk, intents=intents, tokens=tokens)) for chunk in chunks),
        key=lambda item: (item[1], item[0].id),
        reverse=True,
    )
    positive = [item for item in ranked if item[1] > 0]
    top_chunks = [chunk for chunk, _score in positive[:3]]

    if not top_chunks:
        return {
            "answer": "当前任务结果里没有足够证据支持这个问题，建议先查看卖点、槽点或平台差异相关问题。",
            "citations": [],
            "confidence": "low",
            "insufficient_evidence": True,
            "follow_up_suggestions": FOLLOW_UP_SUGGESTIONS["generic"],
        }

    top_score = positive[0][1]
    ai_report = (
        db.query(JobAIReport)
        .filter(JobAIReport.job_id == job_id)
        .order_by(JobAIReport.id.desc())
        .first()
    )
    primary_intent = intents[0]
    return {
        "answer": _build_answer(question, intents=intents, chunks=top_chunks, ai_report=ai_report),
        "citations": [
            {
                "chunk_id": chunk.chunk_id,
                "source_type": chunk.source_type,
                "text": chunk.text,
                "metadata": chunk.metadata_json or {},
            }
            for chunk in top_chunks
        ],
        "confidence": "high" if top_score >= 8 else "medium",
        "insufficient_evidence": False,
        "follow_up_suggestions": FOLLOW_UP_SUGGESTIONS.get(primary_intent, FOLLOW_UP_SUGGESTIONS["generic"]),
    }
