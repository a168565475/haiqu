"""日期表示归一；不替模型裁决任务交期或不同批次的业务含义。"""

import copy
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl.styles.numbers import BUILTIN_FORMATS, is_datetime
from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900, from_excel


TASK_DATE_FIELDS = ("order_date", "delivery_date", "planned_start_date", "planned_end_date")


def cell_date(cell, source):
    """仅转换具有日期格式的真实数值单元格，原始序列值另行保留。"""
    if cell.get("type") != "n":
        return None
    format_id = str(cell.get("num_format_id", ""))
    number_format = cell.get("num_format") or BUILTIN_FORMATS.get(int(format_id) if format_id.isdigit() else -1, "")
    if is_datetime(number_format) not in {"date", "datetime"}:
        return None
    try:
        serial = Decimal(str(cell.get("cache") if cell.get("formula") else cell.get("text")))
        mac = source.get("date1904") in (True, 1, "1", "true")
        if not serial.is_finite() or serial < 1 or (not mac and 60 <= serial < 61):
            return None  # Excel 1900年的虚构2月29日不是有效公历日期。
        converted = from_excel(float(serial), CALENDAR_MAC_1904 if mac else CALENDAR_WINDOWS_1900)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None
    return converted.date().isoformat() if isinstance(converted, datetime) else None


def _iso_date(value, evidence, cells, source):
    text = str(value).strip()
    match = re.fullmatch(r"(\d{4})\s*(?:[-/.]|年)\s*(\d{1,2})\s*(?:[-/.]|月)\s*(\d{1,2})\s*日?", text)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            return None
    # 数字只有与引用的日期单元格一致才是日期，不能把任意订单数量当序列号。
    candidates = set()
    for source_id in evidence.get("source_ids", []):
        cell = cells.get(source_id, {})
        try:
            raw = cell.get("cache") if cell.get("formula") else cell.get("text")
            if Decimal(text) != Decimal(str(raw)):
                continue
        except (InvalidOperation, ValueError, TypeError):
            continue
        normalized = cell_date(cell, source)
        if normalized:
            candidates.add(normalized)
    return next(iter(candidates)) if len(candidates) == 1 else None


def normalize_date_fields(result, source):
    output = copy.deepcopy(result)
    cells = {cell.get("source_id"): cell for sheet in source.get("sheets", []) for cell in sheet.get("cells", [])}
    for block in [output, *output.get("additional_tasks", [])]:
        task = block.get("task", {})
        fields = [(key, task.get(key)) for key in TASK_DATE_FIELDS]
        fields.extend((f"delivery_batches[{index}].delivery_date", batch.get("delivery_date"))
                      for index, batch in enumerate(task.get("delivery_batches", [])))
        for path, field in fields:
            if not isinstance(field, dict) or field.get("status") != "EXTRACTED" or field.get("value") is None:
                continue
            original = field["value"]
            normalized = _iso_date(original, field, cells, source)
            if normalized:
                field["value"] = normalized
                if original != normalized:
                    field["note"] = (field.get("note", "") + f" 日期原值{original}，按原表日期格式归一为{normalized}。").strip()
            else:
                field.update(value=None, status="UNREADABLE",
                             note=(field.get("note", "") + f" 日期原值{original}无法确定为有效完整日期，待核对。").strip())
                issues = block.setdefault("issues", [])
                key = f"date_format_{path}"
                existing = {issue.get("issue_key") for issue in issues}
                while key in existing:
                    key += "_date"
                issues.append({"issue_key": key, "kind": "DATE_FORMAT_INVALID",
                               "message": f"{path}的日期原值{original}无法确定为有效完整日期，已保留原值待核对。",
                               "source_ids": field.get("source_ids", [])})
    return output
