from apps.access_control import sales_policy
from django.db import IntegrityError, transaction
import uuid
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from datetime import timedelta
from collections import defaultdict
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.db.models import Count, OuterRef, Prefetch, Subquery
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from rest_framework import filters, mixins, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response
from openpyxl import Workbook

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.inquiries.images import inquiry_reference_images
from apps.files.models import USABLE_FILE_SCAN_STATUSES
from rest_framework import serializers
from apps.customers.hard_delete import permanently_delete_quotation
from apps.customers.api.views import CustomerApiViewSetBase
from apps.customers.models import CustomerTransactionEntity
from apps.customers.selectors import accessible_customers
from apps.inquiries.models import Inquiry, InquiryStatus, format_inquiry_item_specification
from apps.workflow.api.serializers import TaskListSerializer
from apps.workflow.selectors import tasks_with_context

from ..models import (
    Quotation,
    QuotationContainerConfig,
    QuotationContainerTier,
    QuotationEmailDispatchAttempt,
    QuotationLine,
    QuotationTemplate,
    QuotationVersion,
    QuotationVersionStatus,
)
from ..formal_quotation import build_formal_quotation_pdf
from ..selectors import accessible_quotations, quotations_with_context, versions_with_context
from ..services import (
    create_line,
    create_quotation_draft,
    create_quotation_from_inquiry,
    create_quotation,
    create_tier,
    create_container_tier,
    create_version,
    delete_line,
    delete_container_tier,
    create_sample_invoice_document,
    create_generated_formal_document,
    confirm_manual_dispatch,
    dispatch_version,
    email_dispatch_version,
    issue_version,
    lock_version,
    mark_stale_email_attempts_uncertain,
    register_formal_document,
    resolve_email_dispatch_attempt,
    replace_price_matrix,
    remove_line_product_image,
    set_line_product_image,
    simulate_dispatch_version,
    sync_quotation_line_to_inquiry,
    submit_version_approval,
    transition_quotation,
    update_line,
    upsert_line_packaging,
    update_quotation,
    update_version,
    void_version,
)
from .filters import QuotationFilter
from .image_serializers import QuotationInquiryImageSerializer, QuotationProductImageInputSerializer
from .serializers import (
    EmptyActionSerializer,
    QuotationAcceptSerializer,
    QuotationApprovalSubmitSerializer,
    QuotationCreateSerializer,
    QuotationContainerConfigSerializer,
    QuotationContainerTierSerializer,
    QuotationDraftCreateSerializer,
    InquiryQuotationCreateSerializer,
    QuotationDetailSerializer,
    QuotationDispatchCreateSerializer,
    QuotationDispatchSerializer,
    QuotationEmailAttemptResolutionSerializer,
    QuotationEmailDispatchAttemptSerializer,
    QuotationDocumentCreateSerializer,
    QuotationDocumentSerializer,
    QuotationLineSerializer,
    QuotationLineSyncInquirySerializer,
    QuotationLineSyncInquiryResponseSerializer,
    QuotationLinePackagingSerializer,
    QuotationPriceMatrixSerializer,
    QuotationLineUpdateSerializer,
    QuotationListSerializer,
    QuotationLockSerializer,
    QuotationQuantityTierSerializer,
    QuotationReasonSerializer,
    QuotationManualDispatchSerializer,
    QuotationEmailDispatchSerializer,
    QuotationSimulatedDispatchSerializer,
    QuotationTemplateSerializer,
    QuotationTemplateSellerProfileSerializer,
    QuotationUpdateSerializer,
    QuotationVersionCreateSerializer,
    QuotationVersionDetailSerializer,
    QuotationVersionListSerializer,
    QuotationVersionUpdateSerializer,
)
from ..sample_invoice import SampleInvoiceTemplateError, build_formal_quotation_xlsx, build_sample_invoice
from ..uploads import save_quotation_formal_document, save_quotation_product_image


class QuotationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = QuotationDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = QuotationFilter
    search_fields = ["quotation_number", "subject", "customer_account__account_name"]
    ordering_fields = ["created_at", "updated_at", "quotation_number"]
    ordering = ["-updated_at", "-id"]
    sales_action_permission_map = {"export": "quotations.view_quotation", "lose": "access_control.lose_quotation", "cancel": "access_control.cancel_quotation"}
    action_permission_map = {
        "list": "quotations.view_quotation",
        "summary": "quotations.view_quotation",
        "options": "quotations.view_quotation",
        "creation_options": "quotations.add_quotation",
        "inquiry_context": "quotations.add_quotation",
        "create_from_inquiry": "quotations.add_quotation",
        "export": "quotations.export_quotation",
        "retrieve": "quotations.view_quotation",
        "create": "quotations.add_quotation",
        "destroy": "quotations.delete_quotation",
        "create_draft": "quotations.add_quotation",
        "partial_update": "quotations.change_quotation",
        "versions.GET": "quotations.view_quotationversion",
        "versions.POST": "quotations.add_quotationversion",
        "accept": "quotations.accept_quotation",
        "lose": "quotations.change_quotation",
        "cancel": "quotations.change_quotation",
        "price_history": "quotations.view_quotation",
        "inquiry_images": "quotations.view_quotation",
    }

    @extend_schema(responses=QuotationInquiryImageSerializer(many=True))
    @action(detail=True, methods=['get'], url_path='inquiry-images')
    def inquiry_images(self, request, pk=None):
        quotation = self.get_object()
        images = inquiry_reference_images(quotation.source_inquiry_id, request) if quotation.source_inquiry_id else []
        return Response({'data': [{'id': str(image.pk), 'name': image.original_name,
                                  'url': f'/api/v1/inquiries/{quotation.source_inquiry_id}/images/{image.pk}/'} for image in images]})

    def get_queryset(self):
        permission = self.action_permission_codename("view_quotation")
        queryset = accessible_quotations(self.request, permission)
        if self.request.method not in SAFE_METHODS:
            queryset = queryset.filter(
                archived_at__isnull=True,
                customer_account__archived_at__isnull=True,
            )
        elif self.request.query_params.get("archived", "false").lower() != "all":
            archived = self.request.query_params.get("archived", "false").lower()
            queryset = queryset.filter(archived_at__isnull=archived != "true")
        latest_versions = QuotationVersion.objects.filter(quotation_id=OuterRef("pk")).order_by("-version_number")
        queryset = queryset.annotate(
            latest_version_status=Subquery(latest_versions.values("status")[:1]),
            latest_version_valid_until=Subquery(latest_versions.values("valid_until")[:1]),
            latest_version_currency=Subquery(latest_versions.values("currency_code")[:1]),
        )
        return quotations_with_context(queryset).distinct()

    def destroy(self, request, *args, **kwargs):
        quotation = self.get_object()
        require_matching_etag(request, quotation)
        return Response({"data": permanently_delete_quotation(quotation)})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """报价列表统计必须基于完整可见范围，不能从当前分页结果计算。"""
        queryset = self.filter_queryset(self.get_queryset())
        today = timezone.localdate()
        open_quotations = queryset.filter(outcome_status="OPEN")
        version_statuses = open_quotations.values("latest_version_status").annotate(total=Count("id"))
        by_version_status = {item["latest_version_status"]: item["total"] for item in version_statuses}
        expiring = queryset.filter(
            latest_version_valid_until__gte=today,
            latest_version_valid_until__lte=today + timedelta(days=7),
            outcome_status="OPEN",
        ).count()
        return Response({"data": {
            "all": queryset.count(),
            "draft": by_version_status.get("DRAFT", 0),
            "ready_to_send": by_version_status.get("ISSUED", 0),
            "sent": by_version_status.get("SENT", 0),
            "accepted": queryset.filter(outcome_status="WON").count(),
            "expiring_within_7_days": expiring,
        }})

    @action(detail=False, methods=["get"])
    def options(self, request):
        queryset = self.get_queryset()
        currencies = sorted({value for value in queryset.values_list("latest_version_currency", flat=True) if value})
        owners = queryset.filter(owner_employee_id__isnull=False).values(
            "owner_employee_id", "owner_employee__employee_code", "owner_employee__display_name"
        ).distinct()
        return Response({"data": {
            "outcome_statuses": [{"value": value, "label": label} for value, label in Quotation._meta.get_field("outcome_status").choices],
            "display_statuses": [
                {"value": "DRAFT", "label": "草稿"},
                {"value": "LOCKED", "label": "已锁定"},
                {"value": "READY_TO_SEND", "label": "待发送"},
                {"value": "SENT", "label": "已发送"},
                {"value": "ACCEPTED", "label": "已接受"},
                {"value": "EXPIRED", "label": "已过期"},
                {"value": "REJECTED", "label": "已失单"},
            ],
            "currencies": [{"value": code, "label": code} for code in currencies],
            "owners": [
                {"id": str(owner["owner_employee_id"]), "employee_code": owner["owner_employee__employee_code"], "display_name": owner["owner_employee__display_name"]}
                for owner in owners
            ],
        }})

    @action(detail=False, methods=["get"], url_path="price-history")
    def price_history(self, request):
        """仅返回当前用户可见范围内的真实报价快照，不混入订单或成交价格。"""
        quotations = self.get_queryset().filter(archived_at__isnull=True)
        customer_id = request.query_params.get("customer_account_id")
        product = (request.query_params.get("product") or "").strip()
        container_type = (request.query_params.get("container_type_code") or "").strip()
        currency_code = (request.query_params.get("currency_code") or "").strip().upper()
        try:
            period_months = int(request.query_params.get("period_months", "12"))
        except ValueError:
            period_months = 12
        period_months = period_months if period_months in {3, 6, 12, 24} else 12
        if customer_id:
            quotations = quotations.filter(customer_account_id=customer_id)

        option_quotations = self.get_queryset().filter(archived_at__isnull=True)
        formal_statuses = ["ISSUED", "SENT", "SUPERSEDED"]
        option_versions = versions_with_context(
            QuotationVersion.objects.filter(
                quotation__in=option_quotations,
                quotation__archived_at__isnull=True,
                status__in=formal_statuses,
            )
        )
        customers = list(option_quotations.order_by("customer_account__account_name", "id").values(
            "customer_account_id", "customer_account__account_name"
        ).distinct())
        all_lines = [line for version in option_versions for line in version.lines.all()]
        product_options = sorted({line.product_description_snapshot for line in all_lines if line.product_description_snapshot})
        container_options = sorted({
            tier.container_type_code
            for line in all_lines
            for tier in line.container_tiers.all()
        })
        currency_options = sorted({version.currency_code for version in option_versions if version.currency_code})

        cutoff = timezone.now() - timedelta(days=period_months * 31)
        versions = versions_with_context(
            QuotationVersion.objects.filter(
                quotation__in=quotations,
                quotation__archived_at__isnull=True,
                updated_at__gte=cutoff,
                status__in=formal_statuses,
            ).order_by("-updated_at", "-id")[:1000]
        )
        records = []
        for version in versions:
            if currency_code and version.currency_code != currency_code:
                continue
            terms = version.terms_snapshot if isinstance(version.terms_snapshot, dict) else {}
            for line in version.lines.all():
                if line.unit_price is None:
                    continue
                if product and line.product_description_snapshot != product:
                    continue
                tier_codes = sorted({tier.container_type_code for tier in line.container_tiers.all()})
                if container_type and container_type not in tier_codes:
                    continue
                records.append({
                    "quotation_id": str(version.quotation_id),
                    "version_id": str(version.pk),
                    "date": (version.issued_at or version.updated_at).date().isoformat(),
                    "version_number": version.version_number,
                    "customer_id": str(version.quotation.customer_account_id),
                    "customer_name": version.quotation.customer_account.account_name,
                    "product": line.product_description_snapshot,
                    "container_types": tier_codes,
                    "quantity": str(line.quantity),
                    "unit_code": line.unit_code,
                    "unit_price": str(line.unit_price),
                    "currency_code": version.currency_code,
                    "incoterm": terms.get("incoterm_label") or terms.get("incoterm_code") or "未填写",
                    "status": version.status,
                    "status_label": version.get_status_display(),
                })
        records.sort(key=lambda item: item["date"], reverse=True)
        unit_codes = sorted({item["unit_code"] for item in records})
        record_currencies = sorted({item["currency_code"] for item in records})
        calculation_warning = ""
        if len(record_currencies) > 1:
            calculation_warning = "当前筛选包含多个币种，请先选择单一币种后再计算趋势。"
        elif len(unit_codes) > 1:
            calculation_warning = "当前筛选包含多个计量单位，请缩小到同一单位后再计算趋势。"
        prices = [] if calculation_warning else [Decimal(item["unit_price"]) for item in records]
        latest = prices[0] if prices else None
        average = sum(prices) / len(prices) if prices else None
        minimum = min(prices) if prices else None
        maximum = max(prices) if prices else None
        volatility = ((maximum - minimum) / average * Decimal("100")) if average else None
        series = defaultdict(list)
        if not calculation_warning:
            for record in reversed(records):
                keys = [container_type] if container_type else (record["container_types"] or ["未配置"])
                for key in keys:
                    series[key].append({"date": record["date"], "unit_price": record["unit_price"]})
        return Response({"data": {
            "source_label": "真实报价快照，不含订单成交、成本或市场价格",
            "calculation_warning": calculation_warning,
            "unit_codes": unit_codes,
            "filters": {
                "customers": [{"value": str(item["customer_account_id"]), "label": item["customer_account__account_name"]} for item in customers],
                "products": [{"value": item, "label": item} for item in product_options],
                "container_types": [{"value": item, "label": item} for item in container_options],
                "currencies": [{"value": item, "label": item} for item in currency_options],
                "periods": [{"value": value, "label": f"近 {value} 个月"} for value in [3, 6, 12, 24]],
            },
            "metrics": {
                "latest_quote_price": str(latest) if latest is not None else None,
                "minimum_quote_price": str(minimum) if minimum is not None else None,
                "average_quote_price": str(average.quantize(Decimal("0.0001"))) if average is not None else None,
                "price_volatility_percent": str(volatility.quantize(Decimal("0.01"))) if volatility is not None else None,
            },
            "series": [{"name": name, "points": points} for name, points in sorted(series.items())],
            "records": records[:300],
        }})

    @action(detail=False, methods=["get"], url_path="creation-options")
    def creation_options(self, request):
        """新建报价只暴露当前用户可创建且具备有效交易主体的客户。"""
        customers = accessible_customers(request, "add_quotation").filter(
            archived_at__isnull=True,
        ).prefetch_related(Prefetch(
            "transaction_entities",
            queryset=CustomerTransactionEntity.objects.filter(archived_at__isnull=True).order_by("entity_code", "id"),
        )).order_by("account_name", "id")
        data = []
        for customer in customers:
            entities = list(customer.transaction_entities.all())
            if not entities:
                continue
            data.append({
                "id": str(customer.pk),
                "account_name": customer.account_name,
                "account_code": customer.account_code,
                "entities": [
                    {"id": str(entity.pk), "entity_code": entity.entity_code, "legal_name": entity.legal_name}
                    for entity in entities
                ],
            })
        return Response({"data": data})

    @action(detail=False, methods=["get"], url_path="inquiry-context")
    def inquiry_context(self, request):
        inquiry_id = request.query_params.get("inquiry_id")
        if not inquiry_id:
            return Response({"error": {"message": "缺少 inquiry_id。"}}, status=status.HTTP_400_BAD_REQUEST)
        allowed = accessible_customers(request, "add_quotation").filter(archived_at__isnull=True)
        inquiry = Inquiry.objects.filter(customer_account__in=accessible_customers(request, "view_inquiry")).filter(pk=inquiry_id, customer_account__in=allowed, archived_at__isnull=True).select_related(
            "customer_account", "transaction_entity", "owner_employee"
        ).prefetch_related("items", "quotations__versions").first()
        if inquiry is None:
            raise PermissionDenied("询盘不存在或您没有创建报价权限。")
        currencies = {item.target_currency_code for item in inquiry.items.all() if item.target_currency_code}
        existing_quotes = [
            {
                "id": str(quotation.pk), "quotation_number": quotation.quotation_number, "subject": quotation.subject,
                "status": quotation.versions.order_by("-version_number").first().status if quotation.versions.exists() else "DRAFT",
            }
            for quotation in inquiry.quotations.filter(customer_account__in=accessible_customers(request, "view_quotation"), archived_at__isnull=True, outcome_status="OPEN")
        ]
        entity_options = list(CustomerTransactionEntity.objects.filter(
            customer_account=inquiry.customer_account, archived_at__isnull=True
        ).values("id", "entity_code", "legal_name", "registration_country_code"))
        return self.response_with_etag({"data": {
            "inquiry": {
                "id": str(inquiry.pk), "inquiry_number": inquiry.inquiry_number, "subject": inquiry.subject,
                "status": inquiry.status, "status_label": inquiry.get_status_display(),
                "customer_id": str(inquiry.customer_account_id), "customer_name": inquiry.customer_account.account_name,
                "owner_name": inquiry.owner_employee.display_name if inquiry.owner_employee else "未分配",
                "items": [{"id": str(item.pk), "product_description": item.product_description, "specification": format_inquiry_item_specification(item.specification, item.color, item.material),
                           "color": item.color, "quantity": str(item.quantity), "unit_code": item.unit_code, "target_currency_code": item.target_currency_code}
                          for item in inquiry.items.all()],
            },
            "preflight": [
                {"code": "ITEMS", "label": "核心产品需求已填写", "passed": inquiry.items.exists()},
                {"code": "CUSTOMER", "label": "客户已关联", "passed": bool(inquiry.customer_account_id)},
                {"code": "OWNER", "label": "询盘负责人已分配", "passed": bool(inquiry.owner_employee_id)},
            ],
            "entities": [{**entity, "id": str(entity["id"])} for entity in entity_options],
            "requires_entity": not bool(entity_options or inquiry.transaction_entity_id),
            "can_create_entity": request.user.has_perm("customers.add_customertransactionentity"),
            "default_subject": inquiry.subject,
            "default_currency_code": next(iter(currencies)) if len(currencies) == 1 else "",
            "existing_quotations": existing_quotes,
            "allowed": {"create_quote": inquiry.status in {InquiryStatus.READY_FOR_QUOTE, InquiryStatus.QUOTING}},
        }}, inquiry)

    @action(detail=False, methods=["get"])
    def export(self, request):
        """导出仅含列表摘要，且始终按当前用户的客户数据范围过滤。"""
        queryset = self.filter_queryset(self.get_queryset())
        if queryset.count() > 5000:
            return Response(
                {"error": {"message": "单次最多导出 5000 条，请缩小筛选范围后重试。"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serialized_rows = QuotationListSerializer(
            queryset[:5000], many=True, context=self.get_serializer_context()
        ).data
        workbook = Workbook(write_only=True)
        worksheet = workbook.create_sheet("报价列表")
        worksheet.append(["报价编号", "客户名称", "版本", "币种", "贸易条款", "负责人", "最近更新", "有效期", "报价金额", "状态"])

        def export_text(value):
            if value is None:
                return ""
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            value = str(value)
            return f"'{value}" if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value

        for row in serialized_rows:
            version = row.get("current_version") or {}
            worksheet.append([
                export_text(row["quotation_number"]), export_text(row["customer_name"]),
                f"V{version['version_number']}" if version else "",
                export_text(version.get("currency_code", "")), export_text(version.get("incoterm_label", "")),
                export_text((row.get("owner") or {}).get("display_name", "")),
                export_text(version.get("updated_at") or row["updated_at"]), export_text(version.get("valid_until", "")),
                export_text(f"{version.get('currency_code', '')} {version.get('total_amount', '')}".strip()),
                export_text(row["display_status_label"]),
            ])
        output = BytesIO()
        workbook.save(output)
        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="quotations.xlsx"'
        return response

    def get_serializer_class(self):
        if self.action == "list":
            return QuotationListSerializer
        if self.action == "create":
            return QuotationCreateSerializer
        if self.action == "partial_update":
            return QuotationUpdateSerializer
        return QuotationDetailSerializer

    def create(self, request, *args, **kwargs):
        if self.actor_employee() is None:
            raise PermissionDenied("创建报价需要绑定有效员工档案。")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            quotation = create_quotation(
                validated_data=dict(serializer.validated_data),
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        quotation = quotations_with_context(Quotation.objects.filter(pk=quotation.pk)).get()
        return self.response_with_etag(
            {"data": QuotationDetailSerializer(quotation, context=self.get_serializer_context()).data},
            quotation,
            status.HTTP_201_CREATED,
        )

    @extend_schema(request=InquiryQuotationCreateSerializer, responses=QuotationDetailSerializer)
    @action(detail=False, methods=["post"], url_path="create-from-inquiry")
    def create_from_inquiry(self, request):
        actor = self.actor_employee()
        if actor is None:
            raise PermissionDenied("创建报价需要绑定有效员工档案。")
        if not request.user.has_perm("inquiries.change_inquiry"):
            raise PermissionDenied("创建询盘报价需要询盘修改权限。")
        serializer = InquiryQuotationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        inquiry = data["inquiry_id"]
        if not accessible_customers(request, "add_quotation").filter(pk=inquiry.customer_account_id).exists():
            raise PermissionDenied("您没有当前客户的报价新增范围。")
        if data.get("transaction_entity") and not request.user.has_perm("customers.add_customertransactionentity"):
            raise PermissionDenied("补录交易主体需要客户交易主体新增权限。")
        try:
            quotation, version, replayed = create_quotation_from_inquiry(
                inquiry_id=inquiry.pk,
                entity_id=getattr(data.get("transaction_entity_id"), "pk", None),
                entity_data=data.get("transaction_entity"), subject=data.get("subject", ""),
                currency_code=data["currency_code"], due_at=data["due_at"],
                idempotency_key=data["idempotency_key"], create_another=data["create_another"],
                actor_employee=actor, request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        quotation = quotations_with_context(Quotation.objects.filter(pk=quotation.pk)).get()
        response = self.response_with_etag(
            {"data": {"quotation": QuotationDetailSerializer(quotation, context=self.get_serializer_context()).data,
                      "version_id": str(version.pk), "replayed": replayed}}, quotation,
            status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        )
        response["Inquiry-ETag"] = etag_for_instance(Inquiry.objects.get(pk=inquiry.pk))
        return response

    @extend_schema(request=QuotationDraftCreateSerializer, responses=QuotationDetailSerializer)
    @action(detail=False, methods=["post"], url_path="create-draft")
    def create_draft(self, request):
        if self.actor_employee() is None:
            raise PermissionDenied("创建报价需要绑定有效员工档案。")
        serializer = QuotationDraftCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        version_data = {
            "currency_code": data.pop("currency_code"),
            "valid_until": data.pop("valid_until", None),
        }
        try:
            quotation, version = create_quotation_draft(
                quotation_data=data,
                version_data=version_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        quotation = quotations_with_context(Quotation.objects.filter(pk=quotation.pk)).get()
        response = self.response_with_etag(
            {"data": QuotationDetailSerializer(quotation, context=self.get_serializer_context()).data},
            quotation,
            status.HTTP_201_CREATED,
        )
        response["Quotation-Version-ETag"] = etag_for_instance(version)
        return response

    def retrieve(self, request, *args, **kwargs):
        quotation = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(quotation).data}, quotation)

    def partial_update(self, request, *args, **kwargs):
        quotation = self.get_object()
        require_matching_etag(request, quotation)
        serializer = self.get_serializer(quotation, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            quotation = update_quotation(
                quotation=quotation,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        quotation = quotations_with_context(Quotation.objects.filter(pk=quotation.pk)).get()
        return self.response_with_etag({"data": QuotationDetailSerializer(quotation, context=self.get_serializer_context()).data}, quotation)

    @extend_schema(methods=["GET"], responses=QuotationVersionListSerializer(many=True))
    @extend_schema(
        methods=["POST"],
        request=QuotationVersionCreateSerializer,
        responses=QuotationVersionDetailSerializer,
    )
    @action(detail=True, methods=["get", "post"])
    def versions(self, request, pk=None):
        quotation = self.get_object()
        if request.method == "GET":
            versions = versions_with_context(quotation.versions.all())
            return self.response_with_etag(
                {"data": QuotationVersionListSerializer(versions, many=True).data},
                quotation,
            )
        require_matching_etag(request, quotation)
        serializer = QuotationVersionCreateSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "quotation": quotation},
        )
        serializer.is_valid(raise_exception=True)
        try:
            version, quotation = create_version(
                quotation=quotation,
                validated_data=dict(serializer.validated_data),
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        response = self.response_with_etag(
            {"data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data},
            version,
            status.HTTP_201_CREATED,
        )
        response["Quotation-ETag"] = etag_for_instance(quotation)
        return response

    def _outcome(self, request, action_name, serializer_class):
        quotation = self.get_object()
        require_matching_etag(request, quotation)
        serializer = serializer_class(
            data=request.data,
            context={**self.get_serializer_context(), "quotation": quotation},
        )
        serializer.is_valid(raise_exception=True)
        quotation = transition_quotation(
            quotation=quotation,
            action=action_name,
            accepted_version=serializer.validated_data.get("accepted_version"),
            note=serializer.validated_data.get("note", serializer.validated_data.get("reason", "")),
            actor_employee=self.actor_employee(),
            request=request,
            accepted_price_basis=serializer.validated_data.get("accepted_price_basis"),
            customer_contact=serializer.validated_data.get("customer_contact"),
            accepted_at=serializer.validated_data.get("accepted_at"),
            acceptance_source=serializer.validated_data.get("source", ""),
        )
        quotation = quotations_with_context(Quotation.objects.filter(pk=quotation.pk)).get()
        return self.response_with_etag({"data": QuotationDetailSerializer(quotation, context=self.get_serializer_context()).data}, quotation)

    @extend_schema(request=QuotationAcceptSerializer, responses=QuotationDetailSerializer)
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._outcome(request, "ACCEPTED", QuotationAcceptSerializer)

    @extend_schema(request=QuotationReasonSerializer, responses=QuotationDetailSerializer)
    @action(detail=True, methods=["post"])
    def lose(self, request, pk=None):
        return self._outcome(request, "LOST", QuotationReasonSerializer)

    @extend_schema(request=QuotationReasonSerializer, responses=QuotationDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._outcome(request, "CANCELLED", QuotationReasonSerializer)


class QuotationTemplateViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, CustomerApiViewSetBase):
    serializer_class = QuotationTemplateSerializer
    queryset = QuotationTemplate.objects.filter(archived_at__isnull=True)
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["template_code", "template_name"]
    ordering_fields = ["template_code", "template_name", "template_version"]
    ordering = ["template_code"]
    action_permission_map = {
        "list": "quotations.view_quotationtemplate",
        "retrieve": "quotations.view_quotationtemplate",
        "seller_profile": "quotations.change_quotationtemplate",
    }

    def retrieve(self, request, *args, **kwargs):
        template = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(template).data}, template)

    @extend_schema(request=QuotationTemplateSellerProfileSerializer, responses=QuotationTemplateSerializer)
    @action(detail=True, methods=["get", "patch"], url_path="seller-profile")
    def seller_profile(self, request, pk=None):
        """只允许更新报价模板中受控的卖方联系资料。"""
        template = self.get_object()
        if request.method == "GET":
            return self.response_with_etag({"data": QuotationTemplateSerializer(template).data}, template)

        submitted = QuotationTemplateSellerProfileSerializer(data=request.data, partial=True)
        submitted.is_valid(raise_exception=True)

        with transaction.atomic():
            template = QuotationTemplate.objects.select_for_update().get(pk=template.pk, archived_at__isnull=True)
            require_matching_etag(request, template)
            before_profile = {
                field: (template.template_config or {}).get(config_key, "")
                for field, config_key in {
                    "company_name": "seller_company_name",
                    "contact_person": "seller_contact_person",
                    "phone": "seller_phone",
                    "fax": "seller_fax",
                    "skype": "seller_skype",
                    "qq": "seller_qq",
                    "wechat": "seller_wechat",
                    "whatsapp": "seller_whatsapp",
                    "address": "seller_address",
                    "email": "seller_email",
                    "facebook": "seller_facebook",
                    "website": "seller_website",
                }.items()
            }
            config = dict(template.template_config or {})
            field_mapping = {
                "company_name": "seller_company_name",
                "contact_person": "seller_contact_person",
                "phone": "seller_phone",
                "fax": "seller_fax",
                "skype": "seller_skype",
                "qq": "seller_qq",
                "wechat": "seller_wechat",
                "whatsapp": "seller_whatsapp",
                "address": "seller_address",
                "email": "seller_email",
                "facebook": "seller_facebook",
                "website": "seller_website",
            }
            for field, config_key in field_mapping.items():
                if field in submitted.validated_data:
                    config[config_key] = submitted.validated_data[field].strip()
            template.template_config = config
            template.template_version += 1
            template.save(update_fields=["template_config", "template_version", "updated_at"])
            after_profile = {field: config.get(config_key, "") for field, config_key in field_mapping.items()}
            write_audit_log(
                object_type="QUOTATION_TEMPLATE",
                object_id=template.pk,
                action="SELLER_PROFILE_UPDATED",
                actor_employee=self.actor_employee(),
                before_data={"template_version": template.template_version - 1, "seller_profile": before_profile},
                after_data={"template_version": template.template_version, "seller_profile": after_profile},
                request=request,
            )
        return self.response_with_etag({"data": QuotationTemplateSerializer(template).data}, template)


class QuotationVersionViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    CustomerApiViewSetBase,
):
    http_method_names = ["get", "put", "patch", "post", "options"]
    serializer_class = QuotationVersionDetailSerializer
    sales_action_permission_map = {"lock": "access_control.lock_quotationversion", "submit_approval": "access_control.submit_quotationversion", "void": "access_control.void_quotationversion"}
    action_permission_map = {
        "retrieve": "quotations.view_quotationversion",
        "partial_update": "quotations.change_quotationversion",
        "lines.GET": "quotations.view_quotationline",
        "lines.POST": "quotations.add_quotationline",
        "lock": "quotations.change_quotationversion",
        "submit_approval": "quotations.change_quotationversion",
        "issue": "quotations.issue_quotation",
        "generate_document": "quotations.issue_quotation",
        "generate_formal_pdf": "quotations.issue_quotation",
        "download_formal_document": "quotations.view_quotationdocument",
        "download_formal_xlsx": "quotations.view_quotationdocument",
        "upload_formal_document": "quotations.issue_quotation",
        "generate_sample_invoice": "quotations.change_quotationversion",
        "dispatch_quote": "quotations.dispatch_quotation",
        "manual_dispatch": "quotations.dispatch_quotation",
        "email_dispatch": "quotations.dispatch_quotation",
        "email_attempts": "quotations.dispatch_quotation",
        "simulate_dispatch": "quotations.dispatch_quotation",
        "price_matrix.GET": "quotations.view_quotationversion",
        "price_matrix.PUT": "quotations.change_quotationversion",
        "documents": "quotations.view_quotationdocument",
        "dispatches": "quotations.view_quotationdispatchrecord",
        "tasks": "workflow.view_businesstask",
        "void": "quotations.change_quotationversion",
        "diff": "quotations.view_quotationversion",
    }

    def get_queryset(self):
        permission = self.action_permission_codename("view_quotationversion")
        if sales_policy.enabled() and self.action == "tasks":
            permission = "view_quotationversion"
        quotations = accessible_quotations(self.request, permission).filter(
            archived_at__isnull=True,
            customer_account__archived_at__isnull=True,
        )
        return versions_with_context(QuotationVersion.objects.filter(quotation__in=quotations))

    def get_serializer_class(self):
        if self.action == "partial_update":
            return QuotationVersionUpdateSerializer
        return QuotationVersionDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        version = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(version).data}, version)

    @staticmethod
    def _version_diff(base_version, compare_version):
        changes = []

        def append_change(section, field, before, after):
            before_text = "" if before is None else str(before)
            after_text = "" if after is None else str(after)
            if before_text != after_text:
                changes.append({
                    "section": section,
                    "field": field,
                    "before": before_text or "—",
                    "after": after_text or "—",
                })

        def snapshot_text(snapshot, keys):
            values = []
            for key in keys:
                value = (snapshot or {}).get(key)
                if isinstance(value, list):
                    value = " / ".join(
                        str(item.get("value") or item.get("display_name") or item)
                        if isinstance(item, dict) else str(item)
                        for item in value
                    )
                if value not in (None, "", [], {}):
                    values.append(str(value))
            return " / ".join(values)

        commercial_snapshots = [
            ("买方主体", "transaction_entity_snapshot", ["legal_name", "entity_code", "registration_country_code"]),
            ("买方地址", "address_snapshot", ["address_line1", "address_line2", "city", "state_province", "postal_code", "country_code"]),
            ("买方联系人", "contact_snapshot", ["display_name", "position_title", "methods"]),
            ("报价模板", "template_snapshot", ["template_name", "template_version"]),
        ]
        for label, attribute, keys in commercial_snapshots:
            append_change(
                "商业快照",
                label,
                snapshot_text(getattr(base_version, attribute), keys),
                snapshot_text(getattr(compare_version, attribute), keys),
            )
        append_change("商业快照", "币种", base_version.currency_code, compare_version.currency_code)
        append_change("商业快照", "报价合计", base_version.total_amount, compare_version.total_amount)

        term_labels = {
            "incoterm_code": "贸易术语",
            "incoterm_label": "贸易条款",
            "named_place": "港口/目的地",
            "payment_terms": "付款条件",
            "deposit_percent": "订金比例",
            "lead_time": "交期",
            "tax_rate": "税率",
        }
        append_change("条款与有效期", "有效期", base_version.valid_until, compare_version.valid_until)
        for key, label in term_labels.items():
            append_change(
                "条款与有效期",
                label,
                (base_version.terms_snapshot or {}).get(key),
                (compare_version.terms_snapshot or {}).get(key),
            )
        append_change("条款与有效期", "备注", base_version.notes, compare_version.notes)

        def line_key(line):
            # 历史锁定版本受数据库触发器保护，不能为了新增技术标识而回写。
            # 因此旧行用稳定快照字段退化匹配；后续新行使用 lineage_id 精确关联。
            return str(line.lineage_id) if line.lineage_id else f"legacy:{line.line_number}:{line.product_description_snapshot}"

        base_lines = {line_key(line): line for line in base_version.lines.all()}
        compare_lines = {line_key(line): line for line in compare_version.lines.all()}
        for lineage_id in sorted(set(base_lines) | set(compare_lines)):
            before_line = base_lines.get(lineage_id)
            after_line = compare_lines.get(lineage_id)
            product_name = (
                after_line.product_description_snapshot
                if after_line is not None
                else before_line.product_description_snapshot
            )
            if before_line is None:
                append_change("产品与数量", f"{product_name}（新增）", None, after_line.quantity)
                append_change("价格与装柜量", f"{product_name} 单价", None, after_line.unit_price)
                continue
            if after_line is None:
                append_change("产品与数量", f"{product_name}（删除）", before_line.quantity, None)
                continue
            append_change("产品与数量", f"{product_name} 数量", before_line.quantity, after_line.quantity)
            append_change("产品与数量", f"{product_name} 规格", before_line.specification_snapshot, after_line.specification_snapshot)
            append_change("价格与装柜量", f"{product_name} 单价", before_line.unit_price, after_line.unit_price)
            append_change("价格与装柜量", f"{product_name} 折扣率", before_line.discount_rate, after_line.discount_rate)
            append_change("价格与装柜量", f"{product_name} 行金额", before_line.line_total, after_line.line_total)

            before_prices = {item.price_basis.label: item.unit_price for item in before_line.basis_prices.all()}
            after_prices = {item.price_basis.label: item.unit_price for item in after_line.basis_prices.all()}
            for basis_label in sorted(set(before_prices) | set(after_prices)):
                append_change(
                    "价格与装柜量",
                    f"{product_name} · {basis_label}",
                    before_prices.get(basis_label),
                    after_prices.get(basis_label),
                )

            def container_values(line):
                return {
                    tier.container_type_code: tier.final_quantity
                    for tier in line.container_tiers.all()
                }

            before_containers = container_values(before_line)
            after_containers = container_values(after_line)
            for container_code in sorted(set(before_containers) | set(after_containers)):
                append_change(
                    "价格与装柜量",
                    f"{product_name} · {container_code} 装柜量",
                    before_containers.get(container_code),
                    after_containers.get(container_code),
                )

        def price_basis_values(version):
            return {
                basis.label: f"{basis.incoterm_code} {basis.named_place} {basis.currency_code}".strip()
                for basis in version.price_bases.all()
            }

        base_bases = price_basis_values(base_version)
        compare_bases = price_basis_values(compare_version)
        for basis_label in sorted(set(base_bases) | set(compare_bases)):
            append_change(
                "价格与装柜量",
                f"价格口径 · {basis_label}",
                base_bases.get(basis_label),
                compare_bases.get(basis_label),
            )
        return changes

    @extend_schema(responses=dict)
    @action(detail=True, methods=["get"])
    def diff(self, request, pk=None):
        compare_version = self.get_object()
        base_version_id = request.query_params.get("base_version_id") or compare_version.parent_version_id
        if not base_version_id:
            return Response({"data": {"base_version": None, "compare_version": str(compare_version.pk), "changes": []}})
        base_version = self.get_queryset().filter(pk=base_version_id).first()
        if base_version is None or base_version.quotation_id != compare_version.quotation_id:
            raise PermissionDenied("比较基准必须是当前报价下且您有权限查看的版本。")
        return Response({"data": {
            "base_version": str(base_version.pk),
            "compare_version": str(compare_version.pk),
            "changes": self._version_diff(base_version, compare_version),
        }})

    def partial_update(self, request, *args, **kwargs):
        version = self.get_object()
        require_matching_etag(request, version)
        serializer = self.get_serializer(version, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            version = update_version(
                version=version,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data}, version)

    @extend_schema(methods=["GET"], responses=QuotationLineSerializer(many=True))
    @extend_schema(methods=["POST"], request=QuotationLineSerializer, responses=QuotationLineSerializer)
    @action(detail=True, methods=["get", "post"])
    def lines(self, request, pk=None):
        version = self.get_object()
        if request.method == "GET":
            return self.response_with_etag(
                {"data": QuotationLineSerializer(version.lines.all(), many=True).data},
                version,
            )
        require_matching_etag(request, version)
        serializer = QuotationLineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            line, version = create_line(
                version=version,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        line = QuotationLine.objects.prefetch_related("quantity_tiers").get(pk=line.pk)
        return self.response_with_etag(
            {"data": QuotationLineSerializer(line).data},
            version,
            status.HTTP_201_CREATED,
        )

    @extend_schema(methods=["GET"], responses=QuotationVersionDetailSerializer)
    @extend_schema(methods=["PUT"], request=QuotationPriceMatrixSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["get", "put"], url_path="price-matrix")
    def price_matrix(self, request, pk=None):
        version = self.get_object()
        if request.method == "GET":
            return self.response_with_etag({"data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data}, version)
        require_matching_etag(request, version)
        serializer = QuotationPriceMatrixSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "version": version},
        )
        serializer.is_valid(raise_exception=True)
        version = replace_price_matrix(
            version=version,
            bases_data=[dict(item) for item in serializer.validated_data["price_bases"]],
            actor_employee=self.actor_employee(),
            request=request,
        )
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data}, version)

    @extend_schema(request=QuotationLockSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"])
    def lock(self, request, pk=None):
        version = self.get_object()
        require_matching_etag(request, version)
        serializer = QuotationLockSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "version": version},
        )
        serializer.is_valid(raise_exception=True)
        version = lock_version(
            version=version,
            actor_employee=self.actor_employee(),
            request=request,
            **serializer.validated_data,
        )
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data}, version)

    @extend_schema(request=QuotationApprovalSubmitSerializer)
    @action(detail=True, methods=["post"], url_path="submit-approval")
    def submit_approval(self, request, pk=None):
        version = self.get_object()
        require_matching_etag(request, version)
        serializer = QuotationApprovalSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval, version = submit_version_approval(
            version=version,
            actor_employee=self.actor_employee(),
            request=request,
            **serializer.validated_data,
        )
        from apps.workflow.api.serializers import ApprovalDetailSerializer

        response = self.response_with_etag({"data": ApprovalDetailSerializer(approval).data}, approval)
        response["Quotation-Version-ETag"] = etag_for_instance(version)
        return response

    def _simple_action(self, request, service, serializer_class, **service_kwargs):
        version = self.get_object()
        require_matching_etag(request, version)
        serializer = serializer_class(
            data=request.data,
            context={**self.get_serializer_context(), "version": version},
        )
        serializer.is_valid(raise_exception=True)
        result = service(
            version=version,
            actor_employee=self.actor_employee(),
            request=request,
            **service_kwargs,
            **serializer.validated_data,
        )
        version = result[-1] if isinstance(result, tuple) else result
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data}, version)

    @extend_schema(request=EmptyActionSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        return self._simple_action(request, issue_version, EmptyActionSerializer)

    @extend_schema(request=QuotationDocumentCreateSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"], url_path="generate-document")
    def generate_document(self, request, pk=None):
        return self._simple_action(request, register_formal_document, QuotationDocumentCreateSerializer)

    @extend_schema(request=EmptyActionSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"], url_path="generate-formal-pdf")
    def generate_formal_pdf(self, request, pk=None):
        version = self.get_object()
        require_matching_etag(request, version)
        if version.status not in {"ISSUED", "SENT"}:
            raise ValidationError({"detail": "只有已签发或已发送版本可以生成正式报价 PDF。"})
        content = build_formal_quotation_pdf(version)
        _, version = create_generated_formal_document(
            version=version,
            content=content,
            actor_employee=self.actor_employee(),
            request=request,
        )
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data}, version)

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"], url_path="formal-document-download")
    def download_formal_document(self, request, pk=None):
        version = self.get_object()
        document = version.documents.select_related("business_file").filter(is_formal=True).first()
        if document is None:
            raise ValidationError({"detail": "当前版本尚未生成或登记正式报价文件。"})
        if document.business_file.scan_status not in USABLE_FILE_SCAN_STATUSES:
            raise ValidationError({"detail": "正式报价文件尚未通过安全扫描，暂时无法下载。"})
        media_root = Path(settings.MEDIA_ROOT).resolve()
        file_path = (media_root / document.business_file.storage_key).resolve()
        if media_root not in file_path.parents or not file_path.is_file():
            raise ValidationError({"detail": "正式报价文件不存在，请重新生成或联系管理员。"})
        return FileResponse(
            file_path.open("rb"),
            content_type=document.business_file.content_type,
            as_attachment=True,
            filename=document.business_file.original_name,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="formal-document",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_formal_document(self, request, pk=None):
        version = self.get_object()
        require_matching_etag(request, version)
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            raise ValidationError({"file": "请选择正式报价 PDF 或 XLSX 文件。"})
        if version.status not in {"ISSUED", "SENT"}:
            raise ValidationError({"file": "只有已签发或已发送版本可以登记正式报价文件。"})
        business_file = save_quotation_formal_document(uploaded_file, self.actor_employee())
        _, version = register_formal_document(
            version=version,
            business_file=business_file,
            actor_employee=self.actor_employee(),
            request=request,
        )
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data}, version)

    @action(detail=True, methods=["post"], url_path="generate-sample-invoice")
    def generate_sample_invoice(self, request, pk=None):
        version = self.get_object()
        try:
            content = build_sample_invoice(version)
        except (FileNotFoundError, SampleInvoiceTemplateError) as error:
            raise ValidationError({"detail": str(error)}) from error
        document, version = create_sample_invoice_document(
            version=version, content=content, actor_employee=self.actor_employee(), request=request,
        )
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{document.business_file.original_name}"'
        response["ETag"] = etag_for_instance(version)
        return response

    @extend_schema(
        responses={(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): bytes}
    )
    @action(detail=True, methods=["get"], url_path="formal-xlsx-download")
    def download_formal_xlsx(self, request, pk=None):
        """根据已签发版本快照即时生成 XLSX，不新增或替换正式附件。"""
        version = self.get_object()
        if version.status not in {QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT}:
            raise ValidationError({"detail": "只有已签发或已发送版本可以下载正式报价 XLSX。"})
        try:
            content = build_formal_quotation_xlsx(version)
        except (FileNotFoundError, SampleInvoiceTemplateError) as error:
            raise ValidationError({"detail": str(error)}) from error
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        filename = f"{version.quotation.quotation_number}_V{version.version_number}.xlsx"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @extend_schema(request=QuotationDispatchCreateSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"], url_path="dispatch", url_name="dispatch")
    def dispatch_quote(self, request, pk=None):
        version = self.get_object()
        require_matching_etag(request, version)
        serializer = QuotationDispatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _, version = dispatch_version(
            version=version,
            validated_data=serializer.validated_data,
            actor_employee=self.actor_employee(),
            request=request,
        )
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data}, version)

    @extend_schema(request=QuotationManualDispatchSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"], url_path="manual-dispatch")
    def manual_dispatch(self, request, pk=None):
        version = self.get_object()
        require_matching_etag(request, version)
        serializer = QuotationManualDispatchSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "version": version},
        )
        serializer.is_valid(raise_exception=True)
        _, version = confirm_manual_dispatch(
            version=version,
            actor_employee=self.actor_employee(),
            request=request,
            **serializer.validated_data,
        )
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data}, version)

    @extend_schema(request=QuotationEmailDispatchSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"], url_path="email-dispatch")
    def email_dispatch(self, request, pk=None):
        version = self.get_object()
        serializer = QuotationEmailDispatchSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "version": version},
        )
        serializer.is_valid(raise_exception=True)
        _, version, attempt, _ = email_dispatch_version(
            version=version,
            actor_employee=self.actor_employee(),
            request=request,
            **serializer.validated_data,
        )
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        return self.response_with_etag({
            "data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data,
            "email_attempt": QuotationEmailDispatchAttemptSerializer(attempt).data,
        }, version)

    @extend_schema(responses=QuotationEmailDispatchAttemptSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="email-attempts")
    def email_attempts(self, request, pk=None):
        version = self.get_object()
        queryset = QuotationEmailDispatchAttempt.objects.filter(
            quotation_version=version,
        ).select_related(
            "price_basis",
            "quotation_document",
            "requested_by_employee",
            "resolved_by_employee",
            "dispatch_record",
        )
        idempotency_key = request.query_params.get("idempotency_key", "").strip()
        if idempotency_key:
            try:
                normalized_key = uuid.UUID(idempotency_key)
            except ValueError as error:
                raise ValidationError({"idempotency_key": "邮件幂等键格式无效。"}) from error
            queryset = queryset.filter(idempotency_key=normalized_key)
        mark_stale_email_attempts_uncertain(queryset)
        queryset = queryset.order_by("-created_at", "-id")
        return Response({"data": QuotationEmailDispatchAttemptSerializer(queryset, many=True).data})

    @extend_schema(request=QuotationSimulatedDispatchSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"], url_path="simulate-dispatch")
    def simulate_dispatch(self, request, pk=None):
        version = self.get_object()
        serializer = QuotationSimulatedDispatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _, version = simulate_dispatch_version(
            version=version, recipient=serializer.validated_data.get("recipient", ""),
            notes=serializer.validated_data.get("notes", ""), actor_employee=self.actor_employee(), request=request,
        )
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data}, version)

    @extend_schema(responses=QuotationDocumentSerializer(many=True))
    @action(detail=True, methods=["get"])
    def documents(self, request, pk=None):
        version = self.get_object()
        return Response({"data": QuotationDocumentSerializer(version.documents.all(), many=True).data})

    @extend_schema(responses=QuotationDispatchSerializer(many=True))
    @action(detail=True, methods=["get"])
    def dispatches(self, request, pk=None):
        version = self.get_object()
        return Response({"data": QuotationDispatchSerializer(version.dispatch_records.all(), many=True).data})

    @extend_schema(responses=TaskListSerializer(many=True))
    @action(detail=True, methods=["get"])
    def tasks(self, request, pk=None):
        version = self.get_object()
        task_ids = version.task_links.values_list("business_task_id", flat=True)
        from apps.workflow.selectors import accessible_tasks
        tasks = tasks_with_context(accessible_tasks(request, scope="ANY_ACCESS")).filter(pk__in=task_ids, archived_at__isnull=True)
        return Response({"data": TaskListSerializer(tasks, many=True).data})

    @extend_schema(request=QuotationReasonSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        return self._simple_action(request, void_version, QuotationReasonSerializer)


class QuotationEmailDispatchAttemptViewSet(CustomerApiViewSetBase):
    http_method_names = ["post", "options"]
    serializer_class = QuotationEmailAttemptResolutionSerializer
    action_permission_map = {
        "resolve": "quotations.dispatch_quotation",
    }

    def get_queryset(self):
        quotations = accessible_quotations(self.request, "quotations.dispatch_quotation").filter(
            archived_at__isnull=True,
            customer_account__archived_at__isnull=True,
        )
        return QuotationEmailDispatchAttempt.objects.filter(
            quotation_version__quotation__in=quotations,
        ).select_related(
            "quotation_version__quotation",
            "price_basis",
            "quotation_document",
            "requested_by_employee",
            "resolved_by_employee",
            "dispatch_record",
        )

    @extend_schema(
        request=QuotationEmailAttemptResolutionSerializer,
        responses=QuotationEmailDispatchAttemptSerializer,
    )
    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        attempt = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attempt, version = resolve_email_dispatch_attempt(
            attempt=attempt,
            actor_employee=self.actor_employee(),
            request=request,
            **serializer.validated_data,
        )
        version = versions_with_context(QuotationVersion.objects.filter(pk=version.pk)).get()
        attempt = self.get_queryset().get(pk=attempt.pk)
        return self.response_with_etag({
            "data": QuotationVersionDetailSerializer(version, context=self.get_serializer_context()).data,
            "email_attempt": QuotationEmailDispatchAttemptSerializer(attempt).data,
        }, version)


class QuotationLineViewSet(
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    http_method_names = ["patch", "put", "delete", "get", "post", "options"]
    serializer_class = QuotationLineUpdateSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    action_permission_map = {
        "partial_update": "quotations.change_quotationline",
        "destroy": "quotations.delete_quotationline",
        "quantity_tiers.GET": "quotations.view_quotationquantitytier",
        "quantity_tiers.POST": "quotations.add_quotationquantitytier",
        "packaging.GET": "quotations.view_quotationline",
        "packaging.PUT": "quotations.change_quotationline",
        "container_tiers.GET": "quotations.view_quotationcontainertier",
        "container_tiers.POST": "quotations.add_quotationcontainertier",
        "container_options": "quotations.view_quotationcontainerconfig",
        "product_image.GET": "quotations.view_quotationline",
        "product_image.POST": "quotations.change_quotationline",
        "product_image.DELETE": "quotations.change_quotationline",
        "sync_inquiry": "quotations.change_quotationline",
    }

    def get_queryset(self):
        permission = self.action_permission_codename("change_quotationline")
        quotations = accessible_quotations(self.request, permission).filter(
            archived_at__isnull=True,
            customer_account__archived_at__isnull=True,
        )
        return QuotationLine.objects.filter(
            quotation_version__quotation__in=quotations
        ).select_related("quotation_version", "quotation_version__quotation", "product_image").prefetch_related(
            "quantity_tiers", "packaging", "container_tiers__container_config"
        )

    def partial_update(self, request, *args, **kwargs):
        line = self.get_object()
        require_matching_etag(request, line.quotation_version)
        serializer = self.get_serializer(line, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            line, version = update_line(
                line=line,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return self.response_with_etag({"data": QuotationLineSerializer(line).data}, version)

    @extend_schema(request=QuotationLineSyncInquirySerializer, responses=QuotationLineSyncInquiryResponseSerializer)
    @action(detail=True, methods=["post"], url_path="sync-inquiry")
    def sync_inquiry(self, request, pk=None):
        line = self.get_object()
        serializer = QuotationLineSyncInquirySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            inquiry_item, inquiry = sync_quotation_line_to_inquiry(
                line=line,
                inquiry_etag=serializer.validated_data["inquiry_etag"],
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        response = self.response_with_etag(
            {"data": {"inquiry_item_id": str(inquiry_item.pk), "inquiry_etag": etag_for_instance(inquiry)}},
            line.quotation_version,
        )
        return response

    def destroy(self, request, *args, **kwargs):
        line = self.get_object()
        require_matching_etag(request, line.quotation_version)
        version = delete_line(
            line=line,
            actor_employee=self.actor_employee(),
            request=request,
        )
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response["ETag"] = etag_for_instance(version)
        return response

    @extend_schema(methods=["GET"], responses=QuotationQuantityTierSerializer(many=True))
    @extend_schema(
        methods=["POST"],
        request=QuotationQuantityTierSerializer,
        responses=QuotationQuantityTierSerializer,
    )
    @action(detail=True, methods=["get", "post"], url_path="quantity-tiers")
    def quantity_tiers(self, request, pk=None):
        line = self.get_object()
        version = line.quotation_version
        if request.method == "GET":
            return self.response_with_etag(
                {"data": QuotationQuantityTierSerializer(line.quantity_tiers.all(), many=True).data},
                version,
            )
        require_matching_etag(request, version)
        serializer = QuotationQuantityTierSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tier, version = create_tier(
                line=line,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return self.response_with_etag(
            {"data": QuotationQuantityTierSerializer(tier).data},
            version,
            status.HTTP_201_CREATED,
        )

    @extend_schema(methods=["GET"], responses=QuotationLinePackagingSerializer)
    @extend_schema(methods=["PUT"], request=QuotationLinePackagingSerializer, responses=QuotationLinePackagingSerializer)
    @action(detail=True, methods=["get", "put"])
    def packaging(self, request, pk=None):
        line = self.get_object()
        version = line.quotation_version
        if request.method == "GET":
            if not hasattr(line, "packaging"):
                return Response({"data": None})
            packaging = line.packaging
            return self.response_with_etag({"data": QuotationLinePackagingSerializer(packaging).data}, version)
        require_matching_etag(request, version)
        serializer = QuotationLinePackagingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        packaging, version = upsert_line_packaging(
            line=line,
            validated_data=serializer.validated_data,
            actor_employee=self.actor_employee(),
            request=request,
        )
        return self.response_with_etag({"data": QuotationLinePackagingSerializer(packaging).data}, version)

    @extend_schema(methods=["GET"], responses=QuotationContainerTierSerializer(many=True))
    @extend_schema(methods=["POST"], request=QuotationContainerTierSerializer, responses=QuotationContainerTierSerializer)
    @action(detail=True, methods=["get", "post"], url_path="container-tiers")
    def container_tiers(self, request, pk=None):
        line = self.get_object()
        version = line.quotation_version
        if request.method == "GET":
            return self.response_with_etag(
                {"data": QuotationContainerTierSerializer(line.container_tiers.all(), many=True).data},
                version,
            )
        require_matching_etag(request, version)
        serializer = QuotationContainerTierSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
                tier, version = create_container_tier(
                    line=line,
                    container_config=serializer.validated_data.get("container_config"),
                    container_type_code=serializer.validated_data.get("container_type_code", ""),
                    effective_volume_cbm=serializer.validated_data.get("effective_volume_cbm", Decimal("0")),
                    load_factor=serializer.validated_data.get("load_factor", Decimal("0")),
                    unit_price=serializer.validated_data["unit_price"],
                    actor_employee=self.actor_employee(),
                    request=request,
                )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return self.response_with_etag(
            {"data": QuotationContainerTierSerializer(tier).data},
            version,
            status.HTTP_201_CREATED,
        )

    @extend_schema(responses=QuotationContainerConfigSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="container-options")
    def container_options(self, request, pk=None):
        self.get_object()
        configs = QuotationContainerConfig.objects.filter(
            archived_at__isnull=True,
            is_active=True,
        ).order_by("container_type_code", "config_version")
        return Response({"data": QuotationContainerConfigSerializer(configs, many=True).data})

    @extend_schema(methods=['POST'], request=QuotationProductImageInputSerializer, responses=QuotationLineSerializer)
    @action(detail=True, methods=["get", "post", "delete"], url_path="product-image")
    def product_image(self, request, pk=None):
        line = self.get_object()
        version = line.quotation_version
        if request.method == "GET":
            image = line.product_image
            if image is None:
                return Response(status=status.HTTP_404_NOT_FOUND)
            if image.scan_status not in USABLE_FILE_SCAN_STATUSES:
                return Response({"detail": "图片未通过安全扫描。"}, status=status.HTTP_409_CONFLICT)
            path = Path(settings.MEDIA_ROOT) / image.storage_key
            if not path.is_file():
                return Response({"detail": "图片文件不存在。"}, status=status.HTTP_404_NOT_FOUND)
            return FileResponse(path.open("rb"), content_type=image.content_type)
        require_matching_etag(request, version)
        if version.status != QuotationVersionStatus.DRAFT:
            raise Conflict("报价版本锁定后，产品主图不可修改。")
        if request.method == "DELETE":
            version = remove_line_product_image(line=line, actor_employee=self.actor_employee(), request=request)
            return self.response_with_etag({"data": {"product_image": None}}, version)
        image_file = request.FILES.get("file")
        source_image_id = request.data.get('source_image_id')
        if source_image_id and image_file:
            raise ValidationError({'source_image_id': '选择询盘图片和上传新图片不能同时提交。'})
        if source_image_id:
            source_image_id = serializers.UUIDField().run_validation(source_image_id)
            inquiry_id = version.quotation.source_inquiry_id
            business_file = inquiry_reference_images(inquiry_id, request).filter(pk=source_image_id).first() if inquiry_id else None
            if business_file is None:
                raise ValidationError({'source_image_id': '图片不属于该报价的来源询盘，或当前无权使用。'})
        elif image_file is None:
            return Response({"file": ["请选择产品图片。"]}, status=status.HTTP_400_BAD_REQUEST)
        else:
            business_file = save_quotation_product_image(image_file, self.actor_employee())
        line, version = set_line_product_image(
            line=line, business_file=business_file, actor_employee=self.actor_employee(), request=request,
        )
        return self.response_with_etag({"data": QuotationLineSerializer(line).data}, version)


class QuotationContainerTierViewSet(mixins.DestroyModelMixin, CustomerApiViewSetBase):
    http_method_names = ["delete", "options"]
    serializer_class = QuotationContainerTierSerializer
    action_permission_map = {"destroy": "quotations.delete_quotationcontainertier"}

    def get_queryset(self):
        quotations = accessible_quotations(
            self.request,
            self.action_permission_codename("delete_quotationcontainertier"),
        ).filter(archived_at__isnull=True, customer_account__archived_at__isnull=True)
        return QuotationContainerTier.objects.filter(
            quotation_line__quotation_version__quotation__in=quotations
        ).select_related("quotation_line__quotation_version", "quotation_line__quotation_version__quotation")

    def destroy(self, request, *args, **kwargs):
        tier = self.get_object()
        require_matching_etag(request, tier.quotation_line.quotation_version)
        version = delete_container_tier(tier=tier, actor_employee=self.actor_employee(), request=request)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response["ETag"] = etag_for_instance(version)
        return response
