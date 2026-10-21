from datetime import datetime, time

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.customers.services import model_snapshot
from apps.customers.models import CustomerContact
from apps.inquiries.models import Inquiry, InquiryItem
from apps.quotations.models import Quotation, QuotationLine, QuotationVersion, QuotationVersionStatus

from .models import (
    SampleItem,
    SampleProduct,
    SampleProductSamplingDetail,
    SampleRequest,
    SampleRequestStatus,
    SampleWorkflowStage,
)
from .services import (
    SAMPLE_FIELDS,
    _record_workflow_stage,
    _start_sla,
    _write_sample_records,
    sample_product_values_from_source,
)


TERMINAL_FORM_STATUSES = {
    SampleRequestStatus.CONFIRMED,
    SampleRequestStatus.COMPLETED,
    SampleRequestStatus.FINISHED,
    SampleRequestStatus.REJECTED,
    SampleRequestStatus.CANCELLED,
}


def application_requirements_pending(sample_request):
    if not sample_request.application_payload_hash or sample_request.status not in {
        SampleRequestStatus.PENDING_COMPLETION,
        SampleRequestStatus.MATERIALS_PENDING,
    }:
        return False
    return not any(
        record.stage == SampleWorkflowStage.REQUIREMENTS_COMPLETED
        for record in sample_request.workflow_records.all()
    )


def sample_form_edit_capabilities(sample_request):
    if application_requirements_pending(sample_request) or sample_request.status == SampleRequestStatus.PENDING_COMPLETION:
        return {
            "mode": "COMPLETE",
            "can_full_edit": True,
            "can_report_edit": True,
            "can_complete": True,
        }
    if sample_request.application_payload_hash:
        return {"mode": "READ_ONLY", "can_full_edit": False, "can_report_edit": False, "can_complete": False}
    if sample_request.status in TERMINAL_FORM_STATUSES:
        return {
            "mode": "READ_ONLY",
            "can_full_edit": False,
            "can_report_edit": False,
            "can_complete": False,
        }
    if (
        not sample_request.manual_request_number
        or not sample_request.products.exists()
        or sample_request.products.filter(category__isnull=True).exists()
        or sample_request.products.filter(task_sheet_file__isnull=True).exists()
        or sample_request.items.filter(sample_product__isnull=True).exists()
        or sample_request.items.filter(product_color__isnull=True).exists()
        or sample_request.items.filter(sample_quantity__isnull=True).exists()
    ):
        return {
            "mode": "READ_ONLY",
            "can_full_edit": False,
            "can_report_edit": False,
            "can_complete": False,
        }
    has_reporting = sample_request.items.filter(
        cutting_reported_quantity__gt=0
    ).exists() or sample_request.items.filter(
        metalwork_reported_quantity__gt=0
    ).exists() or sample_request.items.filter(
        cutting_completed=True
    ).exists() or sample_request.items.filter(metalwork_completed=True).exists()
    can_full_edit = (
        sample_request.status == SampleRequestStatus.PENDING
        and not sample_request.fee_records.exists()
        and not sample_request.shipments.exists()
        and not has_reporting
    )
    if can_full_edit:
        return {"mode": "FULL", "can_full_edit": True, "can_report_edit": True, "can_complete": False}
    return {"mode": "REPORT_ONLY", "can_full_edit": False, "can_report_edit": True, "can_complete": False}


def _legacy_datetime(date_value):
    value = datetime.combine(date_value, time.min)
    return timezone.make_aware(value, timezone.get_current_timezone())


def _source_relations(source_type, source_id):
    if source_type == "inquiry":
        inquiry = (
            Inquiry.objects.select_for_update(of=("self",))
            .select_related("customer_account", "transaction_entity", "customer_contact", "owner_employee")
            .prefetch_related("items")
            .get(pk=source_id, archived_at__isnull=True)
        )
        if inquiry.owner_employee_id is None:
            raise Conflict("来源询盘尚未分配业务员。")
        return {
            "customer_account": inquiry.customer_account,
            "transaction_entity": inquiry.transaction_entity,
            "customer_contact": inquiry.customer_contact,
            "owner_employee": inquiry.owner_employee,
            "source_inquiry": inquiry,
            "source_quotation_version": None,
            "inquiry_items": {str(item.pk): item for item in inquiry.items.all()},
            "quotation_lines": {},
        }
    version = (
        QuotationVersion.objects.select_for_update(of=("self",))
        .select_related(
            "quotation__customer_account",
            "quotation__transaction_entity",
            "quotation__owner_employee",
            "quotation__source_inquiry__customer_contact",
        )
        .prefetch_related("lines")
        .filter(pk=source_id, quotation__archived_at__isnull=True)
        .first()
    )
    if version is None:
        quotation = Quotation.objects.select_for_update(of=("self",)).get(pk=source_id, archived_at__isnull=True)
        version = quotation.versions.exclude(status=QuotationVersionStatus.VOID).order_by("-version_number").first()
        if version is None:
            raise Conflict("来源报价没有可用版本。")
        version = (
            QuotationVersion.objects.select_for_update(of=("self",))
            .select_related(
                "quotation__customer_account",
                "quotation__transaction_entity",
                "quotation__owner_employee",
                "quotation__source_inquiry__customer_contact",
            )
            .prefetch_related("lines")
            .get(pk=version.pk)
        )
    if version.status == QuotationVersionStatus.VOID:
        raise Conflict("已作废的报价版本不能创建样品。")
    quotation = version.quotation
    if quotation.owner_employee_id is None:
        raise Conflict("来源报价尚未分配业务员。")
    contact = quotation.source_inquiry.customer_contact if quotation.source_inquiry_id else None
    if contact is None and version.contact_snapshot.get("id"):
        contact = CustomerContact.objects.filter(
            pk=version.contact_snapshot["id"],
            customer_account=quotation.customer_account,
            archived_at__isnull=True,
        ).first()
    return {
        "customer_account": quotation.customer_account,
        "transaction_entity": quotation.transaction_entity,
        "customer_contact": contact,
        "owner_employee": quotation.owner_employee,
        "source_inquiry": quotation.source_inquiry,
        "source_quotation_version": version,
        "inquiry_items": {},
        "quotation_lines": {str(line.pk): line for line in version.lines.all()},
    }


def _validate_source_tampering(validated_data, relations):
    errors = {}
    for field_name, label in [
        ("customer_account", "客户"),
        ("customer_contact", "联系人"),
        ("owner_employee", "业务员"),
    ]:
        submitted = validated_data.get(field_name)
        actual = relations[field_name]
        if (submitted.pk if submitted else None) != (actual.pk if actual else None):
            errors[field_name] = f"{label}必须与来源记录一致，不能修改。"
    if errors:
        raise ValidationError(errors)


def _validate_product_source(product_data, relations):
    inquiry_id = product_data.pop("source_inquiry_item_id", None)
    quotation_id = product_data.pop("source_quotation_line_id", None)
    inquiry_item = None
    quotation_line = None
    if inquiry_id:
        inquiry_item = relations["inquiry_items"].get(str(inquiry_id))
        if inquiry_item is None and relations["source_quotation_version"] is not None:
            inquiry_item = InquiryItem.objects.filter(
                pk=inquiry_id,
                inquiry=relations["source_inquiry"],
            ).first()
        if inquiry_item is None:
            raise ValidationError({"products": "来源询盘产品不属于当前来源记录。"})
    if quotation_id:
        quotation_line = relations["quotation_lines"].get(str(quotation_id))
        if quotation_line is None:
            raise ValidationError({"products": "来源报价产品不属于当前报价版本。"})
    return inquiry_item, quotation_line


def _create_sampling_details(*, product, details, sampling_image_files):
    for line_number, raw_detail in enumerate(details, start=1):
        detail = dict(raw_detail)
        detail.pop("id", None)
        client_key = detail.pop("client_key")
        SampleProductSamplingDetail.objects.create(
            sample_product=product,
            line_number=line_number,
            image_file=sampling_image_files.get(client_key),
            **detail,
        )


def _update_sampling_details(*, product, details, sampling_image_files):
    existing = {str(detail.pk): detail for detail in product.sampling_details.all()}
    kept_ids = {str(detail.get("id")) for detail in details if detail.get("id")}
    if not kept_ids.issubset(existing):
        raise ValidationError({"products": "存在不属于当前产品的打样信息明细 UUID。"})

    temporary_base = max((detail.line_number for detail in existing.values()), default=0) + len(existing) + 1
    for offset, detail in enumerate(existing.values()):
        detail.line_number = temporary_base + offset
        detail.save(update_fields=["line_number"])
    for detail_id, detail in existing.items():
        if detail_id not in kept_ids:
            detail.delete()

    for line_number, raw_detail in enumerate(details, start=1):
        detail_data = dict(raw_detail)
        detail_id = detail_data.pop("id", None)
        client_key = detail_data.pop("client_key")
        if detail_id:
            detail = existing[str(detail_id)]
            detail.line_number = line_number
            for field_name, value in detail_data.items():
                setattr(detail, field_name, value)
            if client_key in sampling_image_files:
                detail.image_file = sampling_image_files[client_key]
            detail.save()
        else:
            SampleProductSamplingDetail.objects.create(
                sample_product=product,
                line_number=line_number,
                image_file=sampling_image_files.get(client_key),
                **detail_data,
            )


def _create_products(*, sample_request, products, task_files, sampling_image_files, source_relations):
    detail_line_number = 1
    for product_line_number, raw_product in enumerate(products, start=1):
        product_data = dict(raw_product)
        details = product_data.pop("details")
        sampling_details = product_data.pop("sampling_details")
        if not sampling_details:
            raise ValidationError({"products": "每个产品至少需要一条打样信息明细。"})
        product_data.pop("id", None)
        client_key = product_data.pop("client_key")
        task_file = task_files.get(client_key)
        if task_file is None:
            raise ValidationError({f"task_sheet_{client_key}": "每个产品必须上传一张任务单图片。"})
        source_inquiry_item, source_quotation_line = _validate_product_source(product_data, source_relations)
        source = source_quotation_line or source_inquiry_item
        if source is not None:
            for field_name, value in sample_product_values_from_source(source).items():
                product_data.setdefault(field_name, value)
        category = product_data.pop("category")
        product = SampleProduct.objects.create(
            sample_request=sample_request,
            source_inquiry_item=source_inquiry_item,
            source_quotation_line=source_quotation_line,
            line_number=product_line_number,
            category=category,
            category_name_snapshot=category.category_name,
            task_sheet_file=task_file,
            **product_data,
        )
        _create_sampling_details(
            product=product,
            details=sampling_details,
            sampling_image_files=sampling_image_files,
        )
        for raw_detail in details:
            detail = dict(raw_detail)
            detail.pop("id", None)
            color = detail.pop("product_color")
            color_code = detail.pop("color_code", "") or color.color_code
            quantity = detail["sample_quantity"]
            SampleItem.objects.create(
                sample_request=sample_request,
                sample_product=product,
                source_inquiry_item=source_inquiry_item,
                source_quotation_line=source_quotation_line,
                line_number=detail_line_number,
                product_description_snapshot=product.product_name,
                specification_snapshot=product.specification,
                requested_quantity=quantity,
                unit_code="PCS",
                product_color=color,
                color_card_snapshot=color.color_card,
                color_name_snapshot=color.color_name,
                color_code_snapshot=color_code,
                **detail,
            )
            detail_line_number += 1


@transaction.atomic
def create_sample_form(*, validated_data, task_files, sampling_image_files, actor_employee, request):
    data = dict(validated_data)
    products = data.pop("products")
    source_type = data.pop("source_type", None)
    source_id = data.pop("source_id", None)
    idempotency_key = data.pop("idempotency_key", "")
    manual_number = data.pop("manual_request_number")
    formal_number = f"HTS-{manual_number}"
    if idempotency_key:
        replayed = SampleRequest.objects.filter(creation_idempotency_key=idempotency_key).first()
        if replayed is not None:
            if replayed.request_number != formal_number:
                raise Conflict("幂等键已被其他样品申请使用，请刷新后重试。")
            return replayed, True
    if SampleRequest.objects.filter(request_number=formal_number).exists():
        raise ValidationError({"manual_request_number": "该打样单号已存在。"})

    if source_type:
        relations = _source_relations(source_type, source_id)
        _validate_source_tampering(data, relations)
        for field_name in ["customer_account", "customer_contact", "owner_employee"]:
            data[field_name] = relations[field_name]
    else:
        relations = {
            "source_inquiry": None,
            "source_quotation_version": None,
            "transaction_entity": None,
            "inquiry_items": {},
            "quotation_lines": {},
        }
        data.setdefault("customer_contact", None)
    submitted_on = data["submitted_on"]
    sample_due_date = data["sample_due_date"]
    sample_request = SampleRequest.objects.create(
        request_number=formal_number,
        manual_request_number=manual_number,
        requested_by_employee=actor_employee,
        created_by_employee=actor_employee,
        creation_idempotency_key=idempotency_key,
        status=SampleRequestStatus.DRAFT,
        transaction_entity=relations.get("transaction_entity"),
        source_inquiry=relations.get("source_inquiry"),
        source_quotation_version=relations.get("source_quotation_version"),
        requested_at=_legacy_datetime(submitted_on),
        requested_due_at=_legacy_datetime(sample_due_date),
        notes="",
        **data,
    )
    from apps.access_control.module_policy import require_sample_reporting_changes
    require_sample_reporting_changes(request, sample_request, [detail for product in products for detail in product['details']])
    _create_products(
        sample_request=sample_request,
        products=products,
        task_files=task_files,
        sampling_image_files=sampling_image_files,
        source_relations=relations,
    )
    sample_request.status = SampleRequestStatus.PENDING
    sample_request.save(update_fields=["status", "updated_at"])
    now = timezone.now()
    _start_sla(sample_request, now)
    _write_sample_records(
        sample_request=sample_request,
        action="CREATED_SUBMITTED",
        actor_employee=actor_employee,
        request=request,
        note=f"创建并提交 {len(products)} 个产品区块。",
    )
    _record_workflow_stage(
        sample_request=sample_request,
        stage=SampleWorkflowStage.REQUEST_CREATED,
        actor_employee=actor_employee,
        note="工厂直接创建样品单。",
        operated_at=sample_request.created_at,
    )
    _record_workflow_stage(
        sample_request=sample_request,
        stage=SampleWorkflowStage.REQUIREMENTS_COMPLETED,
        actor_employee=actor_employee,
        note="样品需求已完整提交。",
        operated_at=now,
    )
    from apps.inquiries.handling_time import sample_submitted
    sample_submitted(sample_request)
    return sample_request, False


def _assert_immutable_sample_fields(sample_request, data, *, completing=False):
    errors = {}
    comparisons = {
        "customer_account": sample_request.customer_account,
        "customer_contact": sample_request.customer_contact,
    }
    if not completing:
        comparisons["manual_request_number"] = sample_request.manual_request_number
    if sample_request.source_inquiry_id or sample_request.source_quotation_version_id:
        comparisons["owner_employee"] = sample_request.owner_employee
    for field_name, expected in comparisons.items():
        submitted = data.get(field_name)
        submitted_value = submitted.pk if hasattr(submitted, "pk") else submitted
        expected_value = expected.pk if hasattr(expected, "pk") else expected
        if submitted_value != expected_value:
            errors[field_name] = "该字段创建后不可修改。"
    if errors:
        raise ValidationError(errors)


def _update_reporting_only(sample_request, products, purpose):
    existing_products = {
        str(product.pk): product
        for product in sample_request.products.prefetch_related("details", "sampling_details")
    }
    submitted_product_ids = {str(product.get("id")) for product in products if product.get("id")}
    if submitted_product_ids != set(existing_products):
        raise Conflict("当前阶段不能增删产品。")
    for product_data in products:
        product = existing_products[str(product_data["id"])]
        product_comparisons = {
            "source_inquiry_item_id": product.source_inquiry_item_id,
            "source_quotation_line_id": product.source_quotation_line_id,
            "category": product.category,
            "product_name": product.product_name,
            "specification": product.specification,
            "length_cm": product.length_cm,
            "armrest_width_cm": product.armrest_width_cm,
            "seat_width_cm": product.seat_width_cm,
            "back_height_cm": product.back_height_cm,
            "seat_height_cm": product.seat_height_cm,
        }
        for field_name, expected in product_comparisons.items():
            submitted = product_data.get(field_name)
            submitted_value = submitted.pk if hasattr(submitted, "pk") else submitted
            expected_value = expected.pk if hasattr(expected, "pk") else expected
            if submitted_value != expected_value:
                raise Conflict("当前阶段不能修改产品基础信息。")
        existing_details = {str(detail.pk): detail for detail in product.details.all()}
        submitted_detail_ids = {str(detail.get("id")) for detail in product_data["details"] if detail.get("id")}
        if submitted_detail_ids != set(existing_details):
            raise Conflict("当前阶段不能增删样品明细。")
        for detail_data in product_data["details"]:
            detail = existing_details[str(detail_data["id"])]
            if (
                detail.sample_quantity != detail_data["sample_quantity"]
                or detail.product_color_id != detail_data["product_color"].pk
                or detail.color_code_snapshot != detail_data.get("color_code", detail.color_code_snapshot)
                or detail.tolerance != detail_data["tolerance"]
                or detail.notes != detail_data.get("notes", "")
            ):
                raise Conflict("当前阶段只能修改报工数量、完成状态和特殊说明。")
            for field_name in [
                "cutting_reported_quantity",
                "metalwork_reported_quantity",
                "cutting_completed",
                "metalwork_completed",
            ]:
                setattr(detail, field_name, detail_data[field_name])
            detail.save(
                update_fields=[
                    "cutting_reported_quantity",
                    "metalwork_reported_quantity",
                    "cutting_completed",
                    "metalwork_completed",
                    "updated_at",
                ]
            )
        existing_sampling_details = {
            str(detail.pk): detail for detail in product.sampling_details.all()
        }
        submitted_sampling_ids = {
            str(detail.get("id"))
            for detail in product_data["sampling_details"]
            if detail.get("id")
        }
        if submitted_sampling_ids != set(existing_sampling_details):
            raise Conflict("当前阶段不能增删打样信息明细。")
        for detail_data in product_data["sampling_details"]:
            detail = existing_sampling_details[str(detail_data["id"])]
            if any(
                [
                    detail.template_key != detail_data.get("template_key", ""),
                    detail.detail_type != detail_data["detail_type"],
                    detail.category_label != detail_data.get("category_label", ""),
                    detail.is_selected != detail_data["is_selected"],
                    detail.description != detail_data.get("description", ""),
                ]
            ):
                raise Conflict("当前阶段不能修改打样信息明细。")
    sample_request.purpose = purpose
    sample_request.save(update_fields=["purpose", "updated_at"])


def _update_full(
    sample_request,
    data,
    products,
    task_files,
    sampling_image_files,
    *,
    preserve_requested_at=False,
    require_sampling_details=True,
    require_task_sheet=True,
):
    for field_name in [
        "owner_employee",
        "shipping_method",
        "order_date",
        "sample_due_date",
        "delivery_batch",
        "sample_type",
        "is_repeat_order",
        "submitted_on",
        "purpose",
    ]:
        setattr(sample_request, field_name, data[field_name])
    if not preserve_requested_at:
        sample_request.requested_at = _legacy_datetime(data["submitted_on"])
    sample_request.requested_due_at = _legacy_datetime(data["sample_due_date"])
    update_fields = [
            "owner_employee",
            "shipping_method",
            "order_date",
            "sample_due_date",
            "delivery_batch",
            "sample_type",
            "is_repeat_order",
            "submitted_on",
            "purpose",
            "requested_due_at",
            "updated_at",
        ]
    if not preserve_requested_at:
        update_fields.append("requested_at")
    sample_request.save(update_fields=update_fields)
    existing_products = {
        str(product.pk): product
        for product in sample_request.products.prefetch_related("details", "sampling_details")
    }
    kept_product_ids = {str(product.get("id")) for product in products if product.get("id")}
    if not kept_product_ids.issubset(existing_products):
        raise ValidationError({"products": "存在不属于当前样品申请的产品 UUID。"})

    # 先把已有行号移到当前最大值之后，避免产品或明细调换顺序时撞上唯一约束。
    product_temp_base = max((product.line_number for product in existing_products.values()), default=0)
    product_temp_base += len(existing_products) + 1
    for offset, product in enumerate(existing_products.values()):
        product.line_number = product_temp_base + offset
        product.save(update_fields=["line_number"])
    existing_items = list(SampleItem.objects.filter(sample_request=sample_request).order_by("line_number", "id"))
    item_temp_base = max((item.line_number for item in existing_items), default=0) + len(existing_items) + 1
    for offset, item in enumerate(existing_items):
        item.line_number = item_temp_base + offset
        item.save(update_fields=["line_number"])

    for product_id, product in existing_products.items():
        if product_id not in kept_product_ids:
            product.details.all().delete()
            product.sampling_details.all().delete()
            product.delete()
    detail_line_number = 1
    for product_line_number, raw_product in enumerate(products, start=1):
        product_data = dict(raw_product)
        details = product_data.pop("details")
        sampling_details = product_data.pop("sampling_details")
        if require_sampling_details and not sampling_details:
            raise ValidationError({"products": "每个产品至少需要一条打样信息明细。"})
        client_key = product_data.pop("client_key")
        product_id = product_data.pop("id", None)
        submitted_inquiry_id = product_data.pop("source_inquiry_item_id", None)
        submitted_quote_id = product_data.pop("source_quotation_line_id", None)
        category = product_data.pop("category")
        if product_id:
            product = existing_products[str(product_id)]
            if submitted_inquiry_id != product.source_inquiry_item_id or submitted_quote_id != product.source_quotation_line_id:
                raise Conflict("产品来源关系创建后不可修改。")
            product.category = category
            product.category_name_snapshot = category.category_name
            product.line_number = product_line_number
            for field_name, value in product_data.items():
                setattr(product, field_name, value)
            if client_key in task_files:
                product.task_sheet_file = task_files[client_key]
            if require_task_sheet and product.task_sheet_file_id is None:
                raise ValidationError({f"task_sheet_{client_key}": "每个产品必须上传一张任务单图片。"})
            product.save()
        else:
            if submitted_inquiry_id or submitted_quote_id:
                raise Conflict("补充产品不能伪造来源关系。")
            task_file = task_files.get(client_key)
            if require_task_sheet and task_file is None:
                raise ValidationError({f"task_sheet_{client_key}": "每个产品必须上传一张任务单图片。"})
            product = SampleProduct.objects.create(
                sample_request=sample_request,
                line_number=product_line_number,
                category=category,
                category_name_snapshot=category.category_name,
                task_sheet_file=task_file,
                **product_data,
            )
        _update_sampling_details(
            product=product,
            details=sampling_details,
            sampling_image_files=sampling_image_files,
        )
        existing_details = {str(detail.pk): detail for detail in product.details.all()}
        kept_detail_ids = {str(detail.get("id")) for detail in details if detail.get("id")}
        if not kept_detail_ids.issubset(existing_details):
            raise ValidationError({"products": "存在不属于当前产品的样品明细 UUID。"})
        for detail_id, detail in existing_details.items():
            if detail_id not in kept_detail_ids:
                detail.delete()
        for raw_detail in details:
            detail_data = dict(raw_detail)
            detail_id = detail_data.pop("id", None)
            color = detail_data.pop("product_color")
            color_code = detail_data.pop("color_code", "") or color.color_code
            quantity = detail_data["sample_quantity"]
            common = {
                "line_number": detail_line_number,
                "product_description_snapshot": product.product_name,
                "specification_snapshot": product.specification,
                "requested_quantity": quantity,
                "unit_code": "PCS",
                "product_color": color,
                "color_card_snapshot": color.color_card,
                "color_name_snapshot": color.color_name,
                "color_code_snapshot": color_code,
                **detail_data,
            }
            if detail_id:
                detail = existing_details[str(detail_id)]
                for field_name, value in common.items():
                    setattr(detail, field_name, value)
                detail.save()
            else:
                SampleItem.objects.create(sample_request=sample_request, sample_product=product, **common)
            detail_line_number += 1


@transaction.atomic
def update_sample_form(
    *,
    sample_request,
    validated_data,
    task_files,
    sampling_image_files,
    actor_employee,
    request,
):
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    capabilities = sample_form_edit_capabilities(sample_request)
    if capabilities["mode"] == "READ_ONLY":
        raise Conflict("当前样品申请已终态，只能查看。")
    data = dict(validated_data)
    products = data.pop("products")
    from apps.access_control.module_policy import require_sample_reporting_changes
    require_sample_reporting_changes(request, sample_request, [detail for product in products for detail in product['details']])
    data.pop("source_type", None)
    data.pop("source_id", None)
    data.pop("idempotency_key", None)
    completing = capabilities["mode"] == "COMPLETE"
    application_completion = completing and bool(sample_request.application_payload_hash)
    _assert_immutable_sample_fields(sample_request, data, completing=completing)
    manual_number = data.get("manual_request_number", "")
    formal_number = f"HTS-{manual_number}" if manual_number else ""
    if completing and not application_completion and SampleRequest.objects.filter(request_number=formal_number).exclude(pk=sample_request.pk).exists():
        raise ValidationError({"manual_request_number": "该打样单号已存在。"})
    before_data = model_snapshot(sample_request, SAMPLE_FIELDS)
    if capabilities["mode"] == "REPORT_ONLY":
        if task_files or sampling_image_files:
            raise Conflict("当前阶段不能替换任务单或打样信息明细图片。")
        base_comparisons = {
            "owner_employee": sample_request.owner_employee,
            "shipping_method": sample_request.shipping_method,
            "order_date": sample_request.order_date,
            "sample_due_date": sample_request.sample_due_date,
            "delivery_batch": sample_request.delivery_batch,
            "sample_type": sample_request.sample_type,
            "is_repeat_order": sample_request.is_repeat_order,
            "submitted_on": sample_request.submitted_on,
        }
        for field_name, expected in base_comparisons.items():
            submitted = data.get(field_name)
            submitted_value = submitted.pk if hasattr(submitted, "pk") else submitted
            expected_value = expected.pk if hasattr(expected, "pk") else expected
            if submitted_value != expected_value:
                raise Conflict("当前阶段只能修改报工数量、完成状态和特殊说明。")
        _update_reporting_only(sample_request, products, data["purpose"])
    else:
        _update_full(
            sample_request,
            data,
            products,
            task_files,
            sampling_image_files,
            preserve_requested_at=completing,
            require_sampling_details=not completing,
            require_task_sheet=not application_completion,
        )
    if completing:
        completed_at = timezone.now()
        if application_completion:
            sample_request.status = SampleRequestStatus.MATERIALS_PENDING
            sample_request.save(update_fields=["status", "updated_at"])
        else:
            sample_request.manual_request_number = manual_number
            sample_request.request_number = formal_number
            sample_request.created_by_employee = actor_employee
            sample_request.status = SampleRequestStatus.PENDING
            sample_request.save(
                update_fields=[
                    "manual_request_number",
                    "request_number",
                    "created_by_employee",
                    "status",
                    "updated_at",
                ]
            )
        _start_sla(sample_request, completed_at)
        _record_workflow_stage(
            sample_request=sample_request,
            stage=SampleWorkflowStage.REQUIREMENTS_COMPLETED,
            actor_employee=actor_employee,
            note="工厂完善并提交样品需求。",
            operated_at=completed_at,
        )
    _write_sample_records(
        sample_request=sample_request,
        action="REQUIREMENTS_COMPLETED" if completing else "FORM_UPDATED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=(
            "工厂完善并提交样品需求"
            if completing
            else ("完整编辑" if capabilities["mode"] == "FULL" else "更新报工与特殊说明")
        ),
    )
    return sample_request
