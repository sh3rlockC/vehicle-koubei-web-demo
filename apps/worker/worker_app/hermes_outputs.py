from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook


PLATFORM_AUTOHOME = "汽车之家"
PLATFORM_DCD = "懂车帝"
DEFAULT_BATCH_SIZE = 20
MAX_REPAIR_RESPONSE_CHARS = 120_000
MAX_AGGREGATE_THEMES_PER_DIRECTION = 6
MAX_AGGREGATE_SUGGESTIONS = 5
MAX_AGGREGATE_PLATFORM_NOTES = 2
LEGACY_LABEL_REPLACEMENTS = {
    "核心卖点TOP": "最满意TOP",
    "核心槽点TOP": "最不满意TOP",
    "核心卖点": "核心好评",
}


@dataclass(frozen=True)
class NormalizedHermesResult:
    report: dict[str, Any]
    keyword_rankings: dict[str, list[dict[str, Any]]]
    qa_chunks: list[dict[str, Any]]
    one_pager_lines: list[str]
    compare_rows: list[dict[str, str]]
    opportunity_rows: list[dict[str, str]]


def _clean_text(value: object, *, limit: int = 900) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _replace_legacy_labels(value: Any) -> Any:
    if isinstance(value, str):
        text = value
        for old, new in LEGACY_LABEL_REPLACEMENTS.items():
            text = text.replace(old, new)
        return text
    if isinstance(value, list):
        return [_replace_legacy_labels(item) for item in value]
    if isinstance(value, dict):
        return {
            _replace_legacy_labels(key) if isinstance(key, str) else key: _replace_legacy_labels(item)
            for key, item in value.items()
        }
    return value


def _clean_generated_text(value: object, *, limit: int = 900) -> str:
    return _replace_legacy_labels(_clean_text(value, limit=limit))


def _first_value(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _clean_text(row.get(key))
        if value:
            return value
    return ""


def _iter_sheet_rows(path: Path) -> list[dict[str, Any]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows: list[dict[str, Any]] = []
    try:
        for worksheet in workbook.worksheets:
            raw_rows = list(worksheet.iter_rows(values_only=True))
            if not raw_rows:
                continue
            header = [_clean_text(cell) for cell in raw_rows[0]]
            if not any(header):
                continue
            for raw_row in raw_rows[1:]:
                row = {header[index]: raw_row[index] for index in range(min(len(header), len(raw_row))) if header[index]}
                if any(_clean_text(value) for value in row.values()):
                    rows.append(row)
    finally:
        workbook.close()
    return rows


def _comment_from_row(row: dict[str, Any], *, platform: str, model_name: str) -> dict[str, str] | None:
    positive_text = _first_value(row, ("最满意", "满意", "优点", "优势", "正向反馈"))
    negative_text = _first_value(row, ("最不满意", "不满意", "缺点", "槽点", "负向反馈"))
    full_text = _first_value(row, ("评价详情", "评价全文", "口碑内容", "内容", "正文", "评论", "原文"))
    date = _first_value(row, ("发表日期", "发布时间", "日期", "时间"))
    row_model = _first_value(row, ("车型", "评价车型", "车款", "车系", "车型名称")) or model_name

    if not any([positive_text, negative_text, full_text]):
        return None
    return {
        "platform": platform,
        "date": date,
        "model_name": row_model,
        "positive_text": positive_text,
        "negative_text": negative_text,
        "full_text": full_text,
    }


def extract_whitelisted_comments(
    *,
    autohome_input: str | Path,
    dcd_input: str | Path | None,
    model_name: str,
) -> list[dict[str, str]]:
    comments: list[dict[str, str]] = []
    autohome_path = Path(autohome_input)
    if autohome_path.exists():
        autohome_index = 1
        for row in _iter_sheet_rows(autohome_path):
            comment = _comment_from_row(row, platform=PLATFORM_AUTOHOME, model_name=model_name)
            if comment:
                comment["comment_id"] = f"autohome_{autohome_index:04d}"
                comments.append(comment)
                autohome_index += 1

    dcd_path = Path(dcd_input) if dcd_input else None
    if dcd_path and dcd_path.exists():
        dcd_index = 1
        for row in _iter_sheet_rows(dcd_path):
            comment = _comment_from_row(row, platform=PLATFORM_DCD, model_name=model_name)
            if comment:
                comment["comment_id"] = f"dcd_{dcd_index:04d}"
                comments.append(comment)
                dcd_index += 1

    return comments


def _parse_comment_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean_text(value, limit=80)
    if not text:
        return None
    match = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _parse_date_param(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _filter_comments_for_date_range(comments: list[dict[str, str]], *, start_date: str, end_date: str) -> list[dict[str, str]]:
    start = _parse_date_param(start_date)
    end = _parse_date_param(end_date)
    if start > end:
        return []
    selected: list[tuple[date, dict[str, str]]] = []
    for comment in comments:
        parsed = _parse_comment_date(comment.get("date"))
        if parsed is not None and start <= parsed <= end:
            selected.append((parsed, comment))
    return [comment for _parsed, comment in sorted(selected, key=lambda item: (item[0], item[1].get("platform", ""), item[1].get("comment_id", "")))]


def _write_progress(progress_file: Path, *, percent: int, message: str, degraded: bool = False) -> None:
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file.write_text(
        json.dumps(
            {
                "percent": max(0, min(100, percent)),
                "message": message,
                "degraded": degraded,
                "updated_at": int(time.time()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _json_default(value: object) -> str:
    return str(value)


def _extract_json(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty response")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    start_positions = [position for position in (stripped.find("{"), stripped.find("[")) if position >= 0]
    if not start_positions:
        raise ValueError("response did not contain JSON")
    start = min(start_positions)
    opener = stripped[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return json.loads(stripped[start : index + 1])
    raise ValueError("response JSON was not balanced")


def _batch_items(values: list[dict[str, str]], batch_size: int) -> list[list[dict[str, str]]]:
    size = max(batch_size, 1)
    return [values[index : index + size] for index in range(0, len(values), size)]


def _runtime_provider(env: dict[str, str]) -> tuple[str, str, dict[str, str]]:
    provider = (env.get("LLM_PROVIDER") or "deepseek").strip().lower()
    model = (env.get("LLM_MODEL_REPORT") or env.get("LLM_MODEL_QA") or "deepseek-chat").strip()
    base_url = (env.get("LLM_BASE_URL") or "").strip()
    api_key = (env.get("LLM_API_KEY") or "").strip()
    updated_env = dict(env)

    if provider in {"deepseek", "deepseek-v4", "deepseekv4", "deepseekv4pro"}:
        updated_env.setdefault("DEEPSEEK_API_KEY", api_key)
        return "deepseek", model, updated_env

    if base_url:
        return "custom:vehicle-koubei", model, updated_env
    return provider or "deepseek", model, updated_env


def _write_hermes_config(env: dict[str, str]) -> dict[str, str]:
    provider, model, updated_env = _runtime_provider(env)
    home = Path(updated_env.get("HOME") or str(Path.home())).expanduser()
    hermes_home = home / ".hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    base_url = (updated_env.get("LLM_BASE_URL") or "").strip()

    lines = [
        "model:",
        f'  default: "{model}"',
        f'  provider: "{provider}"',
    ]
    if base_url:
        lines.extend(
            [
                "custom_providers:",
                "  - name: vehicle-koubei",
                f'    base_url: "{base_url.rstrip("/")}"',
                "    key_env: LLM_API_KEY",
                "    api_mode: chat_completions",
            ]
        )
    (hermes_home / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return updated_env


def _hermes_command_path(command: str) -> str | None:
    if "/" in command:
        return command if Path(command).exists() else None
    return shutil.which(command)


def _safe_debug_label(label: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("._")
    return safe or "hermes"


def _write_hermes_debug(debug_dir: Path | None, *, label: str, attempt: int, kind: str, content: str) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_safe_debug_label(label)}.attempt_{attempt}.{kind}.txt"
    (debug_dir / filename).write_text(content, encoding="utf-8")


def _reset_hermes_debug_dir(debug_dir: Path) -> None:
    if not debug_dir.exists():
        return
    for path in debug_dir.glob("*.txt"):
        if path.is_file():
            path.unlink()


def _process_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _build_json_repair_prompt(*, raw_response: str, parse_error: Exception) -> str:
    response = raw_response.strip()
    if len(response) > MAX_REPAIR_RESPONSE_CHARS:
        response = response[:MAX_REPAIR_RESPONSE_CHARS]
    return (
        "你是 JSON 语法修复器。下面是上一轮模型输出，json.loads 解析失败。\n"
        "任务：只修复 JSON 语法错误，保留原有字段、层级、文本含义和证据 id；不要新增事实，不要重新分析，"
        "不要输出 Markdown、代码块或解释文字。\n"
        "允许修复的问题包括：缺失逗号、缺失引号、括号不配平、尾随逗号、非法控制字符。\n"
        f"解析错误：{parse_error}\n"
        "上一轮输出如下：\n"
        f"{response}"
    )


def _build_batch_prompt(*, model_name: str, batch_index: int, total_batches: int, comments: list[dict[str, str]]) -> str:
    return (
        "你是汽车口碑分析Agent。只根据输入的脱敏原评论JSON分析，不引入外部资料。\n"
        "只返回严格JSON，不要Markdown，不要解释。\n"
        "JSON schema: {\"themes\":[{\"direction\":\"positive|negative\",\"term\":\"主题词\",\"count\":数字,"
        "\"summary\":\"摘要\",\"evidence_ids\":[\"comment_id\"]}],\"suggestions\":[{\"direction\":\"方向\",\"text\":\"建议\"}],"
        "\"platform_notes\":[{\"platform\":\"平台\",\"summary\":\"差异\"}],\"boss_brief\":[\"一句话\"]}。\n"
        "证据只允许填写输入中的 comment_id，不要在 JSON 中复制原评论原句。\n"
        f"车型：{model_name}；批次：{batch_index}/{total_batches}。\n"
        "评论白名单字段如下：\n"
        + json.dumps(comments, ensure_ascii=False, default=_json_default)
    )


def _local_batch_payload(*, batch_index: int, total_batches: int, comments: list[dict[str, str]], reason: str) -> dict[str, Any]:
    evidence_ids = [
        _clean_text(comment.get("comment_id"), limit=80)
        for comment in comments
        if _clean_text(comment.get("comment_id"), limit=80)
    ]
    positive_snippets: list[str] = []
    negative_snippets: list[str] = []
    platform_counter: Counter[str] = Counter()
    for comment in comments:
        platform = _clean_text(comment.get("platform"), limit=80)
        if platform:
            platform_counter[platform] += 1
        positive = _clean_text(comment.get("positive_text"), limit=180)
        negative = _clean_text(comment.get("negative_text"), limit=180)
        full_text = _clean_text(comment.get("full_text"), limit=220)
        if positive:
            positive_snippets.append(positive)
        elif full_text:
            positive_snippets.append(full_text)
        if negative:
            negative_snippets.append(negative)

    fallback_evidence = evidence_ids[:8] or [f"local_batch_{batch_index:03d}"]
    positive_summary = "；".join(positive_snippets[:4]) or "该批 Hermes 输出失败，使用脱敏评论做本地批次兜底。"
    negative_summary = "；".join(negative_snippets[:4]) or "该批未稳定识别独立槽点，建议结合最终汇总继续判断。"
    platform_summary = "；".join(f"{platform} {count} 条" for platform, count in platform_counter.items())
    return {
        "batch": f"{batch_index}/{total_batches}",
        "themes": [
            {
                "direction": "positive",
                "term": "本地批次兜底",
                "count": max(len(positive_snippets), 1),
                "summary": positive_summary,
                "evidence_ids": fallback_evidence,
            },
            {
                "direction": "negative",
                "term": "本地槽点",
                "count": max(len(negative_snippets), 1),
                "summary": negative_summary,
                "evidence_ids": fallback_evidence,
            },
        ],
        "suggestions": [
            {
                "direction": "稳定性",
                "text": f"批次 {batch_index}/{total_batches} 的 Hermes 输出未能解析，已用本地规则兜底；建议优先复核该批证据 id。",
            }
        ],
        "platform_notes": [
            {
                "platform": "本地批次兜底",
                "summary": platform_summary or f"批次 {batch_index}/{total_batches} 共 {len(comments)} 条脱敏评论。",
            }
        ],
        "boss_brief": [f"批次 {batch_index}/{total_batches} 使用本地批次兜底，原因：{_clean_text(reason, limit=120)}"],
    }


def _count_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _compact_evidence_ids(value: Any, *, limit: int = 3) -> list[str]:
    ids: list[str] = []
    for item in _as_list(value):
        text = _clean_text(item, limit=80)
        if text:
            ids.append(text)
        if len(ids) >= limit:
            break
    return ids


def _compact_themes(value: Any) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for direction in ("positive", "negative"):
        themes = [
            item
            for item in _as_list(value)
            if isinstance(item, dict) and _clean_text(item.get("direction"), limit=40) == direction
        ]
        themes.sort(key=lambda item: _count_value(item.get("count")), reverse=True)
        for item in themes[:MAX_AGGREGATE_THEMES_PER_DIRECTION]:
            selected.append(
                {
                    "direction": direction,
                    "term": _clean_text(item.get("term"), limit=80),
                    "count": max(_count_value(item.get("count")), 1),
                    "summary": _clean_text(item.get("summary") or item.get("description"), limit=240),
                    "evidence_ids": _compact_evidence_ids(item.get("evidence_ids")),
                }
            )
    return [item for item in selected if item["term"]]


def _compact_batch_payloads(batch_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for index, payload in enumerate(batch_payloads, start=1):
        if not isinstance(payload, dict):
            continue
        suggestions = []
        for item in _as_list(payload.get("suggestions"))[:MAX_AGGREGATE_SUGGESTIONS]:
            if not isinstance(item, dict):
                continue
            text = _clean_text(item.get("text"), limit=220)
            if text:
                suggestions.append({"direction": _clean_text(item.get("direction"), limit=80), "text": text})

        platform_notes = []
        for item in _as_list(payload.get("platform_notes"))[:MAX_AGGREGATE_PLATFORM_NOTES]:
            if not isinstance(item, dict):
                continue
            summary = _clean_text(item.get("summary"), limit=260)
            if summary:
                platform_notes.append({"platform": _clean_text(item.get("platform"), limit=80), "summary": summary})

        compacted.append(
            {
                "batch": _clean_text(payload.get("batch"), limit=40) or str(index),
                "themes": _compact_themes(payload.get("themes")),
                "suggestions": suggestions,
                "platform_notes": platform_notes,
                "boss_brief": [
                    _clean_text(item, limit=260)
                    for item in _as_list(payload.get("boss_brief"))[:2]
                    if _clean_text(item, limit=260)
                ],
            }
        )
    return compacted


def _build_aggregate_prompt(*, model_name: str, comments: list[dict[str, str]], batch_payloads: list[dict[str, Any]]) -> str:
    sample_counts = Counter(comment["platform"] for comment in comments)
    compacted_payloads = _compact_batch_payloads(batch_payloads)
    return (
        "你是汽车口碑分析Agent。请归并各批分析结果，生成最终结果。只返回严格JSON，不要Markdown。\n"
        "JSON schema: {\"headline\":\"一句话结论\",\"executive_summary\":\"摘要\","
        "\"strength_blocks\":[{\"title\":\"核心好评\",\"summary\":\"...\",\"evidence_ids\":[\"...\"]}],"
        "\"weakness_blocks\":[{\"title\":\"核心槽点\",\"summary\":\"...\",\"evidence_ids\":[\"...\"]}],"
        "\"platform_difference_blocks\":[{\"title\":\"方向\",\"summary\":\"...\",\"evidence_ids\":[\"...\"]}],"
        "\"action_blocks\":[{\"title\":\"建议方向\",\"summary\":\"...\",\"evidence_ids\":[\"...\"]}],"
        "\"boss_brief\":[\"...\"],\"keyword_rankings\":{\"positive\":[{\"term\":\"...\",\"count\":1}],"
        "\"negative\":[{\"term\":\"...\",\"count\":1}]},\"qa_chunks\":[{\"chunk_id\":\"...\",\"source_type\":\"hermes_evidence\","
        "\"text\":\"...\",\"tags\":[\"...\"],\"metadata\":{\"source\":\"hermes\"}}],"
        "\"compare_rows\":[{\"方向\":\"...\",\"汽车之家_优势提及\":\"0\",\"汽车之家_槽点提及\":\"0\",\"懂车帝_优势提及\":\"0\",\"懂车帝_槽点提及\":\"0\"}],"
        "\"opportunity_rows\":[{\"类型\":\"改进\",\"方向\":\"...\",\"建议\":\"...\"}]}。\n"
        f"车型：{model_name}；样本数：汽车之家 {sample_counts.get(PLATFORM_AUTOHOME, 0)} 条，懂车帝 {sample_counts.get(PLATFORM_DCD, 0)} 条。\n"
        "批次结果如下：\n"
        + json.dumps(compacted_payloads, ensure_ascii=False, default=_json_default)
    )


def _call_hermes(
    prompt: str,
    *,
    hermes_command: str,
    env: dict[str, str],
    debug_dir: Path | None = None,
    call_label: str = "hermes",
) -> Any:
    command_path = _hermes_command_path(hermes_command)
    if not command_path:
        raise RuntimeError("hermes command not found")

    env = _write_hermes_config(env)
    provider, model, env = _runtime_provider(env)
    timeout = int(env.get("HERMES_TIMEOUT_SECONDS") or "180")
    json_retries = max(0, int(env.get("HERMES_JSON_RETRIES") or "1"))
    parse_error: Exception | None = None
    current_prompt = prompt
    for attempt in range(json_retries + 1):
        attempt_no = attempt + 1
        try:
            completed = subprocess.run(
                [
                    command_path,
                    "chat",
                    "--provider",
                    provider,
                    "--model",
                    model,
                    "-Q",
                    "-q",
                    current_prompt,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _process_output_text(exc.stdout)
            stderr = _process_output_text(exc.stderr)
            if stdout:
                _write_hermes_debug(debug_dir, label=call_label, attempt=attempt_no, kind="stdout", content=stdout)
            if stderr:
                _write_hermes_debug(debug_dir, label=call_label, attempt=attempt_no, kind="stderr", content=stderr)
            _write_hermes_debug(debug_dir, label=call_label, attempt=attempt_no, kind="timeout", content=f"timed out after {timeout} seconds")
            raise RuntimeError(f"hermes_timeout:{_safe_debug_label(call_label)}:{timeout}s") from exc
        _write_hermes_debug(debug_dir, label=call_label, attempt=attempt_no, kind="stdout", content=completed.stdout)
        if completed.stderr:
            _write_hermes_debug(debug_dir, label=call_label, attempt=attempt_no, kind="stderr", content=completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "hermes failed")
        try:
            return _extract_json(completed.stdout)
        except Exception as exc:
            parse_error = exc
            _write_hermes_debug(debug_dir, label=call_label, attempt=attempt_no, kind="parse_error", content=str(exc))
            if attempt < json_retries:
                current_prompt = _build_json_repair_prompt(raw_response=completed.stdout, parse_error=exc)

    raise ValueError(f"hermes_invalid_json:{parse_error}") from parse_error


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _block(title: str, summary: str, evidence_id: str) -> dict[str, Any]:
    return {"title": title, "summary": summary, "evidence_ids": [evidence_id]}


def _rankings_from_themes(batch_payloads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    counters: dict[str, Counter[str]] = {"positive": Counter(), "negative": Counter()}
    for payload in batch_payloads:
        for theme in _as_list(payload.get("themes")):
            if not isinstance(theme, dict):
                continue
            direction = theme.get("direction")
            if direction not in counters:
                continue
            term = _clean_text(theme.get("term"), limit=80)
            if not term:
                continue
            count = int(theme.get("count") or 1)
            counters[direction][term] += max(count, 1)
    return {
        direction: [{"term": term, "count": count} for term, count in counter.most_common(10)]
        for direction, counter in counters.items()
    }


def _normalize_rankings(payload: dict[str, Any], batch_payloads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rankings = payload.get("keyword_rankings") if isinstance(payload.get("keyword_rankings"), dict) else {}
    derived = _rankings_from_themes(batch_payloads)
    normalized: dict[str, list[dict[str, Any]]] = {}
    for direction in ("positive", "negative"):
        values = _as_list(rankings.get(direction))
        items: list[dict[str, Any]] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            term = _clean_text(item.get("term"), limit=80)
            if not term:
                continue
            items.append({"term": term, "count": int(item.get("count") or item.get("weight") or 1)})
        normalized[direction] = items[:10] or derived[direction]
    return normalized


def _normalize_blocks(value: Any, *, fallback_title: str, fallback_summary: str, evidence_id: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        title = _clean_generated_text(item.get("title"), limit=80) or fallback_title
        summary = _clean_generated_text(item.get("summary"), limit=500)
        if not summary:
            continue
        evidence_ids = [str(eid) for eid in _as_list(item.get("evidence_ids")) if str(eid).strip()]
        blocks.append({"title": title, "summary": summary, "evidence_ids": evidence_ids or [evidence_id]})
    return blocks or [_block(fallback_title, fallback_summary, evidence_id)]


def _summary_from_rankings(items: list[dict[str, Any]]) -> str:
    terms = [str(item.get("term")) for item in items[:5] if item.get("term")]
    return "、".join(terms) if terms else "样本不足，暂未形成稳定主题"


def _evidence_ids_from_themes(batch_payloads: list[dict[str, Any]], direction: str, *, limit: int = 8) -> list[str]:
    evidence_ids: list[str] = []
    for payload in batch_payloads:
        for theme in _as_list(payload.get("themes")):
            if not isinstance(theme, dict) or theme.get("direction") != direction:
                continue
            for evidence_id in _compact_evidence_ids(theme.get("evidence_ids"), limit=3):
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
                if len(evidence_ids) >= limit:
                    return evidence_ids
    return evidence_ids


def _local_aggregate_payload(
    *,
    model_name: str,
    comments: list[dict[str, str]],
    batch_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    rankings = _rankings_from_themes(batch_payloads)
    positive_summary = _summary_from_rankings(rankings["positive"])
    negative_summary = _summary_from_rankings(rankings["negative"])
    headline = f"{model_name} 口碑核心好评集中在{positive_summary}，主要槽点集中在{negative_summary}。"

    suggestions: list[dict[str, str]] = []
    platform_notes: list[dict[str, str]] = []
    boss_brief: list[str] = []
    for payload in batch_payloads:
        for item in _as_list(payload.get("suggestions")):
            if isinstance(item, dict):
                text = _clean_generated_text(item.get("text"), limit=300)
                if text:
                    suggestions.append({"direction": _clean_generated_text(item.get("direction"), limit=80), "text": text})
        for item in _as_list(payload.get("platform_notes")):
            if isinstance(item, dict):
                summary = _clean_generated_text(item.get("summary"), limit=320)
                if summary:
                    platform_notes.append({"platform": _clean_generated_text(item.get("platform"), limit=80), "summary": summary})
        for line in _as_list(payload.get("boss_brief")):
            text = _clean_generated_text(line, limit=240)
            if text:
                boss_brief.append(text)

    action_blocks = [
        {
            "title": suggestion.get("direction") or "产品建议",
            "summary": suggestion["text"],
            "evidence_ids": [f"hermes.suggestion.{index}"],
        }
        for index, suggestion in enumerate(suggestions[:5], start=1)
    ]
    platform_difference_blocks = [
        {
            "title": note.get("platform") or "平台差异",
            "summary": note["summary"],
            "evidence_ids": [f"hermes.platform.{index}"],
        }
        for index, note in enumerate(platform_notes[:4], start=1)
    ]
    opportunity_rows = [
        {
            "类型": "改进",
            "方向": suggestion.get("direction") or "产品体验",
            "建议": suggestion["text"],
        }
        for suggestion in suggestions[:8]
    ]
    compare_rows = [
        {
            "方向": item["term"],
            "汽车之家_优势提及": str(item["count"]),
            "汽车之家_槽点提及": "0",
            "懂车帝_优势提及": "0",
            "懂车帝_槽点提及": "0",
        }
        for item in rankings["positive"][:5]
    ]
    compare_rows.extend(
        {
            "方向": item["term"],
            "汽车之家_优势提及": "0",
            "汽车之家_槽点提及": str(item["count"]),
            "懂车帝_优势提及": "0",
            "懂车帝_槽点提及": "0",
        }
        for item in rankings["negative"][:5]
    )

    return {
        "headline": headline,
        "executive_summary": f"基于 {len(comments)} 条双平台脱敏原评论的 Hermes 批次分析归并。{headline}",
        "strength_blocks": [
            {
                "title": "核心好评",
                "summary": positive_summary,
                "evidence_ids": _evidence_ids_from_themes(batch_payloads, "positive") or ["hermes.strengths"],
            }
        ],
        "weakness_blocks": [
            {
                "title": "核心槽点",
                "summary": negative_summary,
                "evidence_ids": _evidence_ids_from_themes(batch_payloads, "negative") or ["hermes.weaknesses"],
            }
        ],
        "platform_difference_blocks": platform_difference_blocks,
        "action_blocks": action_blocks,
        "boss_brief": boss_brief[:3],
        "keyword_rankings": rankings,
        "qa_chunks": [],
        "compare_rows": compare_rows,
        "opportunity_rows": opportunity_rows,
    }


def _comment_evidence_chunks(comments: list[dict[str, str]], model_name: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, comment in enumerate(comments, start=1):
        comment_id = comment.get("comment_id") or f"comment_{index:04d}"
        parts = [
            f"平台：{comment.get('platform', '')}",
            f"日期：{comment.get('date', '')}",
            f"车型：{comment.get('model_name') or model_name}",
        ]
        if comment.get("positive_text"):
            parts.append(f"最满意：{comment['positive_text']}")
        if comment.get("negative_text"):
            parts.append(f"最不满意：{comment['negative_text']}")
        if comment.get("full_text"):
            parts.append(f"评价全文：{comment['full_text']}")
        text = _clean_generated_text("；".join(part for part in parts if part), limit=1600)
        if not text:
            continue
        chunks.append(
            {
                "chunk_id": comment_id,
                "source_type": "comment_evidence",
                "text": text,
                "tags": [comment.get("platform", ""), model_name, "原评论证据"],
                "metadata": {
                    "source": "hermes_whitelisted_comment",
                    "platform": comment.get("platform", ""),
                    "date": comment.get("date", ""),
                    "model_name": comment.get("model_name") or model_name,
                },
            }
        )
    return chunks


def _normalize_qa_chunks(
    payload: dict[str, Any],
    report: dict[str, Any],
    model_name: str,
    comments: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, item in enumerate(_as_list(payload.get("qa_chunks")), start=1):
        if not isinstance(item, dict):
            continue
        text = _clean_generated_text(item.get("text"), limit=1000)
        if not text:
            continue
        chunks.append(
            {
                "chunk_id": _clean_generated_text(item.get("chunk_id"), limit=120) or f"hermes_{index}",
                "source_type": _clean_generated_text(item.get("source_type"), limit=80) or "hermes_evidence",
                "text": text,
                "tags": [_clean_generated_text(tag, limit=120) for tag in _as_list(item.get("tags")) if str(tag).strip()],
                "metadata": _replace_legacy_labels(item.get("metadata")) if isinstance(item.get("metadata"), dict) else {"source": "hermes"},
            }
        )
    evidence_chunks = _comment_evidence_chunks(comments or [], model_name)
    if chunks:
        return chunks + evidence_chunks

    chunk_id = 1
    for source_type, blocks in (
        ("strength", report.get("strength_blocks") or []),
        ("weakness", report.get("weakness_blocks") or []),
        ("action", report.get("action_blocks") or []),
        ("comparison", report.get("platform_difference_blocks") or []),
    ):
        for block in blocks:
            text = f"{block.get('title', '')}：{block.get('summary', '')}"
            if _clean_text(text):
                chunks.append(
                    {
                        "chunk_id": f"hermes_{chunk_id}",
                        "source_type": "hermes_evidence",
                        "text": text,
                        "tags": [source_type, model_name],
                        "metadata": {"source": "hermes"},
                    }
                )
                chunk_id += 1
    return chunks + evidence_chunks


def _normalize_hermes_payload(
    payload: dict[str, Any],
    *,
    model_name: str,
    comments: list[dict[str, str]],
    batch_payloads: list[dict[str, Any]],
) -> NormalizedHermesResult:
    rankings = _normalize_rankings(payload, batch_payloads)
    positive_summary = _summary_from_rankings(rankings["positive"])
    negative_summary = _summary_from_rankings(rankings["negative"])

    headline = _clean_generated_text(payload.get("headline"), limit=200) or f"{model_name} 口碑核心好评集中在{positive_summary}，主要槽点集中在{negative_summary}。"
    report = {
        "headline": headline,
        "executive_summary": _clean_generated_text(payload.get("executive_summary"), limit=800) or headline,
        "strength_blocks": _normalize_blocks(
            payload.get("strength_blocks"),
            fallback_title="核心好评",
            fallback_summary=positive_summary,
            evidence_id="hermes.strengths",
        ),
        "weakness_blocks": _normalize_blocks(
            payload.get("weakness_blocks"),
            fallback_title="核心槽点",
            fallback_summary=negative_summary,
            evidence_id="hermes.weaknesses",
        ),
        "platform_difference_blocks": _normalize_blocks(
            payload.get("platform_difference_blocks"),
            fallback_title="平台差异",
            fallback_summary="两平台反馈方向已在关键词和原句证据中归并。",
            evidence_id="hermes.platform",
        ),
        "action_blocks": _normalize_blocks(
            payload.get("action_blocks"),
            fallback_title="产品建议",
            fallback_summary="优先针对高频不满意主题制定产品和传播动作。",
            evidence_id="hermes.actions",
        ),
        "boss_brief": [
            _clean_generated_text(line, limit=200)
            for line in _as_list(payload.get("boss_brief"))
            if _clean_generated_text(line, limit=200)
        ][:3],
    }
    if len(report["boss_brief"]) < 3:
        report["boss_brief"] = [
            report["headline"],
            f"最满意TOP集中在：{positive_summary}。",
            f"最不满意TOP集中在：{negative_summary}。",
        ][:3]

    compare_rows = [_replace_legacy_labels(row) for row in _as_list(payload.get("compare_rows")) if isinstance(row, dict)]
    opportunity_rows = [_replace_legacy_labels(row) for row in _as_list(payload.get("opportunity_rows")) if isinstance(row, dict)]
    one_pager_lines = [
        "双平台口碑一页纸总结",
        report["headline"],
        f"最满意TOP5：{positive_summary}",
        f"最不满意TOP5：{negative_summary}",
        *report["boss_brief"],
    ]
    return NormalizedHermesResult(
        report=report,
        keyword_rankings=rankings,
        qa_chunks=_normalize_qa_chunks(payload, report, model_name, comments),
        one_pager_lines=one_pager_lines,
        compare_rows=compare_rows,
        opportunity_rows=opportunity_rows,
    )


def _write_summary_workbook(
    path: Path,
    *,
    model_name: str,
    comments: list[dict[str, str]],
    result: NormalizedHermesResult,
) -> None:
    counts = Counter(comment["platform"] for comment in comments)
    workbook = Workbook()
    overview = workbook.active
    overview.title = "总览摘要"
    overview.append(["模块", "内容"])
    overview.append(["项目", model_name])
    overview.append(["平台样本", f"汽车之家 {counts.get(PLATFORM_AUTOHOME, 0)} 条；懂车帝 {counts.get(PLATFORM_DCD, 0)} 条"])
    overview.append(["综合一句话", result.report["headline"]])

    compare = workbook.create_sheet("跨平台对比")
    compare.append(["方向", "汽车之家_优势提及", "汽车之家_槽点提及", "懂车帝_优势提及", "懂车帝_槽点提及"])
    for row in result.compare_rows[:8]:
        compare.append(
            [
                _clean_text(row.get("方向"), limit=80) or _clean_text(row.get("title"), limit=80) or "平台差异",
                _clean_text(row.get("汽车之家_优势提及")) or "0",
                _clean_text(row.get("汽车之家_槽点提及")) or "0",
                _clean_text(row.get("懂车帝_优势提及")) or "0",
                _clean_text(row.get("懂车帝_槽点提及")) or "0",
            ]
        )
    if compare.max_row == 1:
        compare.append(["整体", "0", "0", "0", "0"])

    business = workbook.create_sheet("综合业务摘要")
    business.append(["模块", "内容"])
    business.append(["核心好评", result.report["strength_blocks"][0]["summary"]])
    business.append(["核心槽点", result.report["weakness_blocks"][0]["summary"]])
    business.append(["产品建议", result.report["action_blocks"][0]["summary"]])
    business.append(["适合人群", "关注高频好评主题且能接受当前槽点的潜在用户"])

    opportunity = workbook.create_sheet("产品机会点")
    opportunity.append(["类型", "方向", "建议"])
    for row in result.opportunity_rows[:8]:
        opportunity.append(
            [
                _clean_text(row.get("类型"), limit=80) or "改进",
                _clean_text(row.get("方向"), limit=80) or _clean_text(row.get("title"), limit=80) or "产品体验",
                _clean_text(row.get("建议"), limit=500) or _clean_text(row.get("summary"), limit=500),
            ]
        )
    if opportunity.max_row == 1:
        for block in result.report["action_blocks"][:3]:
            opportunity.append(["改进", block["title"], block["summary"]])

    one_pager = workbook.create_sheet("一页纸总结")
    for line in result.one_pager_lines:
        one_pager.append([line])

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def _write_terms_workbook(path: Path, rankings: dict[str, list[dict[str, Any]]]) -> None:
    workbook = Workbook()
    positive = workbook.active
    positive.title = "positive_terms"
    positive.append(["term", "weight"])
    for item in rankings.get("positive", []):
        positive.append([item.get("term"), item.get("count", 1)])

    negative = workbook.create_sheet("negative_terms")
    negative.append(["term", "weight"])
    for item in rankings.get("negative", []):
        negative.append([item.get("term"), item.get("count", 1)])

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def _font_path(font_path: str | None) -> str | None:
    if not font_path:
        return None
    path = Path(font_path)
    return str(path) if path.exists() else None


def _fallback_wordcloud_png(path: Path, title: str, terms: list[dict[str, Any]], font_path: str | None) -> None:
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    cjk_font = _font_path(font_path)
    if cjk_font:
        try:
            font = ImageFont.truetype(cjk_font, 28)
        except OSError:
            font = ImageFont.load_default()
    draw.text((40, 40), title, fill=(30, 30, 30), font=font)
    text = "  ".join(str(item.get("term", "")) for item in terms[:20] if item.get("term"))
    draw.text((40, 110), text or "暂无高频词", fill=(70, 70, 70), font=font)
    image.save(path)


def _write_wordclouds(output_dir: Path, *, model_name: str, rankings: dict[str, list[dict[str, Any]]], font_path: str | None) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    image_paths = [
        output_dir / f"{model_name}_优点词云.png",
        output_dir / f"{model_name}_槽点词云.png",
    ]
    try:
        from wordcloud import WordCloud

        for direction, image_path in (("positive", image_paths[0]), ("negative", image_paths[1])):
            frequencies = {str(item["term"]): int(item.get("count") or 1) for item in rankings.get(direction, []) if item.get("term")}
            if not frequencies:
                _fallback_wordcloud_png(image_path, image_path.stem, rankings.get(direction, []), font_path)
                continue
            cloud = WordCloud(
                width=900,
                height=500,
                background_color="white",
                font_path=_font_path(font_path),
                collocations=False,
            )
            cloud.generate_from_frequencies(frequencies)
            cloud.to_file(str(image_path))
    except Exception:
        _fallback_wordcloud_png(image_paths[0], f"{model_name} 优点词云", rankings.get("positive", []), font_path)
        _fallback_wordcloud_png(image_paths[1], f"{model_name} 槽点词云", rankings.get("negative", []), font_path)
    return [str(path) for path in image_paths if path.exists()]


def _write_report_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_replace_legacy_labels(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_qa_chunks(path: Path, chunks: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_validation(path: Path, *, source: str, degraded: bool) -> None:
    path.write_text(
        json.dumps({"ok": True, "source": source, "degraded": degraded}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_checked(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"{command[0]} failed")
    return completed


def _read_table(workbook, sheet_name: str) -> list[dict[str, str]]:
    if sheet_name not in workbook.sheetnames:
        return []
    rows = list(workbook[sheet_name].iter_rows(values_only=True))
    if not rows:
        return []
    header = [_clean_text(cell) for cell in rows[0]]
    values: list[dict[str, str]] = []
    for row in rows[1:]:
        item = {header[index]: _clean_text(row[index]) for index in range(min(len(header), len(row))) if header[index]}
        if any(item.values()):
            values.append(item)
    return values


def _read_one_pager(workbook) -> list[str]:
    if "一页纸总结" not in workbook.sheetnames:
        return []
    lines: list[str] = []
    for row in workbook["一页纸总结"].iter_rows(values_only=True):
        line = " ".join(_clean_text(value) for value in row if _clean_text(value))
        if line:
            lines.append(line)
    return lines


def _report_from_summary(summary_path: Path, *, model_name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    workbook = load_workbook(summary_path, data_only=True)
    try:
        overview = {row.get("模块", ""): row.get("内容", "") for row in _read_table(workbook, "总览摘要")}
        business = {row.get("模块", ""): row.get("内容", "") for row in _read_table(workbook, "综合业务摘要")}
        opportunities = _read_table(workbook, "产品机会点")
        one_pager = _read_one_pager(workbook)
    finally:
        workbook.close()

    report = {
        "headline": overview.get("综合一句话") or (one_pager[1] if len(one_pager) > 1 else f"{model_name} 口碑摘要"),
        "executive_summary": one_pager[1] if len(one_pager) > 1 else overview.get("综合一句话", ""),
        "strength_blocks": [_block("核心好评", business.get("核心好评") or business.get("核心卖点", ""), "business.core_strengths")],
        "weakness_blocks": [_block("核心槽点", business.get("核心槽点", ""), "business.core_weaknesses")],
        "platform_difference_blocks": [],
        "action_blocks": [
            _block(row.get("方向") or row.get("类型") or "产品建议", row.get("建议", ""), f"opportunity.{index}")
            for index, row in enumerate(opportunities[:3], start=1)
            if row.get("建议")
        ],
        "boss_brief": [line for line in one_pager[1:4] if line][:3],
    }
    chunks = _normalize_qa_chunks({}, report, model_name)
    return report, chunks


def _run_rule_fallback(
    *,
    autohome_input: Path,
    dcd_input: Path | None,
    summary_output: Path,
    terms_output: Path,
    wordcloud_output_dir: Path,
    final_report_output: Path,
    qa_chunks_output: Path,
    model_name: str,
    progress_file: Path,
    summary_script: Path,
    wordcloud_script: Path,
    single_platform: bool,
    font_path: str | None,
) -> dict[str, Any]:
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    summary_command = [
        sys.executable,
        str(summary_script),
        "--output",
        str(summary_output),
        "--model-name",
        model_name,
        "--progress-file",
        str(progress_file),
    ]
    if single_platform or not dcd_input or not dcd_input.exists():
        summary_command.extend(["--input", str(autohome_input)])
    else:
        summary_command.extend(["--autohome-input", str(autohome_input), "--dcd-input", str(dcd_input)])
    _run_checked(summary_command, cwd=summary_script.parent)

    wordcloud_command = [
        sys.executable,
        str(wordcloud_script),
        "--input",
        str(summary_output),
        "--output-dir",
        str(wordcloud_output_dir),
        "--model-name",
        model_name,
        "--json",
    ]
    if font_path:
        wordcloud_command.extend(["--font-path", font_path])
    completed = _run_checked(wordcloud_command, cwd=wordcloud_script.parent)
    try:
        payload = _extract_json(completed.stdout)
    except Exception:
        payload = {}
    produced_terms = Path(payload.get("excel_path", "")) if isinstance(payload, dict) and payload.get("excel_path") else terms_output
    if produced_terms.exists() and produced_terms.resolve() != terms_output.resolve():
        terms_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(produced_terms, terms_output)

    report, chunks = _report_from_summary(summary_output, model_name=model_name)
    _write_report_json(final_report_output, report)
    _write_qa_chunks(qa_chunks_output, chunks)
    _write_validation(summary_output.with_suffix(".validation.json"), source="rule-fallback", degraded=True)
    return {
        "summary_path": str(summary_output),
        "terms_path": str(terms_output),
        "final_report_path": str(final_report_output),
        "qa_chunks_path": str(qa_chunks_output),
        "image_paths": payload.get("image_paths", []) if isinstance(payload, dict) else [],
    }


def generate_outputs(
    *,
    autohome_input: str | Path,
    dcd_input: str | Path | None,
    postprocess_input: str | Path | None,
    summary_output: str | Path,
    terms_output: str | Path,
    wordcloud_output_dir: str | Path,
    final_report_output: str | Path,
    qa_chunks_output: str | Path,
    model_name: str,
    progress_file: str | Path,
    summary_script: str | Path,
    wordcloud_script: str | Path,
    hermes_command: str = "hermes",
    single_platform: bool = False,
    font_path: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    active_env = dict(env or os.environ)
    autohome_path = Path(autohome_input)
    dcd_path = Path(dcd_input) if dcd_input else None
    summary_path = Path(summary_output)
    terms_path = Path(terms_output)
    wordcloud_dir = Path(wordcloud_output_dir)
    final_report_path = Path(final_report_output)
    qa_chunks_path = Path(qa_chunks_output)
    progress_path = Path(progress_file)
    debug_dir_value = (active_env.get("HERMES_DEBUG_DIR") or "").strip()
    hermes_debug_dir = Path(debug_dir_value) if debug_dir_value else progress_path.parent.parent / "logs" / "hermes"
    _reset_hermes_debug_dir(hermes_debug_dir)
    comments = extract_whitelisted_comments(autohome_input=autohome_path, dcd_input=dcd_path, model_name=model_name)
    _write_progress(progress_path, percent=10, message=f"读取脱敏原评论 {len(comments)} 条")

    fallback_reason = ""
    api_key = (active_env.get("LLM_API_KEY") or active_env.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        fallback_reason = "hermes_disabled:missing_llm_api_key"

    if not fallback_reason:
        try:
            batch_size = int(active_env.get("HERMES_BATCH_SIZE") or DEFAULT_BATCH_SIZE)
            batches = _batch_items(comments, batch_size)
            batch_payloads: list[dict[str, Any]] = []
            total_batches = max(len(batches), 1)
            for index, batch in enumerate(batches or [[]], start=1):
                _write_progress(progress_path, percent=10 + int(index * 50 / total_batches), message=f"Hermes 分析批次 {index}/{total_batches}")
                payload = _call_hermes(
                    _build_batch_prompt(model_name=model_name, batch_index=index, total_batches=total_batches, comments=batch),
                    hermes_command=hermes_command,
                    env=active_env,
                    debug_dir=hermes_debug_dir,
                    call_label=f"batch_{index:03d}",
                )
                if not isinstance(payload, dict):
                    raise ValueError("hermes_invalid_json:batch payload is not object")
                batch_payloads.append(payload)

            _write_progress(progress_path, percent=70, message="Hermes 汇总批次结果")
            aggregate_source = "hermes"
            aggregate_fallback_reason = ""
            aggregate_env = dict(active_env)
            aggregate_timeout = (active_env.get("HERMES_AGGREGATE_TIMEOUT_SECONDS") or "").strip()
            if aggregate_timeout:
                aggregate_env["HERMES_TIMEOUT_SECONDS"] = aggregate_timeout
            try:
                aggregate_payload = _call_hermes(
                    _build_aggregate_prompt(model_name=model_name, comments=comments, batch_payloads=batch_payloads),
                    hermes_command=hermes_command,
                    env=aggregate_env,
                    debug_dir=hermes_debug_dir,
                    call_label="aggregate",
                )
                if not isinstance(aggregate_payload, dict):
                    raise ValueError("hermes_invalid_json:aggregate payload is not object")
            except Exception as exc:
                aggregate_fallback_reason = str(exc)
                aggregate_source = "hermes-local-aggregate"
                _write_progress(progress_path, percent=82, message="Hermes 汇总超时，使用批次结果本地归并")
                aggregate_payload = _local_aggregate_payload(model_name=model_name, comments=comments, batch_payloads=batch_payloads)

            normalized = _normalize_hermes_payload(aggregate_payload, model_name=model_name, comments=comments, batch_payloads=batch_payloads)
            _write_summary_workbook(summary_path, model_name=model_name, comments=comments, result=normalized)
            _write_terms_workbook(terms_path, normalized.keyword_rankings)
            image_paths = _write_wordclouds(wordcloud_dir, model_name=model_name, rankings=normalized.keyword_rankings, font_path=font_path)
            _write_report_json(final_report_path, normalized.report)
            _write_qa_chunks(qa_chunks_path, normalized.qa_chunks)
            _write_validation(summary_path.with_suffix(".validation.json"), source=aggregate_source, degraded=False)
            _write_progress(progress_path, percent=100, message="Hermes 输出已生成")
            result = {
                "status": "success",
                "degraded": False,
                "source": aggregate_source,
                "summary_path": str(summary_path),
                "terms_path": str(terms_path),
                "final_report_path": str(final_report_path),
                "qa_chunks_path": str(qa_chunks_path),
                "image_paths": image_paths,
                "postprocess_path": str(postprocess_input or ""),
            }
            if aggregate_fallback_reason:
                result["aggregate_fallback_reason"] = aggregate_fallback_reason
            return result
        except Exception as exc:
            fallback_reason = str(exc)

    _write_progress(progress_path, percent=75, message="Hermes 不可用，切换到规则兜底", degraded=True)
    fallback = _run_rule_fallback(
        autohome_input=autohome_path,
        dcd_input=dcd_path,
        summary_output=summary_path,
        terms_output=terms_path,
        wordcloud_output_dir=wordcloud_dir,
        final_report_output=final_report_path,
        qa_chunks_output=qa_chunks_path,
        model_name=model_name,
        progress_file=progress_path,
        summary_script=Path(summary_script),
        wordcloud_script=Path(wordcloud_script),
        single_platform=single_platform,
        font_path=font_path,
    )
    _write_progress(progress_path, percent=100, message="规则兜底输出已生成", degraded=True)
    return {
        "status": "degraded",
        "degraded": True,
        "source": "rule-fallback",
        "fallback_reason": fallback_reason,
        **fallback,
    }


def generate_time_report_outputs(
    *,
    autohome_input: str | Path,
    dcd_input: str | Path | None,
    output_dir: str | Path,
    model_name: str,
    start_date: str,
    end_date: str,
    hermes_command: str = "hermes",
    font_path: str | None = None,
    env: dict[str, str] | None = None,
    progress_file: str | Path | None = None,
) -> dict[str, Any]:
    active_env = dict(env or os.environ)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    progress_path = Path(progress_file) if progress_file else output_path / "time_report.progress.json"
    debug_dir_value = (active_env.get("HERMES_DEBUG_DIR") or "").strip()
    hermes_debug_dir = Path(debug_dir_value) if debug_dir_value else output_path / "logs" / "hermes"
    _reset_hermes_debug_dir(hermes_debug_dir)

    comments = extract_whitelisted_comments(autohome_input=autohome_input, dcd_input=dcd_input, model_name=model_name)
    selected_comments = _filter_comments_for_date_range(comments, start_date=start_date, end_date=end_date)
    if not selected_comments:
        raise ValueError("no_comments_in_date_range")

    platform_counts = dict(Counter(comment["platform"] for comment in selected_comments))
    _write_progress(progress_path, percent=10, message=f"读取时间范围内脱敏原评论 {len(selected_comments)} 条")

    date_label = f"{start_date}_{end_date}"
    summary_path = output_path / f"{model_name}_{date_label}_时间范围口碑摘要.xlsx"
    terms_path = output_path / f"{model_name}_{date_label}_词云词项清单.xlsx"
    final_report_path = output_path / "final_report.json"
    qa_chunks_path = output_path / "qa_chunks.json"
    validation_path = summary_path.with_suffix(".validation.json")

    api_key = (active_env.get("LLM_API_KEY") or active_env.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("hermes_disabled:missing_llm_api_key")

    batch_size = int(active_env.get("HERMES_BATCH_SIZE") or DEFAULT_BATCH_SIZE)
    batches = _batch_items(selected_comments, batch_size)
    total_batches = max(len(batches), 1)
    batch_payloads: list[dict[str, Any]] = []
    batch_fallbacks: list[dict[str, Any]] = []
    for index, batch in enumerate(batches or [[]], start=1):
        _write_progress(progress_path, percent=10 + int(index * 50 / total_batches), message=f"Hermes 分析时间范围批次 {index}/{total_batches}")
        try:
            payload = _call_hermes(
                _build_batch_prompt(model_name=model_name, batch_index=index, total_batches=total_batches, comments=batch),
                hermes_command=hermes_command,
                env=active_env,
                debug_dir=hermes_debug_dir,
                call_label=f"batch_{index:03d}",
            )
        except Exception as exc:
            reason = str(exc) or exc.__class__.__name__
            batch_fallbacks.append({"batch": index, "reason": reason})
            _write_progress(
                progress_path,
                percent=10 + int(index * 50 / total_batches),
                message=f"Hermes 时间范围批次 {index}/{total_batches} 失败，使用本地批次兜底",
            )
            payload = _local_batch_payload(batch_index=index, total_batches=total_batches, comments=batch, reason=reason)
        if not isinstance(payload, dict):
            raise ValueError("hermes_invalid_json:batch payload is not object")
        batch_payloads.append(payload)

    _write_progress(progress_path, percent=70, message="Hermes 汇总时间范围批次结果")
    aggregate_source = "hermes-partial-local-batch" if batch_fallbacks else "hermes"
    aggregate_fallback_reason = ""
    aggregate_env = dict(active_env)
    aggregate_timeout = (active_env.get("HERMES_AGGREGATE_TIMEOUT_SECONDS") or "").strip()
    if aggregate_timeout:
        aggregate_env["HERMES_TIMEOUT_SECONDS"] = aggregate_timeout
    try:
        aggregate_payload = _call_hermes(
            _build_aggregate_prompt(model_name=model_name, comments=selected_comments, batch_payloads=batch_payloads),
            hermes_command=hermes_command,
            env=aggregate_env,
            debug_dir=hermes_debug_dir,
            call_label="aggregate",
        )
        if not isinstance(aggregate_payload, dict):
            raise ValueError("hermes_invalid_json:aggregate payload is not object")
    except Exception as exc:
        aggregate_fallback_reason = str(exc)
        aggregate_source = "hermes-local-aggregate"
        _write_progress(progress_path, percent=82, message="Hermes 汇总超时，使用时间范围批次结果本地归并")
        aggregate_payload = _local_aggregate_payload(model_name=model_name, comments=selected_comments, batch_payloads=batch_payloads)

    normalized = _normalize_hermes_payload(aggregate_payload, model_name=model_name, comments=selected_comments, batch_payloads=batch_payloads)
    normalized.report["report_type"] = "time_range"
    normalized.report["time_range"] = {"start_date": start_date, "end_date": end_date}
    normalized.report["sample_count"] = len(selected_comments)
    normalized.report["platform_counts"] = platform_counts

    _write_summary_workbook(summary_path, model_name=model_name, comments=selected_comments, result=normalized)
    _write_terms_workbook(terms_path, normalized.keyword_rankings)
    image_paths = _write_wordclouds(output_path, model_name=model_name, rankings=normalized.keyword_rankings, font_path=font_path)
    _write_report_json(final_report_path, normalized.report)
    _write_qa_chunks(qa_chunks_path, normalized.qa_chunks)
    _write_validation(validation_path, source=aggregate_source, degraded=False)
    _write_progress(progress_path, percent=100, message="时间范围 Hermes 一页纸已生成")

    artifact_paths = [
        str(final_report_path),
        str(summary_path),
        str(validation_path),
        str(terms_path),
        str(qa_chunks_path),
        *image_paths,
    ]
    result = {
        "status": "completed",
        "degraded": False,
        "source": aggregate_source,
        "sample_count": len(selected_comments),
        "platform_counts": platform_counts,
        "summary_path": str(summary_path),
        "terms_path": str(terms_path),
        "final_report_path": str(final_report_path),
        "qa_chunks_path": str(qa_chunks_path),
        "validation_path": str(validation_path),
        "image_paths": image_paths,
        "artifact_paths": artifact_paths,
        "report_json": normalized.report,
    }
    if aggregate_fallback_reason:
        result["aggregate_fallback_reason"] = aggregate_fallback_reason
    if batch_fallbacks:
        result["batch_fallbacks"] = batch_fallbacks
    return result


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate final koubei outputs through Hermes Agent with rule fallback.")
    parser.add_argument("--autohome-input", required=True)
    parser.add_argument("--dcd-input")
    parser.add_argument("--postprocess-input")
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--terms-output", required=True)
    parser.add_argument("--wordcloud-output-dir", required=True)
    parser.add_argument("--final-report-output", required=True)
    parser.add_argument("--qa-chunks-output", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--summary-script", required=True)
    parser.add_argument("--wordcloud-script", required=True)
    parser.add_argument("--hermes-command", default=os.getenv("HERMES_COMMAND", "hermes"))
    parser.add_argument("--font-path")
    parser.add_argument("--single-platform", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    result = generate_outputs(
        autohome_input=args.autohome_input,
        dcd_input=args.dcd_input,
        postprocess_input=args.postprocess_input,
        summary_output=args.summary_output,
        terms_output=args.terms_output,
        wordcloud_output_dir=args.wordcloud_output_dir,
        final_report_output=args.final_report_output,
        qa_chunks_output=args.qa_chunks_output,
        model_name=args.model_name,
        progress_file=args.progress_file,
        summary_script=args.summary_script,
        wordcloud_script=args.wordcloud_script,
        hermes_command=args.hermes_command,
        single_platform=args.single_platform,
        font_path=args.font_path,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
