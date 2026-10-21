import csv
import json
import uuid
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import filters, mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.customers.hard_delete import permanently_delete_sample
from apps.customers.api.views import CustomerApiViewSetBase
from apps.customers.selectors import accessible_customers
from apps.organizations.models import Employee
from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from apps.reference_data.models import ProductCategory, ProductColor, ProductItemType, ReferenceStatus
from apps.quotations.models import QuotationOutcomeStatus, QuotationVersion, QuotationVersionStatus
from apps.quotations.selectors import accessible_quotations
from apps.workflow.api.serializers import TaskListSerializer
from apps.workflow.selectors import tasks_with_context

from ..models import (
    FeeApprovalStatus,
    FeeVerificationStatus,
    FreightBearer,
    SampleDeliveryBatch,
    SampleItem,
    SampleRequest,
    SampleRequestStatus,
    SampleShipment,
    SampleShippingMethod,
    SampleTolerance,
    SampleType,
)
from ..form_selectors import resolve_form_source
from ..procurement_status import PROCUREMENT_IN_PROGRESS, ordered_sample_ids
from ..form_services import create_sample_form, update_sample_form
from ..selectors import accessible_sample_requests, sample_requests_with_context, shipments_with_context
from ..services import (
    bulk_remind_sample_requests,
    bulk_transfer_sample_requests,
    confirm_sample_finance,
    create_fee_record,
    decide_fee_waiver_approval,
    create_feedback,
    create_requotation_from_feedback,
    create_sample_item,
    create_sample_from_inquiry,
    create_sample_from_quotation_version,
    create_sample_request,
    create_shipment,
    delete_sample_parameter_image,
    delete_sample_item,
    deliver_sample,
    link_sample_file,
    mark_shipment_exception,
    record_shipment_progress,
    ship_sample,
    approve_sample_pmc,
    transition_sample_request,
    upload_sample_parameters,
    update_sample_item,
    update_sample_request,
)
from ..uploads import (
    cleanup_sample_files,
    cleanup_sample_task_files,
    save_payment_evidence,
    save_sample_parameter_image,
    save_sample_task_sheet,
    save_sampling_detail_image,
)
from ..sampling_detail_config import load_sampling_detail_template
from .form_serializers import SampleRequestFormSerializer
from .application_views import SampleApplicationActionsMixin
from .material_views import SampleMaterialActionsMixin
from .sample_issue_views import SampleMaterialIssueActionsMixin
from .filters import SampleRequestFilter
from .serializers import (
    SampleActionSerializer,
    SampleApprovalDecisionSerializer,
    SampleApprovalLinkSerializer,
    SampleBulkReminderSerializer,
    SampleBulkTransferSerializer,
    SampleFeeRecordCreateSerializer,
    SampleFeeRecordSerializer,
    SampleFeedbackCreateSerializer,
    SampleFeedbackSerializer,
    SampleRequotationCreateSerializer,
    SampleRequotationOptionSerializer,
    SampleRequotationResultSerializer,
    SampleFileLinkCreateSerializer,
    SampleFileLinkSerializer,
    SampleItemSerializer,
    SampleItemUpdateSerializer,
    SampleReasonSerializer,
    SampleFromInquiryCreateSerializer,
    SampleFromQuotationCreateSerializer,
    SampleRequestCreateSerializer,
    SampleRequestDetailSerializer,
    SampleRequestListSerializer,
    SampleRequestUpdateSerializer,
    SampleShipmentCreateSerializer,
    SampleShipmentProgressSerializer,
    SampleShipmentSerializer,
    SampleShipSerializer,
    SampleWorkflowActionSerializer,
)


class SampleRequestViewSet(
    SampleApplicationActionsMixin,
    SampleMaterialActionsMixin,
    SampleMaterialIssueActionsMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = SampleRequestDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = SampleRequestFilter
    search_fields = [
        "request_number",
        "purpose",
        "notes",
        "customer_account__account_name",
        "products__product_name",
        "items__product_description_snapshot",
        "shipments__tracking_number",
    ]
    ordering_fields = ["requested_at", "requested_due_at", "created_at", "updated_at"]
    ordering = ["-requested_at", "-id"]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    action_permission_map = {
        "no_materials": "samples.edit_sample_materials",
        "production_report": "samples.change_samplerequest",
        "material_units": "samples.view_samplerequest",
        "material_reference_options": "samples.edit_sample_materials",
        "material_candidates": "samples.edit_sample_materials",
        "materials.GET": "samples.view_samplerequest",
        "procurement_material_context": "samples.view_sample_procurement",
        "materials.PUT": "samples.edit_sample_materials",
        "warehouse_review.GET": "samples.view_samplerequest",
        "warehouse_review.PUT": "samples.review_sample_materials",
        "material_issue.GET": "samples.view_samplerequest",
        "material_issue_initiate": "samples.edit_sample_materials",
        "material_issue_confirm": "samples.review_sample_materials",
        "application_create": "samples.add_samplerequest",
        "application_products": "samples.complete_sample_requirements",
        "application_product_options": "samples.complete_sample_requirements",
        "application_resubmit": "samples.add_samplerequest",
        "director_review": "samples.review_sample_application",
        "list": "samples.view_samplerequest",
        "retrieve": "samples.view_samplerequest",
        "create": "samples.add_samplerequest",
        "destroy": "samples.delete_samplerequest",
        "create_from_inquiry": "samples.add_samplerequest",
        "create_from_quotation": "samples.add_samplerequest",
        "partial_update": "samples.change_samplerequest",
        "items.GET": "samples.view_sampleitem",
        "items.POST": "samples.add_sampleitem",
        "submit": "samples.change_samplerequest",
        "start_preparing": "samples.change_samplerequest",
        "fee_records.GET": "samples.view_samplefeerecord",
        "fee_records.POST": "samples.decide_sample_fee",
        "fee_approval_approve": "samples.change_samplefeerecord",
        "fee_approval_reject": "samples.change_samplefeerecord",
        "shipments.GET": "samples.view_sampleshipment",
        "shipments.POST": "samples.add_sampleshipment",
        "feedback.GET": "samples.view_samplefeedback",
        "feedback.POST": "samples.add_samplefeedback",
        "requotation_options": "samples.view_samplefeedback",
        "create_requotation": "samples.change_samplefeedback",
        "files.GET": "samples.view_samplefilelink",
        "files.POST": "samples.add_samplefilelink",
        "upload_fee_evidence": "samples.add_samplefilelink",
        "finance_confirm": "samples.decide_sample_fee",
        "pmc_approve": "samples.change_samplerequest",
        "metalwork_parameters": "samples.change_samplerequest",
        "cutting_parameters": "samples.change_samplerequest",
        "parameter_image": "samples.change_samplerequest",
        "business_file": "samples.view_samplerequest",
        "tasks": "workflow.view_businesstask",
        "complete": "samples.change_samplerequest",
        "confirm": "samples.change_samplerequest",
        "reject": "samples.change_samplerequest",
        "cancel": "samples.view_samplerequest",
        "summary": "samples.view_samplerequest",
        "options": "samples.view_samplerequest",
        "form_options": "samples.view_samplerequest",
        "form_context": "samples.add_samplerequest",
        "form": "samples.view_samplerequest",
        "export": "samples.view_samplerequest",
        "bulk_transfer": "samples.change_samplerequest",
        "bulk_remind": "workflow.add_businesstask",
    }

    def get_queryset(self):
        from apps.access_control import module_policy
        if module_policy.enabled() and self.action == 'parameter_image':
            queryset = (accessible_sample_requests(self.request, 'access_control.metalwork_sample') |
                        accessible_sample_requests(self.request, 'access_control.cutting_sample'))
        elif module_policy.enabled() and self.action == 'form':
            editable = accessible_sample_requests(self.request, 'samples.change_samplerequest').exclude(status=SampleRequestStatus.PENDING_COMPLETION)
            completable = accessible_sample_requests(self.request, 'samples.complete_sample_requirements').filter(status=SampleRequestStatus.PENDING_COMPLETION)
            legacy_application_completion = accessible_sample_requests(self.request, 'samples.complete_sample_requirements').filter(
                status=SampleRequestStatus.MATERIALS_PENDING,
            ).exclude(application_payload_hash='').exclude(workflow_records__stage='REQUIREMENTS_COMPLETED')
            reportable = module_policy.reportable_samples(self.request).exclude(status=SampleRequestStatus.PENDING_COMPLETION)
            queryset = editable | completable | legacy_application_completion | reportable
        elif module_policy.enabled() and self.action == 'production_report':
            queryset = module_policy.reportable_samples(self.request)
        else:
            permission = 'view_samplerequest' if module_policy.enabled() and self.action in {'tasks', 'bulk_remind'} else self.action_permission_codename('view_samplerequest')
            queryset = accessible_sample_requests(self.request, permission)
        if self.request.method not in SAFE_METHODS:
            queryset = queryset.filter(
                archived_at__isnull=True,
                customer_account__archived_at__isnull=True,
            )
        elif self.request.query_params.get("archived", "false").lower() != "all":
            archived = self.request.query_params.get("archived", "false").lower()
            queryset = queryset.filter(archived_at__isnull=archived != "true")
        return sample_requests_with_context(queryset)

    def destroy(self, request, *args, **kwargs):
        sample_request = self.get_object()
        require_matching_etag(request, sample_request)
        return Response({"data": permanently_delete_sample(sample_request)})

    def get_serializer_class(self):
        if self.action == "list":
            return SampleRequestListSerializer
        if self.action == "create":
            return SampleRequestCreateSerializer
        if self.action == "partial_update":
            return SampleRequestUpdateSerializer
        return SampleRequestDetailSerializer

    @staticmethod
    def _form_payload(request):
        raw_payload = request.data.get("payload")
        if isinstance(raw_payload, dict):
            return raw_payload
        if not isinstance(raw_payload, str):
            raise ValidationError({"payload": "multipart/form-data 必须包含 JSON 格式的 payload 字段。"})
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValidationError({"payload": "payload 不是合法 JSON。"}) from exc
        if not isinstance(payload, dict):
            raise ValidationError({"payload": "payload 必须是 JSON 对象。"})
        return payload

    @staticmethod
    def _form_files(request, products, actor_employee):
        expected_fields = {f"task_sheet_{product['client_key']}" for product in products}
        expected_fields.update(
            f"sampling_image_{detail['client_key']}"
            for product in products
            for detail in product["sampling_details"]
        )
        unexpected = set(request.FILES) - expected_fields
        if unexpected:
            raise ValidationError({"files": f"存在未匹配表单的文件字段：{', '.join(sorted(unexpected))}。"})
        saved_files = []
        task_file_map = {}
        sampling_image_map = {}
        try:
            for product in products:
                field_name = f"task_sheet_{product['client_key']}"
                uploads = request.FILES.getlist(field_name)
                if len(uploads) > 1:
                    raise ValidationError({field_name: "每个产品只能上传一张任务单图片。"})
                if uploads:
                    business_file = save_sample_task_sheet(uploads[0], actor_employee)
                    saved_files.append(business_file)
                    task_file_map[product["client_key"]] = business_file
                for detail in product["sampling_details"]:
                    image_field = f"sampling_image_{detail['client_key']}"
                    image_uploads = request.FILES.getlist(image_field)
                    if len(image_uploads) > 1:
                        raise ValidationError({image_field: "每条打样信息明细只能上传一张图片。"})
                    if image_uploads:
                        business_file = save_sampling_detail_image(image_uploads[0], actor_employee)
                        saved_files.append(business_file)
                        sampling_image_map[detail["client_key"]] = business_file
        except Exception:
            cleanup_sample_task_files(saved_files)
            raise
        return task_file_map, sampling_image_map, saved_files

    def _form_response(self, sample_request, *, replayed=False, created=False):
        sample_request = sample_requests_with_context(SampleRequest.objects.filter(pk=sample_request.pk)).get()
        response = self.response_with_etag(
            {"data": SampleRequestDetailSerializer(sample_request, context=self.get_serializer_context()).data},
            sample_request,
            status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
        if created or replayed:
            response["Idempotent-Replayed"] = "true" if replayed else "false"
        return response

    def create(self, request, *args, **kwargs):
        if self.actor_employee() is None:
            raise PermissionDenied("创建样品申请需要绑定有效员工档案。")
        if "payload" in request.data:
            payload = self._form_payload(request)
            serializer = SampleRequestFormSerializer(data=payload, context=self.get_serializer_context())
            serializer.is_valid(raise_exception=True)
            source_type = serializer.validated_data.get("source_type")
            source_id = serializer.validated_data.get("source_id")
            if source_type == "inquiry":
                if not request.user.has_perm("inquiries.view_inquiry"):
                    raise PermissionDenied("当前账号没有查看来源询盘的权限。")
                resolve_form_source(request=request, source_type=source_type, source_id=source_id)
            elif source_type == "quotation":
                if not request.user.has_perm("quotations.view_quotationversion"):
                    raise PermissionDenied("当前账号没有查看来源报价的权限。")
                resolve_form_source(request=request, source_type=source_type, source_id=source_id)
            task_file_map, sampling_image_map, saved_files = self._form_files(
                request,
                serializer.validated_data["products"],
                self.actor_employee(),
            )
            try:
                sample_request, replayed = create_sample_form(
                    validated_data=dict(serializer.validated_data),
                    task_files=task_file_map,
                    sampling_image_files=sampling_image_map,
                    actor_employee=self.actor_employee(),
                    request=request,
                )
            except IntegrityError as exc:
                cleanup_sample_task_files(saved_files)
                self.raise_integrity_validation_error(exc)
            except Exception:
                cleanup_sample_task_files(saved_files)
                raise
            if replayed:
                cleanup_sample_task_files(saved_files)
            return self._form_response(sample_request, replayed=replayed, created=not replayed)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            sample_request = create_sample_request(
                validated_data=dict(serializer.validated_data),
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        sample_request = sample_requests_with_context(
            SampleRequest.objects.filter(pk=sample_request.pk)
        ).get()
        return self.response_with_etag(
            {"data": SampleRequestDetailSerializer(sample_request, context=self.get_serializer_context()).data},
            sample_request,
            status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["patch"], url_path="form")
    def form(self, request, pk=None):
        sample_request = self.get_object()
        from apps.access_control import module_policy
        from ..form_services import sample_form_edit_capabilities
        if module_policy.enabled():
            mode = sample_form_edit_capabilities(sample_request)['mode']
            permission = 'samples.complete_sample_requirements' if mode == 'COMPLETE' else 'access_control.productionreport_sample' if mode == 'REPORT_ONLY' else 'samples.change_samplerequest'
            permitted = module_policy.can_report_sample(request, sample_request) if mode == 'REPORT_ONLY' else module_policy.can_sample(request, sample_request, permission)
            if not permitted:
                raise PermissionDenied('当前账号没有此样品操作权限。')
        elif sample_request.status == SampleRequestStatus.PENDING_COMPLETION:
            if not request.user.has_perm("samples.complete_sample_requirements"):
                raise PermissionDenied("当前账号没有完善样品需求的权限。")
        elif not request.user.has_perm("samples.change_samplerequest"):
            raise PermissionDenied("当前账号没有编辑样品申请的权限。")
        require_matching_etag(request, sample_request)
        payload = self._form_payload(request)
        serializer = SampleRequestFormSerializer(
            instance=sample_request,
            data=payload,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        task_file_map, sampling_image_map, saved_files = self._form_files(
            request,
            serializer.validated_data["products"],
            self.actor_employee(),
        )
        try:
            sample_request = update_sample_form(
                sample_request=sample_request,
                validated_data=dict(serializer.validated_data),
                task_files=task_file_map,
                sampling_image_files=sampling_image_map,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            cleanup_sample_task_files(saved_files)
            self.raise_integrity_validation_error(exc)
        except Exception:
            cleanup_sample_task_files(saved_files)
            raise
        return self._form_response(sample_request)

    def _source_creation_response(self, sample_request, replayed):
        sample_request = sample_requests_with_context(
            SampleRequest.objects.filter(pk=sample_request.pk)
        ).get()
        response = self.response_with_etag(
            {"data": SampleRequestDetailSerializer(sample_request, context=self.get_serializer_context()).data},
            sample_request,
            status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        )
        response["Idempotent-Replayed"] = "true" if replayed else "false"
        return response

    @extend_schema(request=SampleFromInquiryCreateSerializer, responses=SampleRequestDetailSerializer)
    @action(detail=False, methods=["post"], url_path="create-from-inquiry")
    def create_from_inquiry(self, request):
        if self.actor_employee() is None:
            raise PermissionDenied("创建样品申请需要绑定有效员工档案。")
        if not request.user.has_perm("inquiries.view_inquiry"):
            raise PermissionDenied("当前账号没有查看来源询盘的权限。")
        serializer = SampleFromInquiryCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        validated_data = dict(serializer.validated_data)
        inquiry = validated_data.pop("inquiry")
        idempotency_key = validated_data["idempotency_key"]
        try:
            sample_request, replayed = create_sample_from_inquiry(
                inquiry_id=inquiry.pk,
                validated_data=validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            replayed_sample = SampleRequest.objects.filter(
                creation_idempotency_key=idempotency_key,
                source_inquiry=inquiry,
                source_quotation_version__isnull=True,
            ).first()
            if replayed_sample is not None:
                return self._source_creation_response(replayed_sample, True)
            self.raise_integrity_validation_error(exc)
        return self._source_creation_response(sample_request, replayed)

    @extend_schema(request=SampleFromQuotationCreateSerializer, responses=SampleRequestDetailSerializer)
    @action(detail=False, methods=["post"], url_path="create-from-quotation")
    def create_from_quotation(self, request):
        if self.actor_employee() is None:
            raise PermissionDenied("创建样品申请需要绑定有效员工档案。")
        if not request.user.has_perm("quotations.view_quotationversion"):
            raise PermissionDenied("当前账号没有查看来源报价版本的权限。")
        serializer = SampleFromQuotationCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        validated_data = dict(serializer.validated_data)
        quotation_version = validated_data.pop("quotation_version")
        idempotency_key = validated_data["idempotency_key"]
        try:
            sample_request, replayed = create_sample_from_quotation_version(
                quotation_version_id=quotation_version.pk,
                validated_data=validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            replayed_sample = SampleRequest.objects.filter(
                creation_idempotency_key=idempotency_key,
                source_quotation_version=quotation_version,
            ).first()
            if replayed_sample is not None:
                return self._source_creation_response(replayed_sample, True)
            self.raise_integrity_validation_error(exc)
        return self._source_creation_response(sample_request, replayed)

    def retrieve(self, request, *args, **kwargs):
        sample_request = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(sample_request).data}, sample_request)

    def partial_update(self, request, *args, **kwargs):
        sample_request = self.get_object()
        require_matching_etag(request, sample_request)
        serializer = self.get_serializer(sample_request, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            sample_request = update_sample_request(
                sample_request=sample_request,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        sample_request = sample_requests_with_context(
            SampleRequest.objects.filter(pk=sample_request.pk)
        ).get()
        return self.response_with_etag(
            {"data": SampleRequestDetailSerializer(sample_request, context=self.get_serializer_context()).data},
            sample_request,
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        counts = dict(
            queryset.order_by()
            .values("status")
            .annotate(total=Count("id"))
            .values_list("status", "total")
        )
        return Response(
            {
                "data": {
                    "all": sum(counts.values()),
                    "pending_completion": counts.get(SampleRequestStatus.PENDING_COMPLETION, 0),
                    "pending_payment": counts.get(SampleRequestStatus.PENDING, 0),
                    "pending_pmc": counts.get(SampleRequestStatus.PMC_REVIEW, 0),
                    "pending_director": counts.get(SampleRequestStatus.DIRECTOR_REVIEW, 0),
                    "pending_warehouse": counts.get(SampleRequestStatus.WAREHOUSE_PENDING, 0),
                    "pending_procurement": queryset.filter(status=SampleRequestStatus.PROCUREMENT_PENDING).exclude(pk__in=ordered_sample_ids()).count(),
                    "pending_metalwork": counts.get(SampleRequestStatus.METALWORK_PENDING, 0),
                    "pending_cutting": counts.get(SampleRequestStatus.CUTTING_PENDING, 0),
                    "finished": counts.get(SampleRequestStatus.FINISHED, 0),
                    "pending_shipment": counts.get(SampleRequestStatus.PREPARING, 0),
                    "in_transit": counts.get(SampleRequestStatus.SHIPPED, 0),
                    "pending_feedback": counts.get(SampleRequestStatus.DELIVERED, 0)
                    + counts.get(SampleRequestStatus.FEEDBACK_PENDING, 0),
                    "rejected": counts.get(SampleRequestStatus.REJECTED, 0),
                }
            }
        )

    @action(detail=False, methods=["get"])
    def options(self, request):
        customers = accessible_customers(request, "add_samplerequest").filter(archived_at__isnull=True)
        return Response(
            {
                "data": {
                    "sample_types": [
                        {"value": value, "label": label} for value, label in SampleType.choices
                    ],
                    "statuses": [
                        {"value": value, "label": '等待采购' if value == SampleRequestStatus.PROCUREMENT_PENDING else label}
                        for value, label in SampleRequestStatus.choices
                        if value not in {SampleRequestStatus.FEEDBACK_PENDING, SampleRequestStatus.COMPLETED}
                    ] + [{"value": PROCUREMENT_IN_PROGRESS, "label": "采购中"}],
                    "customers": [
                        {"id": str(customer.pk), "account_code": customer.account_code, "account_name": customer.account_name}
                        for customer in customers.order_by("account_name", "account_code")[:100]
                    ],
                    "owners": [
                        {"id": str(employee.pk), "employee_code": employee.employee_code, "display_name": employee.display_name}
                        for employee in Employee.objects.filter(status="ACTIVE", archived_at__isnull=True)
                        .order_by("employee_code")[:100]
                    ],
                    "fee_decisions": [
                        {"value": value, "label": label}
                        for value, label in [
                            ("PAID", "付费样"),
                            ("FREE", "免费样"),
                            ("WAIVED", "费用豁免"),
                        ]
                    ],
                    "freight_bearers": [
                        {"value": value, "label": label} for value, label in FreightBearer.choices
                    ],
                    "fee_verification_statuses": [
                        {"value": value, "label": label}
                        for value, label in FeeVerificationStatus.choices
                        if value != FeeVerificationStatus.MANUALLY_CONFIRMED
                    ],
                    "fee_approvers": [
                        {"id": str(employee.pk), "employee_code": employee.employee_code, "display_name": employee.display_name}
                        for employee in Employee.objects.filter(status="ACTIVE", archived_at__isnull=True)
                        .order_by("employee_code")[:100]
                    ],
                }
            }
        )

    @action(detail=False, methods=["get"], url_path="form-options")
    def form_options(self, request):
        actor = self.actor_employee()
        if actor is None:
            raise PermissionDenied("样品表单需要绑定有效员工档案。")
        customers = accessible_customers(request, "view_samplerequest").filter(archived_at__isnull=True)
        categories = ProductCategory.objects.filter(
            item_type=ProductItemType.FINISHED,
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).order_by("sort_order", "category_name")
        colors = ProductColor.objects.filter(
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).order_by("sort_order", "color_card", "color_name", "color_code")
        color_rows = [
            {
                "id": str(color.pk),
                "color_card": color.color_card,
                "color_name": color.color_name,
                "color_code": color.color_code,
            }
            for color in colors
        ]
        return Response(
            {
                "data": {
                    "current_maker": {
                        "id": str(actor.pk),
                        "employee_code": actor.employee_code,
                        "display_name": actor.display_name,
                    },
                    "sample_types": [{"value": value, "label": label} for value, label in SampleType.choices],
                    "shipping_methods": [
                        {"value": value, "label": label} for value, label in SampleShippingMethod.choices
                    ],
                    "delivery_batches": [
                        {"value": value, "label": label} for value, label in SampleDeliveryBatch.choices
                    ],
                    "repeat_options": [{"value": True, "label": "是"}, {"value": False, "label": "否"}],
                    "tolerances": [{"value": value, "label": label} for value, label in SampleTolerance.choices],
                    "sampling_detail_template": list(load_sampling_detail_template()),
                    "customers": [
                        {
                            "id": str(customer.pk),
                            "account_code": customer.account_code,
                            "account_name": customer.account_name,
                        }
                        for customer in customers.order_by("account_name", "account_code")[:500]
                    ],
                    "salespeople": [
                        {
                            "id": str(employee.pk),
                            "employee_code": employee.employee_code,
                            "display_name": employee.display_name,
                        }
                        for employee in Employee.objects.filter(status="ACTIVE", archived_at__isnull=True).order_by(
                            "employee_code"
                        )[:500]
                    ],
                    "categories": [
                        {"id": str(category.pk), "category_name": category.category_name}
                        for category in categories
                    ],
                    "color_cards": list(dict.fromkeys(row["color_card"] for row in color_rows)),
                    "colors": color_rows,
                }
            }
        )

    @action(detail=False, methods=["get"], url_path="form-context")
    def form_context(self, request):
        source_type = request.query_params.get("sourceType", "")
        source_id = request.query_params.get("sourceId", "")
        if not source_id:
            raise ValidationError({"sourceId": "请提供来源 UUID。"})
        try:
            source_uuid = uuid.UUID(source_id)
        except (TypeError, ValueError, AttributeError):
            raise ValidationError({"sourceId": "来源 UUID 格式不正确。"}) from None
        if source_type == "inquiry" and not request.user.has_perm("inquiries.view_inquiry"):
            raise PermissionDenied("当前账号没有查看来源询盘的权限。")
        if source_type == "quotation" and not request.user.has_perm("quotations.view_quotationversion"):
            raise PermissionDenied("当前账号没有查看来源报价的权限。")
        return Response(
            {"data": resolve_form_source(request=request, source_type=source_type, source_id=source_uuid)}
        )

    @action(detail=False, methods=["get"])
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        if queryset.count() > 5000:
            raise ValidationError({"detail": "单次最多导出 5000 条，请缩小筛选范围后重试。"})
        rows = SampleRequestListSerializer(queryset[:5000], many=True).data
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(["样品编号", "客户", "类型", "样品明细", "费用", "物流", "业务员", "申请时间", "状态"])

        def safe_csv(value):
            text = "" if value is None else str(value)
            return f"'{text}" if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text

        for row in rows:
            fee = row.get("current_fee") or {}
            shipment = row.get("latest_shipment") or {}
            writer.writerow(
                [
                    safe_csv(value)
                    for value in [
                        row["request_number"], row["customer_name"], row["sample_type_display"],
                        (row.get("item_summary") or {}).get("text", ""),
                        f"{fee.get('currency_code', '')} {fee.get('amount', '')}".strip(),
                        shipment.get("tracking_number") or shipment.get("status_display", ""),
                        (row.get("owner") or {}).get("display_name", ""), row["requested_at"], row["status_display"],
                    ]
                ]
            )
        response["Content-Disposition"] = 'attachment; filename="samples.csv"'
        return response

    @action(detail=False, methods=["post"], url_path="bulk-transfer")
    def bulk_transfer(self, request):
        serializer = SampleBulkTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sample_ids = serializer.validated_data["sample_ids"]
        samples = accessible_sample_requests(request, "change_samplerequest").filter(
            pk__in=sample_ids,
            archived_at__isnull=True,
            customer_account__archived_at__isnull=True,
        )
        if samples.count() != len(set(sample_ids)):
            raise ValidationError({"sample_ids": "部分样品不存在、已归档或无权修改。"})
        updated = bulk_transfer_sample_requests(
            sample_ids=sample_ids,
            etags=serializer.validated_data["etags"],
            owner_employee=serializer.validated_data["owner_employee"],
            note=serializer.validated_data["note"],
            actor_employee=self.actor_employee(),
            request=request,
        )
        return Response({"data": {"updated_count": len(updated)}})

    @action(detail=False, methods=["post"], url_path="bulk-remind")
    def bulk_remind(self, request):
        serializer = SampleBulkReminderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sample_ids = serializer.validated_data["sample_ids"]
        samples = accessible_sample_requests(request, "change_samplerequest").filter(
            pk__in=sample_ids,
            archived_at__isnull=True,
            customer_account__archived_at__isnull=True,
        )
        if samples.count() != len(set(sample_ids)):
            raise ValidationError({"sample_ids": "部分样品不存在、已归档或无权访问。"})
        task_ids = bulk_remind_sample_requests(
            sample_ids=sample_ids,
            etags=serializer.validated_data["etags"],
            note=serializer.validated_data.get("note", ""),
            actor_employee=self.actor_employee(),
            request=request,
        )
        return Response({"data": {"task_count": len(task_ids), "task_ids": [str(task_id) for task_id in task_ids]}})

    def _transition(self, request, action_name, serializer_class=SampleActionSerializer):
        sample_request = self.get_object()
        require_matching_etag(request, sample_request)
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        sample_request = transition_sample_request(
            sample_request=sample_request,
            action=action_name,
            note=serializer.validated_data.get("note", serializer.validated_data.get("reason", "")),
            actor_employee=self.actor_employee(),
            request=request,
        )
        sample_request = sample_requests_with_context(
            SampleRequest.objects.filter(pk=sample_request.pk)
        ).get()
        return self.response_with_etag(
            {"data": SampleRequestDetailSerializer(sample_request, context=self.get_serializer_context()).data},
            sample_request,
        )

    @extend_schema(request=SampleActionSerializer, responses=SampleRequestDetailSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._transition(request, "SUBMITTED")

    @extend_schema(request=SampleActionSerializer, responses=SampleRequestDetailSerializer)
    @action(detail=True, methods=["post"], url_path="start-preparing")
    def start_preparing(self, request, pk=None):
        return self._transition(request, "PREPARING_STARTED")

    @extend_schema(request=SampleActionSerializer, responses=SampleRequestDetailSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._transition(request, "COMPLETED")

    @extend_schema(request=SampleActionSerializer, responses=SampleRequestDetailSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return self._transition(request, "COMPLETED")

    @extend_schema(request=SampleReasonSerializer, responses=SampleRequestDetailSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._transition(request, "REJECTED", SampleReasonSerializer)

    @extend_schema(request=SampleReasonSerializer, responses=SampleRequestDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        sample_request = self.get_object()
        is_own_intake = (
            sample_request.status == SampleRequestStatus.PENDING_COMPLETION
            and sample_request.requested_by_employee_id == getattr(self.actor_employee(), "pk", None)
        )
        from apps.access_control import module_policy
        if not module_policy.enabled() and not is_own_intake and not request.user.has_perm("samples.change_samplerequest"):
            raise PermissionDenied("只能取消自己提交且尚未由工厂完善的样品需求。")
        return self._transition(request, "CANCELLED", SampleReasonSerializer)

    @extend_schema(request=SampleWorkflowActionSerializer, responses=SampleRequestDetailSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="finance-confirm",
        parser_classes=[FormParser, MultiPartParser],
    )
    def finance_confirm(self, request, pk=None):
        sample_request = self.get_object()
        require_matching_etag(request, sample_request)
        serializer = SampleWorkflowActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded_file = request.FILES.get("file")
        business_file = None
        try:
            if uploaded_file is not None:
                business_file = save_payment_evidence(uploaded_file, self.actor_employee())
            sample_request = confirm_sample_finance(
                sample_request=sample_request,
                note=serializer.validated_data.get("note", ""),
                business_file=business_file,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except Exception:
            if business_file is not None:
                cleanup_sample_files([business_file])
            raise
        return self._form_response(sample_request)

    @extend_schema(request=SampleWorkflowActionSerializer, responses=SampleRequestDetailSerializer)
    @action(detail=True, methods=["post"], url_path="pmc-approve")
    def pmc_approve(self, request, pk=None):
        sample_request = self.get_object()
        require_matching_etag(request, sample_request)
        serializer = SampleWorkflowActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sample_request = approve_sample_pmc(
            sample_request=sample_request,
            note=serializer.validated_data.get("note", ""),
            actor_employee=self.actor_employee(),
            request=request,
        )
        return self._form_response(sample_request)

    def _upload_parameters(self, request, parameter_type):
        sample_request = self.get_object()
        require_matching_etag(request, sample_request)
        serializer = SampleWorkflowActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            raise ValidationError({"file": "请选择参数文件。"})
        business_file = save_sample_parameter_image(
            uploaded_file,
            self.actor_employee(),
            parameter_type=parameter_type,
        )
        try:
            sample_request = upload_sample_parameters(
                sample_request=sample_request,
                parameter_type=parameter_type,
                note=serializer.validated_data.get("note", ""),
                business_file=business_file,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except Exception:
            cleanup_sample_files([business_file])
            raise
        return self._form_response(sample_request)

    @extend_schema(request=SampleWorkflowActionSerializer, responses=SampleRequestDetailSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="metalwork-parameters",
        parser_classes=[FormParser, MultiPartParser],
    )
    def metalwork_parameters(self, request, pk=None):
        return self._upload_parameters(request, "metalwork")

    @extend_schema(request=SampleWorkflowActionSerializer, responses=SampleRequestDetailSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="cutting-parameters",
        parser_classes=[FormParser, MultiPartParser],
    )
    def cutting_parameters(self, request, pk=None):
        return self._upload_parameters(request, "cutting")

    @extend_schema(responses=SampleRequestDetailSerializer)
    @action(
        detail=True,
        methods=["delete"],
        url_path=r"parameter-images/(?P<image_id>[^/.]+)",
    )
    def parameter_image(self, request, pk=None, image_id=None):
        sample_request = self.get_object()
        sample_request = delete_sample_parameter_image(
            sample_request=sample_request,
            image_id=image_id,
            actor_employee=self.actor_employee(),
            request=request,
        )
        return self._form_response(sample_request)

    @extend_schema(methods=["GET"], responses=SampleItemSerializer(many=True))
    @extend_schema(methods=["POST"], request=SampleItemSerializer, responses=SampleItemSerializer)
    @action(detail=True, methods=["get", "post"])
    def items(self, request, pk=None):
        sample_request = self.get_object()
        if request.method == "GET":
            return self.response_with_etag(
                {"data": SampleItemSerializer(sample_request.items.all(), many=True).data},
                sample_request,
            )
        require_matching_etag(request, sample_request)
        serializer = SampleItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item, sample_request = create_sample_item(
                sample_request=sample_request,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return self.response_with_etag(
            {"data": SampleItemSerializer(item).data},
            sample_request,
            status.HTTP_201_CREATED,
        )

    @extend_schema(methods=["GET"], responses=SampleFeeRecordSerializer(many=True))
    @extend_schema(
        methods=["POST"],
        request=SampleFeeRecordCreateSerializer,
        responses=SampleFeeRecordSerializer,
    )
    @action(detail=True, methods=["get", "post"], url_path="fee-records")
    def fee_records(self, request, pk=None):
        sample_request = self.get_object()
        if request.method == "GET":
            return self.response_with_etag(
                {"data": SampleFeeRecordSerializer(sample_request.fee_records.all(), many=True).data},
                sample_request,
            )
        require_matching_etag(request, sample_request)
        serializer = SampleFeeRecordCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            record, sample_request = create_fee_record(
                sample_request=sample_request,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return self.response_with_etag(
            {"data": SampleFeeRecordSerializer(record).data},
            sample_request,
            status.HTTP_201_CREATED,
        )

    def _decide_fee_approval(self, request, pk, approved):
        sample_request = self.get_object()
        require_matching_etag(request, sample_request)
        serializer = SampleApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record, approval, sample_request = decide_fee_waiver_approval(
            sample_request=sample_request,
            approval_id=serializer.validated_data["approval_id"],
            approved=approved,
            note=serializer.validated_data.get("note", ""),
            actor_employee=self.actor_employee(),
            request=request,
        )
        response = self.response_with_etag(
            {
                "data": {
                    "fee_record": SampleFeeRecordSerializer(record).data,
                    "approval": SampleApprovalLinkSerializer(approval.sample_link).data,
                }
            },
            sample_request,
        )
        response["Approval-ETag"] = etag_for_instance(approval)
        return response

    @action(detail=True, methods=["post"], url_path="fee-approval/approve")
    def fee_approval_approve(self, request, pk=None):
        return self._decide_fee_approval(request, pk, True)

    @action(detail=True, methods=["post"], url_path="fee-approval/reject")
    def fee_approval_reject(self, request, pk=None):
        return self._decide_fee_approval(request, pk, False)

    @extend_schema(methods=["GET"], responses=SampleShipmentSerializer(many=True))
    @extend_schema(
        methods=["POST"],
        request=SampleShipmentCreateSerializer,
        responses=SampleShipmentSerializer,
    )
    @action(detail=True, methods=["get", "post"])
    def shipments(self, request, pk=None):
        sample_request = self.get_object()
        if request.method == "GET":
            return self.response_with_etag(
                {"data": SampleShipmentSerializer(sample_request.shipments.all(), many=True).data},
                sample_request,
            )
        require_matching_etag(request, sample_request)
        serializer = SampleShipmentCreateSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "sample_request": sample_request},
        )
        serializer.is_valid(raise_exception=True)
        try:
            shipment, sample_request = create_shipment(
                sample_request=sample_request,
                actor_employee=self.actor_employee(),
                request=request,
                **serializer.validated_data,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        shipment = shipments_with_context(SampleShipment.objects.filter(pk=shipment.pk)).get()
        response = self.response_with_etag(
            {"data": SampleShipmentSerializer(shipment).data},
            shipment,
            status.HTTP_201_CREATED,
        )
        response["Sample-Request-ETag"] = etag_for_instance(sample_request)
        return response

    @extend_schema(methods=["GET"], responses=SampleFeedbackSerializer(many=True))
    @extend_schema(
        methods=["POST"],
        request=SampleFeedbackCreateSerializer,
        responses=SampleFeedbackSerializer,
    )
    @action(detail=True, methods=["get", "post"])
    def feedback(self, request, pk=None):
        sample_request = self.get_object()
        if request.method == "GET":
            return self.response_with_etag(
                {"data": SampleFeedbackSerializer(sample_request.feedback_records.all(), many=True).data},
                sample_request,
            )
        require_matching_etag(request, sample_request)
        serializer = SampleFeedbackCreateSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "sample_request": sample_request},
        )
        serializer.is_valid(raise_exception=True)
        feedback, sample_request = create_feedback(
            sample_request=sample_request,
            validated_data=serializer.validated_data,
            actor_employee=self.actor_employee(),
            request=request,
        )
        return self.response_with_etag(
            {"data": SampleFeedbackSerializer(feedback).data},
            sample_request,
            status.HTTP_201_CREATED,
        )

    @extend_schema(
        parameters=[OpenApiParameter("feedback_id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
        responses=SampleRequotationOptionSerializer(many=True),
    )
    @action(
        detail=True,
        methods=["get"],
        url_path=r"feedback/(?P<feedback_id>[^/.]+)/requotation-options",
    )
    def requotation_options(self, request, pk=None, feedback_id=None):
        sample_request = self.get_object()
        if not request.user.has_perm("quotations.view_quotationversion"):
            raise PermissionDenied("缺少查看报价版本权限。")
        get_object_or_404(sample_request.feedback_records, pk=feedback_id)
        quotations = accessible_quotations(request, "quotations.view_quotationversion").filter(
            customer_account=sample_request.customer_account,
            archived_at__isnull=True,
        )
        versions = QuotationVersion.objects.filter(
            quotation__in=quotations,
            lines__isnull=False,
        ).exclude(status=QuotationVersionStatus.VOID).select_related("quotation").distinct().order_by(
            "-updated_at", "-version_number", "-id"
        )[:100]
        origin_quotation = (
            sample_request.source_quotation_version.quotation
            if sample_request.source_quotation_version_id
            else None
        )
        data = []
        for version in versions:
            append_target = None
            if origin_quotation and origin_quotation.outcome_status == QuotationOutcomeStatus.OPEN:
                append_target = origin_quotation
            elif not origin_quotation and version.quotation.outcome_status == QuotationOutcomeStatus.OPEN:
                append_target = version.quotation
            if append_target:
                next_version = (append_target.versions.order_by("-version_number").values_list(
                    "version_number", flat=True
                ).first() or 0) + 1
                target_mode = "APPEND_VERSION"
                target_label = f"沿用 {append_target.quotation_number}，生成 V{next_version}"
            else:
                target_mode = "CREATE_QUOTATION"
                target_label = "来源报价已终态，将创建新报价 V1"
            data.append({
                "quotation_id": version.quotation_id,
                "quotation_number": version.quotation.quotation_number,
                "quotation_outcome_status": version.quotation.outcome_status,
                "version_id": version.pk,
                "version_number": version.version_number,
                "version_status": version.status,
                "currency_code": version.currency_code,
                "subject": version.quotation.subject,
                "updated_at": version.updated_at,
                "is_sample_source": version.pk == sample_request.source_quotation_version_id,
                "target_mode": target_mode,
                "target_label": target_label,
            })
        return self.response_with_etag(
            {"data": SampleRequotationOptionSerializer(data, many=True).data},
            sample_request,
        )

    @extend_schema(
        parameters=[OpenApiParameter("feedback_id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
        request=SampleRequotationCreateSerializer,
        responses=SampleRequotationResultSerializer,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"feedback/(?P<feedback_id>[^/.]+)/create-requotation",
    )
    def create_requotation(self, request, pk=None, feedback_id=None):
        sample_request = self.get_object()
        if not request.user.has_perm("quotations.view_quotationversion"):
            raise PermissionDenied("缺少查看报价版本权限。")
        if not request.user.has_perm("quotations.add_quotationversion"):
            raise PermissionDenied("缺少创建报价版本权限。")
        serializer = SampleRequotationCreateSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "sample_request": sample_request},
        )
        serializer.is_valid(raise_exception=True)
        quotation, version, sample_request, created_new, replayed = create_requotation_from_feedback(
            sample_request=sample_request,
            feedback_id=feedback_id,
            actor_employee=self.actor_employee(),
            request=request,
            **serializer.validated_data,
        )
        response = self.response_with_etag(
            {"data": SampleRequotationResultSerializer({
                "quotation_id": quotation.pk,
                "quotation_number": quotation.quotation_number,
                "quotation_version_id": version.pk,
                "version_number": version.version_number,
                "created_new_quotation": created_new,
                "replayed": replayed,
            }).data},
            sample_request,
            status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        )
        return response

    @extend_schema(methods=["GET"], responses=SampleFileLinkSerializer(many=True))
    @extend_schema(
        methods=["POST"],
        request=SampleFileLinkCreateSerializer,
        responses=SampleFileLinkSerializer,
    )
    @action(detail=True, methods=["get", "post"])
    def files(self, request, pk=None):
        sample_request = self.get_object()
        if request.method == "GET":
            return self.response_with_etag(
                {"data": SampleFileLinkSerializer(sample_request.file_links.all(), many=True).data},
                sample_request,
            )
        require_matching_etag(request, sample_request)
        serializer = SampleFileLinkCreateSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "sample_request": sample_request},
        )
        serializer.is_valid(raise_exception=True)
        try:
            link, sample_request = link_sample_file(
                sample_request=sample_request,
                actor_employee=self.actor_employee(),
                request=request,
                **serializer.validated_data,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        link = sample_request.file_links.select_related("business_file").get(pk=link.pk)
        return self.response_with_etag(
            {"data": SampleFileLinkSerializer(link).data},
            sample_request,
            status.HTTP_201_CREATED,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="file_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="已关联到当前样品单的业务文件 UUID。",
            ),
            OpenApiParameter(
                name="download",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description="传 1 时以附件方式下载，否则在浏览器中预览。",
            ),
        ],
        responses=OpenApiTypes.BINARY,
    )
    @action(
        detail=True,
        methods=["get"],
        url_path=r"business-files/(?P<file_id>[^/.]+)",
    )
    def business_file(self, request, pk=None, file_id=None):
        sample_request = self.get_object()
        business_file = get_object_or_404(
            BusinessFile.objects.filter(
                Q(sample_product_task_sheets__sample_request=sample_request)
                | Q(sample_application_references=sample_request)
                | Q(sample_product_sampling_details__sample_product__sample_request=sample_request)
                | Q(sample_links__sample_request=sample_request)
                | Q(sample_parameter_images__sample_request=sample_request)
                | Q(sample_workflow_records__sample_request=sample_request),
                pk=file_id,
                archived_at__isnull=True,
            ).distinct()
        )
        if business_file.scan_status not in USABLE_FILE_SCAN_STATUSES:
            raise ValidationError({"file": "文件尚未通过安全扫描，暂不能查看。"})
        media_root = Path(settings.MEDIA_ROOT).resolve()
        storage_path = (media_root / business_file.storage_key).resolve()
        try:
            storage_path.relative_to(media_root)
        except ValueError as exc:
            raise Http404("文件路径无效。") from exc
        if not storage_path.is_file():
            raise Http404("文件不存在。")
        return FileResponse(
            storage_path.open("rb"),
            content_type=business_file.content_type,
            as_attachment=request.query_params.get("download") == "1",
            filename=business_file.original_name,
        )

    @extend_schema(request=None, responses=SampleFileLinkSerializer)
    @action(detail=True, methods=["post"], url_path="fee-evidence", parser_classes=[FormParser, MultiPartParser])
    def upload_fee_evidence(self, request, pk=None):
        sample_request = self.get_object()
        require_matching_etag(request, sample_request)
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            raise ValidationError({"file": ["请选择付款凭证。"]})
        business_file = save_payment_evidence(uploaded_file, self.actor_employee())
        try:
            link, sample_request = link_sample_file(
                sample_request=sample_request,
                business_file=business_file,
                file_role="FEE_EVIDENCE",
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            cleanup_sample_files([business_file])
            self.raise_integrity_validation_error(exc)
        except Exception:
            cleanup_sample_files([business_file])
            raise
        link = sample_request.file_links.select_related("business_file").get(pk=link.pk)
        return self.response_with_etag(
            {"data": SampleFileLinkSerializer(link).data},
            sample_request,
            status.HTTP_201_CREATED,
        )

    @extend_schema(responses=TaskListSerializer(many=True))
    @action(detail=True, methods=["get"])
    def tasks(self, request, pk=None):
        sample_request = self.get_object()
        task_ids = sample_request.task_links.values_list("business_task_id", flat=True)
        from apps.workflow.selectors import accessible_tasks
        tasks = tasks_with_context(accessible_tasks(request, 'ANY_ACCESS')).filter(pk__in=task_ids, archived_at__isnull=True)
        return Response({"data": TaskListSerializer(tasks, many=True, context=self.get_serializer_context()).data})


class SampleItemViewSet(
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    http_method_names = ["patch", "delete", "options"]
    serializer_class = SampleItemUpdateSerializer
    action_permission_map = {
        "partial_update": "samples.change_sampleitem",
        "destroy": "samples.delete_sampleitem",
    }

    def get_queryset(self):
        permission = self.action_permission_codename("change_sampleitem")
        requests = accessible_sample_requests(self.request, permission).filter(
            archived_at__isnull=True,
            customer_account__archived_at__isnull=True,
        )
        return SampleItem.objects.filter(sample_request__in=requests).select_related(
            "sample_request",
            "sample_request__customer_account",
        )

    def partial_update(self, request, *args, **kwargs):
        item = self.get_object()
        require_matching_etag(request, item.sample_request)
        serializer = self.get_serializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            item, sample_request = update_sample_item(
                item=item,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        return self.response_with_etag({"data": SampleItemSerializer(item).data}, sample_request)

    def destroy(self, request, *args, **kwargs):
        item = self.get_object()
        require_matching_etag(request, item.sample_request)
        sample_request = delete_sample_item(
            item=item,
            actor_employee=self.actor_employee(),
            request=request,
        )
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response["ETag"] = etag_for_instance(sample_request)
        return response


class SampleShipmentViewSet(mixins.RetrieveModelMixin, CustomerApiViewSetBase):
    http_method_names = ["get", "post", "options"]
    serializer_class = SampleShipmentSerializer
    action_permission_map = {
        "retrieve": "samples.view_sampleshipment",
        "ship": "samples.ship_sample",
        "deliver": "samples.change_sampleshipment",
        "exception": "samples.change_sampleshipment",
        "progress": "samples.change_sampleshipment",
    }

    def get_queryset(self):
        permission_name = {
            "retrieve": "view_sampleshipment",
            "ship": "ship_sample",
        }.get(self.action, "change_sampleshipment")
        permission = self.action_permission_codename(permission_name)
        requests = accessible_sample_requests(self.request, permission).filter(
            archived_at__isnull=True,
            customer_account__archived_at__isnull=True,
        )
        return shipments_with_context(SampleShipment.objects.filter(sample_request__in=requests))

    def retrieve(self, request, *args, **kwargs):
        shipment = self.get_object()
        return self.response_with_etag({"data": SampleShipmentSerializer(shipment).data}, shipment)

    @extend_schema(request=SampleShipSerializer, responses=SampleShipmentSerializer)
    @action(detail=True, methods=["post"])
    def ship(self, request, pk=None):
        shipment = self.get_object()
        require_matching_etag(request, shipment)
        serializer = SampleShipSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "shipment": shipment},
        )
        serializer.is_valid(raise_exception=True)
        try:
            shipment, sample_request = ship_sample(
                shipment=shipment,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        shipment = shipments_with_context(SampleShipment.objects.filter(pk=shipment.pk)).get()
        response = self.response_with_etag({"data": SampleShipmentSerializer(shipment).data}, shipment)
        response["Sample-Request-ETag"] = etag_for_instance(sample_request)
        return response

    @extend_schema(request=SampleActionSerializer, responses=SampleShipmentSerializer)
    @action(detail=True, methods=["post"])
    def deliver(self, request, pk=None):
        shipment = self.get_object()
        require_matching_etag(request, shipment)
        serializer = SampleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shipment, sample_request = deliver_sample(
            shipment=shipment,
            note=serializer.validated_data.get("note", ""),
            actor_employee=self.actor_employee(),
            request=request,
        )
        shipment = shipments_with_context(SampleShipment.objects.filter(pk=shipment.pk)).get()
        response = self.response_with_etag({"data": SampleShipmentSerializer(shipment).data}, shipment)
        response["Sample-Request-ETag"] = etag_for_instance(sample_request)
        return response

    @extend_schema(request=SampleReasonSerializer, responses=SampleShipmentSerializer)
    @action(detail=True, methods=["post"])
    def exception(self, request, pk=None):
        shipment = self.get_object()
        require_matching_etag(request, shipment)
        serializer = SampleReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shipment, sample_request = mark_shipment_exception(
            shipment=shipment,
            note=serializer.validated_data["reason"],
            actor_employee=self.actor_employee(),
            request=request,
        )
        shipment = shipments_with_context(SampleShipment.objects.filter(pk=shipment.pk)).get()
        response = self.response_with_etag({"data": SampleShipmentSerializer(shipment).data}, shipment)
        response["Sample-Request-ETag"] = etag_for_instance(sample_request)
        return response

    @extend_schema(request=SampleShipmentProgressSerializer, responses=SampleShipmentSerializer)
    @action(detail=True, methods=["post"])
    def progress(self, request, pk=None):
        shipment = self.get_object()
        require_matching_etag(request, shipment)
        serializer = SampleShipmentProgressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shipment, sample_request = record_shipment_progress(
            shipment=shipment,
            validated_data=serializer.validated_data,
            actor_employee=self.actor_employee(),
            request=request,
        )
        shipment = shipments_with_context(SampleShipment.objects.filter(pk=shipment.pk)).get()
        response = self.response_with_etag({"data": SampleShipmentSerializer(shipment).data}, shipment)
        response["Sample-Request-ETag"] = etag_for_instance(sample_request)
        return response
