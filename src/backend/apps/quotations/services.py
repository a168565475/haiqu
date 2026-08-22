import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.customers.services import model_snapshot, write_customer_timeline
from apps.workflow.models import ApprovalRequest, ApprovalStatus

from .models import (
    Quotation,
    QuotationDispatchRecord,
    QuotationDocument,
    QuotationDocumentType,
    QuotationFileLink,
    QuotationLine,
    QuotationOutcomeStatus,
    QuotationQuantityTier,
    QuotationVersion,
    QuotationVersionApprovalLink,
    QuotationVersionStatus,
)


MONEY_QUANT = Decimal("0.0001")
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
]
VERSION_FIELDS = [
    "quotation",
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
    "notes",
]
LINE_FIELDS = [
    "quotation_version",
    "line_number",
    "product_description_snapshot",
    "specification_snapshot",
    "quantity",
    "unit_code",
    "unit_price",
    "discount_rate",
    "line_total",
    "notes",
]


def _money(value):
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _line_total(quantity, unit_price, discount_rate):
    return _money(Decimal(quantity) * Decimal(unit_price) * (Decimal("1") - Decimal(discount_rate)))


def _touch(instance):
    instance.updated_at = timezone.now()
    instance.save(update_fields=["updated_at"])


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
def update_quotation(*, quotation, validated_data, actor_employee, request):
    quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
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
    for source_line in source.lines.prefetch_related("quantity_tiers").all():
        copied = QuotationLine.objects.create(
            quotation_version=target,
            line_number=source_line.line_number,
            product_description_snapshot=source_line.product_description_snapshot,
            specification_snapshot=source_line.specification_snapshot,
            quantity=source_line.quantity,
            unit_code=source_line.unit_code,
            unit_price=source_line.unit_price,
            discount_rate=source_line.discount_rate,
            line_total=source_line.line_total,
            notes=source_line.notes,
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


@transaction.atomic
def create_version(*, quotation, validated_data, actor_employee, request):
    quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
    require_matching_etag(request, quotation)
    if quotation.outcome_status != QuotationOutcomeStatus.OPEN:
        raise Conflict("终态报价不能新增版本。")
    source = validated_data.pop("from_version", None)
    if source and source.quotation_id != quotation.pk:
        raise ValidationError({"from_version_id": ["复制来源必须属于当前报价。"]})
    next_number = (quotation.versions.aggregate(value=Max("version_number"))["value"] or 0) + 1
    if source:
        validated_data.setdefault("quotation_template", source.quotation_template)
        validated_data.setdefault("currency_code", source.currency_code)
        validated_data.setdefault("language_code", source.language_code)
        validated_data.setdefault("valid_until", source.valid_until)
        validated_data.setdefault("notes", source.notes)
    version = QuotationVersion.objects.create(
        quotation=quotation,
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
    return version, quotation


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


@transaction.atomic
def create_line(*, version, validated_data, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=version.pk)
    require_matching_etag(request, version)
    _ensure_draft(version)
    data = dict(validated_data)
    if "line_number" not in data:
        current_max = version.lines.aggregate(value=Max("line_number"))["value"] or 0
        data["line_number"] = current_max + 1
    data["line_total"] = _line_total(data["quantity"], data["unit_price"], data.get("discount_rate", 0))
    line = QuotationLine.objects.create(quotation_version=version, **data)
    _touch(version)
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
    for field_name, value in validated_data.items():
        setattr(line, field_name, value)
    line.line_total = _line_total(line.quantity, line.unit_price, line.discount_rate)
    line.save(update_fields=[*validated_data.keys(), "line_total", "updated_at"])
    _touch(version)
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
    line.delete()
    _touch(version)
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
    version.terms_snapshot = {**terms, "tax_rate": str(tax_rate)}
    version.save(
        update_fields=[
            "status",
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
    payload = {
        "version": model_snapshot(version, VERSION_FIELDS),
        "lines": [model_snapshot(line, LINE_FIELDS) for line in version.lines.all()],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@transaction.atomic
def register_formal_document(*, version, business_file, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=version.pk)
    require_matching_etag(request, version)
    if version.status not in {QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT}:
        raise Conflict("只有已签发或已发送版本可以登记正式文档。")
    if version.documents.filter(is_formal=True).exists():
        raise Conflict("当前版本已经存在正式报价文档。")
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
def dispatch_version(*, version, validated_data, actor_employee, request):
    version = QuotationVersion.objects.select_for_update().get(pk=version.pk)
    require_matching_etag(request, version)
    if version.status not in {QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT}:
        raise Conflict("只有已签发或已发送版本可以登记发送。")
    if not version.documents.filter(is_formal=True).exists():
        raise Conflict("登记发送前必须先登记正式报价文档。")
    record = QuotationDispatchRecord.objects.create(
        quotation_version=version,
        dispatched_by_employee=actor_employee,
        dispatched_at=timezone.now(),
        **validated_data,
    )
    before_data = model_snapshot(version, VERSION_FIELDS)
    if version.status == QuotationVersionStatus.ISSUED:
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
def transition_quotation(*, quotation, action, accepted_version, note, actor_employee, request):
    quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
    require_matching_etag(request, quotation)
    if quotation.outcome_status != QuotationOutcomeStatus.OPEN:
        raise Conflict("报价结果已经终结，不能重复变更。")
    before_data = model_snapshot(quotation, QUOTATION_FIELDS)
    if action == "ACCEPTED":
        if accepted_version is None or accepted_version.quotation_id != quotation.pk:
            raise ValidationError({"accepted_version_id": ["接受版本必须属于当前报价。"]})
        if accepted_version.status not in {QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT}:
            raise Conflict("只能接受已签发或已发送的报价版本。")
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
    _write_quote_records(
        quotation=quotation,
        action=action,
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=note,
    )
    return quotation
