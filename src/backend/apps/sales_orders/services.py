from apps.access_control.sales_sources import require_file
from apps.access_control import sales_policy
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import BuyerAddressRequired, Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.files.models import FileScanStatus
from apps.inquiries.models import InquiryStatus
from apps.quotations.models import QuotationOutcomeStatus
from apps.customers.models import CustomerEntityAddress

from .models import (
    CollaborationEventStatus,
    CollaborationEventSource,
    CollaborationEventType,
    DeliveryBatchStatus,
    SalesOrder,
    SalesOrderCollaborationEvent,
    SalesOrderDeliveryBatch,
    SalesOrderDeliveryBatchLine,
    SalesOrderEvidence,
    SalesOrderLine,
    SalesOrderPriceException,
    SalesOrderSource,
    SalesOrderStatus,
    SalesOrderVersion,
)
from .pricing import cny_line_amounts, freeze_sales_rate, validate_cny_total
from .selectors import sales_order_completion_progress


MONEY_QUANT = Decimal("0.0001")
RATE_QUANT = Decimal("0.000001")


def _money(value):
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _quote_unit_price(quote_line, quote_version):
    try:
        price_basis_id = quote_version.quotation.acceptance.price_basis_id
    except AttributeError:
        price_basis_id = None
    if price_basis_id:
        basis_price = quote_line.basis_prices.filter(price_basis_id=price_basis_id).values_list("unit_price", flat=True).first()
        if basis_price is not None:
            return Decimal(basis_price)
    return Decimal(quote_line.unit_price) if quote_line.unit_price is not None else None


def _employee_snapshot(employee):
    if employee is None:
        return None
    return {"id": str(employee.pk), "employee_code": employee.employee_code, "display_name": employee.display_name}


def _address_snapshot(address):
    return {
        "id": str(address.pk),
        "address_code": address.address_code,
        "label": address.label,
        "country_code": address.country_code,
        "state_province": address.state_province,
        "city": address.city,
        "postal_code": address.postal_code,
        "address_line1": address.address_line1,
        "address_line2": address.address_line2,
        "recipient_name": address.recipient_name,
        "recipient_phone": address.recipient_phone,
        "is_verified": address.is_verified,
    }


def _entity_snapshot(entity):
    if entity is None:
        return {}
    return {
        "id": str(entity.pk),
        "entity_code": entity.entity_code,
        "entity_type": entity.entity_type,
        "legal_name": entity.legal_name,
        "english_legal_name": entity.english_legal_name,
        "registration_country_code": entity.registration_country_code,
        "registration_number": entity.registration_number,
        "tax_country_code": entity.tax_country_code,
        "tax_identifier": entity.tax_identifier,
    }


def _draft_buyer_address_snapshot(order):
    if order.buyer_address_id and order.buyer_address.archived_at is None:
        return _address_snapshot(order.buyer_address)
    if order.source_quotation_version_id:
        return dict(order.source_quotation_version.address_snapshot or {})
    return {}


def _freeze_buyer_address_snapshot(order):
    if not order.buyer_address_id:
        raise BuyerAddressRequired()
    address = CustomerEntityAddress.objects.select_for_update().filter(
        pk=order.buyer_address_id,
        archived_at__isnull=True,
    ).first()
    if address is None:
        raise BuyerAddressRequired("所选买方地址已归档或不存在，请重新选择地址。")
    if not order.transaction_entity_id or address.transaction_entity_id != order.transaction_entity_id:
        raise BuyerAddressRequired("所选地址不属于当前买方主体，请重新选择地址。")
    order.buyer_address = address
    order.buyer_address_snapshot = _address_snapshot(address)
    order.save(update_fields=["buyer_address", "buyer_address_snapshot", "updated_at"])


def sales_order_snapshot(order):
    return {
        "order_number": order.order_number,
        "version_number": order.version_number,
        "source_type": order.source_type,
        "source_quotation_version_id": str(order.source_quotation_version_id) if order.source_quotation_version_id else None,
        "customer_account_id": str(order.customer_account_id),
        "transaction_entity_id": str(order.transaction_entity_id) if order.transaction_entity_id else None,
        "buyer_address_id": str(order.buyer_address_id) if order.buyer_address_id else None,
        "buyer_snapshot": order.buyer_snapshot,
        "buyer_address_snapshot": order.buyer_address_snapshot,
        "seller_snapshot": order.seller_snapshot,
        "terms_snapshot": order.terms_snapshot,
        "customer_requirement_snapshot": order.customer_requirement_snapshot,
        "customer_po_number": order.customer_po_number,
        "contract_number": order.contract_number,
        "order_date": order.order_date.isoformat(),
        "direct_order_reason": order.direct_order_reason,
        "currency_code": order.currency_code,
        "exchange_rate": str(order.exchange_rate),
        "exchange_rate_record_id": str(order.exchange_rate_record_id) if order.exchange_rate_record_id else None,
        "exchange_rate_snapshot": order.exchange_rate_snapshot,
        "incoterm_code": order.incoterm_code,
        "payment_terms": order.payment_terms,
        "deposit_required": order.deposit_required,
        "includes_tax": order.includes_tax,
        "tax_basis": order.tax_basis,
        "order_tolerance_percent": str(order.order_tolerance_percent),
        "preproduction_sample_required": order.preproduction_sample_required,
        "confirmation_method": order.confirmation_method,
        "customer_confirmer": order.customer_confirmer,
        "customer_confirmed_at": order.customer_confirmed_at.isoformat() if order.customer_confirmed_at else None,
        "confirmation_summary": order.confirmation_summary,
        "status": order.status,
        "salesperson": _employee_snapshot(order.salesperson),
        "merchandiser": _employee_snapshot(order.merchandiser),
        "total_amount": str(order.total_amount),
        "total_amount_cny": str(order.total_amount_cny) if order.total_amount_cny is not None else None,
        "lines": [
            {
                "id": str(line.pk),
                "line_number": line.line_number,
                "source_quotation_line_id": str(line.source_quotation_line_id) if line.source_quotation_line_id else None,
                "product_id": str(line.product_id) if line.product_id else None,
                "customer_product_name": line.customer_product_name_snapshot,
                "customer_specification": line.customer_specification_snapshot,
                "customer_color": line.customer_color_snapshot,
                "product_number": line.product_number_snapshot,
                "product_name": line.product_name_snapshot,
                "specification": line.specification_snapshot,
                "quantity": str(line.quantity),
                "unit_code": line.unit_code_snapshot,
                "quoted_unit_price": str(line.quoted_unit_price) if line.quoted_unit_price is not None else None,
                "unit_price": str(line.unit_price),
                "line_total": str(line.line_total),
                "unit_price_cny": str(line.unit_price_cny) if line.unit_price_cny is not None else None,
                "line_total_cny": str(line.line_total_cny) if line.line_total_cny is not None else None,
            }
            for line in order.lines.order_by("line_number", "id")
        ],
        "delivery_batches": [
            {
                "id": str(batch.pk),
                "line_number": batch.line_number,
                "batch_number": batch.batch_number,
                "planned_delivery_date": batch.planned_delivery_date.isoformat(),
                "status": batch.status,
                "notes": batch.notes,
                "cancelled_at": batch.cancelled_at.isoformat() if batch.cancelled_at else None,
                "cancellation_reason": batch.cancellation_reason,
                "lines": [
                    {"sales_order_line_id": str(line.sales_order_line_id), "quantity": str(line.quantity)}
                    for line in batch.lines.order_by("sales_order_line__line_number", "id")
                ],
            }
            for batch in order.delivery_batches.order_by("line_number", "id")
        ],
    }


def _validate_source(order_values, lines):
    source_type = order_values["source_type"]
    quote_version = order_values.get("source_quotation_version")
    if source_type == SalesOrderSource.QUOTATION:
        if quote_version is None:
            raise ValidationError({"source_quotation_version_id": "报价转单必须选择来源报价版本。"})
        quotation = quote_version.quotation
        if quotation.outcome_status != QuotationOutcomeStatus.WON or quotation.accepted_version_id != quote_version.pk:
            raise ValidationError({"source_quotation_version_id": "只能从客户已接受的报价版本生成销售订单。"})
        if quotation.customer_account_id != order_values["customer_account"].pk:
            raise ValidationError({"source_quotation_version_id": "来源报价与订单客户不一致。"})
        if not lines:
            raise ValidationError({"lines": "请至少选择一条报价明细。"})
        if any(item.get("source_quotation_line") is None for item in lines):
            raise ValidationError({"lines": "报价来源订单不能添加报价外产品。"})
    else:
        if quote_version is not None:
            raise ValidationError({"source_quotation_version_id": "无报价或返单订单不能绑定报价版本。"})
        if any(item.get("source_quotation_line") is not None for item in lines):
            raise ValidationError({"lines": "直接订单明细不能绑定报价行。"})


def _lock_and_validate_quote_capacity(quote_version, lines, *, exclude_order_id=None):
    if quote_version is None:
        return
    from apps.quotations.models import QuotationLine

    quote_line_ids = [item["source_quotation_line"].pk for item in lines]
    locked_lines = {
        item.pk: item
        for item in QuotationLine.objects.select_for_update()
        .filter(pk__in=quote_line_ids, quotation_version=quote_version)
        .prefetch_related("basis_prices")
    }
    if len(locked_lines) != len(set(quote_line_ids)):
        raise ValidationError({"lines": "订单包含不属于来源报价版本的明细。"})

    current_quantities = defaultdict(lambda: Decimal("0"))
    for item in lines:
        current_quantities[item["source_quotation_line"].pk] += Decimal(item["quantity"])
    for quote_line_id, requested in current_quantities.items():
        reserved_queryset = SalesOrderLine.objects.filter(
            source_quotation_line_id=quote_line_id,
        ).exclude(sales_order__status=SalesOrderStatus.CANCELLED)
        if exclude_order_id:
            reserved_queryset = reserved_queryset.exclude(sales_order_id=exclude_order_id)
        reserved = reserved_queryset.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
        available = Decimal(locked_lines[quote_line_id].quantity) - Decimal(reserved)
        if requested > available:
            raise ValidationError(
                {"lines": f"报价第 {locked_lines[quote_line_id].line_number} 行剩余可转数量为 {available}，本次不能填写 {requested}。"}
            )


def _line_identity(values, product, quote_line):
    """根据产品主档或客户文字输入生成订单行当前快照。

    产品主档存在时，编号、规格和单位始终以主档为准；未建档时保留客户输入，
    允许报价行提供默认名称、规格和单位。颜色目前是客户侧文字快照，不强制绑定全局颜色表。
    """
    customer_name_input = values.pop("customer_product_name_snapshot", None)
    customer_spec_input = values.pop("customer_specification_snapshot", None)
    customer_color_input = values.pop("customer_color_snapshot", None)
    unit_code_input = values.pop("unit_code", None)
    category_input = values.pop("product_category", None)
    unit_input = values.pop("product_unit", None)
    color_input = values.pop("product_color", None)
    image_input = values.pop("product_image", None)
    material_input = values.pop("material", None)
    quotation_color = str(getattr(quote_line, "color_snapshot", None) or "").strip()

    if product is not None:
        inherited_quote = quote_line is not None and getattr(quote_line, "product_id", None) == getattr(product, "pk", None)
        product_name = (getattr(quote_line, "product_description_snapshot", "") if inherited_quote else "") or product.product_name
        specification = (getattr(quote_line, "specification_snapshot", "") if inherited_quote else "") or product.specification
        product_number = (getattr(quote_line, "product_number_snapshot", "") if inherited_quote else "") or product.product_number
        product_code = (getattr(quote_line, "product_code_snapshot", "") if inherited_quote else "") or product.product_code
        unit_code = (getattr(quote_line, "unit_code", "") if inherited_quote else "") or product.unit.unit_code
        product_category = (getattr(quote_line, "product_category", None) if inherited_quote else None) or category_input or product.category
        product_unit = (getattr(quote_line, "product_unit", None) if inherited_quote else None) or unit_input or product.unit
        item_number = (getattr(quote_line, "item_number_snapshot", "") if inherited_quote else "") or product.product_item.item_number
        customer_name = str(customer_name_input).strip() if customer_name_input is not None else product_name
        customer_specification = str(customer_spec_input).strip() if customer_spec_input is not None else specification
        customer_color = str(customer_color_input or "").strip() or quotation_color
    else:
        product_name = str(customer_name_input or "").strip()
        if not product_name and quote_line is not None:
            product_name = str(quote_line.product_description_snapshot or "").strip()
        specification = str(customer_spec_input or "").strip()
        if not specification and quote_line is not None:
            specification = str(quote_line.specification_snapshot or "").strip()
        if not product_name:
            raise ValidationError({"lines": "未关联产品主档时必须填写客户产品名称。"})
        if not specification:
            raise ValidationError({"lines": "未关联产品主档时必须填写规格。"})
        product_number = ""
        product_code = ""
        customer_name = product_name
        customer_specification = specification
        customer_color = str(customer_color_input or "").strip() or quotation_color
        unit_code = str(unit_code_input or (quote_line.unit_code if quote_line is not None else "PCS")).strip().upper()
        if not unit_code:
            unit_code = "PCS"
        product_category = category_input or (getattr(quote_line, "product_category", None) if quote_line is not None else None)
        product_unit = unit_input or (getattr(quote_line, "product_unit", None) if quote_line is not None else None)
        item_number = getattr(quote_line, "item_number_snapshot", "") if quote_line is not None else ""

    return {
        "product": product,
        "product_category": product_category,
        "product_unit": product_unit,
        "product_color": color_input or (getattr(quote_line, "product_color", None) if quote_line is not None else None),
        "product_image": image_input or (getattr(quote_line, "product_image", None) if quote_line is not None else None),
        "item_number_snapshot": item_number,
        "material_snapshot": material_input or (getattr(quote_line, "material_snapshot", "") if quote_line is not None else ""),
        "customer_product_name_snapshot": customer_name,
        "customer_specification_snapshot": customer_specification,
        "customer_color_snapshot": customer_color,
        "product_number_snapshot": product_number,
        "product_code_snapshot": product_code,
        "product_name_snapshot": product_name,
        "specification_snapshot": specification,
        "unit_code_snapshot": unit_code,
    }


def _replace_children(order, lines, batches, evidence_files, actor_employee):
    SalesOrderDeliveryBatchLine.objects.filter(delivery_batch__sales_order=order).delete()
    SalesOrderDeliveryBatch.objects.filter(sales_order=order).delete()
    SalesOrderPriceException.objects.filter(sales_order_line__sales_order=order).delete()
    SalesOrderLine.objects.filter(sales_order=order).delete()
    SalesOrderEvidence.objects.filter(sales_order=order).delete()

    lines_by_key = {}
    total = Decimal("0")
    total_cny = Decimal("0")
    for line_number, submitted in enumerate(lines, start=1):
        values = dict(submitted)
        client_key = values.pop("client_key")
        product = values.pop("product", None)
        quote_line = values.pop("source_quotation_line", None)
        identity = _line_identity(values, product, quote_line)
        quote_price = _quote_unit_price(quote_line, order.source_quotation_version) if quote_line else None
        unit_price = Decimal(values["unit_price"])
        quantity = Decimal(values["quantity"])
        unit_price_cny, line_total_cny = cny_line_amounts(unit_price, quantity, order.exchange_rate)
        difference = unit_price - quote_price if quote_price is not None else Decimal("0")
        difference_rate = (difference / quote_price).quantize(RATE_QUANT) if quote_price else None
        line = SalesOrderLine.objects.create(
            sales_order=order,
            line_number=line_number,
            source_quotation_line=quote_line,
            quoted_quantity_snapshot=quote_line.quantity if quote_line else None,
            quoted_unit_price=quote_price,
            line_total=_money(quantity * unit_price),
            unit_price_cny=unit_price_cny,
            line_total_cny=line_total_cny,
            price_difference=_money(difference),
            price_difference_rate=difference_rate,
            **identity,
            **values,
        )
        lines_by_key[client_key] = line
        total += line.line_total
        total_cny += line.line_total_cny

    allocated = defaultdict(lambda: Decimal("0"))
    for batch_number, submitted in enumerate(batches, start=1):
        values = dict(submitted)
        values.pop("client_key", None)
        batch_lines = values.pop("lines")
        batch = SalesOrderDeliveryBatch.objects.create(
            sales_order=order,
            line_number=batch_number,
            batch_number=f"D{batch_number:02d}",
            **values,
        )
        for batch_line in batch_lines:
            source_key = batch_line["sales_order_line_client_key"]
            source_line = lines_by_key.get(source_key)
            if source_line is None:
                raise ValidationError({"delivery_batches": "交付批次引用了不存在的订单明细。"})
            quantity = Decimal(batch_line["quantity"])
            allocated[source_line.pk] += quantity
            if allocated[source_line.pk] > source_line.quantity:
                raise ValidationError({"delivery_batches": f"产品“{source_line.product_name_snapshot}”的批次数量超过订单数量。"})
            SalesOrderDeliveryBatchLine.objects.create(
                delivery_batch=batch,
                sales_order_line=source_line,
                quantity=quantity,
            )

    for business_file in evidence_files:
        if business_file.scan_status not in {FileScanStatus.CLEAN, FileScanStatus.SKIPPED}:
            raise ValidationError({"evidence_file_ids": f"凭证“{business_file.original_name}”尚未通过安全检查。"})
        SalesOrderEvidence.objects.create(
            sales_order=order,
            business_file=business_file,
            uploaded_by_employee=actor_employee,
        )
    order.total_amount = _money(total)
    validate_cny_total(total_cny)
    order.total_amount_cny = total_cny
    order.save(update_fields=["total_amount", "total_amount_cny", "updated_at"])


def _authorize_order_inputs(request, values, permission, previous=None):
    if not sales_policy.enabled():
        return
    for business_file in values.get("evidence_files", []):
        require_file(request, business_file)
    customer = values["customer_account"]
    if previous is None or previous.customer_account_id != customer.pk:
        sales_policy.require_customer(request, permission, customer)
    sales_policy.validate_document_owner(request, customer, values.get("salesperson"),
        previous.salesperson if previous and previous.customer_account_id == customer.pk else None)
    version = values.get("source_quotation_version")
    if version and (previous is None or version.pk != previous.source_quotation_version_id):
        sales_policy.require_customer(request, "quotations.view_quotationversion", version.quotation.customer_account)


@transaction.atomic
def create_sales_order(*, validated_data, actor_employee, request=None):
    _authorize_order_inputs(request, validated_data, "sales_orders.add_salesorder")
    lines = validated_data.pop("lines")
    batches = validated_data.pop("delivery_batches", [])
    evidence_files = validated_data.pop("evidence_files", [])
    _validate_source(validated_data, lines)
    quote_version = validated_data.get("source_quotation_version")
    _lock_and_validate_quote_capacity(quote_version, lines)
    freeze_sales_rate(validated_data)
    order = SalesOrder.objects.create(
        order_number=next_business_number("SALES_ORDER", validated_data["order_date"]),
        status=SalesOrderStatus.DRAFT,
        created_by_employee=actor_employee,
        **validated_data,
    )
    order.buyer_snapshot = _entity_snapshot(order.transaction_entity)
    order.buyer_address_snapshot = _draft_buyer_address_snapshot(order)
    order.full_clean()
    order.save(update_fields=["buyer_snapshot", "buyer_address_snapshot", "updated_at"])
    _replace_children(order, lines, batches, evidence_files, actor_employee)
    write_audit_log(
        object_type="SALES_ORDER",
        object_id=order.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=order.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data=sales_order_snapshot(order),
        request=request,
    )
    if quote_version and quote_version.quotation.source_inquiry_id:
        from apps.inquiries.handling_time import handle_time_event
        handle_time_event(quote_version.quotation.source_inquiry_id, 'ORDER_CREATED', key=f'ORDER:{order.pk}')
    return order


@transaction.atomic
def update_sales_order(*, order, validated_data, actor_employee, request=None):
    order = SalesOrder.objects.select_for_update().get(pk=order.pk)
    require_matching_etag(request, order)
    if order.status != SalesOrderStatus.DRAFT:
        raise Conflict("已确认销售订单不能直接修改，请发起订单变更。")
    _authorize_order_inputs(request, validated_data, "sales_orders.change_salesorder", order)
    lines = validated_data.pop("lines")
    batches = validated_data.pop("delivery_batches", [])
    evidence_files = validated_data.pop("evidence_files", [])
    _validate_source(validated_data, lines)
    _lock_and_validate_quote_capacity(
        validated_data.get("source_quotation_version"),
        lines,
        exclude_order_id=order.pk,
    )
    before = sales_order_snapshot(order)
    freeze_sales_rate(validated_data, previous=order)
    for field_name, value in validated_data.items():
        setattr(order, field_name, value)
    order.buyer_snapshot = _entity_snapshot(order.transaction_entity)
    order.buyer_address_snapshot = _draft_buyer_address_snapshot(order)
    order.full_clean()
    order.save()
    _replace_children(order, lines, batches, evidence_files, actor_employee)
    write_audit_log(
        object_type="SALES_ORDER",
        object_id=order.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=order.customer_account_id,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=sales_order_snapshot(order),
        request=request,
    )
    return order


@transaction.atomic
def set_sales_order_line_product_image(*, order, line, business_file, actor_employee, request=None):
    """为草稿销售订单行保存产品主图，并记录订单级审计。"""
    order = SalesOrder.objects.select_for_update().get(pk=order.pk)
    require_matching_etag(request, order)
    if order.status != SalesOrderStatus.DRAFT:
        raise Conflict("销售订单确认后不能直接修改产品图片，请发起订单变更。")
    line = SalesOrderLine.objects.select_for_update().get(pk=line.pk, sales_order=order)
    before_image_id = str(line.product_image_id) if line.product_image_id else None
    line.product_image = business_file
    line.save(update_fields=["product_image", "updated_at"])
    order.updated_at = timezone.now()
    order.save(update_fields=["updated_at"])
    write_audit_log(
        object_type="SALES_ORDER_LINE",
        object_id=line.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=order.customer_account_id,
        action="PRODUCT_IMAGE_UPDATED",
        actor_employee=actor_employee,
        before_data={"product_image_id": before_image_id},
        after_data={"product_image_id": str(business_file.pk)},
        request=request,
    )
    return order


@transaction.atomic
def remove_sales_order_line_product_image(*, order, line, actor_employee, request=None):
    """移除草稿销售订单行产品主图，并记录订单级审计。"""
    order = SalesOrder.objects.select_for_update().get(pk=order.pk)
    require_matching_etag(request, order)
    if order.status != SalesOrderStatus.DRAFT:
        raise Conflict("销售订单确认后不能直接修改产品图片，请发起订单变更。")
    line = SalesOrderLine.objects.select_for_update().get(pk=line.pk, sales_order=order)
    before_image_id = str(line.product_image_id) if line.product_image_id else None
    line.product_image = None
    line.save(update_fields=["product_image", "updated_at"])
    order.updated_at = timezone.now()
    order.save(update_fields=["updated_at"])
    write_audit_log(
        object_type="SALES_ORDER_LINE",
        object_id=line.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=order.customer_account_id,
        action="PRODUCT_IMAGE_REMOVED",
        actor_employee=actor_employee,
        before_data={"product_image_id": before_image_id},
        after_data={"product_image_id": None},
        request=request,
    )
    return order


def _validate_confirmed_change_identity(order, order_values):
    immutable_checks = {
        "source_type": (order.source_type, order_values.get("source_type"), "订单来源"),
        "source_quotation_version": (
            order.source_quotation_version_id,
            getattr(order_values.get("source_quotation_version"), "pk", None),
            "来源报价版本",
        ),
        "customer_account": (order.customer_account_id, order_values.get("customer_account").pk, "客户"),
    }
    errors = {
        field_name: f"已确认销售订单不能变更{label}，如确需调整应另建销售订单。"
        for field_name, (current, submitted, label) in immutable_checks.items()
        if current != submitted
    }
    if errors:
        raise ValidationError(errors)


def _confirmed_change_affects_customer(order, order_values, lines, batches):
    header_fields = (
        "transaction_entity",
        "buyer_address",
        "customer_po_number",
        "contract_number",
        "order_date",
        "currency_code",
        "exchange_rate",
        "incoterm_code",
        "payment_terms",
        "deposit_required",
        "includes_tax",
        "tax_basis",
        "order_tolerance_percent",
        "preproduction_sample_required",
        "buyer_snapshot",
        "buyer_address_snapshot",
        "seller_snapshot",
        "terms_snapshot",
        "customer_requirement_snapshot",
        "confirmation_method",
        "customer_confirmer",
        "customer_confirmed_at",
        "confirmation_summary",
    )
    for field_name in header_fields:
        current = getattr(order, field_name)
        submitted = order_values.get(field_name, current)
        if hasattr(current, "pk") or hasattr(submitted, "pk"):
            current = getattr(current, "pk", None)
            submitted = getattr(submitted, "pk", None)
        if current != submitted:
            return True

    existing_lines = {str(item.pk): item for item in order.lines.all()}
    if {str(item.get("client_key") or "") for item in lines} != set(existing_lines):
        return True
    line_fields = (
        "quantity",
        "unit_price",
        "lower_price_reason",
        "quality_requirements",
        "packaging_requirements",
        "shipping_mark_requirements",
    )
    for submitted in lines:
        line = existing_lines.get(str(submitted.get("client_key") or ""))
        if line is None or any(getattr(line, field_name) != submitted.get(field_name, getattr(line, field_name)) for field_name in line_fields):
            return True

    existing_batches = {str(item.pk): item for item in order.delivery_batches.all()}
    if {str(item.get("client_key") or "") for item in batches} != set(existing_batches):
        return True
    for submitted in batches:
        batch = existing_batches.get(str(submitted.get("client_key") or ""))
        if batch is None:
            return True
        if batch.planned_delivery_date != submitted.get("planned_delivery_date") or batch.notes != submitted.get("notes", ""):
            return True
        existing_quantities = {str(item.sales_order_line_id): item.quantity for item in batch.lines.all()}
        submitted_quantities = {
            str(item["sales_order_line_client_key"]): item["quantity"]
            for item in submitted.get("lines", [])
        }
        if existing_quantities != submitted_quantities:
            return True
    return False


def _update_confirmed_children_in_place(order, lines, batches):
    existing_lines = {str(item.pk): item for item in order.lines.select_for_update().all()}
    submitted_line_keys = [str(item["client_key"]) for item in lines]
    if set(submitted_line_keys) != set(existing_lines) or len(submitted_line_keys) != len(set(submitted_line_keys)):
        raise ValidationError({"lines": "订单确认后不能新增、删除或重复订单产品，只能调整数量、价格和要求。"})

    total = Decimal("0")
    total_cny = Decimal("0")
    for line_number, submitted in enumerate(lines, start=1):
        values = dict(submitted)
        line = existing_lines[str(values.pop("client_key"))]
        product = values.pop("product", line.product)
        quote_line = values.pop("source_quotation_line", line.source_quotation_line)
        if getattr(product, "pk", None) != line.product_id or getattr(quote_line, "pk", None) != line.source_quotation_line_id:
            raise ValidationError({"lines": "订单确认后不能更换产品或报价来源行；新增产品请另建销售订单。"})
        identity_inputs = {
            "customer_product_name_snapshot": values.pop("customer_product_name_snapshot", None),
            "customer_specification_snapshot": values.pop("customer_specification_snapshot", None),
            "customer_color_snapshot": values.pop("customer_color_snapshot", None),
            "unit_code": values.pop("unit_code", None),
        }
        if identity_inputs["customer_product_name_snapshot"] is not None and str(
            identity_inputs["customer_product_name_snapshot"]
        ).strip() != line.customer_product_name_snapshot:
            raise ValidationError({"lines": "订单确认后不能更换客户产品名称。"})
        if identity_inputs["customer_specification_snapshot"] is not None and str(
            identity_inputs["customer_specification_snapshot"]
        ).strip() != line.customer_specification_snapshot:
            raise ValidationError({"lines": "订单确认后不能更换客户规格。"})
        if identity_inputs["customer_color_snapshot"] is not None and str(
            identity_inputs["customer_color_snapshot"]
        ).strip() != line.customer_color_snapshot:
            raise ValidationError({"lines": "订单确认后不能更换客户颜色。"})
        quote_price = _quote_unit_price(quote_line, order.source_quotation_version) if quote_line else None
        unit_price = Decimal(values["unit_price"])
        quantity = Decimal(values["quantity"])
        difference = unit_price - quote_price if quote_price is not None else Decimal("0")
        difference_rate = (difference / quote_price).quantize(RATE_QUANT) if quote_price else None
        for field_name, value in values.items():
            setattr(line, field_name, value)
        line.line_number = line_number
        line.quoted_unit_price = quote_price
        line.line_total = _money(quantity * unit_price)
        line.unit_price_cny, line.line_total_cny = cny_line_amounts(unit_price, quantity, order.exchange_rate)
        line.price_difference = _money(difference)
        line.price_difference_rate = difference_rate
        line.full_clean()
        line.save()
        total += line.line_total
        total_cny += line.line_total_cny

    existing_batches = {str(item.pk): item for item in order.delivery_batches.select_for_update().all()}
    submitted_batch_keys = [str(item.get("client_key") or "") for item in batches]
    if set(submitted_batch_keys) != set(existing_batches) or len(submitted_batch_keys) != len(set(submitted_batch_keys)):
        raise ValidationError({"delivery_batches": "订单确认后不能新增、删除或重复交付批次；取消批次请使用单独的取消操作。"})

    allocated = defaultdict(lambda: Decimal("0"))
    for batch_number, submitted in enumerate(batches, start=1):
        values = dict(submitted)
        batch = existing_batches[str(values.pop("client_key"))]
        batch_lines = values.pop("lines")
        batch.line_number = batch_number
        batch.batch_number = f"D{batch_number:02d}"
        for field_name, value in values.items():
            setattr(batch, field_name, value)
        batch.full_clean()
        batch.save()

        existing_batch_lines = {str(item.sales_order_line_id): item for item in batch.lines.select_for_update().all()}
        submitted_keys = [str(item["sales_order_line_client_key"]) for item in batch_lines]
        if set(submitted_keys) != set(existing_batch_lines) or len(submitted_keys) != len(set(submitted_keys)):
            raise ValidationError({"delivery_batches": f"订单确认后不能改变 {batch.batch_number} 的产品组成。"})
        for submitted_line in batch_lines:
            line_key = str(submitted_line["sales_order_line_client_key"])
            quantity = Decimal(submitted_line["quantity"])
            batch_line = existing_batch_lines[line_key]
            batch_line.quantity = quantity
            batch_line.full_clean()
            batch_line.save(update_fields=["quantity", "updated_at"])
            if batch.status == DeliveryBatchStatus.ACTIVE:
                allocated[batch_line.sales_order_line_id] += quantity

    for line in existing_lines.values():
        if allocated[line.pk] != Decimal(line.quantity):
            raise ValidationError({
                "delivery_batches": (
                    f"产品“{line.product_name_snapshot}”变更后订单数量 {line.quantity}，"
                    f"有效交付批次合计 {allocated[line.pk]}，两者必须一致。"
                )
            })
    order.total_amount = _money(total)
    validate_cny_total(total_cny)
    order.total_amount_cny = total_cny
    order.save(update_fields=["total_amount", "total_amount_cny", "updated_at"])


@transaction.atomic
def change_confirmed_sales_order(*, order, validated_data, actor_employee, request=None):
    order = SalesOrder.objects.select_for_update().get(pk=order.pk)
    require_matching_etag(request, order)
    if order.status not in {SalesOrderStatus.CONFIRMED, SalesOrderStatus.FULFILLING, SalesOrderStatus.PAUSED}:
        raise Conflict("只有已确认、履约中或已暂停的销售订单可以发起确认后变更。")

    order_values = dict(validated_data["order"])
    _authorize_order_inputs(request, order_values, "access_control.confirmedchange_salesorder", order)
    change_reason = str(validated_data.get("change_reason") or "").strip()
    if not change_reason:
        raise ValidationError({"change_reason": "订单变更必须填写原因。"})
    lines = order_values.pop("lines")
    batches = order_values.pop("delivery_batches", [])
    evidence_files = order_values.pop("evidence_files", [])
    evidence_file = validated_data.get("change_evidence_file")
    require_file(request, evidence_file)
    transaction_entity_changed = getattr(order_values.get("transaction_entity"), "pk", None) != order.transaction_entity_id
    buyer_address_changed = getattr(order_values.get("buyer_address"), "pk", None) != order.buyer_address_id
    buyer_snapshot_changed = order_values.get("buyer_snapshot", order.buyer_snapshot) != order.buyer_snapshot
    buyer_address_snapshot_changed = (
        order_values.get("buyer_address_snapshot", order.buyer_address_snapshot) != order.buyer_address_snapshot
    )
    customer_facing_change = bool(validated_data.get("customer_facing_change")) or _confirmed_change_affects_customer(
        order, order_values, lines, batches
    )
    if customer_facing_change and evidence_file is None:
        raise ValidationError({"change_evidence_file_id": "产品、数量、价格、交期或客户条款发生变化，必须选择客户书面确认凭证。"})
    if evidence_file and evidence_file.scan_status not in {FileScanStatus.CLEAN, FileScanStatus.SKIPPED}:
        raise ValidationError({"change_evidence_file_id": "变更凭证尚未通过安全检查。"})
    _validate_confirmed_change_identity(order, order_values)
    _validate_source(order_values, lines)
    _lock_and_validate_quote_capacity(order.source_quotation_version, lines, exclude_order_id=order.pk)

    has_production = order.production_tasks.exists()
    if has_production and not validated_data.get("pmc_impact_confirmed"):
        raise ValidationError({"pmc_impact_confirmed": "订单已有生产订单，必须由 PMC 确认本次变更对计划的影响。"})

    before = sales_order_snapshot(order)
    preserved_buyer_snapshot = order.buyer_snapshot
    preserved_buyer_address_snapshot = order.buyer_address_snapshot
    freeze_sales_rate(order_values, previous=order)
    for field_name, value in order_values.items():
        setattr(order, field_name, value)
    order.buyer_snapshot = (
        _entity_snapshot(order.transaction_entity)
        if transaction_entity_changed or buyer_snapshot_changed
        else preserved_buyer_snapshot
    )
    order.buyer_address_snapshot = (
        _draft_buyer_address_snapshot(order)
        if buyer_address_changed or buyer_address_snapshot_changed
        else preserved_buyer_address_snapshot
    )
    order.full_clean()
    order.save()
    _update_confirmed_children_in_place(order, lines, batches)
    for business_file in evidence_files:
        if business_file.scan_status not in {FileScanStatus.CLEAN, FileScanStatus.SKIPPED}:
            raise ValidationError({"evidence_file_ids": f"凭证“{business_file.original_name}”尚未通过安全检查。"})
        SalesOrderEvidence.objects.get_or_create(
            sales_order=order,
            business_file=business_file,
            defaults={"uploaded_by_employee": actor_employee},
        )

    if evidence_file:
        SalesOrderEvidence.objects.get_or_create(
            sales_order=order,
            business_file=evidence_file,
            defaults={"uploaded_by_employee": actor_employee},
        )
    if buyer_address_changed or buyer_address_snapshot_changed:
        _freeze_buyer_address_snapshot(order)
    errors = _confirmation_errors(order)
    if errors:
        raise ValidationError(errors)

    now = timezone.now()
    order.version_number += 1
    order.confirmed_at = now
    order.confirmed_by_employee = actor_employee
    order.save(update_fields=["version_number", "confirmed_at", "confirmed_by_employee", "updated_at"])
    snapshot = sales_order_snapshot(order)
    snapshot["change_control"] = {
        "change_reason": change_reason,
        "customer_facing_change": customer_facing_change,
        "change_evidence_file_id": str(evidence_file.pk) if evidence_file else None,
        "pmc_impact_confirmed": bool(validated_data.get("pmc_impact_confirmed")),
        "had_production_orders": has_production,
    }
    SalesOrderVersion.objects.create(
        sales_order=order,
        version_number=order.version_number,
        snapshot=snapshot,
        change_reason=change_reason,
        confirmed_by_employee=actor_employee,
        confirmed_at=now,
    )
    write_audit_log(
        object_type="SALES_ORDER",
        object_id=order.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=order.customer_account_id,
        action="CONFIRMED_VERSION_CHANGED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=snapshot,
        request=request,
    )
    return order


def _confirmation_errors(order):
    errors = {}
    lines = list(order.lines.select_related("source_quotation_line", "product").all())
    if not lines:
        errors["lines"] = "请至少添加一个产品。"
    if not order.transaction_entity_id:
        errors["transaction_entity_id"] = "确认销售订单前，请选择买方主体。"
    seller_config = order.seller_snapshot.get("template_config", order.seller_snapshot) if isinstance(order.seller_snapshot, dict) else {}
    if not str(seller_config.get("seller_company_name") or seller_config.get("legal_name") or "").strip():
        errors["seller_snapshot"] = "确认销售订单前，请补齐卖方公司名称。"
    if not order.buyer_address_snapshot:
        errors["buyer_address_id"] = "确认销售订单前，请选择当前买方主体的有效地址。"
    confirmation_missing = []
    if not order.confirmation_method:
        confirmation_missing.append("确认方式")
    if not order.customer_confirmer.strip():
        confirmation_missing.append("客户确认人")
    if order.customer_confirmed_at is None:
        confirmation_missing.append("确认时间")
    if not order.confirmation_summary.strip():
        confirmation_missing.append("确认摘要")
    if confirmation_missing:
        errors["customer_confirmation"] = f"请补充：{'、'.join(confirmation_missing)}。"
    if order.source_type != SalesOrderSource.QUOTATION:
        if not order.direct_order_reason.strip():
            errors["direct_order_reason"] = "无报价或返单必须填写直接下单原因。"
        if not order.evidence_links.exists():
            errors["evidence_file_ids"] = "无报价或返单至少需要一份客户确认凭证。"

    allocation = defaultdict(lambda: Decimal("0"))
    for batch_line in SalesOrderDeliveryBatchLine.objects.filter(
        delivery_batch__sales_order=order,
        delivery_batch__status="ACTIVE",
    ):
        allocation[batch_line.sales_order_line_id] += Decimal(batch_line.quantity)
    for line in lines:
        if allocation[line.pk] != Decimal(line.quantity):
            errors.setdefault("delivery_batches", []).append(
                f"产品“{line.product_name_snapshot}”订单数量 {line.quantity} 与有效交付批次合计 {allocation[line.pk]} 不一致。"
            )
    return errors


@transaction.atomic
def confirm_sales_order(*, order, actor_employee, request=None):
    order = SalesOrder.objects.select_for_update().get(pk=order.pk)
    require_matching_etag(request, order)
    if order.status != SalesOrderStatus.DRAFT:
        raise Conflict("只有草稿销售订单可以确认。")
    if order.total_amount_cny is None or not order.exchange_rate_snapshot:
        raise ValidationError({"exchange_rate": "历史销售订单尚未补算人民币金额，请先完成一次性补算。"})
    lines = list(order.lines.select_related("source_quotation_line").all())
    _lock_and_validate_quote_capacity(
        order.source_quotation_version,
        [
            {"source_quotation_line": line.source_quotation_line, "quantity": line.quantity}
            for line in lines
            if line.source_quotation_line_id
        ],
        exclude_order_id=order.pk,
    )
    _freeze_buyer_address_snapshot(order)
    order.buyer_snapshot = _entity_snapshot(order.transaction_entity)
    order.save(update_fields=["buyer_snapshot", "updated_at"])
    errors = _confirmation_errors(order)
    if errors:
        raise ValidationError(errors)
    before = sales_order_snapshot(order)
    now = timezone.now()
    order.status = SalesOrderStatus.CONFIRMED
    order.confirmed_at = now
    order.confirmed_by_employee = actor_employee
    order.save(update_fields=["status", "confirmed_at", "confirmed_by_employee", "updated_at"])
    snapshot = sales_order_snapshot(order)
    SalesOrderVersion.objects.create(
        sales_order=order,
        version_number=order.version_number,
        snapshot=snapshot,
        confirmed_by_employee=actor_employee,
        confirmed_at=now,
    )
    if order.source_quotation_version_id:
        source_inquiry = order.source_quotation_version.quotation.source_inquiry
        if source_inquiry_id := getattr(source_inquiry, "pk", None):
            # 询盘只跟踪到首张销售订单确认；剩余数量和后续拆单由销售订单模块继续跟踪。
            type(source_inquiry).objects.filter(pk=source_inquiry_id).update(status=InquiryStatus.CONVERTED)
            from apps.inquiries.handling_time import handle_time_event
            handle_time_event(source_inquiry_id, 'ORDER_CREATED', now=now)
    write_audit_log(
        object_type="SALES_ORDER",
        object_id=order.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=order.customer_account_id,
        action="CONFIRMED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=snapshot,
        request=request,
    )
    return order


@transaction.atomic
def add_collaboration_event(*, order, validated_data, actor_employee, request=None):
    require_file(request, validated_data.get("evidence_file"))
    order = SalesOrder.objects.select_for_update().get(pk=order.pk)
    require_matching_etag(request, order)
    batch = validated_data.get("delivery_batch")
    if batch and batch.sales_order_id != order.pk:
        raise ValidationError({"delivery_batch_id": "交付批次不属于当前销售订单。"})
    event = SalesOrderCollaborationEvent.objects.create(
        sales_order=order,
        source_type=CollaborationEventSource.MANUAL,
        recorded_by_employee=actor_employee,
        **validated_data,
    )
    event.full_clean()
    order.updated_at = timezone.now()
    order.save(update_fields=["updated_at"])
    write_audit_log(
        object_type="SALES_ORDER",
        object_id=order.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=order.customer_account_id,
        action="COLLABORATION_EVENT_RECORDED",
        actor_employee=actor_employee,
        after_data={"event_id": str(event.pk), "event_type": event.event_type, "status": event.status},
        request=request,
    )
    return event, order


@transaction.atomic
def cancel_delivery_batch(*, order, delivery_batch, reason, evidence_file, actor_employee, request=None):
    order = SalesOrder.objects.select_for_update().get(pk=order.pk)
    require_matching_etag(request, order)
    if order.status not in {SalesOrderStatus.CONFIRMED, SalesOrderStatus.FULFILLING}:
        raise Conflict("只有已确认或履约中的销售订单可以取消交付批次。")
    batch = SalesOrderDeliveryBatch.objects.select_for_update().get(pk=delivery_batch.pk, sales_order=order)
    if batch.status == DeliveryBatchStatus.CANCELLED:
        raise Conflict("该交付批次已经取消。")
    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValidationError({"reason": "取消已确认交付批次必须填写原因。"})
    if not SalesOrderEvidence.objects.filter(sales_order=order, business_file=evidence_file).exists():
        raise ValidationError({"evidence_file_id": "取消批次必须选择当前订单的客户确认凭证。"})
    batch.status = DeliveryBatchStatus.CANCELLED
    batch.cancelled_at = timezone.now()
    batch.cancellation_reason = normalized_reason
    batch.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])
    event = SalesOrderCollaborationEvent.objects.create(
        sales_order=order,
        delivery_batch=batch,
        event_type=CollaborationEventType.NOTE,
        source_type=CollaborationEventSource.SYSTEM,
        status=CollaborationEventStatus.RISK,
        title=f"{batch.batch_number} 已取消，需处理下游单据",
        note=f"{normalized_reason}。请分别检查关联生产订单、BOM、采购申请和供应商采购单。",
        occurred_at=timezone.now(),
        evidence_file=evidence_file,
        recorded_by_employee=actor_employee,
    )
    now = timezone.now()
    order.version_number += 1
    order.confirmed_at = now
    order.confirmed_by_employee = actor_employee
    order.save(update_fields=["version_number", "confirmed_at", "confirmed_by_employee", "updated_at"])
    snapshot = sales_order_snapshot(order)
    snapshot["change_control"] = {
        "change_reason": normalized_reason,
        "customer_facing_change": True,
        "change_evidence_file_id": str(evidence_file.pk),
        "pmc_impact_confirmed": False,
        "delivery_batch_cancelled": str(batch.pk),
    }
    SalesOrderVersion.objects.create(
        sales_order=order,
        version_number=order.version_number,
        snapshot=snapshot,
        change_reason=f"取消 {batch.batch_number}：{normalized_reason}",
        confirmed_by_employee=actor_employee,
        confirmed_at=now,
    )
    write_audit_log(
        object_type="SALES_ORDER",
        object_id=order.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=order.customer_account_id,
        action="DELIVERY_BATCH_CANCELLED",
        actor_employee=actor_employee,
        after_data={
            "delivery_batch_id": str(batch.pk),
            "reason": normalized_reason,
            "event_id": str(event.pk),
            "version_number": order.version_number,
        },
        request=request,
    )
    return batch, order


@transaction.atomic
def complete_sales_order(*, order, exception_close, reason, actor_employee, request=None):
    order = SalesOrder.objects.select_for_update().get(pk=order.pk)
    require_matching_etag(request, order)
    if order.status not in {SalesOrderStatus.CONFIRMED, SalesOrderStatus.FULFILLING}:
        raise Conflict("只有已确认或履约中的销售订单可以完结。")
    normalized_reason = str(reason or "").strip()
    progress = sales_order_completion_progress(order)
    active_demand = progress["active_demand"]
    shipped = progress["shipped_quantity"]
    blockers = progress["blockers"]
    if blockers and not exception_close:
        raise ValidationError({"completion": [*blockers, "商业单证为提醒项，不阻断完结。"]})
    if exception_close and not normalized_reason:
        raise ValidationError({"reason": "异常关闭销售订单必须填写原因。"})
    order.status = SalesOrderStatus.COMPLETED
    order.save(update_fields=["status", "updated_at"])
    SalesOrderCollaborationEvent.objects.create(
        sales_order=order,
        event_type=CollaborationEventType.NOTE,
        source_type=CollaborationEventSource.SYSTEM,
        status=CollaborationEventStatus.RISK if exception_close else CollaborationEventStatus.COMPLETED,
        title="销售订单异常关闭" if exception_close else "销售订单正常完结",
        note=normalized_reason or "全部有效交付数量已发货，余款已登记完成。商业单证不作为阻断项。",
        occurred_at=timezone.now(),
        recorded_by_employee=actor_employee,
    )
    write_audit_log(
        object_type="SALES_ORDER",
        object_id=order.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=order.customer_account_id,
        action="EXCEPTION_CLOSED" if exception_close else "COMPLETED",
        actor_employee=actor_employee,
        after_data={"shipped_quantity": str(shipped), "active_demand": str(active_demand), "reason": normalized_reason},
        request=request,
    )
    return order
