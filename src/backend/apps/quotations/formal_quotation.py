"""固定报价模板 PDF 生成器。

只输出系统已经保存的报价快照和价格口径，不虚构卖方法定名称、地址、
银行账户或其他尚未配置的法律信息。
"""

from io import BytesIO
from pathlib import Path
from decimal import Decimal

from django.conf import settings

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as ReportLabImage, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


BRAND_NAME = "haiqu"


def _text(value):
    return str(value or "-").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _money(value):
    if value is None or value == "":
        return "-"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def _page_footer(canvas, document):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D4D4D8"))
    canvas.line(document.leftMargin, 13 * mm, document.pagesize[0] - document.rightMargin, 13 * mm)
    canvas.setFillColor(colors.HexColor("#71717A"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(document.leftMargin, 8 * mm, "System generated quotation snapshot")
    canvas.drawRightString(
        document.pagesize[0] - document.rightMargin,
        8 * mm,
        f"Page {canvas.getPageNumber()}",
    )
    canvas.restoreState()


def _product_image_cell(line, style):
    """返回安全降级的产品主图单元格，所有转码仅在内存中完成。"""
    business_file = getattr(line, "product_image", None)
    if business_file is None or business_file.scan_status != "CLEAN":
        return Paragraph("-", style)
    try:
        media_root = Path(settings.MEDIA_ROOT).resolve()
        image_path = (media_root / business_file.storage_key).resolve()
        image_path.relative_to(media_root)
        if not image_path.is_file():
            return Paragraph("-", style)
        from PIL import Image

        with Image.open(image_path) as source:
            source.seek(0)  # 历史 GIF 时仅使用安全的第一帧，不改动原始附件。
            source.thumbnail((180, 120), Image.Resampling.LANCZOS)
            if source.mode in {"RGBA", "LA"}:
                output_format = "PNG"
            else:
                source = source.convert("RGB")
                output_format = "JPEG"
            output = BytesIO()
            source.save(output, format=output_format)
            width, height = source.size
        if not width or not height:
            return Paragraph("-", style)
        output.seek(0)
        max_width, max_height = 20 * mm, 15 * mm
        scale = min(max_width / width, max_height / height)
        return ReportLabImage(output, width=width * scale, height=height * scale)
    except Exception:
        return Paragraph("-", style)


def build_formal_quotation_pdf(version):
    """根据锁定版本生成包含全部价格口径的正式报价 PDF。"""
    lines = list(
        version.lines.select_related("product_image").prefetch_related("container_tiers__container_config")
        .all()
        .order_by("line_number", "id")
    )
    price_bases = list(version.price_bases.prefetch_related("line_prices").order_by("sort_order", "id"))
    template_snapshot = version.template_snapshot if isinstance(version.template_snapshot, dict) else {}
    template_config = template_snapshot.get("template_config") or {}
    brand_name = str(template_config.get("seller_company_name") or template_config.get("brand_name") or BRAND_NAME)
    document_title = str(template_config.get("document_title") or "QUOTATION")
    page_size = landscape(A4) if len(price_bases) > 2 else A4
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=page_size,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=19 * mm,
        title=f"Quotation {version.quotation.quotation_number} V{version.version_number}",
        author=brand_name,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "QuotationTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=21,
        alignment=TA_RIGHT,
        textColor=colors.HexColor("#18181B"),
    )
    brand_style = ParagraphStyle(
        "Brand",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=24,
        textColor=colors.HexColor("#18181B"),
    )
    label_style = ParagraphStyle(
        "Label",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#71717A"),
    )
    value_style = ParagraphStyle(
        "Value",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#18181B"),
    )
    right_value_style = ParagraphStyle("RightValue", parent=value_style, alignment=TA_RIGHT)
    table_style = ParagraphStyle("TableText", parent=value_style, fontSize=8, leading=10)
    table_right_style = ParagraphStyle("TableRight", parent=table_style, alignment=TA_RIGHT)

    quotation = version.quotation
    buyer_name = quotation.customer_account.account_name
    contact = version.contact_snapshot or {}
    address = version.address_snapshot or {}
    entity = version.transaction_entity_snapshot or {}
    buyer_address = ", ".join(
        str(part).strip()
        for part in [address.get("address_line1"), address.get("address_line2"), address.get("city"), address.get("country_code")]
        if part
    )
    seller_profile = [
        ("Contact", template_config.get("seller_contact_person")),
        ("Phone", template_config.get("seller_phone")),
        ("Fax", template_config.get("seller_fax")),
        ("WeChat", template_config.get("seller_wechat")),
        ("WhatsApp", template_config.get("seller_whatsapp")),
        ("Skype", template_config.get("seller_skype")),
        ("QQ", template_config.get("seller_qq")),
        ("Email", template_config.get("seller_email")),
        ("Address", template_config.get("seller_address")),
        ("Facebook", template_config.get("seller_facebook")),
        ("Website", template_config.get("seller_website")),
    ]
    seller_contact_text = "<br/>".join(
        f"{_text(label)}: {_text(value)}" for label, value in seller_profile if value
    ) or "-"

    story = []
    header = Table(
        [
            [Paragraph(_text(brand_name), brand_style), Paragraph(_text(document_title), title_style)],
            [
                Paragraph("FIXED TEMPLATE / VERSION SNAPSHOT", label_style),
                Paragraph(f"No. {_text(quotation.quotation_number)} &nbsp;&nbsp; V{version.version_number}", right_value_style),
            ],
        ],
        colWidths=[document.width * 0.5, document.width * 0.5],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.extend([header, Spacer(1, 4 * mm)])

    party_table = Table(
        [
            [Paragraph("SELLER CONTACT", label_style), Paragraph("BUYER", label_style), Paragraph("QUOTATION DETAILS", label_style)],
            [Paragraph(f"<b>{_text(brand_name)}</b><br/>{seller_contact_text}", value_style), Paragraph(_text(entity.get("legal_name") or buyer_name), value_style), Paragraph(f"Issued: {_text(version.issued_at.date() if version.issued_at else '-')}", right_value_style)],
            [Paragraph("", value_style), Paragraph(_text(contact.get("name") or contact.get("display_name")), value_style), Paragraph(f"Valid until: {_text(version.valid_until)}", right_value_style)],
            [Paragraph("", value_style), Paragraph(_text(buyer_address), value_style), Paragraph(f"Currency: {_text(version.currency_code)}", right_value_style)],
        ],
        colWidths=[document.width * 0.34, document.width * 0.36, document.width * 0.30],
    )
    party_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D4D4D8")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E4E4E7")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([party_table, Spacer(1, 5 * mm)])

    headers = ["No.", "Image", "Product", "Specification", "Quantity"]
    headers.extend(basis.label for basis in price_bases)
    rows = [[Paragraph(_text(item), table_style) for item in headers]]
    price_maps = {
        basis.id: {price.quotation_line_id: price for price in basis.line_prices.all()}
        for basis in price_bases
    }
    for line in lines:
        row = [
            Paragraph(str(line.line_number), table_style),
            _product_image_cell(line, table_style),
            Paragraph(_text(line.product_description_snapshot), table_style),
            Paragraph(_text(line.specification_snapshot), table_style),
            Paragraph(f"{_money(line.quantity)} {_text(line.unit_code)}", table_right_style),
        ]
        for basis in price_bases:
            price = price_maps[basis.id].get(line.id)
            row.append(Paragraph(_money(price.unit_price if price else None), table_right_style))
        rows.append(row)

    basis_count = max(1, len(price_bases))
    number_width = 13 * mm
    image_width = 24 * mm
    quantity_width = 24 * mm
    basis_width = max(18 * mm, min(30 * mm, (document.width - 105 * mm) / basis_count))
    description_space = max(36 * mm, document.width - number_width - image_width - quantity_width - basis_width * len(price_bases))
    product_width = description_space * 0.46
    specification_width = description_space - product_width
    line_table = Table(
        rows,
        colWidths=[number_width, image_width, product_width, specification_width, quantity_width] + [basis_width] * len(price_bases),
        repeatRows=1,
    )
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#18181B")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D4D4D8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([line_table, Spacer(1, 5 * mm)])

    container_rows = []
    for line in lines:
        for tier in line.container_tiers.all():
            container_rows.append(
                [
                    Paragraph(_text(line.product_description_snapshot), table_style),
                    Paragraph(_text(tier.container_type_code), table_style),
                    Paragraph(f"{_money(tier.final_quantity)} {_text(line.unit_code)}", table_right_style),
                    Paragraph(f"{_text(version.currency_code)} {_money(tier.unit_price)}", table_right_style),
                    Paragraph(f"{_money(Decimal(tier.load_factor) * 100)}%", table_right_style),
                    Paragraph(_text(tier.override_reason or "System calculated"), table_style),
                ]
            )
    if container_rows:
        story.extend([Paragraph("CONTAINER TIERS", label_style), Spacer(1, 2 * mm)])
        tier_table = Table(
            [[Paragraph(_text(item), table_style) for item in ["Product", "Container", "Quantity", "Unit price", "Load factor", "Notes"]], *container_rows],
            colWidths=[document.width * 0.24, document.width * 0.13, document.width * 0.16, document.width * 0.15, document.width * 0.13, document.width * 0.19],
            repeatRows=1,
        )
        tier_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D4D4D8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.extend([tier_table, Spacer(1, 5 * mm)])

    basis_rows = [[Paragraph("PRICE BASIS", label_style), Paragraph("TERMS", label_style)]]
    max_basis_rows = max(1, len(price_bases))
    for index in range(max_basis_rows):
        basis = price_bases[index] if index < len(price_bases) else None
        left = "-" if basis is None else f"{basis.label}: {basis.incoterm_code} {basis.named_place}".strip()
        if index == 0:
            right = f"Payment: {_text(version.terms_snapshot.get('payment_terms'))}"
        elif index == 1:
            right = f"Delivery: {_text(version.terms_snapshot.get('delivery_time'))}"
        else:
            right = ""
        basis_rows.append([Paragraph(_text(left), value_style), Paragraph(_text(right), right_value_style)])
    basis_table = Table(basis_rows, colWidths=[document.width * 0.62, document.width * 0.38])
    basis_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D4D4D8")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(KeepTogether(basis_table))
    if version.notes:
        story.extend([Spacer(1, 4 * mm), Paragraph("NOTES", label_style), Paragraph(_text(version.notes), value_style)])

    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return output.getvalue()
