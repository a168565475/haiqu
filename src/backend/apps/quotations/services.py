from apps.access_control import sales_policy
import hashlib
import json
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.customers.services import model_snapshot, write_customer_timeline
from apps.email_accounts.services import (
    EmailDeliveryUncertain,
    default_email_account_for_employee,
    email_account_snapshot,
    send_via_email_account,
)
from apps.workflow.models import ApprovalRequest, ApprovalStatus
from apps.inquiries.models import Inquiry, InquiryItem, InquiryStatus, InquiryTaskLink, format_inquiry_item_specification
from apps.inquiries.services import ITEM_FIELDS, prepare_inquiry_item_data
from apps.files.models import BusinessFile, FileScanStatus, USABLE_FILE_SCAN_STATUSES

from .models import (
    Quotation,
    QuotationContainerConfig,
    QuotationContainerTier,
    QuotationDispatchRecord,
    QuotationEmailDispatchAttempt,
    QuotationEmailDispatchAttemptStatus,
    QuotationDocument,
    QuotationDocumentType,
    QuotationFileLink,
    QuotationLine,
    QuotationLinePrice,
    QuotationLinePackaging,
    QuotationOutcomeStatus,
    QuotationQuantityTier,
    QuotationAcceptance,
    QuotationPriceBasis,
    QuotationTemplate,
    QuotationVersion,
    QuotationVersionApprovalLink,
    QuotationVersionStatus,
)


MONEY_QUANT = Decimal("0.0001")
DEFAULT_QUOTATION_TEMPLATE_CODE = "HAIQU_FIXED_BILINGUAL"
QUOTATION_FIELDS = [
    "customer_account",
    "transaction_entity",
    "source_inquiry",
    "owner_employee",
    "quotation_number",
    "outcome_status",
    "accepted_version",
    "subject",
    "outcome_note",
    "creation_idempotency_key",
]
VERSION_FIELDS = [
    "quotation",
    "parent_version",
    "quotation_template",
    "version_number",
    "status",
    "currency_code",
    "language_code",
    "subtotal_amount",
    "discount_amount",
    "tax_amount",
    "total_amount",
    "issued_at",
    "valid_until",
    "locked_at",
    "locked_by_employee",
    "transaction_entity_snapshot",
    "address_snapshot",
    "contact_snapshot",
    "template_snapshot",
    "terms_snapshot",
    "customer_requirement_snapshot",
    "notes",
]
LINE_FIELDS = [
    "quotation_version",
    "source_inquiry_item",
    "lineage_id",
    "line_number",
    "product_description_snapshot",
    "specification_snapshot",
    "color_snapshot",
    "quantity",
    "unit_code",
    "unit_price",
    "discount_rate",
    "line_total",
    "notes",
    "product_image",
    "product",
    "product_category",
    "product_unit",
    "product_color",
    "product_number_snapshot",
    "product_code_snapshot",
    "item_number_snapshot",
    "material_snapshot",
]
PACKAGING_QUANT = Decimal("0.001")


def _money(value):
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _line_total(quantity, unit_price, discount_rate):
    if unit_price is None:
        return None
    return _money(Decimal(quantity) * Decimal(unit_price) * (Decimal("1") - Decimal(discount_rate)))


def quotation_line_values_from_inquiry_item(item):
    """将询盘明细转换为报价明细字段，保留来源与当前快照的边界。"""
    # 当前已确认规则：询盘转报价时目标价先带入报价单价，报价人员可以继续修改。
    unit_price = item.target_unit_price
    return {
        "source_inquiry_item": item,
        "product": item.product,
        "product_category": item.product_category,
        "product_unit": item.product_unit,
        "product_color": item.product_color,
        "product_number_snapshot": item.product_number_snapshot,
        "product_code_snapshot": item.product_code_snapshot,
        "item_number_snapshot": item.item_number_snapshot,
        "product_description_snapshot": item.product_description,
        "specification_snapshot": format_inquiry_item_specification(
            item.specification,
            item.color,
            item.material,
        ),
        "color_snapshot": item.color or None,
        "material_snapshot": item.material,
        "quantity": item.quantity,
        "unit_code": item.unit_code,
        "unit_price": unit_price,
        "line_total": _line_total(item.quantity, unit_price, Decimal("0")),
        "notes": item.notes,
        "product_image": item.product_image,
    }


@transaction.atomic
def sync_quotation_line_to_inquiry(*, line, inquiry_etag, actor_employee, request):
    """将报价明细身份明确同步回来源询盘明细，商业字段和图片保持不变。"""
    # 与报价编辑、BOM 回写保持相同锁顺序，避免版本和明细交叉等待。
    version = QuotationVersion.objects.select_for_update().get(pk=line.quotation_version_id)
    require_matching_etag(request, version)
    _ensure_draft(version)
    line = QuotationLine.objects.select_for_update(of=("self",)).select_related(
        "quotation_version__quotation",
        "source_inquiry_item__inquiry",
        "product",
        "product_category",
        "product_unit",
        "product_color",
    ).get(pk=line.pk)
    source_item = line.source_inquiry_item
    if source_item is None:
        raise Conflict("当前报价明细没有来源询盘明细，不能执行同步。")
    inquiry = Inquiry.objects.select_for_update().get(pk=source_item.inquiry_id)
    if inquiry_etag != etag_for_instance(inquiry):
        from apps.core.api.concurrency import PreconditionFailed

        raise PreconditionFailed("来源询盘已被其他人修改，请重新加载后再同步。")
    if inquiry.status not in {InquiryStatus.DRAFT, InquiryStatus.READY_FOR_QUOTE, InquiryStatus.QUOTING}:
        raise Conflict("当前询盘状态不允许同步产品身份信息。")
    sales_policy.require_customer(request, "inquiries.change_inquiryitem", inquiry.customer_account)
    before_data = model_snapshot(source_item, ITEM_FIELDS)
    product = line.product
    identity_data = {
        "product": product,
        "product_category": line.product_category,
        "product_unit": line.product_unit,
        "product_color": line.product_color,
        "product_description": product.product_name if product is not None else line.product_description_snapshot,
        "specification": product.specification if product is not None else line.specification_snapshot,
        "color": line.color_snapshot or "",
        "material": line.material_snapshot,
        "unit_code": line.unit_code,
    }
    values = prepare_inquiry_item_data(identity_data, existing=source_item)
    for field_name, value in values.items():
        if field_name in ITEM_FIELDS:
            setattr(source_item, field_name, value)
    source_item.save(update_fields=[field for field in values if field in ITEM_FIELDS] + ["updated_at"])
    inquiry.updated_at = timezone.now()
    inquiry.save(update_fields=["updated_at"])
    write_audit_log(
        object_type="INQUIRY_ITEM",
        object_id=source_item.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=inquiry.customer_account_id,
        action="SYNCED_FROM_QUOTATION",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data={
            **model_snapshot(source_item, ITEM_FIELDS),
            "sync_source": {
                "quotation_id": str(version.quotation_id),
                "quotation_number": line.quotation_version.quotation.quotation_number,
                "quotation_version_id": str(version.pk),
                "quotation_version_number": version.version_number,
                "quotation_line_id": str(line.pk),
            },
        },
        request=request,
    )
    write_customer_timeline(
        customer=inquiry.customer_account,
        event_type="INQUIRY_ITEM_SYNCED_FROM_QUOTATION",
        title=f"{inquiry.inquiry_number} 产品信息已从报价同步",
        summary=f"报价明细 {line.product_description_snapshot} 已同步，数量、目标价、日期和图片未改变。",
        source_type="INQUIRY",
        source_id=inquiry.pk,
        actor_employee=actor_employee,
        event_data={
            "quotation_id": str(version.quotation_id),
            "quotation_number": line.quotation_version.quotation.quotation_number,
            "quotation_version_id": str(version.pk),
            "quotation_version_number": version.version_number,
            "quotation_line_id": str(line.pk),
            "inquiry_item_id": str(source_item.pk),
        },
    )
    return source_item, inquiry


def _recalculate_version_amounts(version):
    """报价版本金额只以当前真实报价行为依据，在同一事务内回写。"""
    subtotal = Decimal("0")
    discount = Decimal("0")
    for line in version.lines.all():
        if line.unit_price is None or line.line_total is None:
            continue
        gross_amount = _money(Decimal(line.quantity) * Decimal(line.unit_price))
        subtotal += gross_amount
        discount += gross_amount - Decimal(line.line_total)
    version.subtotal_amount = _money(subtotal)
    version.discount_amount = _money(discount)
    version.total_amount = _money(version.subtotal_amount - version.discount_amount + Decimal(version.tax_amount))
    version.save(update_fields=["subtotal_amount", "discount_amount", "total_amount", "updated_at"])


def _touch(instance):
    instance.updated_at = timezone.now()
    instance.save(update_fields=["updated_at"])


def _carton_cbm(*, length_cm, width_cm, height_cm):
    carton_cbm = (Decimal(length_cm) * Decimal(width_cm) * Decimal(height_cm) / Decimal("1000000")).quantize(
        PACKAGING_QUANT,
        rounding=ROUND_HALF_UP,
    )
    if carton_cbm <= 0:
        raise ValidationError({
            "dimensions": ["箱规体积按三位小数四舍五入后必须至少为 0.001 m³，请检查长、宽、高。"]
        })
    return carton_cbm


def _recalculate_container_tier(*, tier, packaging):
    usable_volume = Decimal(tier.effective_volume_cbm) * Decimal(tier.load_factor)
    carton_count = int((usable_volume / Decimal(packaging.carton_cbm)).to_integral_value(rounding=ROUND_FLOOR))
    tier.auto_carton_count = max(carton_count, 0)
    tier.auto_quantity = Decimal(tier.auto_carton_count * packaging.pieces_per_carton).quantize(MONEY_QUANT)
    tier.final_quantity = tier.auto_quantity
    tier.save(update_fields=["auto_carton_count", "auto_quantity", "final_quantity", "updated_at"])


def _packaging_audit_data(packaging):
    return {
        "quotation_line_id": str(packaging.quotation_line_id),
        "length_cm": str(packaging.length_cm),
        "width_cm": str(packaging.width_cm),
        "height_cm": str(packaging.height_cm),
        "pieces_per_carton": packaging.pieces_per_carton,
        "carton_count": packaging.carton_count,
        "carton_cbm": str(packaging.carton_cbm),
    }


def _write_quote_records(*, quotation, action, actor_employee, request, before_data=None, note=""):
    write_audit_log(
        object_type="QUOTATION",
        object_id=quotation.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=quotation.customer_account_id,
        action=action,
        actor_employee=actor_employee,
        before_data=before_data,
        after_data={**model_snapshot(quotation, QUOTATION_FIELDS), "note": note},
        request=request,
    )
    write_customer_timeline(
        customer=quotation.customer_account,
        event_type=f"QUOTATION_{action}",
        title=f"{quotation.quotation_number} {quotation.subject}",
        summary=note,
        source_type="QUOTATION",
        source_id=quotation.pk,
        actor_employee=actor_employee,
    )


def _write_version_records(*, version, action, actor_employee, request, before_data=None, note=""):
    write_audit_log(
        object_type="QUOTATION_VERSION",
        object_id=version.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=version.quotation.customer_account_id,
        action=action,
        actor_employee=actor_employee,
        before_data=before_data,
        after_data={**model_snapshot(version, VERSION_FIELDS), "note": note},
        request=request,
    )
    write_customer_timeline(
        customer=version.quotation.customer_account,
        event_type=f"QUOTATION_VERSION_{action}",
        title=f"{version.quotation.quotation_number} V{version.version_number}",
        summary=note,
        source_type="QUOTATION_VERSION",
        source_id=version.pk,
        actor_employee=actor_employee,
    )


@transaction.atomic
def create_quotation(*, validated_data, actor_employee, request):
    customer = validated_data["customer_account"]
    sales_policy.require_customer(request, "quotations.add_quotation", customer)
    sales_policy.validate_document_owner(request, customer, validated_data.get("owner_employee"))
    if validated_data.get("source_inquiry"):
        sales_policy.require_customer(request, "inquiries.view_inquiry", customer)
    quotation = Quotation.objects.create(
        quotation_number=next_business_number("QUOTATION"),
        outcome_status=QuotationOutcomeStatus.OPEN,
        **validated_data,
    )
    _write_quote_records(
        quotation=quotation,
        action="CREATED",
        actor_employee=actor_employee,
        request=request,
    )
    return quotation


@transaction.atomic
def create_quotation_draft(*, quotation_data, version_data, actor_employee, request):
    """一次事务创建报价与首个草稿版本，避免网络中断留下无版本报价。"""
    quotation = create_quotation(
        validated_data=quotation_data,
        actor_employee=actor_employee,
        request=request,
    )
    version = QuotationVersion.objects.create(
        quotation=quotation,
        quotation_template=_default_quotation_template(),
        version_number=1,
        status=QuotationVersionStatus.DRAFT,
        currency_code=version_data["currency_code"],
        valid_until=version_data.get("valid_until"),
        language_code="zh-hans",
        terms_snapshot={},
    )
    _touch(quotation)
    _write_version_records(
        version=version,
        action="CREATED",
        actor_employee=actor_employee,
        request=request,
        note="创建首个草稿版本",
    )
    from apps.inquiries.handling_time import quote_created
    quote_created(version)
    return quotation, version


def _next_entity_code(customer):
    """交易主体编号只由服务端生成，避免前端拼接出重复编号。"""
    base = f"{customer.account_code}-LEGAL"[:44]
    candidate = base
    suffix = 1
    from apps.customers.models import CustomerTransactionEntity

    while CustomerTransactionEntity.objects.filter(entity_code=candidate).exists():
        suffix += 1
        candidate = f"{base[:44]}-{suffix}"
    return candidate


def _inquiry_requirement_snapshot(inquiry):
    return {
        "inquiry_id": str(inquiry.pk),
        "inquiry_number": inquiry.inquiry_number,
        "delivery_requirement": inquiry.delivery_requirement,
        "trade_term_code": inquiry.trade_term_code,
        "trade_term_place": inquiry.trade_term_place,
        "items": [
            {
                "inquiry_item_id": str(item.pk),
                "line_number": item.line_number,
                "target_unit_price": str(item.target_unit_price) if item.target_unit_price is not None else None,
                "target_currency_code": item.target_currency_code,
                "color": item.color,
                "expected_date": item.expected_date.isoformat() if item.expected_date else None,
            }
            for item in inquiry.items.all().order_by("line_number", "id")
        ],
    }


@transaction.atomic
def create_quotation_from_inquiry(*, inquiry_id, entity_id, entity_data, subject, currency_code, due_at,
                                  idempotency_key, create_another, actor_employee, request):
    """在一个事务内完成主体补录、报价草稿、来源行、待办与询盘状态更新。"""
    from apps.customers.models import CustomerTransactionEntity
    from apps.workflow.models import TaskOriginType, TaskPriority, TaskType
    from apps.workflow.services import create_task, resolve_task_source

    inquiry = Inquiry.objects.select_for_update(of=("self",)).select_related(
        "customer_account", "owner_employee", "transaction_entity"
    ).prefetch_related("items").get(pk=inquiry_id, archived_at__isnull=True)
    sales_policy.require_customer(request, "inquiries.view_inquiry", inquiry.customer_account)
    sales_policy.require_customer(request, "inquiries.change_inquiry", inquiry.customer_account)
    sales_policy.require_customer(request, "quotations.add_quotation", inquiry.customer_account)
    require_matching_etag(request, inquiry)
    if inquiry.status not in {InquiryStatus.READY_FOR_QUOTE, InquiryStatus.QUOTING}:
        raise Conflict("当前询盘状态不能创建报价。")
    if not inquiry.owner_employee_id:
        raise ValidationError({"detail": "询盘缺少负责人，无法创建报价任务。"})
    if not idempotency_key:
        raise ValidationError({"idempotency_key": ["请提供幂等键。"]})

    existing = Quotation.objects.select_for_update().filter(creation_idempotency_key=idempotency_key).first()
    if existing:
        if existing.source_inquiry_id != inquiry.pk:
            raise Conflict("该幂等键已用于其他询盘报价。")
        return existing, existing.versions.order_by("version_number").first(), True

    active_quotes = Quotation.objects.select_for_update().filter(
        source_inquiry=inquiry, archived_at__isnull=True, outcome_status=QuotationOutcomeStatus.OPEN
    )
    if active_quotes.exists() and not create_another:
        raise Conflict("该询盘已有进行中的报价，请打开已有报价或明确确认新建另一份报价。")

    customer = inquiry.customer_account
    if entity_id:
        entity = CustomerTransactionEntity.objects.select_for_update().filter(
            pk=entity_id, customer_account=customer, archived_at__isnull=True
        ).first()
        if entity is None:
            raise ValidationError({"transaction_entity_id": ["交易主体不存在或不属于当前客户。"]})
    elif inquiry.transaction_entity_id:
        entity = inquiry.transaction_entity
    else:
        if not entity_data:
            raise ValidationError({"transaction_entity": ["请补录客户交易主体。"]})
        legal_name = (entity_data.get("legal_name") or "").strip()
        registration_country_code = (entity_data.get("registration_country_code") or "").strip().upper()
        if not legal_name:
            raise ValidationError({"transaction_entity.legal_name": ["法定主体名称不能为空。"]})
        if not registration_country_code:
            raise ValidationError({"transaction_entity.registration_country_code": ["注册国家不能为空。"]})
        sales_policy.require_customer(request, "customers.add_customertransactionentity", customer)
        entity = CustomerTransactionEntity.objects.create(
            customer_account=customer,
            entity_code=_next_entity_code(customer),
            legal_name=legal_name,
            registration_country_code=registration_country_code,
        )
        write_audit_log(
            object_type="CUSTOMER_TRANSACTION_ENTITY", object_id=entity.pk,
            context_type="CUSTOMER_ACCOUNT", context_id=customer.pk, action="CREATED_FROM_INQUIRY_QUOTE",
            actor_employee=actor_employee, after_data=model_snapshot(entity, ["entity_code", "legal_name", "registration_country_code"]), request=request,
        )
        write_customer_timeline(
            customer=customer, event_type="CUSTOMER_TRANSACTION_ENTITY_CREATED", title="补录客户交易主体",
            summary=entity.legal_name, source_type="CUSTOMER_TRANSACTION_ENTITY", source_id=entity.pk,
            actor_employee=actor_employee,
        )

    quotation, version = create_quotation_draft(
        quotation_data={
            "customer_account": customer,
            "transaction_entity": entity,
            "source_inquiry": inquiry,
            "owner_employee": sales_policy.primary_owner(customer) if sales_policy.enabled() else inquiry.owner_employee,
            "subject": subject.strip() or inquiry.subject,
            "creation_idempotency_key": idempotency_key,
        },
        version_data={"currency_code": currency_code, "valid_until": None},
        actor_employee=actor_employee, request=request,
    )
    version.customer_requirement_snapshot = _inquiry_requirement_snapshot(inquiry)
    version.save(update_fields=["customer_requirement_snapshot", "updated_at"])
    for item in inquiry.items.all().order_by("line_number", "id"):
        QuotationLine.objects.create(
            quotation_version=version,
            line_number=item.line_number,
            discount_rate=Decimal("0"),
            **quotation_line_values_from_inquiry_item(item),
        )
    _touch(version)
    _write_version_records(version=version, action="INQUIRY_ITEMS_IMPORTED", actor_employee=actor_employee,
                           request=request, note=f"来源询盘：{inquiry.inquiry_number}；价格待录入")

    task = create_task(
        validated_data={
            "assignee_employee": inquiry.owner_employee,
            "title": f"完成报价草稿：{quotation.quotation_number}",
            "description": f"来源询盘：{inquiry.inquiry_number}",
            "due_at": due_at,
            "priority": TaskPriority.HIGH,
            "task_type": TaskType.QUOTATION_FOLLOW_UP,
            "origin_type": TaskOriginType.BUSINESS_EVENT,
            "origin_code": "INQUIRY_CREATE_QUOTATION",
        },
        actor_employee=actor_employee, request=request,
        resolved_source=resolve_task_source("QUOTATION_VERSION", version.pk),
    )
    InquiryTaskLink.objects.create(inquiry=inquiry, business_task=task, is_primary_source=False)

    if inquiry.status == InquiryStatus.READY_FOR_QUOTE:
        before_status = inquiry.status
        inquiry.status = InquiryStatus.QUOTING
        inquiry.transaction_entity = entity
        inquiry.save(update_fields=["status", "transaction_entity", "updated_at"])
        write_audit_log(
            object_type="INQUIRY", object_id=inquiry.pk, context_type="CUSTOMER_ACCOUNT", context_id=customer.pk,
            action="QUOTE_DRAFT_CREATED", actor_employee=actor_employee,
            before_data={"status": before_status}, after_data={"status": inquiry.status, "quotation_id": str(quotation.pk)},
            request=request,
        )
        write_customer_timeline(
            customer=customer, event_type="INQUIRY_QUOTING", title=f"询盘进入报价中：{inquiry.inquiry_number}",
            summary=f"已创建报价草稿 {quotation.quotation_number}", source_type="INQUIRY", source_id=inquiry.pk,
            actor_employee=actor_employee,
        )
    return quotation, version, False


@transaction.atomic
def update_quotation(*, quotation, validated_data, actor_employee, request):
    quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
    if "owner_employee" in validated_data:
        sales_policy.validate_document_owner(request, quotation.customer_account, validated_data["owner_employee"], quotation.owner_employee)
    if validated_data.get("source_inquiry"):
        sales_policy.require_customer(request, "inquiries.view_inquiry", validated_data["source_inquiry"].customer_account)
    require_matching_etag(request, quotation)
    if quotation.outcome_status != QuotationOutcomeStatus.OPEN:
        raise Conflict("终态报价不能再修改。")
    if quotation.versions.exclude(status=QuotationVersionStatus.DRAFT).exists() and any(
        field in validated_data for field in ["transaction_entity", "source_inquiry"]
    ):
        raise Conflict("已有锁定版本时不能修改交易主体或来源询价。")
    before_data = model_snapshot(quotation, QUOTATION_FIELDS)
    for field_name, value in validated_data.items():
        setattr(quotation, field_name, value)
    quotation.save(update_fields=[*validated_data.keys(), "updated_at"])
    _write_quote_records(
        quotation=quotation,
        action="UPDATED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
    )
    return quotation


def _copy_version_content(source, target):
    line_map = {}
    for source_line in source.lines.prefetch_related(
        "quantity_tiers", "container_tiers__container_config", "basis_prices"
    ).select_related("packaging").all():
        copied_data = {
            "quotation_version": target,
            "source_inquiry_item": source_line.source_inquiry_item,
            "line_number": source_line.line_number,
            "product_description_snapshot": source_line.product_description_snapshot,
            "specification_snapshot": source_line.specification_snapshot,
            "color_snapshot": source_line.color_snapshot,
            "quantity": source_line.quantity,
            "unit_code": source_line.unit_code,
            "unit_price": source_line.unit_price,
            "discount_rate": source_line.discount_rate,
            "line_total": source_line.line_total,
            "notes": source_line.notes,
            "product_image": source_line.product_image,
            "product": source_line.product,
            "product_category": source_line.product_category,
            "product_unit": source_line.product_unit,
            "product_color": source_line.product_color,
            "product_number_snapshot": source_line.product_number_snapshot,
            "product_code_snapshot": source_line.product_code_snapshot,
            "item_number_snapshot": source_line.item_number_snapshot,
            "material_snapshot": source_line.material_snapshot,
        }
        if source_line.lineage_id:
            copied_data["lineage_id"] = source_line.lineage_id
        copied = QuotationLine.objects.create(
            **copied_data,
        )
        line_map[source_line.pk] = copied
        QuotationQuantityTier.objects.bulk_create(
            [
                QuotationQuantityTier(
                    quotation_line=copied,
                    min_quantity=tier.min_quantity,
                    max_quantity=tier.max_quantity,
                    unit_price=tier.unit_price,
                )
                for tier in source_line.quantity_tiers.all()
            ]
        )
        try:
            source_packaging = source_line.packaging
        except QuotationLinePackaging.DoesNotExist:
            continue
        packaging = QuotationLinePackaging.objects.create(
            quotation_line=copied,
            length_cm=source_packaging.length_cm,
            width_cm=source_packaging.width_cm,
            height_cm=source_packaging.height_cm,
            pieces_per_carton=source_packaging.pieces_per_carton,
            carton_count=source_packaging.carton_count,
            gross_weight_kg=source_packaging.gross_weight_kg,
            net_weight_kg=source_packaging.net_weight_kg,
            carton_cbm=source_packaging.carton_cbm,
        )
        for source_tier in source_line.container_tiers.all():
            copied_tier = QuotationContainerTier.objects.create(
                quotation_line=copied,
                tier_number=source_tier.tier_number,
                container_config=source_tier.container_config,
                container_type_code=source_tier.container_type_code,
                effective_volume_cbm=source_tier.effective_volume_cbm,
                load_factor=source_tier.load_factor,
                unit_price=source_tier.unit_price,
                auto_carton_count=0,
                auto_quantity=Decimal("0"),
                final_quantity=Decimal("0"),
            )
            _recalculate_container_tier(tier=copied_tier, packaging=packaging)

    basis_map = {}
    for source_basis in source.price_bases.all():
        basis_map[source_basis.pk] = QuotationPriceBasis.objects.create(
            quotation_version=target,
            label=source_basis.label,
            incoterm_code=source_basis.incoterm_code,
            named_place=source_basis.named_place,
            currency_code=source_basis.currency_code,
            is_default=source_basis.is_default,
            sort_order=source_basis.sort_order,
            notes=source_basis.notes,
        )
    QuotationLinePrice.objects.bulk_create(
        [
            QuotationLinePrice(
                quotation_line=line_map[source_price.quotation_line_id],
                price_basis=basis_map[source_price.price_basis_id],
                unit_price=source_price.unit_price,
                surcharge_note=source_price.surcharge_note,
                is_manual_override=source_price.is_manual_override,
                override_reason=source_price.override_reason,
            )
            for source_price in QuotationLinePrice.objects.filter(
                quotation_line__quotation_version=source
            )
        ]
    )


@transaction.atomic
def replace_price_matrix(*, version, bases_data, actor_employee, request):
    """原子替换草稿版本的价格口径矩阵，并将默认口径同步到兼容金额字段。"""
    version = QuotationVersion.objects.select_for_update().select_related("quotation").get(pk=version.pk)
    require_matching_etag(request, version)
    _ensure_draft(version)
    if not bases_data:
        raise ValidationError({"price_bases": ["至少需要一个价格口径。"]})
    if sum(1 for item in bases_data if item.get("is_default")) != 1:
        raise ValidationError({"price_bases": ["必须且只能设置一个默认价格口径。"]})

    lines = {str(line.pk): line for line in version.lines.select_for_update().all()}
    expected_line_ids = set(lines)
    before_data = {
        "price_basis_count": version.price_bases.count(),
        "line_price_count": QuotationLinePrice.objects.filter(
            quotation_line__quotation_version=version
        ).count(),
    }
    QuotationLinePrice.objects.filter(quotation_line__quotation_version=version).delete()
    version.price_bases.all().delete()

    default_prices = {}
    for sort_order, basis_data in enumerate(bases_data, start=1):
        line_prices = basis_data.pop("line_prices")
        basis = QuotationPriceBasis.objects.create(
            quotation_version=version,
            sort_order=sort_order,
            **basis_data,
        )
        submitted_line_ids = {str(item["quotation_line"].pk) for item in line_prices}
        if submitted_line_ids != expected_line_ids:
            raise ValidationError({
                "price_bases": [f"价格口径“{basis.label}”必须为当前版本全部报价明细填写价格。"]
            })
        for price_data in line_prices:
            line = price_data.pop("quotation_line")
            if line.quotation_version_id != version.pk:
                raise ValidationError({"price_bases": ["价格明细包含其他报价版本的产品。"]})
            QuotationLinePrice.objects.create(
                quotation_line=line,
                price_basis=basis,
                **price_data,
            )
            if basis.is_default:
                default_prices[line.pk] = price_data["unit_price"]

    for line in lines.values():
        line.unit_price = default_prices[line.pk]
        line.line_total = _line_total(line.quantity, line.unit_price, line.discount_rate)
        line.save(update_fields=["unit_price", "line_total", "updated_at"])
    _recalculate_version_amounts(version)
    _write_version_records(
        version=version,
        action="PRICE_MATRIX_REPLACED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=f"已维护 {len(bases_data)} 个价格口径。",
    )
    return version


@transaction.atomic
def create_version(*, quotation, validated_data, actor_employee, request):
    quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
    require_matching_etag(request, quotation)
    if quotation.outcome_status != QuotationOutcomeStatus.OPEN:
        raise Conflict("终态报价不能新增版本。")
    source = validated_data.pop("from_version", None)
    if source:
        sales_policy.require_customer(request, "quotations.view_quotationversion", source.quotation.customer_account)
    if source and source.quotation_id != quotation.pk:
        raise ValidationError({"from_version_id": ["复制来源必须属于当前报价。"]})
    next_number = (quotation.versions.aggregate(value=Max("version_number"))["value"] or 0) + 1
    if source:
        validated_data.setdefault("quotation_template", source.quotation_template)
        validated_data.setdefault("currency_code", source.currency_code)
        validated_data.setdefault("language_code", source.language_code)
        validated_data.setdefault("valid_until", source.valid_until)
        validated_data.setdefault("notes", source.notes)
        # 新草稿先继承来源版本的正式商业快照，避免版本差异页把未重新锁定
        # 误判为“买方主体/地址/联系人被删除”；再次锁定时会用最新选择覆盖。
        validated_data.setdefault("transaction_entity_snapshot", source.transaction_entity_snapshot)
        validated_data.setdefault("address_snapshot", source.address_snapshot)
        validated_data.setdefault("contact_snapshot", source.contact_snapshot)
        validated_data.setdefault("template_snapshot", source.template_snapshot)
        validated_data.setdefault("customer_requirement_snapshot", source.customer_requirement_snapshot)
        # 复制版本的行与金额快照必须同步，避免差异页出现“无字段变化但总额变化”。
        validated_data.setdefault("subtotal_amount", source.subtotal_amount)
        validated_data.setdefault("discount_amount", source.discount_amount)
        validated_data.setdefault("tax_amount", source.tax_amount)
        validated_data.setdefault("total_amount", source.total_amount)
    else:
        validated_data.setdefault("quotation_template", _default_quotation_template())
    version = QuotationVersion.objects.create(
        quotation=quotation,
        parent_version=source,
        version_number=next_number,
        status=QuotationVersionStatus.DRAFT,
        terms_snapshot=source.terms_snapshot if source else {},
        **validated_data,
    )
    if source:
        _copy_version_content(source, version)
    _touch(quotation)
    _write_version_records(
        version=version,
        action="CREATED",
        actor_employee=actor_employee,
        request=request,
        note=f"复制自 V{source.version_number}" if source else "",
    )
    from apps.inquiries.handling_time import quote_created
    quote_created(version)
    return version, quotation


@transaction.atomic
def create_requotation_draft(
    *,
    source_version,
    target_quotation,
    new_quotation_data,
    valid_until,
    feedback_note,
    actor_employee,
    request,
):
    """复制任意同客户历史版本；开放报价追加版本，终态报价则创建新报价。"""

    source = QuotationVersion.objects.select_for_update().select_related(
        "quotation__customer_account",
    ).get(pk=source_version.pk)
    sales_policy.require_customer(request, "quotations.view_quotationversion", source.quotation.customer_account)
    sales_policy.require_customer(request, "quotations.add_quotationversion", source.quotation.customer_account)
    if source.status == QuotationVersionStatus.VOID:
        raise Conflict("已作废的报价版本不能作为再报价复制来源。")
    if not source.lines.exists():
        raise ValidationError({"source_quotation_version_id": ["复制来源至少需要一条报价明细。"]})

    created_new_quotation = target_quotation is None
    if created_new_quotation:
        quotation_data = dict(new_quotation_data)
        if quotation_data["customer_account"].pk != source.quotation.customer_account_id:
            raise ValidationError({"source_quotation_version_id": ["复制来源必须属于同一客户。"]})
        quotation = create_quotation(
            validated_data=quotation_data,
            actor_employee=actor_employee,
            request=request,
        )
        version_number = 1
    else:
        quotation = Quotation.objects.select_for_update().get(pk=target_quotation.pk)
        if quotation.customer_account_id != source.quotation.customer_account_id:
            raise ValidationError({"source_quotation_version_id": ["复制来源必须属于同一客户。"]})
        if quotation.outcome_status != QuotationOutcomeStatus.OPEN:
            raise Conflict("目标报价已经终态，不能追加新版本。")
        version_number = (quotation.versions.aggregate(value=Max("version_number"))["value"] or 0) + 1

    note_parts = [source.notes.strip(), feedback_note.strip()]
    version = QuotationVersion.objects.create(
        quotation=quotation,
        parent_version=source,
        quotation_template=source.quotation_template or _default_quotation_template(),
        version_number=version_number,
        status=QuotationVersionStatus.DRAFT,
        currency_code=source.currency_code,
        language_code=source.language_code,
        subtotal_amount=source.subtotal_amount,
        discount_amount=source.discount_amount,
        tax_amount=source.tax_amount,
        total_amount=source.total_amount,
        valid_until=valid_until,
        transaction_entity_snapshot=source.transaction_entity_snapshot,
        address_snapshot=source.address_snapshot,
        contact_snapshot=source.contact_snapshot,
        template_snapshot=source.template_snapshot,
        terms_snapshot=source.terms_snapshot,
        customer_requirement_snapshot=source.customer_requirement_snapshot,
        notes="\n".join(part for part in note_parts if part),
    )
    _copy_version_content(source, version)
    _touch(quotation)
    _write_version_records(
        version=version,
        action="CREATED_FROM_SAMPLE_FEEDBACK",
        actor_employee=actor_employee,
        request=request,
        note=f"复制自 {source.quotation.quotation_number} V{source.version_number}",
    )
    from apps.inquiries.handling_time import quote_created
    quote_created(version)
    return quotation, version, created_new_quotation


@transaction.atomic
def update_version(*, version, validated_data, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=version.pk)
    require_matching_etag(request, version)
    if version.status != QuotationVersionStatus.DRAFT:
        raise Conflict("只有草稿报价版本可以修改。")
    before_data = model_snapshot(version, VERSION_FIELDS)
    for field_name, value in validated_data.items():
        setattr(version, field_name, value)
    version.save(update_fields=[*validated_data.keys(), "updated_at"])
    _write_version_records(
        version=version,
        action="UPDATED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
    )
    return version


def _ensure_draft(version):
    if version.status != QuotationVersionStatus.DRAFT:
        raise Conflict("报价版本锁定后，明细和阶梯价不可修改。")


def _apply_line_product_snapshots(data, *, current=None):
    """只在建立新关联时取产品主档快照，编辑同一关联不重新套用主档默认值。"""
    values = dict(data)
    product = values.get("product", getattr(current, "product", None))
    product_changed = current is None or (
        "product" in values and getattr(current, "product_id", None) != getattr(product, "pk", None)
    )
    if product is None:
        if "product" in values:
            values.update({
                "product_number_snapshot": "",
                "product_code_snapshot": "",
                "item_number_snapshot": "",
            })
        return values
    if product_changed:
        values.update({
            "product_category": product.category,
            "product_unit": product.unit,
            "product_number_snapshot": product.product_number,
            "product_code_snapshot": product.product_code,
            "item_number_snapshot": product.product_item.item_number,
        })
    return values


@transaction.atomic
def create_line(*, version, validated_data, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=version.pk)
    require_matching_etag(request, version)
    _ensure_draft(version)
    data = _apply_line_product_snapshots(validated_data)
    if "line_number" not in data:
        current_max = version.lines.aggregate(value=Max("line_number"))["value"] or 0
        data["line_number"] = current_max + 1
    data["line_total"] = _line_total(data["quantity"], data["unit_price"], data.get("discount_rate", 0))
    line = QuotationLine.objects.create(quotation_version=version, **data)
    _recalculate_version_amounts(version)
    write_audit_log(
        object_type="QUOTATION_LINE",
        object_id=line.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=version.quotation.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data=model_snapshot(line, LINE_FIELDS),
        request=request,
    )
    return line, version


@transaction.atomic
def update_line(*, line, validated_data, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=line.quotation_version_id)
    require_matching_etag(request, version)
    _ensure_draft(version)
    line = QuotationLine.objects.select_for_update().get(pk=line.pk)
    before_data = model_snapshot(line, LINE_FIELDS)
    validated_data = _apply_line_product_snapshots(validated_data, current=line)
    for field_name, value in validated_data.items():
        setattr(line, field_name, value)
    line.line_total = _line_total(line.quantity, line.unit_price, line.discount_rate)
    line.save(update_fields=[*validated_data.keys(), "line_total", "updated_at"])
    _recalculate_version_amounts(version)
    write_audit_log(
        object_type="QUOTATION_LINE",
        object_id=line.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=version.quotation.customer_account_id,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=model_snapshot(line, LINE_FIELDS),
        request=request,
    )
    return line, version


@transaction.atomic
def delete_line(*, line, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=line.quotation_version_id)
    require_matching_etag(request, version)
    _ensure_draft(version)
    line = QuotationLine.objects.select_for_update().get(pk=line.pk)
    before_data = model_snapshot(line, LINE_FIELDS)
    line_id = line.pk
    line.quantity_tiers.all().delete()
    line.container_tiers.all().delete()
    QuotationLinePackaging.objects.filter(quotation_line=line).delete()
    line.delete()
    _recalculate_version_amounts(version)
    write_audit_log(
        object_type="QUOTATION_LINE",
        object_id=line_id,
        context_type="CUSTOMER_ACCOUNT",
        context_id=version.quotation.customer_account_id,
        action="DELETED",
        actor_employee=actor_employee,
        before_data=before_data,
        request=request,
    )
    return version


@transaction.atomic
def create_tier(*, line, validated_data, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=line.quotation_version_id)
    require_matching_etag(request, version)
    _ensure_draft(version)
    tier = QuotationQuantityTier.objects.create(quotation_line=line, **validated_data)
    _touch(version)
    write_audit_log(
        object_type="QUOTATION_QUANTITY_TIER",
        object_id=tier.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=version.quotation.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data={
            "quotation_line_id": str(line.pk),
            "min_quantity": str(tier.min_quantity),
            "max_quantity": str(tier.max_quantity) if tier.max_quantity is not None else None,
            "unit_price": str(tier.unit_price),
        },
        request=request,
    )
    return tier, version


@transaction.atomic
def upsert_line_packaging(*, line, validated_data, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=line.quotation_version_id)
    require_matching_etag(request, version)
    _ensure_draft(version)
    line = QuotationLine.objects.select_for_update().get(pk=line.pk)
    carton_cbm = _carton_cbm(
        length_cm=validated_data["length_cm"],
        width_cm=validated_data["width_cm"],
        height_cm=validated_data["height_cm"],
    )
    packaging, created = QuotationLinePackaging.objects.select_for_update().get_or_create(
        quotation_line=line,
        defaults={**validated_data, "carton_cbm": carton_cbm},
    )
    before_data = None if created else _packaging_audit_data(packaging)
    if not created:
        for field_name, value in validated_data.items():
            setattr(packaging, field_name, value)
        packaging.carton_cbm = carton_cbm
        packaging.save(update_fields=[*validated_data.keys(), "carton_cbm", "updated_at"])
    for tier in line.container_tiers.select_for_update().all():
        _recalculate_container_tier(tier=tier, packaging=packaging)
    _touch(version)
    write_audit_log(
        object_type="QUOTATION_LINE_PACKAGING",
        object_id=packaging.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=version.quotation.customer_account_id,
        action="CREATED" if created else "UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=_packaging_audit_data(packaging),
        request=request,
    )
    return packaging, version


@transaction.atomic
def create_container_tier(*, line, container_type_code, effective_volume_cbm, load_factor, unit_price, actor_employee, request, container_config=None):
    version = QuotationVersion.objects.select_for_update().get(pk=line.quotation_version_id)
    require_matching_etag(request, version)
    _ensure_draft(version)
    line = QuotationLine.objects.select_for_update().get(pk=line.pk)
    try:
        packaging = QuotationLinePackaging.objects.select_for_update().get(quotation_line=line)
    except QuotationLinePackaging.DoesNotExist as exc:
        raise ValidationError({"detail": "请先保存包装信息，再配置装柜数量档。"}) from exc
    config = None
    if container_config is not None:
        config = QuotationContainerConfig.objects.select_for_update().get(
            pk=container_config.pk,
            archived_at__isnull=True,
            is_active=True,
        )
        container_type_code = config.container_type_code
        effective_volume_cbm = config.effective_volume_cbm
        load_factor = config.default_load_factor
    if line.container_tiers.filter(container_type_code=container_type_code).exists():
        raise ValidationError({"container_type_code": "当前报价行已存在该柜型数量档。"})
    tier_number = (line.container_tiers.aggregate(value=Max("tier_number"))["value"] or 0) + 1
    tier = QuotationContainerTier.objects.create(
        quotation_line=line,
        tier_number=tier_number,
        container_config=config,
        container_type_code=container_type_code,
        effective_volume_cbm=effective_volume_cbm,
        load_factor=load_factor,
        unit_price=unit_price,
        auto_carton_count=0,
        auto_quantity=Decimal("0"),
        final_quantity=Decimal("0"),
    )
    _recalculate_container_tier(tier=tier, packaging=packaging)
    _touch(version)
    write_audit_log(
        object_type="QUOTATION_CONTAINER_TIER",
        object_id=tier.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=version.quotation.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data={
            "quotation_line_id": str(line.pk),
            "container_config_id": str(config.pk) if config else None,
            "container_type_code": tier.container_type_code,
            "effective_volume_cbm": str(tier.effective_volume_cbm),
            "load_factor": str(tier.load_factor),
            "unit_price": str(tier.unit_price),
            "config_version": config.config_version if config else None,
            "auto_carton_count": tier.auto_carton_count,
            "auto_quantity": str(tier.auto_quantity),
        },
        request=request,
    )
    return tier, version


@transaction.atomic
def delete_container_tier(*, tier, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=tier.quotation_line.quotation_version_id)
    require_matching_etag(request, version)
    _ensure_draft(version)
    tier = QuotationContainerTier.objects.select_for_update().select_related("quotation_line").get(pk=tier.pk)
    before_data = {
        "quotation_line_id": str(tier.quotation_line_id),
        "container_config_id": str(tier.container_config_id),
        "container_type_code": tier.container_type_code,
        "tier_number": tier.tier_number,
    }
    tier_id = tier.pk
    tier.delete()
    _touch(version)
    write_audit_log(
        object_type="QUOTATION_CONTAINER_TIER",
        object_id=tier_id,
        context_type="CUSTOMER_ACCOUNT",
        context_id=version.quotation.customer_account_id,
        action="DELETED",
        actor_employee=actor_employee,
        before_data=before_data,
        request=request,
    )
    return version


def _entity_snapshot(entity):
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
    }


def _contact_snapshot(contact):
    return {
        "id": str(contact.pk),
        "display_name": contact.display_name,
        "position_title": contact.position_title,
        "methods": [
            {
                "method_type": method.method_type,
                "value": method.raw_value,
                "is_primary": method.is_primary,
                "is_preferred": method.is_preferred,
            }
            for method in contact.methods.filter(archived_at__isnull=True).order_by("method_type", "id")
        ],
    }


def _default_quotation_template():
    return QuotationTemplate.objects.filter(
        template_code=DEFAULT_QUOTATION_TEMPLATE_CODE,
        archived_at__isnull=True,
    ).first()


def _template_snapshot(template):
    if template is None:
        return {
            "template_code": "DEFAULT",
            "template_name": "系统默认固定模板",
            "template_version": 1,
            "requires_approval": False,
            "template_config": {},
        }
    return {
        "id": str(template.pk),
        "template_code": template.template_code,
        "template_name": template.template_name,
        "template_version": template.template_version,
        "requires_approval": template.requires_approval,
        "template_config": template.template_config,
    }


def _recalculate(version, tax_rate):
    gross = Decimal("0")
    subtotal = Decimal("0")
    for line in version.lines.select_for_update().all():
        if line.unit_price is None:
            raise Conflict(f"报价明细「{line.product_description_snapshot}」尚未录入单价。")
        gross += Decimal(line.quantity) * Decimal(line.unit_price)
        calculated = _line_total(line.quantity, line.unit_price, line.discount_rate)
        if line.line_total != calculated:
            line.line_total = calculated
            line.save(update_fields=["line_total", "updated_at"])
        subtotal += calculated
    subtotal = _money(subtotal)
    discount = _money(gross - subtotal)
    tax = _money(subtotal * Decimal(tax_rate))
    return subtotal, discount, tax, _money(subtotal + tax)


@transaction.atomic
def lock_version(*, version, address, contact, tax_rate, terms, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().select_related(
        "quotation__transaction_entity"
    ).get(pk=version.pk)
    require_matching_etag(request, version)
    _ensure_draft(version)
    if not version.lines.exists():
        raise Conflict("报价版本至少包含一条明细后才能锁定。")
    missing_prices = list(version.lines.filter(unit_price__isnull=True).values_list("product_description_snapshot", flat=True))
    if missing_prices:
        raise Conflict(f"以下报价明细尚未录入单价：{'、'.join(missing_prices)}。")
    if version.quotation_template is None:
        version.quotation_template = _default_quotation_template()
    if version.quotation_template is None:
        raise Conflict("固定报价模板尚未建档，暂时不能锁定报价。")
    before_data = model_snapshot(version, VERSION_FIELDS)
    subtotal, discount, tax, total = _recalculate(version, tax_rate)
    now = timezone.now()
    version.status = QuotationVersionStatus.LOCKED
    version.subtotal_amount = subtotal
    version.discount_amount = discount
    version.tax_amount = tax
    version.total_amount = total
    version.locked_at = now
    version.locked_by_employee = actor_employee
    version.transaction_entity_snapshot = _entity_snapshot(version.quotation.transaction_entity)
    version.address_snapshot = _address_snapshot(address)
    version.contact_snapshot = _contact_snapshot(contact)
    version.template_snapshot = _template_snapshot(version.quotation_template)
    version.terms_snapshot = {
        **(version.terms_snapshot or {}),
        **terms,
        "tax_rate": str(tax_rate),
    }
    version.save(
        update_fields=[
            "status",
            "quotation_template",
            "subtotal_amount",
            "discount_amount",
            "tax_amount",
            "total_amount",
            "locked_at",
            "locked_by_employee",
            "transaction_entity_snapshot",
            "address_snapshot",
            "contact_snapshot",
            "template_snapshot",
            "terms_snapshot",
            "updated_at",
        ]
    )
    _write_version_records(
        version=version,
        action="LOCKED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
    )
    return version


@transaction.atomic
def submit_version_approval(*, version, approver_employee, reason, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=version.pk)
    require_matching_etag(request, version)
    if version.status != QuotationVersionStatus.LOCKED:
        raise Conflict("只有已锁定版本可以提交审批。")
    if version.quotation_template is None or not version.quotation_template.requires_approval:
        raise Conflict("当前报价模板不要求审批。")
    if approver_employee.pk == getattr(actor_employee, "pk", None):
        raise ValidationError({"approver_employee_id": ["申请人不能审批自己的报价。"]})
    if version.approval_links.filter(approval_request__status=ApprovalStatus.PENDING).exists():
        raise Conflict("当前版本已有待处理审批。")
    approval = ApprovalRequest.objects.create(
        current_approver_employee=approver_employee,
        requested_by_employee=actor_employee,
        approval_type="QUOTATION_VERSION",
        status=ApprovalStatus.PENDING,
        request_reason=reason,
        submitted_at=timezone.now(),
    )
    QuotationVersionApprovalLink.objects.create(quotation_version=version, approval_request=approval)
    _touch(version)
    _write_version_records(
        version=version,
        action="APPROVAL_SUBMITTED",
        actor_employee=actor_employee,
        request=request,
        note=reason,
    )
    return approval, version


def _approval_satisfied(version):
    if version.quotation_template is None or not version.quotation_template.requires_approval:
        return True
    return version.approval_links.filter(approval_request__status=ApprovalStatus.APPROVED).exists()


@transaction.atomic
def issue_version(*, version, actor_employee, request, note=""):
    version = QuotationVersion.objects.select_for_update().select_related("quotation").get(
        pk=version.pk
    )
    require_matching_etag(request, version)
    if version.status != QuotationVersionStatus.LOCKED:
        raise Conflict("只有已锁定版本可以签发。")
    if not version.lines.exists():
        raise Conflict("正式报价必须包含至少一条明细。")
    if not all(
        [version.transaction_entity_snapshot, version.address_snapshot, version.contact_snapshot]
    ):
        raise Conflict("正式报价缺少交易主体、地址或联系人快照。")
    if not _approval_satisfied(version):
        raise Conflict("报价尚未取得有效审批。")
    if version.valid_until and version.valid_until < timezone.localdate():
        raise Conflict("报价版本已经过期，不能签发。")
    now = timezone.now()
    before_data = model_snapshot(version, VERSION_FIELDS)
    version.status = QuotationVersionStatus.ISSUED
    version.issued_at = now
    version.save(update_fields=["status", "issued_at", "updated_at"])
    version.quotation.versions.filter(
        status__in=[QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT]
    ).exclude(pk=version.pk).update(status=QuotationVersionStatus.SUPERSEDED, updated_at=now)
    _write_version_records(
        version=version,
        action="ISSUED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=note,
    )
    return version


def quotation_snapshot_hash(version):
    price_bases = []
    for basis in version.price_bases.prefetch_related("line_prices").order_by("sort_order", "id"):
        price_bases.append(
            {
                "id": str(basis.id),
                "label": basis.label,
                "incoterm_code": basis.incoterm_code,
                "named_place": basis.named_place,
                "currency_code": basis.currency_code,
                "is_default": basis.is_default,
                "sort_order": basis.sort_order,
                "notes": basis.notes,
                "line_prices": [
                    {
                        "quotation_line_id": str(price.quotation_line_id),
                        "unit_price": str(price.unit_price),
                        "surcharge_note": price.surcharge_note,
                        "is_manual_override": price.is_manual_override,
                        "override_reason": price.override_reason,
                    }
                    for price in basis.line_prices.all()
                ],
            }
        )
    payload = {
        "version": model_snapshot(version, VERSION_FIELDS),
        "lines": [model_snapshot(line, LINE_FIELDS) for line in version.lines.all()],
        "price_bases": price_bases,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@transaction.atomic
def register_formal_document(*, version, business_file, actor_employee, request):
    from apps.files.reference_guards import require_non_finance_receipt_file
    require_non_finance_receipt_file(business_file)
    version = QuotationVersion.objects.select_for_update().get(pk=version.pk)
    require_matching_etag(request, version)
    if version.status not in {QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT}:
        raise Conflict("只有已签发或已发送版本可以登记正式文档。")
    existing_document = version.documents.filter(is_formal=True).first()
    if existing_document is not None:
        has_formal_dispatch = version.dispatch_records.filter(is_simulated=False).exists()
        if version.status != QuotationVersionStatus.ISSUED or has_formal_dispatch:
            raise Conflict("已发送或已有正式发送记录的报价文件不可替换。")
        existing_document.is_formal = False
        existing_document.document_type = QuotationDocumentType.OTHER
        existing_document.save(update_fields=["is_formal", "document_type", "updated_at"])
    document = QuotationDocument.objects.create(
        quotation_version=version,
        business_file=business_file,
        document_type=QuotationDocumentType.FORMAL,
        is_formal=True,
        generated_by_employee=actor_employee,
        generated_at=timezone.now(),
        snapshot_hash=quotation_snapshot_hash(version),
    )
    QuotationFileLink.objects.get_or_create(
        quotation_version=version,
        business_file=business_file,
        defaults={"file_role": "FORMAL_DOCUMENT"},
    )
    _touch(version)
    _write_version_records(
        version=version,
        action="DOCUMENT_REGISTERED",
        actor_employee=actor_employee,
        request=request,
        note=business_file.original_name,
    )
    return document, version


@transaction.atomic
def create_generated_formal_document(*, version, content, actor_employee, request):
    """保存系统固定模板生成的 PDF，并登记为当前版本唯一正式报价文件。"""
    version = QuotationVersion.objects.select_for_update().select_related("quotation").get(pk=version.pk)
    require_matching_etag(request, version)
    if version.status not in {QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT}:
        raise Conflict("只有已签发或已发送版本可以生成正式报价 PDF。")
    existing_document = version.documents.filter(is_formal=True).first()
    if existing_document is not None:
        has_formal_dispatch = version.dispatch_records.filter(is_simulated=False).exists()
        if version.status != QuotationVersionStatus.ISSUED or has_formal_dispatch:
            raise Conflict("已发送或已有正式发送记录的报价文件不可重新生成。")
        existing_document.is_formal = False
        existing_document.document_type = QuotationDocumentType.OTHER
        existing_document.save(update_fields=["is_formal", "document_type", "updated_at"])

    content_hash = hashlib.sha256(content).hexdigest()
    relative_key = Path("quotation-documents") / timezone.now().strftime("%Y/%m") / f"{uuid.uuid4()}.pdf"
    final_path = Path(settings.MEDIA_ROOT) / relative_key
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(content)
    business_file = BusinessFile.objects.create(
        uploaded_by_employee=actor_employee,
        original_name=f"{version.quotation.quotation_number}_V{version.version_number}.pdf",
        storage_key=relative_key.as_posix(),
        content_type="application/pdf",
        size_bytes=len(content),
        content_hash=content_hash,
        scan_status=FileScanStatus.CLEAN,
        scanned_at=timezone.now(),
        scan_message="系统固定报价模板生成。",
    )
    document = QuotationDocument.objects.create(
        quotation_version=version,
        business_file=business_file,
        document_type=QuotationDocumentType.FORMAL,
        is_formal=True,
        generated_by_employee=actor_employee,
        generated_at=timezone.now(),
        snapshot_hash=quotation_snapshot_hash(version),
    )
    QuotationFileLink.objects.create(
        quotation_version=version,
        business_file=business_file,
        file_role="FORMAL_DOCUMENT",
    )
    _touch(version)
    _write_version_records(
        version=version,
        action="DOCUMENT_GENERATED",
        actor_employee=actor_employee,
        request=request,
        note=business_file.original_name,
    )
    return document, version


@transaction.atomic
def dispatch_version(
    *,
    version,
    validated_data,
    actor_employee,
    request,
    require_formal_document=True,
    enforce_etag=True,
    reconcile_external_result=False,
):
    from apps.files.reference_guards import require_non_finance_receipt_file
    require_non_finance_receipt_file(validated_data.get("evidence_file"))
    version = QuotationVersion.objects.select_for_update().select_related("quotation").get(pk=version.pk)
    if enforce_etag:
        require_matching_etag(request, version)
    outcome_is_open = version.quotation.outcome_status == QuotationOutcomeStatus.OPEN
    status_allows_dispatch = version.status in {QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT}
    if not outcome_is_open and not reconcile_external_result:
        raise Conflict("报价结果已经终结，不能再次发送。")
    if not status_allows_dispatch and not reconcile_external_result:
        raise Conflict("只有已签发或已发送版本可以登记发送。")
    if require_formal_document and not reconcile_external_result and not version.documents.filter(is_formal=True).exists():
        raise Conflict("登记发送前必须先登记正式报价文档。")
    first_formal_dispatch = not version.dispatch_records.filter(is_simulated=False).exists()
    record = QuotationDispatchRecord.objects.create(
        quotation_version=version,
        dispatched_by_employee=actor_employee,
        dispatched_at=timezone.now(),
        **validated_data,
    )
    before_data = model_snapshot(version, VERSION_FIELDS)
    if outcome_is_open and version.status == QuotationVersionStatus.ISSUED:
        version.status = QuotationVersionStatus.SENT
        version.save(update_fields=["status", "updated_at"])
    else:
        _touch(version)
    _write_version_records(
        version=version,
        action="DISPATCHED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=f"渠道：{record.channel}",
    )
    inquiry = version.quotation.source_inquiry
    if outcome_is_open and inquiry and inquiry.status == InquiryStatus.QUOTING:
        before_status = inquiry.status
        inquiry.status = InquiryStatus.QUOTED
        inquiry.save(update_fields=["status", "updated_at"])
        write_audit_log(
            object_type="INQUIRY", object_id=inquiry.pk, context_type="CUSTOMER_ACCOUNT",
            context_id=inquiry.customer_account_id, action="QUOTE_SENT",
            actor_employee=actor_employee, before_data={"status": before_status},
            after_data={"status": inquiry.status, "quotation_version_id": str(version.pk)}, request=request,
        )
        write_customer_timeline(
            customer=inquiry.customer_account, event_type="INQUIRY_QUOTED",
            title=f"询盘已报价：{inquiry.inquiry_number}", summary=version.quotation.quotation_number,
            source_type="INQUIRY", source_id=inquiry.pk, actor_employee=actor_employee,
        )
    if outcome_is_open and inquiry and first_formal_dispatch:
        from apps.inquiries.handling_time import handle_time_event
        handle_time_event(inquiry.pk, 'QUOTE_SENT', key=f'QUOTE_SENT:{version.pk}', context={'source_label': f'{version.quotation.quotation_number} V{version.version_number}'})
    return record, version


def _validate_dispatch_context(*, version, price_basis, require_formal_document=True):
    if version.quotation.outcome_status != QuotationOutcomeStatus.OPEN:
        raise Conflict("报价结果已经终结，不能再次发送。")
    if version.status not in {QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT}:
        raise Conflict("只有已签发或已发送版本可以正式发送。")
    if require_formal_document and not version.documents.filter(is_formal=True).exists():
        raise Conflict("正式发送前必须先登记正式报价文档。")
    if price_basis.quotation_version_id != version.pk:
        raise ValidationError({"price_basis_id": ["发送价格口径必须属于当前报价版本。"]})


def confirm_manual_dispatch(*, version, price_basis, recipient_snapshot, evidence_file,
                            external_reference, follow_up_due_at, evidence_note,
                            actor_employee, request):
    _validate_dispatch_context(
        version=version,
        price_basis=price_basis,
        require_formal_document=False,
    )
    if evidence_file is None and not external_reference.strip() and not evidence_note.strip():
        raise ValidationError({"evidence_note": ["人工发送必须填写证据说明、外部凭证号或上传证据文件。"]})
    return dispatch_version(
        version=version,
        validated_data={
            "channel": "MANUAL",
            "recipient_snapshot": recipient_snapshot,
            "external_reference": external_reference,
            "follow_up_due_at": follow_up_due_at,
            "notes": evidence_note,
            "price_basis": price_basis,
            "evidence_file": evidence_file,
            "is_simulated": False,
        },
        actor_employee=actor_employee,
        request=request,
        require_formal_document=False,
    )


EMAIL_ATTEMPT_STALE_AFTER = timedelta(seconds=60)


def _email_attempt_error_text(error):
    detail = getattr(error, "detail", None)
    if detail is None:
        return str(error)
    if isinstance(detail, (dict, list)):
        return json.dumps(detail, ensure_ascii=False, default=str)
    return str(detail)


def _email_attempt_payload_hash(*, version, price_basis, document, recipient, cc, subject, body,
                                follow_up_due_at):
    payload = {
        "quotation_version_id": str(version.pk),
        "price_basis_id": str(price_basis.pk),
        "quotation_document_id": str(document.pk),
        "document_hash": document.business_file.content_hash,
        "recipient": recipient,
        "cc": cc,
        "subject": subject,
        "body": body,
        "follow_up_due_at": follow_up_due_at.isoformat() if follow_up_due_at else None,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _set_email_attempt_status(*, attempt_id, status, error_message=""):
    QuotationEmailDispatchAttempt.objects.filter(pk=attempt_id).update(
        status=status,
        error_message=error_message,
        updated_at=timezone.now(),
    )


def mark_stale_email_attempts_uncertain(queryset):
    """只有超过 SMTP 超时时间仍未结束的尝试才转为待核对。"""
    return queryset.filter(
        status=QuotationEmailDispatchAttemptStatus.PROCESSING,
        updated_at__lt=timezone.now() - EMAIL_ATTEMPT_STALE_AFTER,
    ).update(
        status=QuotationEmailDispatchAttemptStatus.UNCERTAIN,
        error_message="发送请求已中断或超时，邮件投递结果需要人工核对。",
        updated_at=timezone.now(),
    )


def _email_dispatch_values(*, attempt):
    return {
        "channel": "EMAIL",
        "recipient_snapshot": attempt.recipient_snapshot,
        "external_reference": "",
        "follow_up_due_at": attempt.follow_up_due_at,
        "notes": f"邮件服务已接受投递；主题：{attempt.subject}",
        "price_basis": attempt.price_basis,
        "evidence_file": None,
        "is_simulated": False,
    }


def email_dispatch_version(*, version, price_basis, recipient, cc, subject, body,
                           follow_up_due_at, idempotency_key, actor_employee, request):
    """持久化外部发送尝试；SMTP 结果不明确时禁止盲目重发。"""
    with transaction.atomic():
        locked_version = QuotationVersion.objects.select_for_update().select_related("quotation").get(pk=version.pk)
        existing = QuotationEmailDispatchAttempt.objects.select_for_update().select_related(
            "quotation_document__business_file",
        ).filter(
            quotation_version=locked_version,
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            replay_hash = _email_attempt_payload_hash(
                version=locked_version,
                price_basis=price_basis,
                document=existing.quotation_document,
                recipient=recipient,
                cc=cc,
                subject=subject,
                body=body,
                follow_up_due_at=follow_up_due_at,
            )
            if existing.payload_hash != replay_hash:
                raise Conflict("该邮件幂等键已用于不同内容，请刷新后重新发送。")
            if existing.status == QuotationEmailDispatchAttemptStatus.ACCEPTED and existing.dispatch_record_id:
                return existing.dispatch_record, locked_version, existing, True
            raise Conflict("该邮件发送请求已经存在，请先核对当前尝试状态。")
        require_matching_etag(request, locked_version)
        _validate_dispatch_context(version=locked_version, price_basis=price_basis)
        document = locked_version.documents.select_related("business_file").filter(is_formal=True).first()
        if document is None:
            raise Conflict("正式报价文件不存在，无法发送邮件。")
        if document.business_file.scan_status not in USABLE_FILE_SCAN_STATUSES:
            raise Conflict("正式报价文件尚未通过安全扫描，无法发送邮件。")
        payload_hash = _email_attempt_payload_hash(
            version=locked_version,
            price_basis=price_basis,
            document=document,
            recipient=recipient,
            cc=cc,
            subject=subject,
            body=body,
            follow_up_due_at=follow_up_due_at,
        )
        attempt = QuotationEmailDispatchAttempt.objects.create(
            quotation_version=locked_version,
            price_basis=price_basis,
            quotation_document=document,
            requested_by_employee=actor_employee,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            recipient=recipient,
            cc_snapshot=cc,
            subject=subject,
            body_html=body,
            attachment_snapshot={
                "document_id": str(document.pk),
                "business_file_id": str(document.business_file_id),
                "filename": document.business_file.original_name,
                "content_type": document.business_file.content_type,
                "size_bytes": document.business_file.size_bytes,
                "content_hash": document.business_file.content_hash,
            },
            follow_up_due_at=follow_up_due_at,
        )

    try:
        email_account = default_email_account_for_employee(actor_employee)
        account_snapshot = email_account_snapshot(email_account)
        recipient_snapshot = {
            "email": recipient,
            "cc": cc,
            "email_account": {
                "id": account_snapshot["id"],
                "display_name": account_snapshot["display_name"],
                "sender_email": account_snapshot["sender_email"],
            },
        }
        QuotationEmailDispatchAttempt.objects.filter(pk=attempt.pk).update(
            recipient_snapshot=recipient_snapshot,
            updated_at=timezone.now(),
        )
        attempt.recipient_snapshot = recipient_snapshot
        file_path = Path(settings.MEDIA_ROOT) / document.business_file.storage_key
        if not file_path.is_file():
            raise Conflict("正式报价文件不存在，无法发送邮件。")
        send_via_email_account(
            account=email_account,
            subject=subject,
            body=body,
            html_body=body,
            recipient=recipient,
            cc=cc,
            attachments=[(
                document.business_file.original_name,
                file_path.read_bytes(),
                document.business_file.content_type,
            )],
        )
    except EmailDeliveryUncertain as error:
        _set_email_attempt_status(
            attempt_id=attempt.pk,
            status=QuotationEmailDispatchAttemptStatus.UNCERTAIN,
            error_message=_email_attempt_error_text(error),
        )
        raise Conflict("邮件投递结果待核对，请先查看发件箱，不能直接重复发送。") from error
    except Conflict as error:
        _set_email_attempt_status(
            attempt_id=attempt.pk,
            status=QuotationEmailDispatchAttemptStatus.FAILED,
            error_message=_email_attempt_error_text(error),
        )
        raise
    except Exception as error:
        # 能到达这里的异常发生在 SMTP 调用前的账户解密、附件读取等准备阶段，
        # 尚未产生外部投递副作用，因此可以明确标记为失败而不是待核对。
        _set_email_attempt_status(
            attempt_id=attempt.pk,
            status=QuotationEmailDispatchAttemptStatus.FAILED,
            error_message=_email_attempt_error_text(error),
        )
        raise Conflict("邮件发送前准备失败，请检查邮件账户和正式附件后重试。") from error

    try:
        record, current_version = dispatch_version(
            version=version,
            validated_data=_email_dispatch_values(attempt=attempt),
            actor_employee=actor_employee,
            request=request,
            enforce_etag=False,
            reconcile_external_result=True,
        )
    except Exception as error:
        _set_email_attempt_status(
            attempt_id=attempt.pk,
            status=QuotationEmailDispatchAttemptStatus.UNCERTAIN,
            error_message="邮件服务已接受投递，但本地发送记录写入失败，需要人工核对。",
        )
        raise Conflict("邮件已提交至外部服务，但本地记录未确认，请先核对后处理。") from error

    QuotationEmailDispatchAttempt.objects.filter(pk=attempt.pk).update(
        status=QuotationEmailDispatchAttemptStatus.ACCEPTED,
        dispatch_record=record,
        error_message="",
        updated_at=timezone.now(),
    )
    attempt.status = QuotationEmailDispatchAttemptStatus.ACCEPTED
    attempt.dispatch_record = record
    attempt.error_message = ""
    return record, current_version, attempt, False


@transaction.atomic
def resolve_email_dispatch_attempt(*, attempt, result, note, actor_employee, request):
    attempt = QuotationEmailDispatchAttempt.objects.select_for_update().select_related(
        "quotation_version__quotation",
        "price_basis",
        "quotation_document",
    ).get(pk=attempt.pk)
    version = QuotationVersion.objects.select_for_update().get(pk=attempt.quotation_version_id)
    require_matching_etag(request, version)
    if attempt.status != QuotationEmailDispatchAttemptStatus.UNCERTAIN:
        raise Conflict("只有结果待核对的邮件尝试可以人工确认。")

    before_data = {
        "status": attempt.status,
        "error_message": attempt.error_message,
    }
    if result == "ACCEPTED":
        record, version = dispatch_version(
            version=version,
            validated_data=_email_dispatch_values(attempt=attempt),
            actor_employee=actor_employee,
            request=request,
            enforce_etag=False,
            reconcile_external_result=True,
        )
        attempt.status = QuotationEmailDispatchAttemptStatus.ACCEPTED
        attempt.dispatch_record = record
        attempt.error_message = ""
    else:
        attempt.status = QuotationEmailDispatchAttemptStatus.FAILED
        attempt.error_message = "用户核对发件箱后确认邮件未投递。"
    attempt.resolved_by_employee = actor_employee
    attempt.resolved_at = timezone.now()
    attempt.resolution_note = note
    attempt.save(update_fields=[
        "status",
        "dispatch_record",
        "error_message",
        "resolved_by_employee",
        "resolved_at",
        "resolution_note",
        "updated_at",
    ])
    write_audit_log(
        object_type="QUOTATION_EMAIL_DISPATCH_ATTEMPT",
        object_id=attempt.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=version.quotation.customer_account_id,
        action="EMAIL_DISPATCH_ATTEMPT_RESOLVED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data={"status": attempt.status, "resolution_note": note},
        request=request,
    )
    return attempt, version


@transaction.atomic
def set_line_product_image(*, line, business_file, actor_employee, request):
    from apps.files.reference_guards import require_non_finance_receipt_file
    require_non_finance_receipt_file(business_file)
    version = QuotationVersion.objects.select_for_update().get(pk=line.quotation_version_id)
    require_matching_etag(request, version)
    _ensure_draft(version)
    line = QuotationLine.objects.select_for_update().get(pk=line.pk)
    before_data = model_snapshot(line, LINE_FIELDS)
    line.product_image = business_file
    line.save(update_fields=["product_image", "updated_at"])
    _touch(version)
    write_audit_log(
        object_type="QUOTATION_LINE", object_id=line.pk, context_type="CUSTOMER_ACCOUNT",
        context_id=version.quotation.customer_account_id, action="PRODUCT_IMAGE_UPDATED",
        actor_employee=actor_employee, before_data=before_data,
        after_data=model_snapshot(line, LINE_FIELDS), request=request,
    )
    _write_version_records(
        version=version, action="PRODUCT_IMAGE_UPDATED", actor_employee=actor_employee,
        request=request, note=business_file.original_name,
    )
    return line, version


@transaction.atomic
def remove_line_product_image(*, line, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=line.quotation_version_id)
    require_matching_etag(request, version)
    _ensure_draft(version)
    line = QuotationLine.objects.select_for_update().get(pk=line.pk)
    before_data = model_snapshot(line, LINE_FIELDS)
    line.product_image = None
    line.save(update_fields=["product_image", "updated_at"])
    _touch(version)
    write_audit_log(
        object_type="QUOTATION_LINE", object_id=line.pk, context_type="CUSTOMER_ACCOUNT",
        context_id=version.quotation.customer_account_id, action="PRODUCT_IMAGE_REMOVED",
        actor_employee=actor_employee, before_data=before_data,
        after_data=model_snapshot(line, LINE_FIELDS), request=request,
    )
    _write_version_records(
        version=version, action="PRODUCT_IMAGE_REMOVED", actor_employee=actor_employee,
        request=request, note="已移除报价产品主图",
    )
    return version


@transaction.atomic
def create_sample_invoice_document(*, version, content, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().select_related("quotation").get(pk=version.pk)
    require_matching_etag(request, version)
    relative_key = Path("quotation-exports") / timezone.now().strftime("%Y/%m") / f"{uuid.uuid4()}.xlsx"
    final_path = Path(settings.MEDIA_ROOT) / relative_key
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(content)
    business_file = BusinessFile.objects.create(
        uploaded_by_employee=actor_employee,
        original_name=f"{version.quotation.quotation_number}_sample_invoice_demo.xlsx",
        storage_key=relative_key.as_posix(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=len(content),
        content_hash=hashlib.sha256(content).hexdigest(),
        scan_status=FileScanStatus.CLEAN,
        scanned_at=timezone.now(),
        scan_message="系统生成的演示样品发票导出文件。",
    )
    document = QuotationDocument.objects.create(
        quotation_version=version,
        business_file=business_file,
        document_type=QuotationDocumentType.DRAFT,
        is_formal=False,
        generated_by_employee=actor_employee,
        generated_at=timezone.now(),
        snapshot_hash=hashlib.sha256(content).hexdigest(),
    )
    _touch(version)
    _write_version_records(
        version=version, action="SAMPLE_INVOICE_EXPORTED", actor_employee=actor_employee,
        request=request, note="已生成演示样品发票 XLSX，不是正式付款凭证。",
    )
    return document, version


@transaction.atomic
def simulate_dispatch_version(*, version, recipient, notes, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().select_related("quotation").get(pk=version.pk)
    require_matching_etag(request, version)
    record = QuotationDispatchRecord.objects.create(
        quotation_version=version,
        dispatched_by_employee=actor_employee,
        dispatched_at=timezone.now(),
        channel="SIMULATED_EMAIL",
        recipient_snapshot={"email": recipient or "demo-recipient@example.test", "source": "DEMO"},
        notes=notes or "模拟发送成功：未实际投递，未改变报价或询盘状态。",
        is_simulated=True,
    )
    _touch(version)
    _write_version_records(
        version=version, action="SIMULATED_DISPATCH", actor_employee=actor_employee,
        request=request, note=f"模拟发送至 {record.recipient_snapshot['email']}；未实际投递。",
    )
    return record, version


@transaction.atomic
def void_version(*, version, reason, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=version.pk)
    require_matching_etag(request, version)
    if version.status == QuotationVersionStatus.VOID:
        raise Conflict("报价版本已经作废。")
    if version.quotation.accepted_version_id == version.pk:
        raise Conflict("已接受版本不能作废。")
    if version.status == QuotationVersionStatus.DRAFT:
        raise Conflict("草稿版本无需作废，可继续修改或删除明细。")
    before_data = model_snapshot(version, VERSION_FIELDS)
    version.status = QuotationVersionStatus.VOID
    version.save(update_fields=["status", "updated_at"])
    _write_version_records(
        version=version,
        action="VOIDED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=reason,
    )
    return version


@transaction.atomic
def transition_quotation(*, quotation, action, accepted_version, note, actor_employee, request,
                         accepted_price_basis=None, customer_contact=None, accepted_at=None,
                         acceptance_source=""):
    quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
    require_matching_etag(request, quotation)
    if quotation.outcome_status != QuotationOutcomeStatus.OPEN:
        raise Conflict("报价结果已经终结，不能重复变更。")
    before_data = model_snapshot(quotation, QUOTATION_FIELDS)
    if action == "ACCEPTED":
        if accepted_version is None or accepted_version.quotation_id != quotation.pk:
            raise ValidationError({"accepted_version_id": ["接受版本必须属于当前报价。"]})
        if accepted_version.status != QuotationVersionStatus.SENT:
            raise Conflict("只能记录已正式发送报价版本的客户接受结果。")
        if accepted_price_basis is None or accepted_price_basis.quotation_version_id != accepted_version.pk:
            raise ValidationError({"price_basis_id": ["接受价格口径必须属于接受版本。"]})
        if customer_contact and customer_contact.customer_account_id != quotation.customer_account_id:
            raise ValidationError({"customer_contact_id": ["确认联系人必须属于报价客户。"]})
        quotation.outcome_status = QuotationOutcomeStatus.WON
        quotation.accepted_version = accepted_version
    elif action == "LOST":
        quotation.outcome_status = QuotationOutcomeStatus.LOST
    elif action == "CANCELLED":
        quotation.outcome_status = QuotationOutcomeStatus.CANCELLED
    quotation.outcome_note = note
    quotation.save(
        update_fields=["outcome_status", "accepted_version", "outcome_note", "updated_at"]
    )
    if action == "ACCEPTED":
        QuotationAcceptance.objects.create(
            quotation=quotation,
            quotation_version=accepted_version,
            price_basis=accepted_price_basis,
            customer_contact=customer_contact,
            accepted_at=accepted_at,
            source=acceptance_source,
            note=note,
            recorded_by_employee=actor_employee,
        )
        if quotation.source_inquiry_id:
            from apps.inquiries.services import mark_inquiry_quote_accepted

            mark_inquiry_quote_accepted(
                inquiry=quotation.source_inquiry,
                actor_employee=actor_employee,
                request=request,
                note=f"客户已接受报价 {quotation.quotation_number} V{accepted_version.version_number}。",
            )
    _write_quote_records(
        quotation=quotation,
        action=action,
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=note,
    )
    return quotation
