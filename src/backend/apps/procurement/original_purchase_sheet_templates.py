"""在确认的采购合同原件中填冻结数据，保留条款、页面设置和原印章。"""

import re
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .fabric_purchase_sheet_template import (
    DRAWING, DRAWING_PATH, MAIN, MONEY_QUANT, NS, SHEET_PATH, STRINGS_PATH,
    STYLES_PATH, WORKBOOK_PATH, FabricPurchaseSheetTemplateError,
    _cell_text, _compact_strings, _decimal_text, _numeric_style, _set_value,
    _shift_reference, _text, _text_height,
)
from .purchase_sheet_line_display import purchase_sheet_line_display


RESOURCE_DIR = Path(__file__).with_name("resources")
TEMPLATE_PATHS = {
    "FOAM_CUTTING": RESOURCE_DIR / "foam_purchase_contract.xlsx",
    "AUXILIARY": RESOURCE_DIR / "auxiliary_purchase_contract.xlsx",
    "PLASTIC_PART": RESOURCE_DIR / "plastic_purchase_contract.xlsx",
    "WEBBING_ACTUAL_WEIGHT": RESOURCE_DIR / "webbing_purchase_contract.xlsx",
}
# 明细后的首行、签订日期行、金额列；其它原版行与条款保持不变。
LAYOUTS = {
    "FOAM_CUTTING": (7, 18, "F"),
    "AUXILIARY": (8, 19, "G"),
    "PLASTIC_PART": (13, 24, "I"),
    "WEBBING_ACTUAL_WEIGHT": (7, 18, "H"),
}
REFERENCE_NOTE = "参考图：仅作参考，以本单文字规格、数量和要求为准。"


class OriginalPurchaseSheetTemplateError(FabricPurchaseSheetTemplateError):
    """原版结构或采购数据无法安全映射。"""


def _template_code(sheet):
    version = getattr(sheet, "template_version", None)
    return getattr(getattr(version, "template", None), "template_code", None)


def uses_original_purchase_contract_template(sheet):
    content = sheet.content_snapshot if isinstance(sheet.content_snapshot, dict) else {}
    order = content.get("order") if isinstance(content.get("order"), dict) else {}
    return _template_code(sheet) in TEMPLATE_PATHS and order.get("source_type") != "SAMPLE"


def _number(value, label, *, positive=False):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OriginalPurchaseSheetTemplateError(f"{label}缺少有效数字。") from exc
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise OriginalPurchaseSheetTemplateError(f"{label}必须为有效{'正' if positive else '非负'}数字。")
    return number


def _date(value, label):
    try:
        return date.fromisoformat(_text(value))
    except ValueError as exc:
        raise OriginalPurchaseSheetTemplateError(f"{label}缺少有效日期，不能沿用原版示例日期。") from exc


def _amount(quantity, price, frozen, label):
    try:
        amount = (quantity * price).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise OriginalPurchaseSheetTemplateError(f"{label}超出有效计算范围。") from exc
    if frozen not in (None, "") and _number(frozen, label) != amount:
        raise OriginalPurchaseSheetTemplateError(f"{label}与计价数量、单价不一致，请先保存采购表。")
    return amount


def _prepare(content):
    order = content.get("order") if isinstance(content.get("order"), dict) else {}
    task = _text(order.get("production_task_number"))
    if order.get("source_type") == "SAMPLE" or not task:
        raise OriginalPurchaseSheetTemplateError("原版合同需要已冻结的生产任务单号，不能用销售订单号或样品单号代替。")
    mode = _text(content.get("settlement_mode")) or "NORMAL"
    if mode not in {"NORMAL", "ACTUAL_WEIGHT"}:
        raise OriginalPurchaseSheetTemplateError("当前采购表结算方式无效。")
    lines = content.get("lines")
    if not isinstance(lines, list) or not lines or len(lines) > 5000 or any(not isinstance(line, dict) for line in lines):
        raise OriginalPurchaseSheetTemplateError("原版合同需要 1 至 5000 条有效采购明细。")
    prepared, dates = [], set()
    for index, line in enumerate(lines, 1):
        unit = _text(line.get("unit"))
        if not unit or not _text(line.get("part_name")):
            raise OriginalPurchaseSheetTemplateError(f"第 {index} 行缺少品名或采购单位。")
        row = {"line": line, "display": purchase_sheet_line_display(line), "quantity": _number(line.get("quantity"), f"第 {index} 行数量", positive=True)}
        row["price"] = _number(line.get("unit_price"), f"第 {index} 行单价")
        # 兼容已有按实结算合同；原快照未包含实际结算重量，不能从下单数量推算金额。
        row["amount"] = None if mode == "ACTUAL_WEIGHT" else _amount(row["quantity"], row["price"], line.get("amount"), f"第 {index} 行金额")
        if _text(line.get("delivery_date")):
            dates.add(_date(line["delivery_date"], f"第 {index} 行交期"))
        prepared.append(row)
    amounts = [row["amount"] for row in prepared]
    total = None if any(amount is None for amount in amounts) else sum(amounts, Decimal("0"))
    if content.get("total_amount") not in (None, "") and (total is None or _number(content["total_amount"], "合同合计") != total):
        raise OriginalPurchaseSheetTemplateError("合同合计与明细计价结果不一致，请先保存采购表。")
    mixed_dates = len(dates) > 1 or (dates and any(not _text(row["line"].get("delivery_date")) for row in prepared))
    if mixed_dates:
        for row in prepared:
            row["display"]["attributes"] += f"；交期：{_text(row['line'].get('delivery_date')) or '未填写'}"
    return task, prepared, total, dates


def _replace(cell, strings, pattern, replacement):
    if cell.get("t") != "s":
        raise OriginalPurchaseSheetTemplateError("原版固定文字结构已变化，请恢复确认的原件。")
    value = cell.find("m:v", NS)
    try:
        shared = strings[int(value.text)]
    except (IndexError, ValueError, TypeError, AttributeError) as exc:
        raise OriginalPurchaseSheetTemplateError("原版固定文字缺失。") from exc
    count = 0
    for node in shared.iter(f"{{{MAIN}}}t"):
        node.text, matches = re.subn(pattern, lambda _: replacement, node.text or "")
        count += matches
    if count != 1:
        raise OriginalPurchaseSheetTemplateError("原版固定文字位置已变化，不能安全替换。")


def _resize(sheet, end, count):
    data = sheet.find("m:sheetData", NS)
    if data is None:
        raise OriginalPurchaseSheetTemplateError("原版缺少明细区域。")
    originals = {int(row.get("r")): row for row in data}
    if any(number not in originals for number in (6, end - 1, end, end + 1)):
        raise OriginalPurchaseSheetTemplateError("原版明细或条款位置已变化。")
    delta = count - (end - 6)
    details = []
    for index in range(count):
        old_number = 6 if index == 0 else end - 1 if index == count - 1 else min(7, end - 1)
        row = deepcopy(originals[old_number])
        row.set("r", str(6 + index))
        for cell in row.findall("m:c", NS):
            cell.set("r", re.sub(r"\d+$", str(6 + index), cell.get("r")))
            _set_value(cell, None)
        details.append(row)
    following = []
    for number, row in originals.items():
        if number >= end:
            row.set("r", str(number + delta))
            for cell in row.findall("m:c", NS):
                cell.set("r", _shift_reference(cell.get("r"), delta, end))
                formula = cell.find("m:f", NS)
                if formula is not None and formula.text:
                    formula.text = _shift_reference(formula.text, delta, end)
            following.append(row)
    for row in list(data):
        data.remove(row)
    for row in [*(row for number, row in originals.items() if number < 6), *details, *following]:
        data.append(row)
    merges = sheet.find("m:mergeCells", NS)
    if merges is None:
        raise OriginalPurchaseSheetTemplateError("原版合并区域缺失。")
    for merge in list(merges):
        numbers = [int(value) for value in re.findall(r"\d+", merge.get("ref"))]
        if any(6 <= number < end for number in numbers):
            merges.remove(merge)
        else:
            merge.set("ref", _shift_reference(merge.get("ref"), delta, end))
    for node in sheet.iter():
        if node.tag != f"{{{MAIN}}}mergeCell":
            for attribute in ("ref", "sqref", "activeCell"):
                if attribute in node.attrib:
                    node.set(attribute, _shift_reference(node.get(attribute), delta, end))
    return delta, details, merges


def _alignment(styles, cell, cache, **attributes):
    base = int(cell.get("s", "0"))
    key = (base, tuple(sorted(attributes.items())))
    if key not in cache:
        xfs = styles.find("m:cellXfs", NS)
        if xfs is None or base >= len(xfs):
            raise OriginalPurchaseSheetTemplateError("原版单元格样式缺失。")
        style = deepcopy(xfs[base])
        alignment = style.find("m:alignment", NS)
        if alignment is None:
            alignment = ET.SubElement(style, f"{{{MAIN}}}alignment")
        alignment.attrib.update(attributes)
        style.set("applyAlignment", "1")
        cache[key] = str(len(xfs))
        xfs.append(style)
        xfs.set("count", str(len(xfs)))
    cell.set("s", cache[key])


def _row_height(sheet, number):
    row = sheet.find(f"m:sheetData/m:row[@r='{number}']", NS)
    default = sheet.find("m:sheetFormatPr", NS)
    return Decimal(row.get("ht", default.get("defaultRowHeight", "15") if default is not None else "15")) if row is not None else Decimal("15")


def _height_before(sheet, number):
    return sum((_row_height(sheet, row) for row in range(1, number)), Decimal("0"))


def _validate_drawings(drawing, code):
    message = "原版印章或参考图结构无效，请联系管理员恢复已确认的原件。"
    end, last, _ = LAYOUTS[code]
    expected_rows = [last - 2]
    if code != "WEBBING_ACTUAL_WEIGHT":
        expected_rows.append(5 if code == "PLASTIC_PART" else end - 1)
    if len(drawing) != len(expected_rows):
        raise OriginalPurchaseSheetTemplateError(message)

    def required(parent, path):
        node = parent.find(path, NS)
        if node is None:
            raise OriginalPurchaseSheetTemplateError(message)
        return node

    def integer(value, minimum=0, maximum=9223372036854775807):
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise OriginalPurchaseSheetTemplateError(message) from exc
        if not minimum <= number <= maximum:
            raise OriginalPurchaseSheetTemplateError(message)
        return number

    for anchor, expected_row in zip(drawing, expected_rows):
        if anchor.tag not in {f"{{{DRAWING}}}oneCellAnchor", f"{{{DRAWING}}}twoCellAnchor"}:
            raise OriginalPurchaseSheetTemplateError(message)
        for path in ("xdr:from", "xdr:to") if anchor.tag.endswith("twoCellAnchor") else ("xdr:from",):
            marker = required(anchor, path)
            row = integer(required(marker, "xdr:row").text, maximum=last - 1)
            integer(required(marker, "xdr:col").text, maximum=16383)
            integer(required(marker, "xdr:rowOff").text)
            integer(required(marker, "xdr:colOff").text)
            if path == "xdr:from" and row != expected_row:
                raise OriginalPurchaseSheetTemplateError(message)
        required(anchor, "xdr:pic")
        blip = required(anchor, ".//a:blip")
        if not blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"):
            raise OriginalPurchaseSheetTemplateError(message)
        transform = required(anchor, ".//a:xfrm")
        offset, size = required(transform, "a:off"), required(transform, "a:ext")
        for attribute in ("x", "y"):
            integer(offset.get(attribute))
        for attribute in ("cx", "cy"):
            integer(size.get(attribute), minimum=1)
            if anchor.tag.endswith("oneCellAnchor"):
                integer(required(anchor, "xdr:ext").get(attribute), minimum=1)


def _position_drawings(drawing, sheet, code, end, delta):
    """原图转固定尺寸锚点：增加明细只移动，不随跨行范围拉伸。"""
    for index, anchor in enumerate(list(drawing)):
        start = anchor.find("xdr:from", NS)
        transform = anchor.find(".//a:xfrm", NS)
        if start is None or transform is None:
            raise OriginalPurchaseSheetTemplateError("原版图片定位结构缺失。")
        old_row = int(start.find("xdr:row", NS).text) + 1
        new_row = old_row + delta if old_row >= end else old_row
        offset = transform.find("a:off", NS)
        size = transform.find("a:ext", NS)
        if offset is None or size is None:
            raise OriginalPurchaseSheetTemplateError("原版图片尺寸结构缺失。")
        row_offset = int(start.find("xdr:rowOff", NS).text)
        if index == 1 and code in {"FOAM_CUTTING", "AUXILIARY"}:
            # 备注文字在图片上方；图片仍留在原版备注区域。
            row = sheet.find(f"m:sheetData/m:row[@r='{new_row}']", NS)
            row_offset = int(Decimal(row.get("referenceTextHeight")) * 12700)
            row.attrib.pop("referenceTextHeight", None)
        elif index == 1 and code == "PLASTIC_PART":
            row_offset = 44 * 12700
        start.find("xdr:row", NS).text = str(new_row - 1)
        start.find("xdr:rowOff", NS).text = str(row_offset)
        # 辅料数据列重新分配宽度，但印章和参考图仍使用原绝对横坐标。
        if code == "AUXILIARY":
            remaining = int(offset.get("x"))
            column = 0
            for definition in sheet.findall("m:cols/m:col", NS):
                if int(definition.get("min")) > 7:
                    break
                width = Decimal(definition.get("width"))
                width_emu = int(width * 7 + 5) * 9525
                if remaining < width_emu:
                    break
                remaining -= width_emu
                column += 1
            start.find("xdr:col", NS).text = str(column)
            start.find("xdr:colOff", NS).text = str(remaining)
        offset.set("y", str(int(_height_before(sheet, new_row) * 12700) + row_offset))
        if anchor.tag == f"{{{DRAWING}}}twoCellAnchor":
            anchor.tag = f"{{{DRAWING}}}oneCellAnchor"
            anchor.attrib.pop("editAs", None)
            finish = anchor.find("xdr:to", NS)
            if finish is not None:
                anchor.remove(finish)
            anchor.insert(1, ET.Element(f"{{{DRAWING}}}ext", dict(size.attrib)))


def build_original_purchase_contract_xlsx(sheet):
    code = _template_code(sheet)
    if code not in TEMPLATE_PATHS:
        raise OriginalPurchaseSheetTemplateError("未找到此采购表对应的已确认原版。")
    content = sheet.content_snapshot if isinstance(sheet.content_snapshot, dict) else {}
    task, prepared, total, dates = _prepare(content)
    tax = _number(content.get("tax_rate"), "合同税率")
    if tax > 100:
        raise OriginalPurchaseSheetTemplateError("合同税率不能超过 100%。")
    freight = _text(content.get("freight_bearer"))
    buyer, seller = (content.get(key) if isinstance(content.get(key), dict) else {} for key in ("buyer", "seller"))
    if not freight or not _text(buyer.get("name")) or not _text(seller.get("name")):
        raise OriginalPurchaseSheetTemplateError("合同缺少甲乙方名称或运费承担方。")
    purchased = _date(content.get("purchase_date"), "采购日期")
    end, last, amount_col = LAYOUTS[code]
    try:
        source = ZipFile(TEMPLATE_PATHS[code])
    except (OSError, BadZipFile) as exc:
        raise OriginalPurchaseSheetTemplateError("已确认的采购原版文件不可用，请联系管理员恢复。") from exc
    with source:
        try:
            root, strings, styles, drawing = (ET.fromstring(source.read(path)) for path in (SHEET_PATH, STRINGS_PATH, STYLES_PATH, DRAWING_PATH))
        except (KeyError, ET.ParseError) as exc:
            raise OriginalPurchaseSheetTemplateError("原版缺少必要工作表、图片或样式结构。") from exc
        _validate_drawings(drawing, code)
        delta, detail_rows, merges = _resize(root, end, len(prepared))
        cells = {cell.get("r"): cell for cell in root.findall(".//m:c", NS)}
        def cell(address):
            if address not in cells:
                raise OriginalPurchaseSheetTemplateError(f"原版缺少必要单元格 {address}。")
            return cells[address]
        number_cache, alignment_cache = {}, {}
        if code == "PLASTIC_PART":
            # 原 B/G/H/I 属于纵向合并区域，拆行后补回 F6 的完整细边框。
            xfs = styles.find("m:cellXfs", NS)
            border_id = xfs[int(cell("F6").get("s"))].get("borderId")
            border_styles = {}
            for number in range(6, 6 + len(prepared)):
                for column in "BGHI":
                    target = cell(f"{column}{number}")
                    base = int(target.get("s", "0"))
                    if base not in border_styles:
                        style = deepcopy(xfs[base])
                        style.set("borderId", border_id)
                        border_styles[base] = str(len(xfs))
                        xfs.append(style)
                    target.set("s", border_styles[base])
            xfs.set("count", str(len(xfs)))
        def write(address, value, *, formula=None, suffix=""):
            target = cell(address)
            _set_value(target, value, formula=formula)
            if isinstance(value, Decimal):
                _numeric_style(styles, target, value, number_cache)
                if suffix:
                    # 单据有混合单位时保留数值类型与公式，同时显示本行单位。
                    formats, xfs = styles.find("m:numFmts", NS), styles.find("m:cellXfs", NS)
                    base = xfs[int(target.get("s"))]
                    existing = next(item.get("formatCode") for item in formats if item.get("numFmtId") == base.get("numFmtId"))
                    format_code = existing + '" ' + suffix.replace('"', '""') + '"'
                    key = (int(target.get("s")), format_code)
                    if key not in number_cache:
                        fmt_id = str(max(163, *(int(item.get("numFmtId")) for item in formats)) + 1)
                        ET.SubElement(formats, f"{{{MAIN}}}numFmt", {"numFmtId": fmt_id, "formatCode": format_code})
                        formats.set("count", str(len(formats)))
                        style = deepcopy(base)
                        style.set("numFmtId", fmt_id)
                        number_cache[key] = str(len(xfs))
                        xfs.append(style)
                        xfs.set("count", str(len(xfs)))
                    target.set("s", number_cache[key])
            return target
        def merge(reference):
            if reference.split(":")[0] != reference.split(":")[-1]:
                ET.SubElement(merges, f"{{{MAIN}}}mergeCell", {"ref": reference})
        _replace(cell("A1"), strings, r"(?<=订单编号)[^）)]+", task)
        if code in {"AUXILIARY", "WEBBING_ACTUAL_WEIGHT"}:
            write("A2", f"甲方（需方）：{_text(buyer['name'])}\n乙方（供方）：{_text(seller['name'])}")
        else:
            for address, party, prefix, suffix in (("A2", buyer, "采购方", "甲方"), ("A3", seller, "供货方", "乙方")):
                _replace(cell(address), strings, rf"(?<={prefix}：).*?(?=\s+以下简称{suffix})", _text(party["name"]))
        _replace(cell("A4"), strings, r"\d+(?:\.\d+)?(?=%增值税)", _decimal_text(tax))
        _replace(cell("A4"), strings, r"含送货到好甲方的运费", f"运费由{freight}承担")
        units = {_text(row["line"].get("unit")) for row in prepared}
        one_unit = next(iter(units)) if len(units) == 1 else ""
        quantity_header = f"数量（{one_unit}）" if one_unit else "数量"
        price_header = f"含税单价（元/{one_unit}）" if one_unit else "含税单价"
        if code == "AUXILIARY":
            columns = root.find("m:cols", NS)
            widths = ("16", "18", "23", "10", "9", "10", "12.1666666666667")
            for definition, width in zip(columns, widths):
                definition.set("width", width)
            headers = ("产品名称", "产品规格", "物料属性", "颜色", quantity_header, price_header, "总金额（元）")
        elif code == "FOAM_CUTTING":
            headers = ("订单编号", "产品名称", "产品描述", quantity_header, price_header, "金额（元）")
        elif code == "WEBBING_ACTUAL_WEIGHT":
            headers = ("订单编号", "物料属性", "颜色", "产品规格", "产品名称", quantity_header, price_header, "总金额（元）")
        else:
            headers = None
            for address, title in (("A5", "参考图"), ("C5", "颜色"), ("D5", "详细描述"),
                                   ("F5", "单位"), ("G5", "数量"), ("H5", "含税单价")):
                write(address, title)
        if headers:
            for index, title in enumerate(headers):
                write(f"{chr(65 + index)}5", title)
        for index, row in enumerate(prepared):
            number, line, display = 6 + index, row["line"], row["display"]
            description = "；".join(value for value in (f"规格：{display['specification']}" if display["specification"] else "", display["attributes"]) if value)
            text_fields = []
            if code == "FOAM_CUTTING":
                if display["color"]:
                    description += f"；颜色：{display['color']}"
                values = (("A", task, 24), ("B", _text(line["part_name"]), 24), ("C", description, 19))
                quantity_col, price_col = "D", "E"
            elif code == "AUXILIARY":
                values = (("A", _text(line["part_name"]), 16), ("B", display["specification"], 18), ("C", display["attributes"], 23), ("D", display["color"], 10))
                quantity_col, price_col = "E", "F"
            elif code == "WEBBING_ACTUAL_WEIGHT":
                values = (("A", task, 10), ("B", display["attributes"], 15), ("C", display["color"], 20), ("D", display["specification"], 12), ("E", _text(line["part_name"]), 11))
                quantity_col, price_col = "F", "G"
            else:
                values = (("C", display["color"], 13), ("D", f"{_text(line['part_name'])}；{description}".rstrip("；"), 24),
                          ("B", _text(line.get("product_name")) or _text(line["part_name"]), 13))
                write(f"F{number}", _text(line["unit"]))
                quantity_col, price_col = "G", "H"
                merge(f"D{number}:E{number}")
            for column, text, capacity in values:
                target = write(f"{column}{number}", text or "—")
                _alignment(styles, target, alignment_cache, wrapText="1", vertical="center")
                text_fields.append((text, capacity))
            suffix = _text(line["unit"]) if not one_unit and code != "PLASTIC_PART" else ""
            write(f"{quantity_col}{number}", row["quantity"], suffix=suffix)
            write(f"{price_col}{number}", row["price"], suffix=f"元/{suffix}" if suffix else "")
            if row["amount"] is None:
                write(f"{amount_col}{number}", "待结算")
            else:
                write(f"{amount_col}{number}", row["amount"], formula=f"ROUND({quantity_col}{number}*{price_col}{number},4)")
            detail_rows[index].set("ht", str(max(_text_height(value, capacity, 27, "采购明细") for value, capacity in text_fields)))
            detail_rows[index].set("customHeight", "1")
        if code == "PLASTIC_PART":
            count = len(prepared)
            merge(f"A6:A{5 + count}")
            _alignment(styles, write("A6", "参考图\n以文字规格为准"), alignment_cache, vertical="top", wrapText="1")
            reference_height = Decimal(drawing[1].find(".//a:xfrm/a:ext", NS).get("cy")) / 12700 + 48
            current_height = sum(Decimal(row.get("ht")) for row in detail_rows)
            if current_height < reference_height:
                addition = (reference_height - current_height) / count
                for row in detail_rows:
                    row.set("ht", str(Decimal(row.get("ht")) + addition))
        note, date_row = end + delta, last + delta
        note_text = f"备注：{_text(content.get('remark'))}"
        if code in {"FOAM_CUTTING", "AUXILIARY", "PLASTIC_PART"}:
            note_text += f"\n{REFERENCE_NOTE}"
        _alignment(styles, write(f"A{note}", note_text), alignment_cache, vertical="top", horizontal="left", wrapText="1")
        note_element = root.find(f"m:sheetData/m:row[@r='{note}']", NS)
        text_height = _text_height(note_text, 90 if code != "WEBBING_ACTUAL_WEIGHT" else 70, 27, "合同备注")
        height = max(Decimal(text_height), _row_height(root, note))
        if code in {"FOAM_CUTTING", "AUXILIARY"}:
            image_height = Decimal(drawing[1].find(".//a:xfrm/a:ext", NS).get("cy")) / 12700
            height = max(height, text_height + image_height + 8)
            if height > 409:
                raise OriginalPurchaseSheetTemplateError("合同备注和参考图超过原版单行可打印高度，请缩短备注。")
            note_element.set("referenceTextHeight", str(text_height + 4))
        note_element.set("ht", str(height))
        note_element.set("customHeight", "1")
        write(f"{amount_col}{note}", total if total is not None else "按实际送货重量结算",
              formula=f"SUM({amount_col}6:{amount_col}{5 + len(prepared)})" if total is not None else None)
        delivery = "、".join(f"{item.year}年{item.month}月{item.day}日" for item in sorted(dates)) or "约定采购交期"
        _replace(cell(f"A{note + 1}"), strings, r"\d{4}年\d{1,2}月\d{1,2}日", delivery)
        _replace(cell(f"A{note + 1}"), strings, r"运输费用由[甲乙]方负责", f"运输费用由{freight}负责")
        if code == "AUXILIARY":
            _replace(cell(f"A{note + 1}"), strings, r"(?<=开)\d+(?:\.\d+)?(?=%发票)", _decimal_text(tax))
            write(f"E{17 + delta}", "乙方")
        _replace(cell(f"A{date_row}"), strings, r"\d{4}\.\d{1,2}\.\d{1,2}", f"{purchased.year}.{purchased.month}.{purchased.day}")
        delivery_row = root.find(f"m:sheetData/m:row[@r='{note + 1}']", NS)
        delivery_row.set("ht", str(_text_height(_cell_text(cell(f"A{note + 1}"), strings), 125, _row_height(root, note + 1), "合同交期")))
        delivery_row.set("customHeight", "1")
        merges.set("count", str(len(merges)))
        _position_drawings(drawing, root, code, end, delta)
        strings = _compact_strings(root, strings)
        updates = {path: ET.tostring(value, encoding="utf-8", xml_declaration=True) for path, value in (
            (SHEET_PATH, root), (STRINGS_PATH, strings), (STYLES_PATH, styles), (DRAWING_PATH, drawing),
        )}
        workbook = source.read(WORKBOOK_PATH).decode("utf-8")
        shifted = re.sub(r"(<definedName\b[^>]*>)(.*?)(</definedName>)", lambda match: match.group(1) + _shift_reference(match.group(2), delta, end) + match.group(3), workbook, flags=re.DOTALL)
        if shifted != workbook:
            updates[WORKBOOK_PATH] = shifted.encode("utf-8")
        output = BytesIO()
        with ZipFile(output, "w") as result:
            for item in source.infolist():
                result.writestr(item, updates.get(item.filename, source.read(item.filename)))
        return output.getvalue()
