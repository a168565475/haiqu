"""按客户提供的固定 Excel 版式生成报价 XLSX。

直接修改 XLSX 内部 XML，保留原模板中的图片、图形、样式和打印设置。
报价内容只来自当前版本快照、产品包装和装柜数量档，不沿用模板示例业务数据。
"""

import re
from copy import deepcopy
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from django.conf import settings


TEMPLATE_PATH = Path(settings.BASE_DIR) / "apps" / "quotations" / "resources" / "camping_bed_quotation_template.xlsx"
SHEET_XML_PATH = "xl/worksheets/sheet1.xml"
DRAWING_XML_PATH = "xl/drawings/drawing1.xml"
DRAWING_RELS_PATH = "xl/drawings/_rels/drawing1.xml.rels"
WORKBOOK_XML_PATH = "xl/workbook.xml"

SPREADSHEET_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DRAWING_NAMESPACE = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
DRAWING_MAIN_NAMESPACE = "http://schemas.openxmlformats.org/drawingml/2006/main"
DRAWING_REL_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"

NAMESPACES = {"main": SPREADSHEET_NAMESPACE}
DRAWING_NAMESPACES = {
    "xdr": DRAWING_NAMESPACE,
    "a": DRAWING_MAIN_NAMESPACE,
    "r": DRAWING_REL_NAMESPACE,
}
CELL_REFERENCE_PATTERN = re.compile(r"(\$?[A-Z]{1,3})(\$?)(\d+)")

FIRST_DATA_ROW = 6
PRODUCT_BLOCK_HEIGHT = 8
SOURCE_REPEAT_BLOCK_START = 12
SOURCE_REPEAT_BLOCK_END = 19
SOURCE_FOLLOWING_ROW = 20
SOURCE_USED_END_ROW = 106
PRODUCT_BLOCK_Y_EMU = 2_641_600
MAX_CONTAINER_TIERS_PER_LINE = 6
DEFAULT_SELLER_COMPANY_NAME = "JINHUA SUPERGROUP LEISURE PRODUCTS CO.,LTD"


class SampleInvoiceTemplateError(ValueError):
    """模板结构或报价数据无法安全映射时返回可读错误。"""


def _decimal_text(value):
    if value is None:
        return ""
    text = format(Decimal(value), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _xml_bytes(root):
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def _cell_map(sheet_root):
    return {
        cell.attrib["r"]: cell
        for cell in sheet_root.findall(".//main:c", NAMESPACES)
        if cell.attrib.get("r")
    }


def _set_cell_value(cell, value):
    for child in list(cell):
        cell.remove(child)

    if value is None or value == "":
        cell.attrib.pop("t", None)
        return

    if isinstance(value, (int, float, Decimal)):
        cell.attrib.pop("t", None)
        ElementTree.SubElement(cell, f"{{{SPREADSHEET_NAMESPACE}}}v").text = _decimal_text(value)
        return

    cell.attrib["t"] = "inlineStr"
    inline_string = ElementTree.SubElement(cell, f"{{{SPREADSHEET_NAMESPACE}}}is")
    text = ElementTree.SubElement(inline_string, f"{{{SPREADSHEET_NAMESPACE}}}t")
    text.text = str(value)


def _set_cell_formula(cell, formula):
    for child in list(cell):
        cell.remove(child)
    cell.attrib.pop("t", None)
    ElementTree.SubElement(cell, f"{{{SPREADSHEET_NAMESPACE}}}f").text = formula.lstrip("=")


def _set_value(cells, coordinate, value):
    cell = cells.get(coordinate)
    if cell is None:
        raise SampleInvoiceTemplateError(f"报价模板缺少必要单元格 {coordinate}，请恢复标准模板后重试。")
    _set_cell_value(cell, value)


def _set_formula(cells, coordinate, formula):
    cell = cells.get(coordinate)
    if cell is None:
        raise SampleInvoiceTemplateError(f"报价模板缺少必要单元格 {coordinate}，请恢复标准模板后重试。")
    _set_cell_formula(cell, formula)


def _shift_reference(reference, row_delta, threshold=SOURCE_FOLLOWING_ROW):
    if not reference or not row_delta:
        return reference

    def replace(match):
        row_number = int(match.group(3))
        if row_number < threshold:
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}{row_number + row_delta}"

    return CELL_REFERENCE_PATTERN.sub(replace, reference)


def _shift_row_element(row, row_delta):
    row_number = int(row.attrib["r"])
    row.attrib["r"] = str(row_number + row_delta)
    for cell in row.findall("main:c", NAMESPACES):
        cell.attrib["r"] = _shift_reference(cell.attrib["r"], row_delta, threshold=row_number)


def _clone_row_block(source_rows, row_delta):
    cloned_rows = []
    for source_row in source_rows:
        cloned = deepcopy(source_row)
        _shift_row_element(cloned, row_delta)
        cloned_rows.append(cloned)
    return cloned_rows


def _range_rows(reference):
    rows = [int(item[2]) for item in CELL_REFERENCE_PATTERN.findall(reference or "")]
    return (min(rows), max(rows)) if rows else (0, 0)


def _resize_product_blocks(sheet_root, line_count):
    if line_count < 1:
        raise SampleInvoiceTemplateError("报价至少需要一条产品明细才能导出 XLSX。")

    row_delta = PRODUCT_BLOCK_HEIGHT * (line_count - 2)
    sheet_data = sheet_root.find("main:sheetData", NAMESPACES)
    if sheet_data is None:
        raise SampleInvoiceTemplateError("报价模板缺少工作表数据区。")
    rows = list(sheet_data)
    source_rows = [
        row for row in rows
        if SOURCE_REPEAT_BLOCK_START <= int(row.attrib.get("r", "0")) <= SOURCE_REPEAT_BLOCK_END
    ]
    if len(source_rows) != PRODUCT_BLOCK_HEIGHT:
        raise SampleInvoiceTemplateError("报价模板的产品区块结构已变化，请恢复标准模板后重试。")

    fixed_rows = [row for row in rows if int(row.attrib.get("r", "0")) < SOURCE_REPEAT_BLOCK_START]
    following_rows = [row for row in rows if int(row.attrib.get("r", "0")) >= SOURCE_FOLLOWING_ROW]
    for row in following_rows:
        _shift_row_element(row, row_delta)

    repeated_rows = []
    for product_index in range(1, line_count):
        repeated_rows.extend(_clone_row_block(source_rows, PRODUCT_BLOCK_HEIGHT * (product_index - 1)))

    for row in list(sheet_data):
        sheet_data.remove(row)
    for row in [*fixed_rows, *repeated_rows, *following_rows]:
        sheet_data.append(row)

    merge_cells = sheet_root.find("main:mergeCells", NAMESPACES)
    if merge_cells is not None:
        source_merges = []
        preserved_merges = []
        for merge in list(merge_cells):
            start_row, end_row = _range_rows(merge.attrib.get("ref", ""))
            if SOURCE_REPEAT_BLOCK_START <= start_row and end_row <= SOURCE_REPEAT_BLOCK_END:
                source_merges.append(merge.attrib["ref"])
            elif start_row >= SOURCE_FOLLOWING_ROW:
                merge.attrib["ref"] = _shift_reference(merge.attrib["ref"], row_delta)
                preserved_merges.append(merge)
            else:
                preserved_merges.append(merge)
        for merge in list(merge_cells):
            merge_cells.remove(merge)
        for merge in preserved_merges:
            merge_cells.append(merge)
        for product_index in range(1, line_count):
            block_delta = PRODUCT_BLOCK_HEIGHT * (product_index - 1)
            for source_ref in source_merges:
                cloned_merge = ElementTree.Element(f"{{{SPREADSHEET_NAMESPACE}}}mergeCell")
                cloned_merge.attrib["ref"] = _shift_reference(
                    source_ref,
                    block_delta,
                    threshold=SOURCE_REPEAT_BLOCK_START,
                )
                merge_cells.append(cloned_merge)
        merge_cells.attrib["count"] = str(len(list(merge_cells)))

    dimension = sheet_root.find("main:dimension", NAMESPACES)
    if dimension is not None:
        dimension.attrib["ref"] = f"A1:M{SOURCE_USED_END_ROW + row_delta}"
    for element in sheet_root.iter():
        for attribute in ("ref", "sqref"):
            if attribute in element.attrib and element is not dimension and element.tag != f"{{{SPREADSHEET_NAMESPACE}}}mergeCell":
                element.attrib[attribute] = _shift_reference(element.attrib[attribute], row_delta)
    return row_delta


def _stable_item_number(line):
    stable_source = str(line.lineage_id or line.pk).replace("-", "").upper()
    return f"ITEM-{stable_source[:8]}"


def _price_heading(version):
    basis = version.price_bases.filter(is_default=True).first() or version.price_bases.order_by("sort_order", "id").first()
    if basis is None:
        return version.currency_code
    label = (basis.label or basis.incoterm_code).strip()
    place = (basis.named_place or "").strip()
    if place and place.casefold() not in label.casefold():
        label = f"{label} {place}"
    return f"{label} / {version.currency_code}".strip(" /")


def _write_product_block(cells, start_row, line, price_heading):
    tiers = list(line.container_tiers.all())
    if not tiers:
        raise SampleInvoiceTemplateError(f"报价行 {line.line_number} 尚未配置装柜数量档，无法生成正式 XLSX。")
    if len(tiers) > MAX_CONTAINER_TIERS_PER_LINE:
        raise SampleInvoiceTemplateError(
            f"报价行 {line.line_number} 有 {len(tiers)} 条装柜数量档，模板每个产品最多支持 {MAX_CONTAINER_TIERS_PER_LINE} 条。"
        )

    header_row = start_row - 2
    _set_value(cells, f"B{header_row}", line.product_description_snapshot)
    _set_value(cells, f"M{header_row}", price_heading)
    for row in range(start_row, start_row + MAX_CONTAINER_TIERS_PER_LINE):
        for column in "KLM":
            _set_value(cells, f"{column}{row}", None)

    _set_value(cells, f"A{start_row}", _stable_item_number(line))
    _set_value(cells, f"B{start_row}", None)
    _set_value(cells, f"C{start_row}", line.specification_snapshot)
    packaging = getattr(line, "packaging", None)
    if packaging is not None:
        _set_value(cells, f"D{start_row}", packaging.length_cm)
        _set_value(cells, f"E{start_row}", packaging.width_cm)
        _set_value(cells, f"F{start_row}", packaging.height_cm)
        _set_value(cells, f"G{start_row}", packaging.pieces_per_carton)
        _set_formula(cells, f"H{start_row}", f"D{start_row}*E{start_row}*F{start_row}/1000000")
        _set_value(cells, f"I{start_row}", packaging.gross_weight_kg)
        _set_value(cells, f"J{start_row}", packaging.net_weight_kg)
    else:
        for column in "DEFGHIJ":
            _set_value(cells, f"{column}{start_row}", None)

    for offset, tier in enumerate(tiers):
        row = start_row + offset
        _set_value(cells, f"K{row}", tier.container_type_code)
        _set_value(cells, f"L{row}", tier.final_quantity)
        _set_value(cells, f"M{row}", tier.unit_price)


def _seller_profile_text(template_config):
    lines = []
    address = str(template_config.get("seller_address") or "").strip()
    if address:
        lines.append(f"Add: {address}")

    def append_group(items):
        values = [f"{label}: {str(value).strip()}" for label, value in items if str(value or "").strip()]
        if values:
            lines.append("   ".join(values))

    append_group((("Email", template_config.get("seller_email")), ("Mobile / What's App", template_config.get("seller_whatsapp"))))
    append_group((("Skype", template_config.get("seller_skype")), ("Wechat", template_config.get("seller_wechat"))))
    append_group((("Tel", template_config.get("seller_phone")), ("Fax", template_config.get("seller_fax"))))
    append_group((("Website", template_config.get("seller_website")), ("Facebook", template_config.get("seller_facebook"))))
    append_group((("QQ", template_config.get("seller_qq")), ("Contact Person", template_config.get("seller_contact_person"))))
    return "\n".join(lines)


def _excel_date_serial(value):
    return (value - date(1899, 12, 30)).days


def _write_sheet_values(sheet_root, version, lines, row_delta):
    cells = _cell_map(sheet_root)
    template_snapshot = version.template_snapshot if isinstance(version.template_snapshot, dict) else {}
    template_config = template_snapshot.get("template_config") or {}
    if not template_config and version.quotation_template_id:
        template_config = version.quotation_template.template_config or {}

    _set_value(cells, "A2", _seller_profile_text(template_config))
    _set_value(cells, "A3", f"Quotation: {version.quotation.quotation_number}")
    issue_date = version.issued_at.date() if version.issued_at else version.created_at.date()
    _set_value(cells, "K3", _excel_date_serial(issue_date))

    heading = _price_heading(version)
    for index, line in enumerate(lines):
        _write_product_block(cells, FIRST_DATA_ROW + PRODUCT_BLOCK_HEIGHT * index, line, heading)

    remarks_start = SOURCE_FOLLOWING_ROW + row_delta
    terms = version.terms_snapshot if isinstance(version.terms_snapshot, dict) else {}
    customer_name = (
        (version.transaction_entity_snapshot or {}).get("english_legal_name")
        or (version.transaction_entity_snapshot or {}).get("legal_name")
        or version.quotation.customer_account.account_name
    )
    note_text = " ".join(str(version.notes or "None").split())
    if len(note_text) > 140:
        note_text = f"{note_text[:137]}..."
    remarks = [
        "REMARKS:",
        f"1, Price basis: {heading}.",
        f"2, Payment: {terms.get('payment_terms') or 'Not specified'}.",
        f"3, Lead time: {terms.get('lead_time') or 'Not specified'}.",
        f"4, Customer: {customer_name}.",
        f"5, Quotation valid until: {version.valid_until.isoformat() if version.valid_until else 'Not specified'}.",
        f"6, Notes: {note_text}.",
    ]
    for offset, value in enumerate(remarks):
        _set_value(cells, f"B{remarks_start + offset}", value)


def _shift_anchor(anchor, row_delta, y_delta):
    for path in ("xdr:from/xdr:row", "xdr:to/xdr:row"):
        row = anchor.find(path, DRAWING_NAMESPACES)
        if row is not None and row.text is not None:
            row.text = str(int(row.text) + row_delta)
    for offset in anchor.findall(".//a:off", DRAWING_NAMESPACES):
        if "y" in offset.attrib:
            offset.attrib["y"] = str(int(offset.attrib["y"]) + y_delta)


def _product_image_png(line):
    business_file = getattr(line, "product_image", None)
    if business_file is None or business_file.scan_status != "CLEAN":
        return None
    try:
        media_root = Path(settings.MEDIA_ROOT).resolve()
        image_path = (media_root / business_file.storage_key).resolve()
        image_path.relative_to(media_root)
        if not image_path.is_file():
            return None
        from PIL import Image, ImageOps

        with Image.open(image_path) as source:
            source.seek(0)
            output_image = ImageOps.exif_transpose(source).convert("RGBA")
            output_image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            output = BytesIO()
            output_image.save(output, format="PNG", optimize=True)
        return output.getvalue()
    except Exception:
        return None


def _prepare_drawing(template_zip, lines, row_delta, seller_company_name):
    drawing_root = ElementTree.fromstring(template_zip.read(DRAWING_XML_PATH))
    relationships_root = ElementTree.fromstring(template_zip.read(DRAWING_RELS_PATH))

    title_node = next(
        (node for node in drawing_root.findall(".//a:t", DRAWING_NAMESPACES) if "SUPERGROUP LEISURE PRODUCTS" in (node.text or "")),
        None,
    )
    if title_node is not None:
        title_node.text = seller_company_name

    product_anchors = []
    for anchor in list(drawing_root):
        from_row = anchor.find("xdr:from/xdr:row", DRAWING_NAMESPACES)
        from_col = anchor.find("xdr:from/xdr:col", DRAWING_NAMESPACES)
        blip = anchor.find(".//a:blip", DRAWING_NAMESPACES)
        if (
            from_row is not None and from_col is not None and blip is not None
            and int(from_col.text or "-1") == 1 and int(from_row.text or "-1") in {5, 13}
        ):
            product_anchors.append(anchor)
            drawing_root.remove(anchor)

    if not product_anchors:
        raise SampleInvoiceTemplateError("报价模板缺少产品图片区域。")
    product_anchor_template = min(
        product_anchors,
        key=lambda anchor: int(anchor.find("xdr:from/xdr:row", DRAWING_NAMESPACES).text),
    )
    sample_relationship_ids = {
        blip.attrib.get(f"{{{DRAWING_REL_NAMESPACE}}}embed")
        for anchor in product_anchors
        for blip in anchor.findall(".//a:blip", DRAWING_NAMESPACES)
    }
    skipped_media_paths = set()
    for relationship in list(relationships_root):
        if relationship.attrib.get("Id") in sample_relationship_ids:
            target = relationship.attrib.get("Target", "").replace("../", "xl/")
            if target:
                skipped_media_paths.add(target)
            relationships_root.remove(relationship)

    y_delta = (row_delta // PRODUCT_BLOCK_HEIGHT) * PRODUCT_BLOCK_Y_EMU
    for anchor in list(drawing_root):
        from_row = anchor.find("xdr:from/xdr:row", DRAWING_NAMESPACES)
        if from_row is not None and int(from_row.text or "0") >= SOURCE_FOLLOWING_ROW - 1:
            _shift_anchor(anchor, row_delta, y_delta)

    existing_ids = [
        int(node.attrib["id"])
        for node in drawing_root.findall(".//xdr:cNvPr", DRAWING_NAMESPACES)
        if node.attrib.get("id", "").isdigit()
    ]
    next_shape_id = max(existing_ids or [2000]) + 1
    existing_relationship_numbers = [
        int(match.group(1))
        for relationship in relationships_root
        if (match := re.fullmatch(r"rId(\d+)", relationship.attrib.get("Id", "")))
    ]
    next_relationship_number = max(existing_relationship_numbers or [0]) + 1
    media_files = {}
    for index, line in enumerate(lines):
        image_bytes = _product_image_png(line)
        if image_bytes is None:
            continue
        relationship_id = f"rId{next_relationship_number}"
        next_relationship_number += 1
        media_name = f"quotation-product-{index + 1}.png"
        relationship = ElementTree.Element(f"{{{PACKAGE_REL_NAMESPACE}}}Relationship")
        relationship.attrib.update({
            "Id": relationship_id,
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            "Target": f"../media/{media_name}",
        })
        relationships_root.append(relationship)

        anchor = deepcopy(product_anchor_template)
        _shift_anchor(anchor, PRODUCT_BLOCK_HEIGHT * index, PRODUCT_BLOCK_Y_EMU * index)
        blip = anchor.find(".//a:blip", DRAWING_NAMESPACES)
        blip.attrib[f"{{{DRAWING_REL_NAMESPACE}}}embed"] = relationship_id
        non_visual = anchor.find(".//xdr:cNvPr", DRAWING_NAMESPACES)
        if non_visual is not None:
            non_visual.attrib["id"] = str(next_shape_id)
            non_visual.attrib["name"] = f"报价产品图片 {index + 1}"
            next_shape_id += 1
        drawing_root.append(anchor)
        media_files[f"xl/media/{media_name}"] = image_bytes

    return _xml_bytes(drawing_root), _xml_bytes(relationships_root), media_files, skipped_media_paths


def _prepare_workbook_xml(template_zip, row_delta):
    root = ElementTree.fromstring(template_zip.read(WORKBOOK_XML_PATH))
    namespace = {"main": SPREADSHEET_NAMESPACE}
    for defined_name in root.findall("main:definedNames/main:definedName", namespace):
        if defined_name.attrib.get("name") == "_xlnm.Print_Area" and defined_name.text:
            defined_name.text = _shift_reference(defined_name.text, row_delta)
    return _xml_bytes(root)


def build_formal_quotation_xlsx(version):
    """返回按固定模板和冻结报价数据生成的 XLSX 二进制内容。"""
    if not TEMPLATE_PATH.is_file():
        raise FileNotFoundError("报价 XLSX 模板未部署。")

    lines = list(
        version.lines.select_related("packaging", "product_image")
        .prefetch_related("container_tiers")
        .order_by("line_number", "id")
    )
    with ZipFile(TEMPLATE_PATH) as template_zip:
        try:
            sheet_root = ElementTree.fromstring(template_zip.read(SHEET_XML_PATH))
        except KeyError as error:
            raise SampleInvoiceTemplateError("报价模板缺少主工作表，无法生成下载文件。") from error

        row_delta = _resize_product_blocks(sheet_root, len(lines))
        _write_sheet_values(sheet_root, version, lines, row_delta)
        template_snapshot = version.template_snapshot if isinstance(version.template_snapshot, dict) else {}
        template_config = template_snapshot.get("template_config") or {}
        if not template_config and version.quotation_template_id:
            template_config = version.quotation_template.template_config or {}
        seller_company_name = str(
            template_config.get("seller_company_name") or DEFAULT_SELLER_COMPANY_NAME
        ).strip()
        drawing_xml, drawing_rels_xml, media_files, skipped_media_paths = _prepare_drawing(
            template_zip,
            lines,
            row_delta,
            seller_company_name,
        )
        replacements = {
            SHEET_XML_PATH: _xml_bytes(sheet_root),
            DRAWING_XML_PATH: drawing_xml,
            DRAWING_RELS_PATH: drawing_rels_xml,
            WORKBOOK_XML_PATH: _prepare_workbook_xml(template_zip, row_delta),
        }

        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as output_zip:
            for item in template_zip.infolist():
                if item.filename in skipped_media_paths:
                    continue
                output_zip.writestr(item, replacements.get(item.filename, template_zip.read(item.filename)))
            for media_path, media_bytes in media_files.items():
                output_zip.writestr(media_path, media_bytes)
    return output.getvalue()


def build_sample_invoice(version):
    """兼容旧调用名称；内容已升级为真实报价 XLSX。"""
    return build_formal_quotation_xlsx(version)
