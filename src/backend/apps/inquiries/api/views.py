from apps.access_control.sales_sources import filter_activity
from apps.access_control import sales_policy
import csv
import re
from datetime import timedelta
from pathlib import Path
from tempfile import SpooledTemporaryFile
from zipfile import ZipFile, ZIP_DEFLATED

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes
from rest_framework import filters, mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.core.api.concurrency import require_matching_etag
from apps.crm.models import CustomerTimelineEvent
from apps.customers.hard_delete import permanently_delete_inquiry
from apps.customers.api.views import CustomerApiViewSetBase
from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from apps.files.uploads import save_scanned_image
from apps.organizations.selectors import employee_filter_choices
from apps.workflow.api.serializers import TaskListSerializer
from apps.workflow.selectors import tasks_with_context

from ..figma_demo import DEMO_SOURCE_SYSTEM, is_figma_demo_request, seed_figma_demo_inquiries
from ..selectors import with_quotation_presence
from ..models import InquiryPriority
from ..deletion_preview import inquiry_deletion_preview
from ..worktime import due_soon_query
from ..services import set_inquiry_priority
from ..services import upload_inquiry_attachment
from ..services import remove_inquiry_item_product_image, set_inquiry_item_product_image
from ..uploads import save_inquiry_product_image
from .serializers import InquiryAttachmentUploadSerializer
from .serializers import InquiryPrioritySerializer
from ..models import Inquiry, InquiryItem
from ..selectors import ACTIVE_INQUIRY_STATUSES, assignable_employees, accessible_inquiries, inquiry_display_stage, inquiry_sla_summary, inquiries_with_context
from ..services import (
    create_inquiry,
    create_inquiry_item,
    delete_inquiry_item,
    link_inquiry_file,
    attach_inquiry_contact,
    assign_inquiry,
    mark_inquiry_invalid,
    record_inquiry_communication,
    save_inquiry_draft,
    transition_inquiry,
    update_inquiry,
    update_inquiry_item,
)
from .filters import InquiryFilter
from .serializers import (
    InquiryActionSerializer,
    InquiryAssignSerializer,
    InquiryBulkAssignSerializer,
    InquiryBulkInvalidSerializer,
    InquiryCommunicationSerializer,
    InquiryContactAttachSerializer,
    InquiryCreateSerializer,
    InquiryDraftSaveSerializer,
    InquiryDetailSerializer,
    InquiryFileLinkCreateSerializer,
    InquiryFileLinkSerializer,
    InquiryItemSerializer,
    InquiryItemUpdateSerializer,
    InquiryProductImageUploadSerializer,
    InquiryInvalidSerializer,
    InquiryListSerializer,
    InquiryReasonSerializer,
    InquiryRichTextRequiredNoteSerializer,
    InquiryRequiredNoteSerializer,
    InquiryUpdateSerializer,
    InquiryWangImageUploadSerializer,
)


class InquiryViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = InquiryDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = InquiryFilter
    search_fields = ["inquiry_number", "subject", "description", "customer_account__account_name"]
    ordering_fields = ["received_at", "requested_due_at", "submitted_at", "created_at", "updated_at"]
    ordering = ["-received_at", "-id"]
    from apps.access_control.sales_operations import INQUIRY_ACTIONS
    sales_action_permission_map = {action: f"access_control.{code}_inquiry" for action, code in INQUIRY_ACTIONS.items()}
    action_permission_map = {
        "list": "inquiries.view_inquiry",
        "priority": "inquiries.change_inquiry",
        "export": "inquiries.view_inquiry",
        "retrieve": "inquiries.view_inquiry",
        "create": "inquiries.add_inquiry",
        "destroy": "inquiries.delete_inquiry",
        "deletion_preview": "inquiries.delete_inquiry",
        "partial_update": "inquiries.change_inquiry",
        "draft": "inquiries.change_inquiry",
        "submit": "inquiries.change_inquiry",
        "start": "inquiries.change_inquiry",
        "respond": "inquiries.change_inquiry",
        "attach_contact": "inquiries.change_inquiry",
        "confirm_requirements": "inquiries.change_inquiry",
        "sync_quotation": "inquiries.change_inquiry",
        "mark_quoted": "inquiries.change_inquiry",
        "follow_up": "inquiries.change_inquiry",
        "mark_lost": "inquiries.change_inquiry",
        "close": "inquiries.change_inquiry",
        "cancel": "inquiries.change_inquiry",
        "options": "inquiries.view_inquiry",
        "metrics": "inquiries.view_inquiry",
        "assignment_queue": "inquiries.view_inquiry",
        "board": "inquiries.view_inquiry",
        "assign": "inquiries.assign_inquiry",
        "bulk_assign": "inquiries.bulk_change_inquiry",
        "mark_invalid": "inquiries.change_inquiry",
        "bulk_mark_invalid": "inquiries.bulk_change_inquiry",
        "demo_seed": "inquiries.add_inquiry",
        "items.GET": "inquiries.view_inquiryitem",
        "items.POST": "inquiries.add_inquiryitem",
        "files.GET": "inquiries.view_inquiryfilelink",
        "files.POST": "inquiries.add_inquiryfilelink",
        "wang_image_upload": "inquiries.change_inquiry",
        "image": "inquiries.view_inquiryfilelink",
        "download_file": "inquiries.view_inquiryfilelink",
        "download_files": "inquiries.view_inquiryfilelink",
        "upload_attachment": "inquiries.add_inquiryfilelink",
        "tasks": "workflow.view_businesstask",
        "timeline": "inquiries.view_inquiry",
    }

    def get_queryset(self):
        from apps.access_control.sales_policy import enabled
        scope = self.action_permission_codename("view_inquiry") if enabled() and self.action != "tasks" else "view_inquiry"
        queryset = accessible_inquiries(self.request, scope)
        if is_figma_demo_request(self.request):
            queryset = queryset.filter(source_system=DEMO_SOURCE_SYSTEM)
        if self.request.method not in SAFE_METHODS:
            queryset = queryset.filter(
                archived_at__isnull=True,
                customer_account__archived_at__isnull=True,
            )
        elif self.request.query_params.get("archived", "false").lower() != "all":
            archived = self.request.query_params.get("archived", "false").lower()
            queryset = queryset.filter(archived_at__isnull=archived != "true")
        return inquiries_with_context(queryset, request=self.request, list_mode=self.action in {"list", "assignment_queue", "board", "export"})

    @extend_schema(
        description="按当前筛选和排序导出账号可见的全部询盘，不按页截断；最多 5000 条。",
        responses={(200, "text/csv"): str},
    )
    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        if queryset.count() > 5000:
            raise ValidationError({"detail": "单次最多导出 5000 条，请缩小筛选范围后重试。"})
        rows = InquiryListSerializer(
            queryset[:5000], many=True, context=self.get_serializer_context()
        ).data
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow([
            "询盘编号", "客户名称", "国家/地区", "来源", "优先级", "负责人", "状态",
            "已转报价", "产品描述", "产品项数", "接收时间", "预估金额（目标单价×数量）", "预算币种", "预算下限", "预算上限",
        ])

        def safe_cell(value):
            text = "" if value is None else str(value)
            # Excel 会执行公式前缀；前置空白也不能绕过检查。
            if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
                return "'" + text
            return text

        for row in rows:
            summary = row["product_amount"]
            product_amount = "—"
            if summary["item_count"]:
                product_amount = "待补齐" if summary["missing_price_count"] else " / ".join(
                    f'{total["currency_code"]} {total["amount"]}' for total in summary["totals"]
                )
            writer.writerow([safe_cell(value) for value in [
                row["inquiry_number"], row["customer"]["name"], row["customer"]["country_code"],
                row["source"]["display_name"], row["priority_display"] or "未设置", (row["owner"] or {}).get("display_name", ""),
                row["status_display"], "是" if row["has_quotation"] else "否", row["product_summary"]["first_description"],
                row["product_summary"]["item_count"], row["received_at"], product_amount,
                row["estimated_currency_code"], row["estimated_amount_min"], row["estimated_amount_max"],
            ]])
        response["Content-Disposition"] = 'attachment; filename="inquiries.csv"'
        response["Cache-Control"] = "no-store"
        return response

    @action(detail=False, methods=["post"], url_path="demo-seed")
    def demo_seed(self, request):
        if sales_policy.enabled() and not sales_policy.access_for(request)["is_superuser"]:
            raise PermissionDenied("示例创建仅限超级管理员。")
        if not is_figma_demo_request(request):
            raise ValidationError({"demo": "仅支持 demo=figma 初始化示例数据。"})
        inquiries = seed_figma_demo_inquiries()
        return Response({"data": {"created_or_existing": len(inquiries), "inquiry_ids": [str(inquiry.pk) for inquiry in inquiries]}})

    def get_serializer_class(self):
        if self.action == "list":
            return InquiryListSerializer
        if self.action == "create":
            return InquiryCreateSerializer
        if self.action == "partial_update":
            return InquiryUpdateSerializer
        if self.action == "draft":
            return InquiryDraftSaveSerializer
        return InquiryDetailSerializer

    def destroy(self, request, *args, **kwargs):
        inquiry = self.get_object()
        require_matching_etag(request, inquiry)
        return Response({"data": permanently_delete_inquiry(inquiry)})

    @action(detail=True, methods=["get"], url_path="deletion-preview")
    def deletion_preview(self, request, pk=None):
        inquiry = self.get_object()
        return self.response_with_etag({"data": inquiry_deletion_preview(inquiry)}, inquiry)

    def _ensure_assignable_owner(self, employee):
        if not assignable_employees(self.request).filter(pk=employee.pk).exists():
            raise PermissionDenied("不能分配给该员工：员工不在当前可分配组织范围内或已离职。")

    def _ensure_owner_change_allowed(self, owner_employee, current_owner_id=None):
        if owner_employee is None and current_owner_id is None:
            return
        if getattr(owner_employee, "pk", None) == current_owner_id:
            return
        if not self.request.user.has_perm("inquiries.assign_inquiry"):
            raise PermissionDenied("指定或变更负责人需要询盘分配权限。")
        if owner_employee is not None:
            self._ensure_assignable_owner(owner_employee)

    @action(detail=False, methods=["get"])
    def options(self, request):
        from apps.reference_data.services import legacy_dictionary_groups
        grouped, _config_version = legacy_dictionary_groups(["INQUIRY_SOURCE"])
        countries = list(
            self.get_queryset()
            .exclude(customer_account__primary_country_code="")
            .order_by("customer_account__primary_country_code")
            .values_list("customer_account__primary_country_code", flat=True)
            .distinct()
        )
        return Response({"data": {
            "statuses": [{"code": code, "display_name": label} for code, label in Inquiry._meta.get_field("status").choices],
            "priorities": [{"code": code, "display_name": label} for code, label in InquiryPriority.choices],
            "sources": [
                {
                    "item_code": item["item_code"],
                    "display_name": item["display_name"],
                    "sort_order": item["sort_order"],
                }
                for item in grouped["INQUIRY_SOURCE"]
            ],
            "owner_filters": [{"id": str(employee.pk), "employee_code": employee.employee_code, "display_name": employee.display_name} for employee in employee_filter_choices(assignable_employees(request), self.get_queryset().values("owner_employee_id"))],
            "owners": [{"id": str(employee.pk), "employee_code": employee.employee_code, "display_name": employee.display_name} for employee in assignable_employees(request)],
            "countries": countries,
            "invalid_reason_codes": ["DUPLICATE", "SPAM", "UNPROCESSABLE", "OTHER"],
        }})

    @action(detail=False, methods=["get"])
    def metrics(self, request):
        from zoneinfo import ZoneInfo
        from apps.quotations.models import Quotation
        now = timezone.now()
        shanghai = ZoneInfo("Asia/Shanghai")
        local_now = now.astimezone(shanghai)
        start_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_month = start_today.replace(day=1)
        count_base = accessible_inquiries(request, "view_inquiry").filter(archived_at__isnull=True)
        if is_figma_demo_request(request):
            count_base = count_base.filter(source_system=DEMO_SOURCE_SYSTEM)
        mine = Q(owner_employee=self.actor_employee())
        unassigned = Q(owner_employee__isnull=True)
        if sales_policy.enabled():
            assignments = sales_policy.current_primary_assignments()
            mine = Q(customer_account_id__in=assignments.filter(employee=self.actor_employee()).values("customer_account_id"))
            unassigned = ~Q(customer_account_id__in=assignments.values("customer_account_id"))
        list_counts = count_base.aggregate(
            all=Count("pk", distinct=True),
            mine=Count("pk", filter=mine, distinct=True),
            unassigned=Count("pk", filter=unassigned, distinct=True),
        )
        if is_figma_demo_request(request):
            return Response({"data": {
                "timezone": "Asia/Shanghai", "due_soon_minutes": 30,
                "list_counts": list_counts,
                "today_new": 8, "today_new_delta": 2, "quote_accepted": 6, "pending_order": 4, "due_soon": 1,
                "conversion": {"numerator": 2, "denominator": 8, "rate": 25.0},
                "quoting": 1, "awaiting_customer": 1,
                "has_quotation": with_quotation_presence(self.get_queryset(), self.request).filter(has_quotation=True).count(),
            }})
        base = accessible_inquiries(request, "view_inquiry").filter(archived_at__isnull=True)
        today_new = base.filter(received_at__gte=start_today).count()
        previous_new = base.filter(received_at__gte=start_today - timedelta(days=1), received_at__lt=start_today).count()
        valid_month = base.filter(received_at__gte=start_month).exclude(status__in=["DRAFT", "CANCELLED", "CLOSED"])
        sent_quotes = Quotation.objects.filter(archived_at__isnull=True, versions__status="SENT")
        if sales_policy.enabled():
            from apps.customers.selectors import accessible_customers
            sent_quotes = sent_quotes.filter(customer_account__in=accessible_customers(request, "view_quotationversion"))
        sent_month = valid_month.filter(quotations__in=sent_quotes).distinct().count()
        valid_count = valid_month.count()
        from apps.sales_orders.models import SalesOrder

        sales_order_exists = SalesOrder.objects.filter(
            source_quotation_version__quotation__source_inquiry_id=OuterRef("pk"),
            archived_at__isnull=True,
        )
        if sales_policy.enabled():
            from apps.sales_orders.selectors import accessible_sales_orders
            sales_order_exists = sales_order_exists.filter(pk__in=accessible_sales_orders(request).values("pk"))
        quote_accepted = base.filter(status="QUOTE_ACCEPTED")
        return Response({"data": {
            "timezone": "Asia/Shanghai", "due_soon_minutes": 30,
            "list_counts": list_counts,
            "today_new": today_new, "today_new_delta": today_new - previous_new,
            "quote_accepted": quote_accepted.count(),
            "has_quotation": with_quotation_presence(base, self.request).filter(has_quotation=True).count(),
            "pending_order": quote_accepted.annotate(
                has_sales_order=Exists(sales_order_exists)
            ).filter(has_sales_order=False).count(),
            "due_soon": base.filter(due_soon_query(now), sla_links__is_current=True).distinct().count(),
            "conversion": {"numerator": sent_month, "denominator": valid_count, "rate": round(sent_month / valid_count * 100, 1) if valid_count else 0},
            "quoting": base.filter(status="QUOTING").count(), "awaiting_customer": base.filter(status="FOLLOW_UP").count(),
        }})

    @action(detail=False, methods=["get"], url_path="assignment-queue")
    def assignment_queue(self, request):
        rows = self.filter_queryset(self.get_queryset().filter(owner_employee__isnull=True, status__in=ACTIVE_INQUIRY_STATUSES).order_by("received_at", "id"))
        page = self.paginate_queryset(rows)
        data = InquiryListSerializer(page if page is not None else rows, many=True, context=self.get_serializer_context()).data
        for row, inquiry in zip(data, page if page is not None else rows):
            owners = getattr(inquiry.customer_account, "current_primary_owners", [])
            row["suggested_owner"] = {"id": str(owners[0].employee_id), "display_name": owners[0].employee.display_name} if owners else None
        return self.get_paginated_response(data) if page is not None else Response({"data": data})

    @action(detail=False, methods=["get"])
    def board(self, request):
        rows = list(self.get_queryset().filter(status__in=ACTIVE_INQUIRY_STATUSES).order_by("-received_at", "-id")[:200])
        lanes = {"PENDING_CONFIRMATION": [], "REQUIREMENTS": [], "QUOTING": [], "QUOTE_ACCEPTED": []}
        for inquiry in rows:
            demo_stage = (inquiry.source_snapshot or {}).get("figma_demo", {}).get("display_stage", {}) if is_figma_demo_request(request) else {}
            stage = demo_stage.get("code") or inquiry_display_stage(inquiry)[0]
            if stage in lanes and len(lanes[stage]) < 50:
                lanes[stage].append(inquiry)
        labels = {"PENDING_CONFIRMATION": "待确认", "REQUIREMENTS": "需求确认", "QUOTING": "报价中", "QUOTE_ACCEPTED": "报价已接受"}
        return Response({"data": {"read_only": True, "lanes": [{"code": code, "label": labels[code], "count": len(items), "cards": InquiryListSerializer(items, many=True, context=self.get_serializer_context()).data} for code, items in lanes.items()]}})

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        inquiry = self.get_object()
        serializer = InquiryAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        owner = serializer.validated_data["owner_employee"]
        self._ensure_assignable_owner(owner)
        inquiry = assign_inquiry(inquiry=inquiry, owner_employee=owner, reason=serializer.validated_data.get("reason", ""), actor_employee=self.actor_employee(), request=request)
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk), list_mode=True, request=self.request).get()
        return self.response_with_etag({"data": InquiryDetailSerializer(inquiry, context=self.get_serializer_context()).data}, inquiry)

    @extend_schema(request=InquiryPrioritySerializer, responses=InquiryListSerializer)
    @action(detail=True, methods=["post"])
    def priority(self, request, pk=None):
        inquiry = self.get_object()
        serializer = InquiryPrioritySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inquiry = set_inquiry_priority(
            inquiry=inquiry, priority=serializer.validated_data["priority"],
            actor_employee=self.actor_employee(), request=request,
        )
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk), list_mode=True, request=self.request).get()
        return self.response_with_etag({"data": InquiryListSerializer(inquiry, context=self.get_serializer_context()).data}, inquiry)

    @action(detail=True, methods=["post"], url_path="mark-invalid")
    def mark_invalid(self, request, pk=None):
        inquiry = self.get_object()
        serializer = InquiryInvalidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inquiry = mark_inquiry_invalid(
            inquiry=inquiry,
            actor_employee=self.actor_employee(),
            request=request,
            reason_code=serializer.validated_data["reason_code"],
            reason_detail=serializer.validated_data.get("reason_detail", ""),
        )
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk), list_mode=True, request=self.request).get()
        return self.response_with_etag({"data": InquiryDetailSerializer(inquiry, context=self.get_serializer_context()).data}, inquiry)

    def _bulk_rows(self, items):
        ids = [item["id"] for item in items]
        rows = list(self.get_queryset().filter(pk__in=ids).select_for_update(of=("self",)))
        if len(rows) != len(ids):
            raise PermissionDenied("部分询盘不存在或不在当前数据范围内。")
        return {str(row.pk): row for row in rows}

    @action(detail=False, methods=["post"], url_path="bulk-assign")
    def bulk_assign(self, request):
        if not sales_policy.has_permission(request, "inquiries.assign_inquiry"):
            raise PermissionDenied("批量分配还需要单笔分配权限。")
        serializer = InquiryBulkAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        owner = serializer.validated_data["owner_employee"]
        self._ensure_assignable_owner(owner)
        with transaction.atomic():
            rows = self._bulk_rows(serializer.validated_data["items"])
            for item in serializer.validated_data["items"]:
                sales_policy.require_customer(request, "inquiries.assign_inquiry", rows[str(item["id"])].customer_account)
                assign_inquiry(inquiry=rows[str(item["id"])], owner_employee=owner, reason=serializer.validated_data.get("reason", ""), actor_employee=self.actor_employee(), request=request, expected_etag=item["etag"])
        return Response({"data": {"updated": len(rows)}})

    @action(detail=False, methods=["post"], url_path="bulk-mark-invalid")
    def bulk_mark_invalid(self, request):
        serializer = InquiryBulkInvalidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            rows = self._bulk_rows(serializer.validated_data["items"])
            for item in serializer.validated_data["items"]:
                sales_policy.require_customer(request, "access_control.markinvalid_inquiry", rows[str(item["id"])].customer_account)
                mark_inquiry_invalid(inquiry=rows[str(item["id"])], actor_employee=self.actor_employee(), request=request, expected_etag=item["etag"], reason_code=serializer.validated_data["reason_code"], reason_detail=serializer.validated_data.get("reason_detail", ""))
        return Response({"data": {"updated": len(rows)}})

    def create(self, request, *args, **kwargs):
        if self.actor_employee() is None:
            raise PermissionDenied("创建询价需要绑定有效员工档案。")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            inquiry = create_inquiry(
                validated_data=dict(serializer.validated_data),
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk), request=self.request).get()
        return self.response_with_etag(
            {"data": InquiryDetailSerializer(inquiry, context=self.get_serializer_context()).data},
            inquiry,
            status.HTTP_201_CREATED,
        )

    def retrieve(self, request, *args, **kwargs):
        inquiry = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(inquiry).data}, inquiry)

    def partial_update(self, request, *args, **kwargs):
        inquiry = self.get_object()
        require_matching_etag(request, inquiry)
        serializer = self.get_serializer(inquiry, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            inquiry = update_inquiry(
                inquiry=inquiry,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk), request=self.request).get()
        return self.response_with_etag(
            {"data": InquiryDetailSerializer(inquiry, context=self.get_serializer_context()).data},
            inquiry,
        )

    @extend_schema(request=InquiryDraftSaveSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["patch"], url_path="draft")
    def draft(self, request, pk=None):
        inquiry = self.get_object()
        serializer = self.get_serializer(inquiry, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            inquiry = save_inquiry_draft(
                inquiry=inquiry,
                validated_data=dict(serializer.validated_data),
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk), request=self.request).get()
        return self.response_with_etag(
            {"data": InquiryDetailSerializer(inquiry, context=self.get_serializer_context()).data},
            inquiry,
        )

    def _transition(self, request, action_name, serializer_class=InquiryActionSerializer):
        inquiry = self.get_object()
        require_matching_etag(request, inquiry)
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data.get("note", serializer.validated_data.get("reason", ""))
        inquiry = transition_inquiry(
            inquiry=inquiry,
            action=action_name,
            note=note,
            actor_employee=self.actor_employee(),
            request=request,
        )
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk), request=self.request).get()
        return self.response_with_etag(
            {"data": InquiryDetailSerializer(inquiry, context=self.get_serializer_context()).data},
            inquiry,
        )

    @extend_schema(request=InquiryActionSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._transition(request, "SUBMITTED")

    @extend_schema(request=InquiryActionSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        return self._transition(request, "STARTED")

    @extend_schema(request=InquiryCommunicationSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"])
    def respond(self, request, pk=None):
        inquiry = self.get_object()
        serializer = InquiryCommunicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inquiry, _communication = record_inquiry_communication(
            inquiry=inquiry,
            actor_employee=self.actor_employee(),
            request=request,
            is_first_response=True,
            **serializer.validated_data,
        )
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk), request=self.request).get()
        return self.response_with_etag(
            {"data": InquiryDetailSerializer(inquiry, context=self.get_serializer_context()).data},
            inquiry,
        )

    @extend_schema(request=InquiryContactAttachSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"], url_path="attach-contact")
    def attach_contact(self, request, pk=None):
        inquiry = self.get_object()
        serializer = InquiryContactAttachSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "inquiry": inquiry},
        )
        serializer.is_valid(raise_exception=True)
        inquiry = attach_inquiry_contact(
            inquiry=inquiry,
            actor_employee=self.actor_employee(),
            request=request,
            **serializer.validated_data,
        )
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk), request=self.request).get()
        return self.response_with_etag(
            {"data": InquiryDetailSerializer(inquiry, context=self.get_serializer_context()).data},
            inquiry,
        )

    @extend_schema(request=InquiryActionSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"], url_path="confirm-requirements")
    def confirm_requirements(self, request, pk=None):
        return self._transition(request, "CONFIRMED_REQUIREMENTS")

    @extend_schema(request=InquiryActionSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"], url_path="sync-quotation")
    def sync_quotation(self, request, pk=None):
        return self._transition(request, "SYNCED_QUOTATION")

    @extend_schema(request=InquiryActionSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"], url_path="mark-quoted")
    def mark_quoted(self, request, pk=None):
        return self._transition(request, "MARKED_QUOTED")

    @extend_schema(request=InquiryCommunicationSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"], url_path="follow-up")
    def follow_up(self, request, pk=None):
        inquiry = self.get_object()
        serializer = InquiryCommunicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inquiry, _communication = record_inquiry_communication(
            inquiry=inquiry,
            actor_employee=self.actor_employee(),
            request=request,
            is_first_response=False,
            **serializer.validated_data,
        )
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk), request=self.request).get()
        return self.response_with_etag(
            {"data": InquiryDetailSerializer(inquiry, context=self.get_serializer_context()).data},
            inquiry,
        )

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        inquiry = self.get_object()
        communication_ids = inquiry.communication_links.values_list("communication_id", flat=True)
        sample_ids = inquiry.sample_requests.filter(archived_at__isnull=True).values_list("pk", flat=True)
        quotation_ids = inquiry.quotations.filter(archived_at__isnull=True).values_list("pk", flat=True)
        from apps.sales_orders.models import SalesOrder

        sales_order_ids = SalesOrder.objects.filter(
            source_quotation_version__quotation_id__in=quotation_ids,
            archived_at__isnull=True,
        ).values_list("pk", flat=True)
        events = CustomerTimelineEvent.objects.filter(customer_account_id=inquiry.customer_account_id).filter(
            Q(source_type="INQUIRY", source_id=inquiry.pk)
            | Q(source_type="CUSTOMER_COMMUNICATION", source_id__in=communication_ids)
            | Q(source_type="QUOTATION", source_id__in=quotation_ids)
            | Q(source_type="SAMPLE_REQUEST", source_id__in=sample_ids)
            | Q(source_type="SALES_ORDER", source_id__in=sales_order_ids)
        ).order_by("-occurred_at", "-id")
        events = filter_activity(events, request)
        page = self.paginate_queryset(events)
        rows = page if page is not None else events
        data = [
            {
                "id": str(event.pk),
                "event_type": event.event_type,
                "source_type": event.source_type,
                "source_id": str(event.source_id),
                "title": event.title,
                "summary": event.summary,
                "occurred_at": event.occurred_at,
                "event_data": event.event_data,
            }
            for event in rows
        ]
        return self.get_paginated_response(data) if page is not None else Response({"data": data})

    @extend_schema(request=InquiryReasonSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"], url_path="mark-lost")
    def mark_lost(self, request, pk=None):
        return self._transition(request, "MARKED_LOST", InquiryReasonSerializer)

    @extend_schema(request=InquiryReasonSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        return self._transition(request, "CLOSED", InquiryReasonSerializer)

    @extend_schema(request=InquiryReasonSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._transition(request, "CANCELLED", InquiryReasonSerializer)

    @extend_schema(
        methods=["GET"],
        responses=InquiryItemSerializer(many=True),
    )
    @extend_schema(
        methods=["POST"],
        request=InquiryItemSerializer,
        responses=InquiryItemSerializer,
    )
    @action(detail=True, methods=["get", "post"])
    def items(self, request, pk=None):
        inquiry = self.get_object()
        if request.method == "GET":
            items = inquiry.items.select_related(
                "product",
                "product_category",
                "product_unit",
                "product_color",
                "product_image",
            ).all()
            response = self.response_with_etag(
                {"data": InquiryItemSerializer(items, many=True).data},
                inquiry,
            )
            return response
        require_matching_etag(request, inquiry)
        serializer = InquiryItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item, inquiry = create_inquiry_item(
                inquiry=inquiry,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return self.response_with_etag(
            {"data": InquiryItemSerializer(item).data},
            inquiry,
            status.HTTP_201_CREATED,
        )

    @extend_schema(
        methods=["GET"],
        responses=InquiryFileLinkSerializer(many=True),
    )
    @extend_schema(
        methods=["POST"],
        request=InquiryFileLinkCreateSerializer,
        responses=InquiryFileLinkSerializer,
    )
    @action(detail=True, methods=["get", "post"])
    def files(self, request, pk=None):
        inquiry = self.get_object()
        if request.method == "GET":
            return self.response_with_etag(
                {"data": InquiryFileLinkSerializer(inquiry.file_links.all(), many=True).data},
                inquiry,
            )
        require_matching_etag(request, inquiry)
        serializer = InquiryFileLinkCreateSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "inquiry": inquiry},
        )
        serializer.is_valid(raise_exception=True)
        try:
            link, inquiry = link_inquiry_file(
                inquiry=inquiry,
                actor_employee=self.actor_employee(),
                request=request,
                **serializer.validated_data,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        link = inquiry.file_links.select_related("business_file").get(pk=link.pk)
        return self.response_with_etag(
            {"data": InquiryFileLinkSerializer(link).data},
            inquiry,
            status.HTTP_201_CREATED,
        )

    @staticmethod
    def _download_path(business_file):
        if business_file.scan_status not in USABLE_FILE_SCAN_STATUSES:
            raise ValidationError({"detail": "附件尚未通过安全扫描，暂时无法下载。"})
        root = Path(settings.MEDIA_ROOT).resolve()
        path = (root / business_file.storage_key).resolve()
        if root not in path.parents or not path.is_file():
            raise Http404("附件文件不存在。")
        return path

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"], url_path=r"files/(?P<file_id>[0-9a-f-]{36})/download")
    def download_file(self, request, pk=None, file_id=None):
        inquiry = self.get_object()
        link = inquiry.file_links.select_related("business_file").filter(
            business_file_id=file_id, business_file__archived_at__isnull=True,
        ).first()
        if link is None:
            raise Http404("未找到可访问的附件。")
        path = self._download_path(link.business_file)
        try:
            stream = path.open("rb")
        except OSError as exc:
            raise Http404("附件暂时无法读取。") from exc
        response = FileResponse(stream, as_attachment=True, filename=link.business_file.original_name, content_type="application/octet-stream")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @extend_schema(responses={(200, "application/zip"): bytes})
    @action(detail=True, methods=["get"], url_path="files-download")
    def download_files(self, request, pk=None):
        inquiry = self.get_object()
        links = list(inquiry.file_links.select_related("business_file").filter(
            business_file__archived_at__isnull=True,
        ).order_by("created_at", "id")[:101])
        if not links:
            raise ValidationError({"detail": "暂无可下载附件。"})
        if len(links) > 100:
            raise ValidationError({"detail": "附件超过 100 个，请逐个下载。"})
        paths = [(link.business_file, self._download_path(link.business_file)) for link in links]
        archive = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
        try:
            with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
                total = 0
                for index, (business_file, path) in enumerate(paths, 1):
                    # 逐块限制实际读取量；使用序号和纯文件名，避免同名覆盖或压缩包路径穿越。
                    filename = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', business_file.original_name).strip(' .')[:180] or '附件'
                    with path.open("rb") as source, bundle.open(f"{index:03d}_{filename}", "w") as target:
                        while chunk := source.read(1024 * 1024):
                            total += len(chunk)
                            if total > 100 * 1024 * 1024:
                                raise ValidationError({"detail": "附件合计超过 100 MB，请逐个下载。"})
                            target.write(chunk)
            archive.seek(0)
        except OSError as exc:
            archive.close()
            raise Http404("部分附件暂时无法读取，请刷新后重试。") from exc
        except Exception:
            archive.close()
            raise
        response = FileResponse(archive, as_attachment=True, filename=f"{inquiry.inquiry_number}_附件.zip", content_type="application/zip")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @extend_schema(request=InquiryAttachmentUploadSerializer, responses=InquiryFileLinkSerializer)
    @action(detail=True, methods=["post"], url_path="attachments")
    def upload_attachment(self, request, pk=None):
        if not request.user.has_perm("inquiries.change_inquiry"):
            raise PermissionDenied("当前账号没有编辑询盘权限。")
        actor = self.actor_employee()
        if actor is None:
            raise PermissionDenied("上传附件需要关联有效员工。")
        inquiry = self.get_object()
        sales_policy.require_customer(request, "inquiries.change_inquiry", inquiry.customer_account)
        serializer = InquiryAttachmentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        link, inquiry = upload_inquiry_attachment(
            inquiry=inquiry, uploaded_file=serializer.validated_data["file"],
            upload_id=serializer.validated_data["upload_id"], actor_employee=actor, request=request,
        )
        return self.response_with_etag({"data": InquiryFileLinkSerializer(link).data}, inquiry)

    @extend_schema(request=InquiryWangImageUploadSerializer)
    @action(detail=True, methods=["post"], url_path="images")
    def wang_image_upload(self, request, pk=None):
        inquiry = self.get_object()
        business_file = None
        try:
            actor = self.actor_employee()
            if actor is None:
                raise PermissionDenied("上传沟通图片需要绑定有效员工档案。")
            require_matching_etag(request, inquiry)
            serializer = InquiryWangImageUploadSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            business_file = save_scanned_image(
                serializer.validated_data["file"],
                actor,
                storage_folder=f"inquiries/{inquiry.pk}",
                field_label="沟通图片",
            )
            _link, inquiry = link_inquiry_file(
                inquiry=inquiry,
                business_file=business_file,
                file_role="COMMUNICATION_IMAGE",
                actor_employee=actor,
                request=request,
            )
        except APIException as exc:
            if business_file is not None:
                self._remove_orphaned_image(business_file)
            return Response(
                {"errno": 1, "message": self._wang_upload_error_message(exc)},
                status=status.HTTP_200_OK,
            )
        except IntegrityError as exc:
            if business_file is not None:
                self._remove_orphaned_image(business_file)
            return Response(
                {"errno": 1, "message": "图片关联失败，请刷新后重试。"},
                status=status.HTTP_200_OK,
            )

        source = f"/api/v1/inquiries/{inquiry.pk}/images/{business_file.pk}/"
        response = self.response_with_etag(
            {
                "errno": 0,
                "data": {
                    "url": source,
                    "alt": business_file.original_name,
                },
            },
            inquiry,
        )
        response.data["data"]["etag"] = response["ETag"]
        return response

    @action(detail=True, methods=["get"], url_path=r"images/(?P<file_id>[0-9a-f-]{36})")
    def image(self, request, pk=None, file_id=None):
        inquiry = self.get_object()
        link = inquiry.file_links.select_related("business_file").filter(
            business_file_id=file_id,
            business_file__archived_at__isnull=True,
            business_file__scan_status__in=USABLE_FILE_SCAN_STATUSES,
            business_file__content_type__startswith="image/",
        ).first()
        if link is None:
            raise Http404("未找到可访问的沟通图片。")

        storage_root = Path(settings.MEDIA_ROOT).resolve()
        file_path = (storage_root / link.business_file.storage_key).resolve()
        if storage_root not in file_path.parents or not file_path.is_file():
            raise Http404("沟通图片文件不存在。")
        response = FileResponse(
            file_path.open("rb"),
            as_attachment=False,
            filename=link.business_file.original_name,
            content_type=link.business_file.content_type,
        )
        response["Cache-Control"] = "private, max-age=300"
        return response

    @staticmethod
    def _remove_orphaned_image(business_file):
        storage_root = Path(settings.MEDIA_ROOT).resolve()
        file_path = (storage_root / business_file.storage_key).resolve()
        business_file.delete()
        if storage_root in file_path.parents:
            file_path.unlink(missing_ok=True)

    @staticmethod
    def _wang_upload_error_message(exc):
        detail = getattr(exc, "detail", exc)
        while isinstance(detail, (list, tuple)) and detail:
            detail = detail[0]
        if isinstance(detail, dict):
            detail = next(iter(detail.values()), "图片上传失败，请稍后重试。")
            while isinstance(detail, (list, tuple)) and detail:
                detail = detail[0]
        return str(detail or "图片上传失败，请稍后重试。")

    @extend_schema(responses=TaskListSerializer(many=True))
    @action(detail=True, methods=["get"])
    def tasks(self, request, pk=None):
        inquiry = self.get_object()
        task_ids = inquiry.task_links.values_list("business_task_id", flat=True)
        from apps.workflow.selectors import accessible_tasks
        tasks = tasks_with_context(accessible_tasks(request, scope="ANY_ACCESS")).filter(pk__in=task_ids, archived_at__isnull=True)
        return Response({"data": TaskListSerializer(tasks, many=True).data})


class InquiryItemViewSet(
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    http_method_names = ["get", "post", "patch", "delete", "options"]
    serializer_class = InquiryItemUpdateSerializer
    action_permission_map = {
        "partial_update": "inquiries.change_inquiryitem",
        "destroy": "inquiries.delete_inquiryitem",
        "product_image.GET": "inquiries.view_inquiryitem",
        "product_image.POST": "inquiries.change_inquiryitem",
        "product_image.DELETE": "inquiries.change_inquiryitem",
    }

    def get_queryset(self):
        permission = self.action_permission_codename("change_inquiryitem")
        inquiries = accessible_inquiries(self.request, permission).filter(
            archived_at__isnull=True,
            customer_account__archived_at__isnull=True,
        )
        return InquiryItem.objects.filter(inquiry__in=inquiries).select_related(
            "inquiry",
            "inquiry__customer_account",
            "product",
            "product_category",
            "product_unit",
            "product_color",
            "product_image",
        )

    def partial_update(self, request, *args, **kwargs):
        item = self.get_object()
        require_matching_etag(request, item.inquiry)
        serializer = self.get_serializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            item, inquiry = update_inquiry_item(
                item=item,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return self.response_with_etag({"data": InquiryItemSerializer(item).data}, inquiry)

    def destroy(self, request, *args, **kwargs):
        item = self.get_object()
        require_matching_etag(request, item.inquiry)
        inquiry = delete_inquiry_item(
            item=item,
            actor_employee=self.actor_employee(),
            request=request,
        )
        response = Response(status=status.HTTP_204_NO_CONTENT)
        from apps.core.api.concurrency import etag_for_instance

        response["ETag"] = etag_for_instance(inquiry)
        return response

    @extend_schema(methods=["POST"], request=InquiryProductImageUploadSerializer, responses=InquiryItemSerializer)
    @extend_schema(methods=["GET"], responses=OpenApiTypes.BINARY)
    @extend_schema(methods=["DELETE"], request=None, responses=InquiryItemSerializer)
    @action(detail=True, methods=["get", "post", "delete"], url_path="product-image")
    def product_image(self, request, pk=None):
        item = self.get_object()
        image = item.product_image
        if request.method == "GET":
            if image is None or image.archived_at is not None:
                raise Http404("当前产品明细没有产品图片。")
            if image.scan_status not in USABLE_FILE_SCAN_STATUSES:
                raise ValidationError({"detail": "图片尚未通过安全扫描，暂时无法查看。"})
            path = (Path(settings.MEDIA_ROOT) / image.storage_key).resolve()
            root = Path(settings.MEDIA_ROOT).resolve()
            if root not in path.parents or not path.is_file():
                raise Http404("产品图片文件不存在。")
            response = FileResponse(path.open("rb"), content_type=image.content_type)
            response["Cache-Control"] = "private, no-store"
            response["X-Content-Type-Options"] = "nosniff"
            return response

        if request.method == "DELETE":
            inquiry = remove_inquiry_item_product_image(
                item=item,
                actor_employee=self.actor_employee(),
                request=request,
            )
            updated = InquiryItem.objects.select_related("product_image").get(pk=item.pk)
            return self.response_with_etag({"data": InquiryItemSerializer(updated).data}, inquiry)

        image_file = request.FILES.get("file")
        if image_file is None:
            return Response({"file": ["请选择产品图片。"]}, status=status.HTTP_400_BAD_REQUEST)
        business_file = None
        try:
            business_file = save_inquiry_product_image(
                image_file,
                self.actor_employee(),
                item.inquiry_id,
            )
            updated, inquiry = set_inquiry_item_product_image(
                item=item,
                business_file=business_file,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except Exception:
            if business_file is not None:
                path = Path(settings.MEDIA_ROOT) / business_file.storage_key
                path.unlink(missing_ok=True)
                business_file.delete()
            raise
        return self.response_with_etag({"data": InquiryItemSerializer(updated).data}, inquiry)
