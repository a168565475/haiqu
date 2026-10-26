"""仅填充用户确认的布面采购原版 XLSX，保留固定条款、样式与甲方印章。"""

import re
import unicodedata
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


TEMPLATE_PATH = Path(__file__).with_name("resources") / "fabric_purchase_contract.xlsx"
SHEET_PATH = "xl/worksheets/sheet1.xml"
STRINGS_PATH = "xl/sharedStrings.xml"
STYLES_PATH = "xl/styles.xml"
DRAWING_PATH = "xl/drawings/drawing1.xml"
WORKBOOK_PATH = "xl/workbook.xml"
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
ART = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"m": MAIN, "xdr": DRAWING, "a": ART}
CELL_REFERENCE = re.compile(r"(\$?[A-Z]{1,3})(\$?)(\d+)")
MONEY_QUANT = Decimal("0.0001")

ET.register_namespace("", MAIN)
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
ET.register_namespace("xdr", DRAWING)
ET.register_namespace("a", ART)
ET.register_namespace("a14", "http://schemas.microsoft.com/office/drawing/2010/main")


class FabricPurchaseSheetTemplateError(ValueError):
    """原版结构或冻结采购数据不能安全映射到布面合同。"""


def uses_fabric_contract_template(sheet):
    content = sheet.content_snapshot if isinstance(sheet.content_snapshot, dict) else {}
    order = content.get("order") if isinstance(content.get("order"), dict) else {}
    version = getattr(sheet, "template_version", None)
    template = getattr(version, "template", None)
    return getattr(template, "template_code", None) == "FABRIC" and order.get("source_type") != "SAMPLE"


def _text(value):
    return str(value if value is not None else "").strip()


def _decimal(value, label):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FabricPurchaseSheetTemplateError(f"{label}缺少有效数字，不能生成布面采购合同。") from exc
    if not result.is_finite() or result < 0:
        raise FabricPurchaseSheetTemplateError(f"{label}必须为有效非负数字。")
    return result


def _decimal_text(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _date(value, label):
    try:
        return date.fromisoformat(_text(value))
    except ValueError as exc:
        raise FabricPurchaseSheetTemplateError(f"{label}缺少有效日期，不能沿用原版示例日期。") from exc


def _line_fields(line):
    snapshot = line.get("material_attributes_snapshot")
    fields = snapshot.get("fields") if isinstance(snapshot, dict) else []
    fields = [field for field in fields if isinstance(field, dict)] if isinstance(fields, list) else []
    description = []
    for label, key in (("品名", "part_name"), ("规格", "specification"), ("材质", "material")):
        value = _text(line.get(key))
        if key not in line or line.get(key) is None:
            value = next((_text(field.get("value")) for field in fields if field.get("key") == key or field.get("label") == label), "")
        if value:
            description.append(f"{label}：{value}")
    widths, colors = [], []
    for field in fields:
        key, label, value = (_text(field.get(name)) for name in ("key", "label", "value"))
        if not label or not value or key == "tube_coating_color" or label == "喷塑颜色":
            continue
        if key in {"part_name", "specification", "material"} or label in {"品名", "部件名称", "规格", "材质"}:
            continue
        if key == "fabric_width" or label == "门幅":
            if re.fullmatch(r"\d+(?:\.\d+)?", value):
                value = _decimal_text(Decimal(value))
            target, item = widths, value
        elif key == "fabric_color_name" or label == "颜色":
            target, item = colors, value
        elif key == "fabric_color_code" or label == "色号":
            target, item = colors, f"色号：{value}"
        else:
            target, item = description, f"{label}：{value}"
        if item not in target:
            target.append(item)
    remark = _text(line.get("remark"))
    if remark and f"要求：{remark}" not in description:
        description.append(f"要求：{remark}")
    return "；".join(description) or "—", " / ".join(widths) or "—", " / ".join(colors) or "—"


def _set_value(cell, value, *, formula=None):
    for child in list(cell):
        cell.remove(child)
    cell.attrib.pop("t", None)
    if formula is not None:
        ET.SubElement(cell, f"{{{MAIN}}}f").text = formula
    if isinstance(value, Decimal):
        ET.SubElement(cell, f"{{{MAIN}}}v").text = _decimal_text(value)
    elif value not in (None, ""):
        cell.set("t", "inlineStr")
        node = ET.SubElement(ET.SubElement(cell, f"{{{MAIN}}}is"), f"{{{MAIN}}}t")
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        node.text = str(value)


def _replace_original_text(cell, strings, pattern, replacement):
    if cell.get("t") != "s":
        raise FabricPurchaseSheetTemplateError("布面原版的固定文字结构已变化，请恢复确认的原版文件。")
    value = cell.find("m:v", NS)
    try:
        original = strings[int(value.text)]
    except (IndexError, TypeError, ValueError, AttributeError) as exc:
        raise FabricPurchaseSheetTemplateError("布面原版缺少固定文字。") from exc
    count = 0
    for text in original.iter(f"{{{MAIN}}}t"):
        text.text, replaced = re.subn(pattern, lambda match: replacement(match), text.text or "")
        count += replaced
    if count != 1:
        raise FabricPurchaseSheetTemplateError("布面原版的固定文字位置已变化，不能安全替换。")


def _cell_text(cell, strings):
    if cell.get("t") == "s":
        value = strings[int(cell.find("m:v", NS).text)]
    else:
        value = cell
    return "".join(node.text or "" for node in value.iter(f"{{{MAIN}}}t"))


def _compact_strings(sheet, strings):
    references = [cell for cell in sheet.findall(".//m:c", NS) if cell.get("t") == "s"]
    used = sorted({int(cell.find("m:v", NS).text) for cell in references})
    mapping = {old: new for new, old in enumerate(used)}
    compact = ET.Element(strings.tag, {**strings.attrib, "count": str(len(references)), "uniqueCount": str(len(used))})
    for old in used:
        compact.append(strings[old])
    for cell in references:
        value = cell.find("m:v", NS)
        value.text = str(mapping[int(value.text)])
    return compact


def _shift_reference(value, delta, threshold=8):
    def replace(match):
        number = int(match.group(3))
        return f"{match.group(1)}{match.group(2)}{number + delta}" if number >= threshold else match.group(0)
    return CELL_REFERENCE.sub(replace, value)


def _shift_row(row, delta):
    old_number = int(row.get("r"))
    row.set("r", str(old_number + delta))
    for cell in row.findall("m:c", NS):
        cell.set("r", _shift_reference(cell.get("r"), delta, old_number))
        formula = cell.find("m:f", NS)
        if formula is not None and formula.text:
            formula.text = _shift_reference(formula.text, delta)


def _resize_rows(sheet, count):
    sheet_data = sheet.find("m:sheetData", NS)
    if sheet_data is None:
        raise FabricPurchaseSheetTemplateError("布面原版缺少明细区域。")
    rows = {int(row.get("r")): row for row in sheet_data}
    if any(number not in rows for number in (6, 7, 8, 9, 19)):
        raise FabricPurchaseSheetTemplateError("布面原版明细或条款行已变化。")
    delta = count - 2
    new_rows = []
    for index in range(count):
        row = deepcopy(rows[6 if index == 0 else 7])
        _shift_row(row, 6 + index - int(row.get("r")))
        new_rows.append(row)
    following = [row for number, row in rows.items() if number >= 8]
    for row in following:
        _shift_row(row, delta)
    for row in list(sheet_data):
        sheet_data.remove(row)
    for row in [*(row for number, row in rows.items() if number < 6), *new_rows, *following]:
        sheet_data.append(row)
    merges = sheet.find("m:mergeCells", NS)
    if merges is not None:
        for merge in list(merges):
            reference = merge.get("ref")
            if reference == "G6:G7":
                if count < 2:
                    merges.remove(merge)
                else:
                    merge.set("ref", f"G6:G{5 + count}")
            else:
                merge.set("ref", _shift_reference(reference, delta))
        merges.set("count", str(len(merges)))
    for node in sheet.iter():
        if node.tag == f"{{{MAIN}}}mergeCell":
            continue
        for attribute in ("ref", "sqref", "activeCell"):
            if attribute in node.attrib:
                node.set(attribute, _shift_reference(node.get(attribute), delta))
    return delta, new_rows


def _numeric_style(styles, cell, value, cache):
    base_index = int(cell.get("s", "0"))
    text = _decimal_text(value)
    fraction = text.partition(".")[2]
    code = "0." + "#" * len(fraction) if fraction else "0"
    key = (base_index, code)
    if key not in cache:
        formats = styles.find("m:numFmts", NS)
        xfs = styles.find("m:cellXfs", NS)
        if formats is None or xfs is None or base_index >= len(xfs):
            raise FabricPurchaseSheetTemplateError("布面原版数字样式缺失。")
        matching = next((item.get("numFmtId") for item in formats if item.get("formatCode") == code), None)
        if matching is None:
            matching = str(max(163, *(int(item.get("numFmtId")) for item in formats)) + 1)
            ET.SubElement(formats, f"{{{MAIN}}}numFmt", {"numFmtId": matching, "formatCode": code})
            formats.set("count", str(len(formats)))
        style = deepcopy(xfs[base_index])
        style.set("numFmtId", matching)
        style.set("applyNumberFormat", "1")
        cache[key] = str(len(xfs))
        xfs.append(style)
        xfs.set("count", str(len(xfs)))
    cell.set("s", cache[key])


def _text_height(value, capacity, minimum, label):
    count, used = 1, 0
    for char in value:
        size = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if char == "\n" or used + size > capacity:
            count, used = count + 1, 0
        if char != "\n":
            used += size
    height = max(minimum, count * 16 + 8)
    if height > 409:
        raise FabricPurchaseSheetTemplateError(f"{label}文字过长，超过原版单行可完整打印的高度，请调整后重试。")
    return height


def build_fabric_purchase_sheet_xlsx(sheet):
    content = sheet.content_snapshot if isinstance(sheet.content_snapshot, dict) else {}
    order = content.get("order") if isinstance(content.get("order"), dict) else {}
    task_number = _text(order.get("production_task_number"))
    if order.get("source_type") == "SAMPLE" or not task_number:
        raise FabricPurchaseSheetTemplateError("布面原版需要已冻结的生产任务单号；当前采购表缺失该单号，不能用销售订单号或样品单号代替。")
    if content.get("settlement_mode") == "ACTUAL_WEIGHT":
        raise FabricPurchaseSheetTemplateError("布面原版按米计价，不支持按实际重量结算。")
    tax_rate = _decimal(content.get("tax_rate"), "合同税率")
    freight_bearer = _text(content.get("freight_bearer"))
    if not freight_bearer:
        raise FabricPurchaseSheetTemplateError("合同缺少运费承担方，不能沿用原版示例约定。")
    lines = content.get("lines") or []
    if not isinstance(lines, list) or any(not isinstance(line, dict) for line in lines):
        raise FabricPurchaseSheetTemplateError("布面采购明细格式无效。")
    prepared, dates = [], set()
    for index, line in enumerate(lines, 1):
        if _text(line.get("unit")).casefold() not in {"米", "m", "meter", "metre"}:
            raise FabricPurchaseSheetTemplateError(f"第 {index} 行单位不是米，不能套用布面按米采购原版。")
        quantity = _decimal(line.get("quantity"), f"第 {index} 行数量")
        price = _decimal(line.get("unit_price"), f"第 {index} 行单价")
        try:
            amount = (quantity * price).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:
            raise FabricPurchaseSheetTemplateError(f"第 {index} 行金额超出有效计算范围。") from exc
        prepared.append((_line_fields(line), quantity, price, amount))
        if _text(line.get("delivery_date")):
            dates.add(_date(line["delivery_date"], f"第 {index} 行交期"))
    if len(dates) > 1 or (dates and any(not _text(line.get("delivery_date")) for line in lines)):
        prepared = [((f"{fields[0]}；交期：{_text(line.get('delivery_date')) or '未填写'}", fields[1], fields[2]), quantity, price, amount)
                    for line, (fields, quantity, price, amount) in zip(lines, prepared)]
    delivery = "、".join(f"{item.year}年{item.month}月{item.day}日" for item in sorted(dates)) or "约定采购交期"
    purchase_date = _date(content.get("purchase_date"), "采购日期")
    try:
        source = ZipFile(TEMPLATE_PATH)
    except (OSError, BadZipFile) as exc:
        raise FabricPurchaseSheetTemplateError("已确认的布面采购原版文件不可用，请联系管理员恢复。") from exc
    with source:
        try:
            sheet_root, strings, styles, drawing = (ET.fromstring(source.read(path)) for path in (SHEET_PATH, STRINGS_PATH, STYLES_PATH, DRAWING_PATH))
        except (KeyError, ET.ParseError) as exc:
            raise FabricPurchaseSheetTemplateError("布面原版缺少必要工作表、印章或样式结构。") from exc
        delta, detail_rows = _resize_rows(sheet_root, len(lines))
        cells = {cell.get("r"): cell for cell in sheet_root.findall(".//m:c", NS)}
        def cell(address):
            if address not in cells:
                raise FabricPurchaseSheetTemplateError(f"布面原版缺少必要单元格 {address}。")
            return cells[address]
        _replace_original_text(cell("A1"), strings, r"(?<=订单编号)[^）)]+", lambda match: task_number)
        for address, key, prefix, suffix in (("A2", "buyer", "采购方", "甲方"), ("A3", "seller", "供货方", "乙方")):
            party = content.get(key) if isinstance(content.get(key), dict) else {}
            _replace_original_text(cell(address), strings, rf"(?<={prefix}：).*?(?=\s+以下简称{suffix})", lambda match, party=party: _text(party.get("name")) or "—")
        _replace_original_text(cell("A4"), strings, r"\d+(?:\.\d+)?(?=%增值税)", lambda match: _decimal_text(tax_rate))
        _replace_original_text(cell("A4"), strings, r"含送货到好甲方的运费", lambda match: f"运费由{freight_bearer}承担")
        _set_value(cell("G5"), "订单编号")
        total, cache = Decimal("0"), {}
        for index, (fields, quantity, price, amount) in enumerate(prepared):
            row = 6 + index
            for column, value in zip("ABC", fields):
                _set_value(cell(f"{column}{row}"), value)
            for column, value in (("D", quantity), ("E", price), ("F", amount)):
                target = cell(f"{column}{row}")
                _set_value(target, value, formula=f"ROUND(D{row}*E{row},4)" if column == "F" else None)
                _numeric_style(styles, target, value, cache)
            _set_value(cell(f"G{row}"), task_number if index == 0 else None)
            detail_rows[index].set("ht", str(max(_text_height(value, capacity, 27, "采购明细") for value, capacity in zip(fields, (25, 9, 14)))))
            detail_rows[index].set("customHeight", "1")
            total += amount
        note_row = 8 + delta
        _replace_original_text(cell(f"A{note_row}"), strings, r"^.*$", lambda match: f"备注：{_text(content.get('remark'))}")
        _set_value(cell(f"F{note_row}"), total, formula=f"SUM(F6:F{5 + len(lines)})" if lines else "0")
        _numeric_style(styles, cell(f"F{note_row}"), total, cache)
        _replace_original_text(cell(f"A{9 + delta}"), strings, r"\d{4}年\d{1,2}月\d{1,2}日", lambda match: delivery)
        _replace_original_text(cell(f"A{9 + delta}"), strings, r"运输费用由乙方负责", lambda match: f"运输费用由{freight_bearer}负责")
        _replace_original_text(cell(f"A{19 + delta}"), strings, r"\d{4}\.\d{1,2}\.\d{1,2}", lambda match: f"{purchase_date.year}.{purchase_date.month}.{purchase_date.day}")
        height_delta = sum(Decimal(row.get("ht")) for row in detail_rows) - Decimal("54")
        for number, capacity, label in ((note_row, 62, "合同备注"), (9 + delta, 104, "合同交期")):
            row = sheet_root.find(f"m:sheetData/m:row[@r='{number}']", NS)
            original_height = Decimal(row.get("ht"))
            height = _text_height(_cell_text(cell(f"A{number}"), strings), capacity, original_height, label)
            row.set("ht", str(height))
            row.set("customHeight", "1")
            height_delta += Decimal(height) - original_height
        for anchor in drawing:
            from_row = anchor.find("xdr:from/xdr:row", NS)
            if from_row is None or int(from_row.text) < 7:
                continue
            for path in ("xdr:from/xdr:row", "xdr:to/xdr:row"):
                row = anchor.find(path, NS)
                if row is not None:
                    row.text = str(int(row.text) + delta)
            for offset in anchor.findall(".//a:off", NS):
                if "y" in offset.attrib:
                    offset.set("y", str(int(offset.get("y")) + int(height_delta * 12700)))
        strings = _compact_strings(sheet_root, strings)
        updates = {path: ET.tostring(root, encoding="utf-8", xml_declaration=True) for path, root in (
            (SHEET_PATH, sheet_root), (STRINGS_PATH, strings), (STYLES_PATH, styles), (DRAWING_PATH, drawing),
        )}
        workbook = source.read(WORKBOOK_PATH).decode("utf-8")
        shifted = re.sub(r"(<definedName\b[^>]*>)(.*?)(</definedName>)", lambda match: match.group(1) + _shift_reference(match.group(2), delta) + match.group(3), workbook, flags=re.DOTALL)
        if shifted != workbook:
            updates[WORKBOOK_PATH] = shifted.encode("utf-8")
        output = BytesIO()
        with ZipFile(output, "w") as result:
            for item in source.infolist():
                result.writestr(item, updates.get(item.filename, source.read(item.filename)))
        return output.getvalue()
