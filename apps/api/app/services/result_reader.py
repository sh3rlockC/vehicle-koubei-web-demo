from __future__ import annotations

import re
from pathlib import Path

from openpyxl import load_workbook


def _iter_table_rows(worksheet, *, limit: int | None = None) -> list[dict[str, str]]:
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
    data_rows: list[dict[str, str]] = []
    for row in rows[1:]:
        values = {header[index]: row[index] for index in range(min(len(header), len(row))) if header[index]}
        if not any(value not in (None, "") for value in values.values()):
            continue
        normalized = {key: "" if value is None else str(value) for key, value in values.items()}
        data_rows.append(normalized)
        if limit is not None and len(data_rows) >= limit:
            break
    return data_rows


def _parse_sample_counts(overview_rows: list[dict[str, str]]) -> dict[str, int]:
    for row in overview_rows:
        if row.get("模块") != "平台样本":
            continue
        content = row.get("内容", "")
        match = re.search(r"汽车之家\s+(\d+)\s+条.*?懂车帝\s+(\d+)\s+条", content)
        if match:
            return {
                "autohome_count": int(match.group(1)),
                "dcd_count": int(match.group(2)),
            }
    return {"autohome_count": 0, "dcd_count": 0}


def _read_one_pager_lines(worksheet, *, limit: int = 12) -> list[str]:
    lines: list[str] = []
    for row in worksheet.iter_rows(values_only=True):
        values = [str(value).strip() for value in row if value not in (None, "")]
        if not values:
            continue
        lines.append(" ".join(values))
        if len(lines) >= limit:
            break
    return lines


def read_summary_workbook(path: str | Path) -> dict:
    workbook = load_workbook(Path(path), data_only=True)

    overview_rows = _iter_table_rows(workbook["总览摘要"])
    compare_rows = _iter_table_rows(workbook["跨平台对比"], limit=8)
    business_rows = _iter_table_rows(workbook["综合业务摘要"])
    opportunity_rows = _iter_table_rows(workbook["产品机会点"], limit=8)
    one_pager_lines = _read_one_pager_lines(workbook["一页纸总结"])

    return {
        "sample_counts": _parse_sample_counts(overview_rows),
        "overview_rows": overview_rows,
        "compare_rows": compare_rows,
        "business_rows": business_rows,
        "opportunity_rows": opportunity_rows,
        "one_pager_lines": one_pager_lines,
    }
