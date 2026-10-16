"""按已确认的真实采购表品类版式生成可继续编辑的 Excel 文件。"""

from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
import unicodedata

from django.conf import settings
from apps.files.models import is_file_scan_usable
from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins

from .purchase_sheet_services import _structured_sections
from .material_attribute_snapshot import purchase_line_attribute_text


THIN = Side(style="thin", color="000000")
TABLE_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BODY_ALIGNMENT = Alignment(vertical="center", wrap_text=True)
CENTER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)
TITLE_FONT = Font(name="宋体", size=18, bold=True)
BODY_FONT = Font(name="宋体", size=10)
BOLD_FONT = Font(name="宋体", size=10, bold=True)


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)


def _media_image_path(business_file):
    if business_file is None or not str(business_file.content_type or "").startswith("image/") or not is_file_scan_usable(business_file.scan_status):
        return None
    media_root = Path(settings.MEDIA_ROOT).resolve()
    file_path = (media_root / business_file.storage_key).resolve()
    try:
        file_path.relative_to(media_root)
    except ValueError:
        return None
    return file_path if file_path.is_file() else None


def _style_range(ws, row_start, row_end, column_start, column_end, *, bold=False, center=False):
    for row in range(row_start, row_end + 1):
        for column in range(column_start, column_end + 1):
            cell = ws.cell(row=row, column=column)
            cell.border = TABLE_BORDER
            cell.alignment = CENTER_ALIGNMENT if center else BODY_ALIGNMENT
            cell.font = BOLD_FONT if bold else BODY_FONT


def _merge_text(ws, row, column_count, text, *, height, bold=False, center=False):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=column_count)
    cell = ws.cell(row=row, column=1, value=text)
    _style_range(ws, row, row, 1, column_count, bold=bold, center=center)
    cell.alignment = CENTER_ALIGNMENT if center else BODY_ALIGNMENT
    ws.row_dimensions[row].height = height


def _layout_name(sheet, content):
    template = sheet.template_version.template
    code = str(template.template_code or "").upper()
    name = str(template.template_name or "")
    categories = set(template.supplier_categories or [])
    if content.get("settlement_mode") == "ACTUAL_WEIGHT" or "WEBBING" in code or "织带" in name:
        return "WEBBING"
    if "FOAM" in code or "喷胶棉" in name or "裁片" in name:
        return "FOAM"
    if "PLASTIC" in code or "塑料" in name or "PLASTIC_PART" in categories:
        return "PLASTIC"
    if "FABRIC" in code or "布面" in name or "FABRIC" in categories:
        return "FABRIC"
    return "AUXILIARY"


def _layout_config(layout):
    if layout == "PLASTIC":
        return {
            "widths": [20, 14, 14, 5, 22, 14, 12, 18, 20],
            "headers": ["产品图", "产品名称", "产品图片", "详细描述", "", "单品数量", "套", "含税单价（元/套）", "金额（元）"],
            "quantity_column": 6,
            "price_column": 8,
            "amount_column": 9,
            "image_column": 1,
        }
    if layout == "FABRIC":
        return {
            "widths": [31, 13, 18, 13, 18, 14, 19],
            "headers": ["产品描述", "门幅（米）", "颜色", "数量（米）", "含税单价（元/米）", "金额（元）", "订单编号"],
            "quantity_column": 4,
            "price_column": 5,
            "amount_column": 6,
            "image_column": None,
        }
    if layout == "WEBBING":
        return {
            "widths": [16, 15, 18, 20, 22, 14, 20, 20],
            "headers": ["订单编号", "图片", "颜色", "产品规格", "产品名称", "数量（米）", "含税单价（元/KG）", "总金额（元）"],
            "quantity_column": 6,
            "price_column": 7,
            "amount_column": 8,
            "image_column": 2,
        }
    if layout == "FOAM":
        return {
            "widths": [24, 18, 35, 15, 20, 20],
            "headers": ["订单编号", "产品名称", "产品描述", "数量（片）", "含税单价（元/片）", "金额（元）"],
            "quantity_column": 4,
            "price_column": 5,
            "amount_column": 6,
            "image_column": None,
        }
    return {
        "widths": [10, 22, 32, 22, 14, 18, 19],
        "headers": ["序号", "产品名称", "产品规格", "颜色/要求", "数量", "含税单价（元）", "总金额（元）"],
        "quantity_column": 5,
        "price_column": 6,
        "amount_column": 7,
        "image_column": None,
    }


def _line_values(layout, line, index, order_number, actual_weight, sample_source=False):
    from .pipe_purchase import pipe_print_description
    name = line.get("part_name") or line.get("product_name") or ""
    specification = line.get("specification") or line.get("product_specification") or ""
    source_attributes = purchase_line_attribute_text(
        line.get("material_attributes_snapshot"),
        line.get("section_title"),
    )
    if source_attributes:
        specification = f"{source_attributes}\n{specification}" if specification else source_attributes
    if line.get('measurement_kind') == 'PIPE':
        specification += '\n' + pipe_print_description(line)
    color_or_requirement = line.get("remark") or line.get("material") or ""
    if sample_source:
        color_or_requirement = "；".join(str(line.get(key) or "").strip() for key in ("material", "remark") if str(line.get(key) or "").strip())
    quantity = _number(line.get("quantity"))
    price = _number(line.get("unit_price"))
    amount = "按实际送货重量结算" if actual_weight else _number(line.get("amount"))
    if layout == "PLASTIC":
        return ["", name, "", specification + ("\n" + color_or_requirement if sample_source and color_or_requirement else ""), "", quantity, line.get("unit") or "", price, amount]
    if layout == "FABRIC":
        description = name if not specification else f"{name}\n{specification}"
        return [description, "", color_or_requirement, quantity, price, amount, order_number]
    if layout == "WEBBING":
        return [order_number, "", color_or_requirement, specification, name, quantity, price, amount]
    if layout == "FOAM":
        return [order_number, name, specification + ("\n" + color_or_requirement if sample_source and color_or_requirement else ""), quantity, price, amount]
    return [index, name, specification, color_or_requirement, quantity, price, amount]


def _add_image(ws, image_path, anchor, *, width=72, height=54):
    if not image_path:
        return
    image = ExcelImage(str(image_path))
    image.width = width
    image.height = height
    ws.add_image(image, anchor)


def _sample_text_chunks(value, width):
    """按列宽保守估算换行；每块至多24行，避免超过Excel行高上限。"""
    if not isinstance(value, str):
        return [(value, 1)]
    capacity = max(4, int(width) - 3)
    chunks, current, used, count = [], '', 0, 1
    for char in value:
        size = 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
        if char == '\n' or used + size > capacity:
            if count >= 24:
                chunks.append((current, count))
                current, count = '', 1
            else:
                count += 1
            used = 0
        current += char
        if char != '\n':
            used += size
    chunks.append((current, count))
    return chunks


def _write_detail_rows(ws, sheet, content, layout, config, start_row):
    line_images = {
        str(item.source_purchase_order_line_id): item.image_file
        for item in sheet.line_images.select_related("image_file").all()
    }
    lines = list(content.get("lines") or [])
    order = content.get("order") or {}
    order_number = (order.get("source_number") if order.get("source_type") == "SAMPLE" else order.get("sales_order_number")) or ""
    actual_weight = content.get("settlement_mode") == "ACTUAL_WEIGHT"
    column_count = len(config["headers"])
    row = start_row
    for index, line in enumerate(lines, start=1):
        values = _line_values(layout, line, index, order_number, actual_weight, order.get("source_type") == "SAMPLE")
        parts = [[(value, 1)] for value in values]
        if order.get("source_type") == "SAMPLE":
            widths = list(config["widths"])
            if layout == "PLASTIC":
                widths[3] += widths[4]
            parts = [_sample_text_chunks(value, width) for value, width in zip(values, widths)]
        first_values = [part[0][0] for part in parts]
        for column, value in enumerate(first_values, start=1):
            ws.cell(row=row, column=column, value=value)
        if layout == "PLASTIC":
            ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=5)
        _style_range(ws, row, row, 1, column_count)
        for column in (config["quantity_column"], config["price_column"], config["amount_column"]):
            ws.cell(row=row, column=column).alignment = CENTER_ALIGNMENT
            ws.cell(row=row, column=column).number_format = "0.00##"
        quantity_value = values[config["quantity_column"] - 1]
        price_value = values[config["price_column"] - 1]
        if not actual_weight and isinstance(quantity_value, (int, float)) and isinstance(price_value, (int, float)):
            quantity_letter = get_column_letter(config["quantity_column"])
            price_letter = get_column_letter(config["price_column"])
            ws.cell(row=row, column=config["amount_column"], value=f"={quantity_letter}{row}*{price_letter}{row}")
            ws.cell(row=row, column=config["amount_column"]).number_format = "0.00##"
        image_path = _media_image_path(line_images.get(str(line.get("source_purchase_order_line_id") or "")))
        if config["image_column"]:
            _add_image(ws, image_path, f"{get_column_letter(config['image_column'])}{row}")
        ws.row_dimensions[row].height = max(58, max(part[0][1] for part in parts) * 14 + 12)
        row += 1
        for continuation in range(1, max(len(part) for part in parts)):
            height = 1
            for column, part in enumerate(parts, 1):
                if continuation < len(part):
                    value, count = part[continuation]
                    ws.cell(row=row, column=column, value=value)
                    height = max(height, count)
            if layout == "PLASTIC":
                ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=5)
            _style_range(ws, row, row, 1, column_count)
            ws.row_dimensions[row].height = max(58, height * 14 + 12)
            row += 1
    return lines, line_images, row


def _write_total_and_note(ws, content, layout, config, row, lines, line_images):
    column_count = len(config["headers"])
    amount_column = config["amount_column"]
    actual_weight = content.get("settlement_mode") == "ACTUAL_WEIGHT"
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(1, amount_column - 2))
    ws.cell(row=row, column=1, value=f"备注：{content.get('remark') or ''}")
    ws.cell(row=row, column=amount_column - 1, value="总金额")
    if actual_weight:
        ws.cell(row=row, column=amount_column, value="按实际送货重量结算")
    elif lines:
        amount_letter = get_column_letter(amount_column)
        ws.cell(row=row, column=amount_column, value=f"=SUM({amount_letter}6:{amount_letter}{row - 1})")
        ws.cell(row=row, column=amount_column).number_format = "0.00##"
    _style_range(ws, row, row, 1, column_count)
    ws.cell(row=row, column=amount_column - 1).font = BOLD_FONT
    ws.cell(row=row, column=amount_column).font = BOLD_FONT
    ws.cell(row=row, column=amount_column - 1).alignment = CENTER_ALIGNMENT
    ws.cell(row=row, column=amount_column).alignment = CENTER_ALIGNMENT
    ws.row_dimensions[row].height = 38

    # 辅料和喷胶棉原表把图片放在明细下方的备注区域，而不是额外增加图片列。
    if layout in {"AUXILIARY", "FOAM"}:
        first_image = next(
            (
                _media_image_path(line_images.get(str(line.get("source_purchase_order_line_id") or "")))
                for line in lines
                if line_images.get(str(line.get("source_purchase_order_line_id") or ""))
            ),
            None,
        )
        if first_image:
            row += 1
            _merge_text(ws, row, column_count, "采购图片：", height=110)
            _add_image(ws, first_image, f"A{row}", width=120, height=90)
    return row + 1


def _write_sections_and_signature(ws, sheet, content, start_row, column_count):
    sections = _structured_sections(content)
    row = start_row
    _merge_text(ws, row, column_count, f"二、支付方式和交期：{sections['payment_and_delivery']}", height=58)
    row += 1
    _merge_text(ws, row, column_count, "三、产品质量标准：", height=30, bold=True)
    for index, standard in enumerate(sections["quality_standards"], start=1):
        row += 1
        _merge_text(ws, row, column_count, f"{index}. {standard}", height=72)
    row += 1
    _merge_text(ws, row, column_count, f"四、送货交接：{sections['delivery_handover']}", height=58)
    row += 1
    _merge_text(ws, row, column_count, f"五、特别说明：{sections['special_instructions']}", height=82)
    row += 1
    _merge_text(ws, row, column_count, f"六、争议解决：{sections['dispute_resolution']}", height=58)
    row += 1
    _merge_text(ws, row, column_count, f"七、合同生效：{sections['effectiveness']}", height=58)

    buyer = content.get("buyer") or {}
    seller = content.get("seller") or {}
    party_row = row + 1
    split = max(1, column_count // 2)
    ws.merge_cells(start_row=party_row, start_column=1, end_row=party_row, end_column=split)
    ws.merge_cells(start_row=party_row, start_column=split + 1, end_row=party_row, end_column=column_count)
    ws.cell(party_row, 1, value=f"甲方（采购方）：{buyer.get('name') or '—'}")
    ws.cell(party_row, split + 1, value=f"乙方（供货方）：{seller.get('name') or '—'}")
    _style_range(ws, party_row, party_row, 1, column_count, bold=True)
    ws.row_dimensions[party_row].height = 32

    signature_row = party_row + 1
    ws.merge_cells(start_row=signature_row, start_column=1, end_row=signature_row, end_column=split)
    ws.merge_cells(start_row=signature_row, start_column=split + 1, end_row=signature_row, end_column=column_count)
    ws.cell(signature_row, 1, value=f"盖章：\n\n签署日期：{content.get('purchase_date') or ''}")
    ws.cell(signature_row, split + 1, value="盖章：\n\n签署日期：")
    _style_range(ws, signature_row, signature_row, 1, column_count)
    ws.row_dimensions[signature_row].height = 150

    seal = getattr(sheet, "seal_image", None)
    seal_path = _media_image_path(seal.image_file if seal else None)
    _add_image(ws, seal_path, f"B{signature_row}", width=110, height=110)
    return signature_row


def build_supplier_purchase_sheet_xlsx(sheet):
    content = sheet.content_snapshot if isinstance(sheet.content_snapshot, dict) else {}
    layout = _layout_name(sheet, content)
    config = _layout_config(layout)
    column_count = len(config["headers"])
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "采购合同"
    worksheet.sheet_view.showGridLines = False

    for index, width in enumerate(config["widths"], start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width

    order = content.get("order") or {}
    order_number = (order.get("source_number") if order.get("source_type") == "SAMPLE" else order.get("sales_order_number")) or "—"
    title = content.get("title") or "采购合同"
    _merge_text(worksheet, 1, column_count, f"{title}\n（订单编号{order_number}）", height=52, bold=True, center=True)
    worksheet["A1"].font = TITLE_FONT
    buyer = content.get("buyer") or {}
    seller = content.get("seller") or {}
    _merge_text(worksheet, 2, column_count, f"采购方：{buyer.get('name') or '—'}（以下简称甲方）", height=28)
    _merge_text(worksheet, 3, column_count, f"供货方：{seller.get('name') or '—'}（以下简称乙方）", height=32)
    _merge_text(
        worksheet,
        4,
        column_count,
        f"一、产品名称、规格、数量、单价、总额（含 {content.get('tax_rate') or '13'}% 增值税，运费由{content.get('freight_bearer') or '—'}承担）",
        height=38,
        bold=True,
    )

    for column, header in enumerate(config["headers"], start=1):
        worksheet.cell(row=5, column=column, value=header)
    if layout == "PLASTIC":
        worksheet.merge_cells(start_row=5, start_column=4, end_row=5, end_column=5)
    _style_range(worksheet, 5, 5, 1, column_count, bold=True, center=True)
    worksheet.row_dimensions[5].height = 42

    lines, line_images, total_row = _write_detail_rows(worksheet, sheet, content, layout, config, 6)
    section_start = _write_total_and_note(worksheet, content, layout, config, total_row, lines, line_images)
    final_row = _write_sections_and_signature(worksheet, sheet, content, section_start, column_count)

    worksheet.print_area = f"A1:{get_column_letter(column_count)}{final_row}"
    worksheet.page_setup.orientation = "portrait"
    worksheet.page_setup.paperSize = worksheet.PAPERSIZE_A4
    worksheet.page_setup.fitToWidth = 1
    worksheet.page_setup.fitToHeight = 0
    worksheet.sheet_properties.pageSetUpPr.fitToPage = True
    worksheet.page_margins = PageMargins(left=0.2, right=0.2, top=0.3, bottom=0.3, header=0.1, footer=0.1)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
