from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.customers.models import CustomerAccount, CustomerAssignment, CustomerContact, CustomerTransactionEntity
from apps.customers.selectors import accessible_customers
from apps.inquiries.models import Inquiry, InquiryStatus
from apps.quotations.models import Quotation, QuotationOutcomeStatus, QuotationVersion, QuotationVersionStatus
from apps.samples.models import SampleRequest, SampleRequestStatus
from apps.workflow.models import BusinessTask, TaskStatus
from apps.workflow.selectors import accessible_tasks

from .permissions import HasActiveEmployee


SEARCH_TYPES = {"CUSTOMER", "ENTITY", "CONTACT", "INQUIRY", "QUOTATION"}


def _has(request, permission):
    return request.user.is_superuser or request.user.has_perm(permission)


class GlobalSearchView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", OpenApiTypes.STR, required=True, description="至少 2 个字符"),
            OpenApiParameter("types", OpenApiTypes.STR, required=False, description="逗号分隔的资源类型"),
        ],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request):
        if not _has(request, "customers.view_customeraccount"):
            raise PermissionDenied("缺少客户查看权限，不能使用全局搜索。")
        query = request.query_params.get("q", "").strip()
        if len(query) < 2:
            raise ValidationError({"q": "搜索词至少需要 2 个字符。"})
        requested_types = {
            item.strip().upper() for item in request.query_params.get("types", ",".join(sorted(SEARCH_TYPES))).split(",") if item.strip()
        }
        invalid_types = requested_types - SEARCH_TYPES
        if invalid_types:
            raise ValidationError({"types": f"不支持的资源类型：{', '.join(sorted(invalid_types))}。"})
        customers = accessible_customers(request, "view_customeraccount").filter(archived_at__isnull=True)
        results = []
        if "CUSTOMER" in requested_types:
            for item in customers.filter(
                Q(account_code__icontains=query) | Q(account_name__icontains=query)
                | Q(english_name__icontains=query) | Q(short_name__icontains=query)
            ).order_by("account_code")[:10]:
                results.append({
                    "type": "CUSTOMER", "id": str(item.pk), "customer_id": str(item.pk),
                    "title": f"{item.account_code} · {item.account_name}", "subtitle": item.english_name,
                    "url": f"/customers/{item.pk}",
                })
        if "ENTITY" in requested_types and _has(request, "customers.view_customertransactionentity"):
            for item in CustomerTransactionEntity.objects.filter(
                customer_account__in=customers, archived_at__isnull=True
            ).filter(
                Q(entity_code__icontains=query) | Q(legal_name__icontains=query)
                | Q(english_legal_name__icontains=query) | Q(registration_number__icontains=query)
            ).select_related("customer_account").order_by("entity_code")[:10]:
                results.append({
                    "type": "ENTITY", "id": str(item.pk), "customer_id": str(item.customer_account_id),
                    "title": f"{item.entity_code} · {item.legal_name}",
                    "subtitle": item.customer_account.account_name, "url": f"/customers/{item.customer_account_id}/entities/{item.pk}",
                })
        if "CONTACT" in requested_types and _has(request, "customers.view_customercontact"):
            for item in CustomerContact.objects.filter(
                customer_account__in=customers, archived_at__isnull=True
            ).filter(
                Q(display_name__icontains=query) | Q(position_title__icontains=query)
                | Q(methods__raw_value__icontains=query) | Q(methods__normalized_value__icontains=query)
            ).select_related("customer_account").distinct().order_by("display_name")[:10]:
                results.append({
                    "type": "CONTACT", "id": str(item.pk), "customer_id": str(item.customer_account_id),
                    "title": item.display_name, "subtitle": f"{item.customer_account.account_name} · {item.position_title}".strip(" ·"),
                    "url": f"/customers/{item.customer_account_id}/contacts/{item.pk}",
                })
        if "INQUIRY" in requested_types and _has(request, "inquiries.view_inquiry"):
            for item in Inquiry.objects.filter(customer_account__in=customers, archived_at__isnull=True).filter(
                Q(inquiry_number__icontains=query) | Q(subject__icontains=query)
            ).select_related("customer_account").order_by("-received_at")[:10]:
                results.append({
                    "type": "INQUIRY", "id": str(item.pk), "customer_id": str(item.customer_account_id),
                    "title": f"{item.inquiry_number} · {item.subject}", "subtitle": item.customer_account.account_name,
                    "url": f"/inquiries/{item.pk}",
                })
        if "QUOTATION" in requested_types and _has(request, "quotations.view_quotation"):
            for item in Quotation.objects.filter(customer_account__in=customers, archived_at__isnull=True).filter(
                Q(quotation_number__icontains=query) | Q(subject__icontains=query)
            ).select_related("customer_account").order_by("-created_at")[:10]:
                results.append({
                    "type": "QUOTATION", "id": str(item.pk), "customer_id": str(item.customer_account_id),
                    "title": f"{item.quotation_number} · {item.subject}", "subtitle": item.customer_account.account_name,
                    "url": f"/quotations/{item.pk}",
                })
        return Response({"data": results, "meta": {"q": query, "total": len(results)}})


def _customer_scoped_task_queryset(request, customers):
    return accessible_tasks(request).filter(
        Q(customer_links__customer_account__in=customers)
        | Q(communication_links__communication__customer_account__in=customers)
        | Q(inquiry_links__inquiry__customer_account__in=customers)
        | Q(quotation_links__quotation_version__quotation__customer_account__in=customers)
        | Q(sample_links__sample_request__customer_account__in=customers)
    ).distinct()


def _dashboard_payload(request, customers):
    now = timezone.now()
    today = timezone.localdate()
    customer_count = customers.filter(archived_at__isnull=True).count()
    inquiries = Inquiry.objects.none()
    if _has(request, "inquiries.view_inquiry"):
        inquiries = Inquiry.objects.filter(customer_account__in=customers, archived_at__isnull=True)
    quotations = Quotation.objects.none()
    if _has(request, "quotations.view_quotation"):
        quotations = Quotation.objects.filter(customer_account__in=customers, archived_at__isnull=True)
    samples = SampleRequest.objects.none()
    if _has(request, "samples.view_samplerequest"):
        samples = SampleRequest.objects.filter(customer_account__in=customers, archived_at__isnull=True)
    tasks = BusinessTask.objects.none()
    if _has(request, "workflow.view_businesstask"):
        tasks = _customer_scoped_task_queryset(request, customers).filter(archived_at__isnull=True)
    active_inquiry_statuses = [InquiryStatus.DRAFT, InquiryStatus.SUBMITTED, InquiryStatus.IN_PROGRESS, InquiryStatus.QUOTED]
    active_sample_statuses = [
        SampleRequestStatus.DRAFT, SampleRequestStatus.PENDING, SampleRequestStatus.PREPARING,
        SampleRequestStatus.SHIPPED, SampleRequestStatus.FEEDBACK_PENDING,
    ]
    expiring_versions = QuotationVersion.objects.none()
    if _has(request, "quotations.view_quotationversion"):
        expiring_versions = QuotationVersion.objects.filter(
            quotation__in=quotations, status__in=[QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT],
            valid_until__gte=today, valid_until__lte=today + timedelta(days=14),
        ).select_related("quotation", "quotation__customer_account").order_by("valid_until")[:10]
    return {
        "counts": {
            "customers": customer_count,
            "open_inquiries": inquiries.filter(status__in=active_inquiry_statuses).count(),
            "open_quotations": quotations.filter(outcome_status=QuotationOutcomeStatus.OPEN).count(),
            "active_sample_requests": samples.filter(status__in=active_sample_statuses).count(),
            "open_tasks": tasks.filter(status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS]).count(),
            "overdue_tasks": tasks.filter(
                status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS], due_at__lt=now
            ).count(),
        },
        "recent_customers": [
            {"id": str(item.pk), "account_code": item.account_code, "account_name": item.account_name, "updated_at": item.updated_at}
            for item in customers.filter(archived_at__isnull=True).order_by("-updated_at", "-id")[:10]
        ],
        "due_inquiries": [
            {"id": str(item.pk), "number": item.inquiry_number, "subject": item.subject, "requested_due_at": item.requested_due_at}
            for item in inquiries.filter(status__in=active_inquiry_statuses, requested_due_at__isnull=False).order_by("requested_due_at")[:10]
        ],
        "expiring_quotation_versions": [
            {
                "id": str(item.pk), "quotation_id": str(item.quotation_id),
                "quotation_number": item.quotation.quotation_number, "version_number": item.version_number,
                "valid_until": item.valid_until,
            } for item in expiring_versions
        ],
        "sample_queue": [
            {"id": str(item.pk), "request_number": item.request_number, "status": item.status, "requested_due_at": item.requested_due_at}
            for item in samples.filter(status__in=active_sample_statuses).order_by("requested_due_at", "requested_at")[:10]
        ],
    }


class MyDashboardView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        if not _has(request, "customers.view_customeraccount"):
            raise PermissionDenied("缺少客户查看权限。")
        customers = accessible_customers(request, "view_customeraccount")
        return Response({"data": _dashboard_payload(request, customers), "meta": {"scope": "ME"}})


class ManagerDashboardView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        if not request.user.is_superuser and not request.user.has_perm("customers.view_all_customer"):
            raise PermissionDenied("管理驾驶舱要求“查看全部客户”权限。")
        customers = accessible_customers(request, "view_customeraccount")
        payload = _dashboard_payload(request, customers)
        now = timezone.now()
        owners = CustomerAssignment.objects.filter(
            customer_account__in=customers, assignment_role="PRIMARY_OWNER", effective_from__lte=now
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now)).values(
            "employee_id", "employee__employee_code", "employee__display_name"
        ).annotate(customer_count=Count("customer_account", distinct=True)).order_by("-customer_count", "employee__employee_code")
        payload["owner_distribution"] = list(owners)
        return Response({"data": payload, "meta": {"scope": "MANAGER"}})
