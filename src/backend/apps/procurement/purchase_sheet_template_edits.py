"""仅将用户明确修改的标题/条款写回原版，未编辑的合同保持原文。"""

import re
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .fabric_purchase_sheet_template import (
    DRAWING_PATH, NS, SHEET_PATH, STRINGS_PATH, _cell_text, _set_value, _text_height,
)

EDITABLE_TEMPLATE_FIELDS = (
    "title", "payment_and_delivery", "quality_standards", "delivery_handover",
    "special_instructions", "dispute_resolution", "effectiveness",
)
TERM_PREFIXES = {
    "payment_and_delivery": "二、支付方式和交期：", "delivery_handover": "四、送货交接：",
    "special_instructions": "五、特别说明：", "dispute_resolution": "六、争议解决：",
    "effectiveness": "七、",
}


def original_template_terms(cells):
    """cells 为原版 A 列从上至下的文本；返回弹窗实际应编辑的原文。"""
    result = {}
    for index, text in enumerate(cells):
        for key, prefix in TERM_PREFIXES.items():
            if text.startswith(prefix[:2]):
                result[key] = text.removeprefix(prefix)
        if text.startswith("三、"):
            result["quality_standards"] = [re.sub(r"^\d+[.、]\s*", "", value) for block in cells[index + 1:index + 3] for value in block.splitlines() if value]
    if cells:
        result["title"] = re.split(r"[（(]订单编号", cells[0])[0].strip()
    return result


def apply_original_template_edits(data, content):
    edits = set(content.get("original_template_edits") or []) & set(EDITABLE_TEMPLATE_FIELDS)
    if not edits:
        return data
    with ZipFile(BytesIO(data)) as source:
        root = ET.fromstring(source.read(SHEET_PATH))
        strings = ET.fromstring(source.read(STRINGS_PATH))
        drawing = ET.fromstring(source.read(DRAWING_PATH))
        cells = {c.get("r"): c for c in root.findall(".//m:c", NS)}
        row_elements = {int(r.get("r")): r for r in root.findall("m:sheetData/m:row", NS)}
        height_changes = {}

        def write(address, text):
            target = cells[address]
            _set_value(target, text)
            row_number = int(re.search(r"\d+", address)[0])
            row = row_elements[row_number]
            old_height = float(row.get("ht", "15"))
            height = float(_text_height(text, 100, old_height, "合同条款"))
            row.set("ht", str(height))
            row.set("customHeight", "1")
            height_changes[row_number] = height - old_height

        if "title" in edits:
            old = _cell_text(cells["A1"], strings)
            suffix = re.search(r"[（(]订单编号.*", old, re.DOTALL)
            write("A1", str(content.get("title") or "") + ("\n" + suffix[0] if suffix else ""))
        for address, cell in cells.items():
            if not re.fullmatch(r"A\d+", address):
                continue
            text = _cell_text(cell, strings)
            for key, prefix in TERM_PREFIXES.items():
                if key in edits and text.startswith(prefix[:2]):
                    write(address, prefix + str(content.get(key) or ""))
            if "quality_standards" in edits and text.startswith("三、"):
                row = int(address[1:])
                quality = content.get("quality_standards") or []
                write(f"A{row + 1}", f"1. {quality[0]}" if quality else "")
                write(f"A{row + 2}", "\n".join(f"{index}. {value}" for index, value in enumerate(quality[1:], 2)))
        for anchor in drawing:
            start = anchor.find("xdr:from/xdr:row", NS)
            if start is None:
                continue
            shift = sum(delta for row, delta in height_changes.items() if row <= int(start.text))
            for offset in anchor.findall(".//a:off", NS):
                if "y" in offset.attrib:
                    offset.set("y", str(int(offset.get("y")) + round(shift * 12700)))
        updates = {SHEET_PATH: ET.tostring(root, encoding="utf-8", xml_declaration=True),
                   DRAWING_PATH: ET.tostring(drawing, encoding="utf-8", xml_declaration=True)}
        output = BytesIO()
        with ZipFile(output, "w") as result:
            for item in source.infolist():
                result.writestr(item, updates.get(item.filename, source.read(item.filename)))
        return output.getvalue()
