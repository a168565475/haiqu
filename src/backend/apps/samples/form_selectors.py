from rest_framework.exceptions import NotFound, ValidationError
from django.utils import timezone

from apps.customers.models import CustomerContact
from apps.customers.selectors import accessible_customers
from apps.inquiries.models import Inquiry, InquiryStatus, format_inquiry_item_specification
from apps.inquiries.images import inquiry_reference_images
from apps.files.models import USABLE_FILE_SCAN_STATUSES
from apps.quotations.models import QuotationVersion, QuotationVersionStatus

from .models import SampleRequest, SampleRequestStatus, SampleType
from .procurement_status import sample_status_display


INELIGIBLE_INQUIRY_STATUSES = {
    InquiryStatus.DRAFT,
    InquiryStatus.LOST,
    InquiryStatus.CLOSED,
    InquiryStatus.CANCELLED,
}
TERMINAL_SAMPLE_STATUSES = {
    SampleRequestStatus.CONFIRMED,
    SampleRequestStatus.COMPLETED,
    SampleRequestStatus.REJECTED,
    SampleRequestStatus.CANCELLED,
}


def _sample_type_options():
    return [{"value": value, "label": label} for value, label in SampleType.choices]


def _customer_payload(customer):
    return {
        "id": str(customer.pk),
        "account_code": customer.account_code,
        "account_name": customer.account_name,
    }


def _contact_payload(contact):
    if contact is None:
        return None
    return {"id": str(contact.pk), "display_name": contact.display_name}


def _owner_payload(owner):
    if owner is None:
        return None
    return {"id": str(owner.pk), "employee_code": owner.employee_code, "display_name": owner.display_name}


def _local_date(value):
    if value is None:
        return None
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.date().isoformat()


def _source_basic_info(inquiry):
    if inquiry is None:
        return {"order_date": None, "sample_due_date": None}
    return {
        "order_date": _local_date(inquiry.received_at),
        "sample_due_date": _local_date(inquiry.requested_due_at),
    }


def _quotation_line_reference_images(line):
    image = line.product_image
    if image is None or image.archived_at is not None or image.scan_status not in USABLE_FILE_SCAN_STATUSES:
        return []
    return [{
        "id": str(image.pk),
        "name": image.original_name,
        "url": f"/api/v1/quotation-lines/{line.pk}/product-image/",
    }]


def _unfinished_samples(queryset):
    return [
        {
            "id": str(sample.pk),
            "number": sample.intake_number or sample.request_number,
            "status": sample.status,
            "status_display": sample_status_display(sample),
        }
        for sample in queryset.exclude(status__in=TERMINAL_SAMPLE_STATUSES).order_by("-requested_at", "-id")[:5]
    ]


def resolve_form_source(*, request, source_type, source_id, customer_permission="add_samplerequest", for_creation=True):
    customers = accessible_customers(request, customer_permission).filter(archived_at__isnull=True)
    if source_type == "inquiry":
        try:
            inquiry = (
                Inquiry.objects.filter(customer_account__in=customers, archived_at__isnull=True)
                .select_related("customer_account", "transaction_entity", "customer_contact", "owner_employee")
                .prefetch_related("items")
                .get(pk=source_id)
            )
        except Inquiry.DoesNotExist as exc:
            raise NotFound("来源询盘不存在或当前账号无权访问。") from exc
        if for_creation and inquiry.status in INELIGIBLE_INQUIRY_STATUSES:
            raise ValidationError({"sourceId": "当前询盘状态不能创建样品需求。"})
        if inquiry.owner_employee_id is None:
            raise ValidationError({"sourceId": "来源询盘尚未分配业务员。"})
        if for_creation and not inquiry.items.exists():
            raise ValidationError({"sourceId": "来源询盘没有产品，不能创建样品需求。"})
        return {
            "source_type": "inquiry",
            "source_id": str(inquiry.pk),
            "source_parent_id": None,
            "source_version_id": None,
            "source_number": inquiry.inquiry_number,
            "reference_images": [{'id': str(image.pk), 'name': image.original_name, 'url': f'/api/v1/inquiries/{inquiry.pk}/images/{image.pk}/'} for image in inquiry_reference_images(inquiry.pk, request)],
            "customer": _customer_payload(inquiry.customer_account),
            "contact": _contact_payload(inquiry.customer_contact),
            "owner": _owner_payload(inquiry.owner_employee),
            "transaction_entity_id": str(inquiry.transaction_entity_id) if inquiry.transaction_entity_id else None,
            "basic_info": _source_basic_info(inquiry),
            "suggested_due_date": _local_date(inquiry.requested_due_at),
            "sample_types": _sample_type_options(),
            "unfinished_samples": _unfinished_samples(
                SampleRequest.objects.filter(
                    source_inquiry=inquiry,
                    source_quotation_version__isnull=True,
                    archived_at__isnull=True,
                )
            ),
            "products": [
                {
                    "id": str(item.pk),
                    "source_inquiry_item_id": str(item.pk),
                    "source_quotation_line_id": None,
                    "product_id": str(item.product_id) if item.product_id else None,
                    "product_name": item.product_description,
                    "specification": format_inquiry_item_specification(item.specification, item.color, item.material),
                    "source_quantity": str(item.quantity),
                    "source_unit_code": item.unit_code,
                }
                for item in inquiry.items.all()
            ],
        }

    if source_type != "quotation":
        raise ValidationError({"sourceType": "来源类型仅支持 inquiry 或 quotation。"})
    version = (
        QuotationVersion.objects.filter(
            pk=source_id,
            quotation__customer_account__in=customers,
            quotation__archived_at__isnull=True,
        )
        .select_related(
            "quotation__customer_account",
            "quotation__transaction_entity",
            "quotation__owner_employee",
            "quotation__source_inquiry__customer_contact",
        )
        .prefetch_related("lines__product_image")
        .first()
    )
    if version is None:
        raise NotFound("来源报价版本不存在或当前账号无权访问。")
    latest_version_id = (
        version.quotation.versions.exclude(status=QuotationVersionStatus.VOID)
        .order_by("-version_number", "-id")
        .values_list("id", flat=True)
        .first()
    )
    if for_creation and (version.status != QuotationVersionStatus.SENT or latest_version_id != version.pk):
        raise ValidationError({"sourceId": "只能从当前已发送且未作废的报价版本创建样品需求。"})
    quotation = version.quotation
    if quotation.owner_employee_id is None:
        raise ValidationError({"sourceId": "来源报价尚未分配业务员。"})
    if for_creation and not version.lines.exists():
        raise ValidationError({"sourceId": "来源报价版本没有产品，不能创建样品需求。"})
    contact = quotation.source_inquiry.customer_contact if quotation.source_inquiry_id else None
    if contact is None and version.contact_snapshot.get("id"):
        contact = CustomerContact.objects.filter(
            pk=version.contact_snapshot["id"],
            customer_account=quotation.customer_account,
            archived_at__isnull=True,
        ).first()
    return {
        "source_type": "quotation",
        "source_id": str(version.pk),
        "source_parent_id": str(quotation.pk),
        "source_version_id": str(version.pk),
        "source_number": f"{quotation.quotation_number} · V{version.version_number}",
        "reference_images": [],
        "customer": _customer_payload(quotation.customer_account),
        "contact": _contact_payload(contact),
        "owner": _owner_payload(quotation.owner_employee),
        "transaction_entity_id": str(quotation.transaction_entity_id) if quotation.transaction_entity_id else None,
        "linked_inquiry_id": str(quotation.source_inquiry_id) if quotation.source_inquiry_id else None,
        "basic_info": _source_basic_info(quotation.source_inquiry),
        "suggested_due_date": _local_date(
            quotation.source_inquiry.requested_due_at if quotation.source_inquiry_id else None
        ),
        "sample_types": _sample_type_options(),
        "unfinished_samples": _unfinished_samples(
            SampleRequest.objects.filter(source_quotation_version=version, archived_at__isnull=True)
        ),
        "products": [
            {
                "id": str(line.pk),
                "source_inquiry_item_id": str(line.source_inquiry_item_id) if line.source_inquiry_item_id else None,
                "source_quotation_line_id": str(line.pk),
                "product_id": str(line.product_id) if line.product_id else None,
                "product_name": line.product_description_snapshot,
                "specification": line.specification_snapshot,
                "source_quantity": str(line.quantity),
                "source_unit_code": line.unit_code,
                "reference_images": _quotation_line_reference_images(line),
            }
            for line in version.lines.all()
        ],
    }
