"""供应商采购表 PDF 生成器。

版式以业务实际使用的 A4 采购合同为准，只渲染已保存的采购表快照。
草稿保留水印；已上传的产品图片与甲方盖章图片按当前版本带入。
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO
from pathlib import Path

from django.conf import settings
from PIL import Image as PillowImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as ReportLabImage
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Table, TableStyle


FONT_NAME = "PurchaseSans"
FONT_DIRECTORY = Path(__file__).with_name("fonts")
for name, filename in ((FONT_NAME, "NotoSansSC-Regular.ttf"),
                       ("PurchaseSans-Bold", "NotoSansSC-Bold.ttf"),
                       ("PurchaseSerif-Bold", "NotoSerifSC-Bold.ttf")):
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIRECTORY / filename)))
pdfmetrics.registerFontFamily(FONT_NAME, normal=FONT_NAME, bold="PurchaseSans-Bold",
                              italic=FONT_NAME, boldItalic="PurchaseSans-Bold")
pdfmetrics.registerFontFamily("PurchaseSerif-Bold", normal="PurchaseSerif-Bold", bold="PurchaseSerif-Bold")

BLACK = colors.HexColor("#1f1d18")
# 将确认稿的 830px A4 纸张映射到 PDF 点数，所有区块共用此比例。
PX = A4[0] / 830


def _text(value, fallback="—"):
    normalized = str(value or "").strip()
    return escape(normalized or fallback).replace("\n", "<br/>")


def _number(value):
    if value in (None, ""):
        return "—"
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    if not decimal_value.is_finite():
        return "—"
    formatted = f"{decimal_value:f}"
    return (formatted.rstrip("0").rstrip(".") if "." in formatted else formatted) or "0"


def _money(value):
    if value in (None, ""):
        return "待结算"
    try:
        number = Decimal(str(value))
        return f"{number:,.2f}" if number.is_finite() else "待结算"
    except (InvalidOperation, TypeError, ValueError):
        return "待结算"


def _contract_date(value):
    try:
        parsed = date.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return str(value or "—")
    return f"{parsed.year}.{parsed.month}.{parsed.day}"


def _page_decorator(is_draft):
    def draw(canvas, _document):
        if not is_draft:
            return
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#ededed"))
        canvas.setFont("PurchaseSans-Bold", 64 * PX)
        for top in (200, 510, 820):
            for left in (340, 590):
                canvas.saveState()
                canvas.translate(left * PX, A4[1] - top * PX)
                canvas.rotate(32)
                canvas.drawCentredString(0, 0, "草稿")
                canvas.restoreState()
        canvas.restoreState()

    return draw


def _line_image_paths(sheet):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    result = {}
    for item in sheet.line_images.select_related("image_file").all():
        path = (media_root / item.image_file.storage_key).resolve()
        if media_root in path.parents and path.is_file() and item.image_file.content_type.startswith("image/"):
            result[str(item.source_purchase_order_line_id)] = path
    return result


def _seal_image_path(sheet):
    item = getattr(sheet, "seal_image", None)
    if item is None:
        return None
    media_root = Path(settings.MEDIA_ROOT).resolve()
    path = (media_root / item.image_file.storage_key).resolve()
    if media_root in path.parents and path.is_file() and item.image_file.content_type.startswith("image/"):
        return path
    return None


def _safe_image(path, max_width, max_height):
    if not path:
        return None
    try:
        with PillowImage.open(path) as source_image:
            source_image.verify()
        return ReportLabImage(str(path), width=max_width, height=max_height, kind="proportional")
    except Exception:
        return None


def _structured_sections(content):
    legacy_terms = [str(item).strip() for item in content.get("terms") or [] if str(item).strip()]
    quality = content.get("quality_standards")
    if not isinstance(quality, list) or not quality:
        quality = legacy_terms[:2] or ["产品应符合双方确认的规格、样品及质量要求。"]
    return [
        ("二、支付方式和交期", content.get("payment_and_delivery") or "付款方式和采购交期以双方确认内容为准。"),
        ("三、产品质量标准", quality),
        ("四、送货交接", content.get("delivery_handover") or "乙方送货至甲方指定地点并按约定完成验收交接。"),
        ("五、特别说明", content.get("special_instructions") or ""),
        ("六、争议解决", content.get("dispute_resolution") or "双方先友好协商；协商不成，依法处理。"),
        ("七、合同生效", content.get("effectiveness") or "本采购表自双方签字或盖章之日起生效。"),
    ]


def _one_cell_table(flowable, width, *, min_height=None):
    # minRowHeights 只规定最小高度；长条款可增长并在页内拆分，不能固定高度截断。
    table = Table([[flowable]], colWidths=[width], minRowHeights=[min_height or 0], splitInRow=1)
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.65, BLACK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 15 * PX),
        ("RIGHTPADDING", (0, 0), (-1, -1), 15 * PX),
        ("TOPPADDING", (0, 0), (-1, -1), 8 * PX),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8 * PX),
    ]))
    return table


def build_supplier_purchase_sheet_pdf(sheet, *, draft=False):
    content = sheet.content_snapshot if isinstance(sheet.content_snapshot, dict) else {}
    output = BytesIO()
    width = 774 * PX
    document = BaseDocTemplate(
        output, pagesize=A4,
        title=f"{sheet.sheet_number} V{sheet.version_number}",
        author=str((content.get("buyer") or {}).get("name") or ""),
    )
    frame = Frame(28 * PX, 28 * PX, width, A4[1] - 48 * PX,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    document.addPageTemplates(PageTemplate(id="contract", frames=[frame], onPage=_page_decorator(draft)))
    body = ParagraphStyle("ContractBody", fontName=FONT_NAME, fontSize=14.885 * PX,
                          leading=22.327 * PX, textColor=BLACK, wordWrap="CJK")
    small = ParagraphStyle("ContractSmall", parent=body, fontSize=13.024 * PX, leading=21 * PX)
    center = ParagraphStyle("ContractCenter", parent=body, alignment=TA_CENTER)
    heading = ParagraphStyle("ContractHeading", parent=body)
    header = ParagraphStyle("ContractHeader", parent=small, alignment=TA_CENTER)
    title_style = ParagraphStyle("ContractTitle", parent=body, fontName="PurchaseSerif-Bold", fontSize=26 * PX,
                                 leading=36 * PX, alignment=TA_CENTER)
    right = ParagraphStyle("ContractRight", parent=small, alignment=TA_RIGHT)
    buyer, seller, order = (content.get(key) or {} for key in ("buyer", "seller", "order"))
    actual_weight = content.get("settlement_mode") == "ACTUAL_WEIGHT"
    lines = content.get("lines") or []
    columns = [width * item / 832 for item in (58, 156, 154, 116, 114, 114, 120)]
    title = Table([[Paragraph(
        f"<b>{_text(content.get('title'), '购销合同')}</b>　"
        f"<font size='{23 * PX}'><b>（订单编号  {_text(order.get('source_number') if order.get('source_type') == 'SAMPLE' else order.get('sales_order_number'))}）</b></font>", title_style
    )]], colWidths=[width], minRowHeights=[52 * PX])
    title.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0)]))
    party = Paragraph(
        f"<b>采购单号：{_text(sheet.sheet_number)}</b><br/>"
        f"甲方（采购方）：{_text(buyer.get('name'))}<br/>"
        f"乙方（供货方）：{_text(seller.get('name'))}", body)
    legal = Paragraph(
        "根据《中华人民共和国民法典》《中华人民共和国产品质量法》等国家和地方政府部门有关法律法规，双方经过充分友好协商，本着诚实守信的原则，就采购方向供货方购买产品一事，达成以下约定：", small)
    story = [title, _one_cell_table(party, width, min_height=86 * PX),
             _one_cell_table(legal, width, min_height=64 * PX),
             _one_cell_table(Paragraph("<b>一、采购产品名称、规格、数量、单价及金额</b>", heading), width, min_height=39 * PX)]
    labels = ["序号", "产品名称", "产品规格", "颜色/要求", "数量", "含税单价<br/>（元）", "总金额<br/>（元）"]
    rows = [[Paragraph(f"<b>{label}</b>", header) for label in labels]]
    for index, line in enumerate(lines, 1):
        from .pipe_purchase import pipe_print_description
        specification = str(line.get('specification') or '')
        if line.get('measurement_kind') == 'PIPE':
            specification += '\n' + pipe_print_description(line)
        requirement = "；".join(str(line.get(key) or "").strip() for key in ("material", "remark") if str(line.get(key) or "").strip())
        price = _number(line.get("unit_price"))
        if price != "—":
            # 单价至少两位小数，保留超过两位的实际精度。
            price = f"{Decimal(price):.2f}" if len(price.partition(".")[2]) < 2 else price
        values = [str(index), _text(line.get("part_name")), _text(specification),
                  _text(requirement), f"{_number(line.get('quantity'))} {_text(line.get('unit'), '')}",
                  price, "待结算" if actual_weight else _money(line.get("amount"))]
        rows.append([Paragraph(value, body if col in (1, 2, 3) else center) for col, value in enumerate(values)])
    if not lines:
        rows.append([Paragraph("暂无采购明细", center)] + [""] * 6)
    table = Table(rows, colWidths=columns, repeatRows=1, splitInRow=1,
                  minRowHeights=[50 * PX] + [36 * PX] * (len(rows) - 1))
    table_style = [("GRID", (0, 0), (-1, -1), 0.65, BLACK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                   ("LEFTPADDING", (0, 0), (-1, -1), 10 * PX), ("RIGHTPADDING", (0, 0), (-1, -1), 7 * PX),
                   ("TOPPADDING", (0, 0), (-1, -1), 4 * PX), ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * PX)]
    if not lines:
        table_style.append(("SPAN", (0, 1), (-1, 1)))
    table.setStyle(TableStyle(table_style))
    story.append(table)

    image_paths = _line_image_paths(sheet) if content.get("show_image", True) else {}
    # 与编辑器一致，使用明细顺序中的首张图片，避免查询顺序决定展示内容。
    image_path = next((image_paths.get(str(line.get("source_purchase_order_line_id"))) for line in lines
                       if image_paths.get(str(line.get("source_purchase_order_line_id")))), None)
    image = _safe_image(image_path, 150 * PX, 102 * PX)
    image_cell = image
    if image_cell is None:
        icon = ReportLabImage(str(FONT_DIRECTORY / "pdf-picture.png"), width=16.745 * PX, height=16.745 * PX)
        placeholder = [icon, Paragraph("暂无图片", ParagraphStyle("ImageEmpty", parent=small, spaceBefore=7 * PX,
                       alignment=TA_CENTER, textColor=colors.HexColor("#6f6a61")))]
        image_cell = Table([[placeholder]], colWidths=[150 * PX], rowHeights=[102 * PX])
        image_cell.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd6c9"), 1, [2, 2]),
                                       ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f3ec")),
                                       ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    remark_width = width * 398 / 832 - 30 * PX
    remark_box = Table([[Paragraph(_text(content.get("remark"), ""), small)]], colWidths=[remark_width],
                       minRowHeights=[62 * PX], splitInRow=1)
    remark_box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd6c9")),
                                    ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    remark_box.spaceAfter = 10 * PX
    remarks = [Paragraph("<b>备注：</b>", ParagraphStyle("RemarkLabel", parent=body, spaceAfter=10 * PX)), remark_box,
               Paragraph(f"税率 {_text(content.get('tax_rate'), '13')}% · 运费由{_text(content.get('freight_bearer'))}承担", small)]
    total = "待结算" if actual_weight else _money(content.get("total_amount"))
    media = Table([[image_cell, remarks, Paragraph("<b>合计</b>", center), Paragraph(f"<b>{total}</b>", center)]],
                  colWidths=[width * item / 832 for item in (200, 398, 114, 120)],
                  minRowHeights=[148 * PX], splitInRow=1)
    media.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.65, BLACK),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (0, 0), "CENTER"),
                              ("VALIGN", (0, 0), (0, 0), "TOP"), ("TOPPADDING", (0, 0), (0, 0), 14 * PX),
                              ("LEFTPADDING", (0, 0), (1, 0), 15 * PX), ("RIGHTPADDING", (0, 0), (1, 0), 15 * PX),
                              ("TOPPADDING", (1, 0), (-1, -1), 8 * PX), ("BOTTOMPADDING", (0, 0), (-1, -1), 8 * PX)]))
    story.append(media)
    for label, value in _structured_sections(content):
        text = "<br/>".join(f"{index}. {_text(item)}" for index, item in enumerate(value, 1)) if isinstance(value, list) else _text(value)
        story.append(_one_cell_table([Paragraph(f"<b>{label}</b>", heading), Paragraph(text, small)], width, min_height=64 * PX))

    seal = _safe_image(_seal_image_path(sheet), 116 * PX, 80 * PX) or ""
    signature = Table([[Paragraph("<b>甲方</b>", body), ""], [seal, ""],
                       [Paragraph("请确认无误盖章回传", small), Paragraph(f"签订日期：{_text(_contract_date(content.get('purchase_date')))}", right)]],
                      colWidths=[width / 2, width / 2], minRowHeights=[36 * PX, 88 * PX, 34 * PX])
    signature.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.65, BLACK),
                                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 15 * PX),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 15 * PX)]))
    story.append(signature)
    document.build(story)
    return output.getvalue()
