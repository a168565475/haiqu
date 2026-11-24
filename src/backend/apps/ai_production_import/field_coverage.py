"""按原表证据补齐管材遗漏字段，不推算、写库或覆盖已判读内容。"""

import copy
import re
import unicodedata
from decimal import Decimal, InvalidOperation


TUBE_REQUIRED_FIELDS = {
    "length_value": "切割长度（mm）",
    "unit_consumption": "每成品单耗",
    "tube_cut_piece_count": "每根切割支数",
}
_CUT_HEADERS = {"切割支数", "每根切数", "每根切割支数", "每根切割数量", "每根可切支数"}
_ISSUE_KINDS = {"BOM_FIELD_MISSING", "BOM_FIELD_CONFLICT"}


def _text(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


def _position(ref):
    match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", str(ref))
    if not match:
        return None
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - ord("A") + 1
    return int(match[2]), column


def _positive_number(value, *, integer=False):
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number <= 0:
        return None
    if integer and (number != number.to_integral_value() or number > 2147483647):
        return None
    return number


def _source_cells(source):
    known = source.get("source_index", {})
    cells_by_id, sheets = {}, []
    for sheet in source.get("sheets", []):
        cells = {}
        for cell in sheet.get("cells", []):
            identifier = cell.get("source_id")
            indexed = known.get(identifier, {})
            position = _position(cell.get("ref"))
            matches_sheet = (indexed.get("sheet_part") == sheet.get("part") if indexed.get("sheet_part")
                             else indexed.get("sheet") == sheet.get("name"))
            if not position or indexed.get("kind") != "cell" or indexed.get("ref") != cell.get("ref") or not matches_sheet:
                continue
            cells[position] = cell
            cells_by_id[identifier] = (len(sheets), position, cell)
        merges = []
        for merged in sheet.get("merged_cells", []):
            endpoints = str(merged).split(":")
            if len(endpoints) == 2:
                first, last = map(_position, endpoints)
                if first and last:
                    merges.append((first, last))
        sheets.append({"name": sheet.get("name", ""), "cells": cells, "merges": merges})
    return cells_by_id, sheets


def _material_row(line, cells_by_id):
    part = line.get("part_name", {})
    raw_ids = set(line.get("raw_content", {}).get("source_ids", []))
    candidates = {}
    if part.get("status") != "EXTRACTED" or not _text(part.get("value")):
        return None
    for identifier in part.get("source_ids", []):
        found = cells_by_id.get(identifier)
        if found and identifier in raw_ids and _text(found[2].get("text")) == _text(part["value"]):
            candidates[(found[0], found[1][0])] = identifier
    return (*next(iter(candidates)), next(iter(candidates.values()))) if len(candidates) == 1 else None


def _length_group_header(sheet, row, left, right):
    headers = []
    for first, last in sheet["merges"]:
        if last[0] < row and first[1] <= left and last[1] >= right:
            cell = sheet["cells"].get(first)
            if cell and _text(cell.get("text")):
                headers.append((last[0], cell))
    if not headers:
        return None
    cell = max(headers, key=lambda item: item[0])[1]
    return cell if re.search(r"(?:原材料|原料|长料)长度|长料长", _text(cell.get("text"))) else None


def _cut_column_header(sheet, row, column):
    # 只认明确的每根切数列；单独“支数”通常为采购量，不能采用。
    headers = []
    for position, cell in sheet["cells"].items():
        if position[0] >= row or not _text(cell.get("text")) or _positive_number(cell.get("text")) is not None:
            continue
        covered = position[1] == column or any(first == position and first[1] <= column <= last[1]
                                              for first, last in sheet["merges"])
        if covered:
            headers.append((position[0], cell))
    if not headers:
        return None
    cell = max(headers, key=lambda item: item[0])[1]
    label = re.sub(r"\((?:支|支/根|根)\)$", "", _text(cell.get("text")))
    return cell if label in _CUT_HEADERS else None


def _recover_cut_count(line, cells_by_id, sheets):
    located = _material_row(line, cells_by_id)
    if located is None:
        return None, "未能从品名与原文引用确定唯一材料行。"
    sheet_index, row, part_id = located
    sheet = sheets[sheet_index]
    raw_ids = set(line.get("raw_content", {}).get("source_ids", []))
    candidates = []
    for (cell_row, column), cell in sheet["cells"].items():
        if cell_row != row or cell["source_id"] not in raw_ids:
            continue
        number = _positive_number(cell.get("text"), integer=True)
        if number is None:
            continue
        sources = []
        left, right = sheet["cells"].get((row, column - 1), {}), sheet["cells"].get((row, column + 1), {})
        header = _length_group_header(sheet, row, column - 1, column + 1)
        if (_text(left.get("text")) == "切" and _text(right.get("text")) == "支" and header
                and left.get("source_id") in raw_ids and right.get("source_id") in raw_ids):
            sources = [part_id, header["source_id"], left["source_id"], cell["source_id"], right["source_id"]]
        else:
            header = _cut_column_header(sheet, row, column)
            if header:
                sources = [part_id, header["source_id"], cell["source_id"]]
        if sources:
            candidates.append((int(number), sources, cell["ref"]))
    if not candidates:
        return None, "未取得同行明确的每根切割支数；不能用总支数、单耗或长料长度推算。"
    values = {item[0] for item in candidates}
    source_ids = list(dict.fromkeys(identifier for item in candidates for identifier in item[1]))
    if len(values) > 1:
        positions = "、".join(f"{sheet['name']}!{item[2]}={item[0]}" for item in candidates)
        return {"value": None, "status": "CONFLICT", "source_ids": source_ids,
                "note": f"A01：同一材料行切割支数冲突（{positions}），待核对。"}, ""
    value = candidates[0][0]
    positions = "、".join(f"{sheet['name']}!{item[2]}" for item in candidates)
    return {"value": value, "status": "EXTRACTED", "source_ids": source_ids,
            "note": f"A01 来源补齐：按原表明确切割支数 {positions} 读取为 {value}，未按长度推算。"}, ""


def complete_tube_field_coverage(result, source):
    """接收 normalize_erp_fields 后的结果，返回独立副本；每个任务保留自己的问题。"""
    completed = copy.deepcopy(result)
    cells_by_id, sheets = _source_cells(source)
    for block in [completed, *completed.get("additional_tasks", [])]:
        for bom in block.get("boms", []):
            for line in bom.get("lines", []):
                if line.get("section") != "管材类":
                    continue
                fields = line.setdefault("erp_fields", {})
                for key, label in TUBE_REQUIRED_FIELDS.items():
                    existing = fields.get(key)
                    if existing is not None and existing.get("status") != "MISSING":
                        continue
                    issue_key = f"field-coverage/{bom['product_key']}/{line['line_key']}/{key}"
                    block["issues"] = [issue for issue in block.get("issues", [])
                                       if not (issue["issue_key"] == issue_key and issue["kind"] in _ISSUE_KINDS)]
                    field, reason = None, "未取得对应结果，请核对原表。"
                    if key == "tube_cut_piece_count":
                        field, reason = _recover_cut_count(line, cells_by_id, sheets)
                    elif key == "unit_consumption":
                        quantity, unit = line.get("quantity", {}), line.get("unit", {})
                        if (line.get("quantity_basis") == "UNIT_CONSUMPTION" and quantity.get("status") == "EXTRACTED"
                                and unit.get("status") == "EXTRACTED" and _text(unit.get("value"))
                                and _positive_number(quantity.get("value")) is not None):
                            field = copy.deepcopy(quantity)
                            field["note"] = (field.get("note", "") + "；按已明确的每成品用量承接单耗。").lstrip("；")
                    if field is None:
                        field = {"value": None, "status": "MISSING", "source_ids": list((existing or {}).get("source_ids", [])),
                                 "note": f"A01：{label}{reason}"}
                    fields[key] = field
                    if field["status"] != "EXTRACTED":
                        name = line.get("part_name", {}).get("value") or line["line_key"]
                        block["issues"].append({"issue_key": issue_key, "kind": f"BOM_FIELD_{field['status']}",
                                                "message": f"{name}：{label}待核对。{field['note']}",
                                                "source_ids": list(field["source_ids"])})
    return completed
