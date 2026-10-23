from apps.access_control import sales_policy
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Q
from django.http import FileResponse
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.organizations.selectors import active_department_employees, employee_filter_choices
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.files.models import USABLE_FILE_SCAN_STATUSES
from apps.organizations.models import Employee, EmployeeStatus
from apps.reference_data.models import DictionaryStatus, ReferenceDictionary
from apps.reference_data.services import legacy_dictionary_groups

from ..complaint_services import (
    add_complaint_progress,
    attach_complaint_image,
    create_complaint,
    update_complaint,
)
from ..models import ComplaintStatus, CustomerComplaint, CustomerComplaintAttachment
from ..selectors import accessible_customers
from .complaint_serializers import (
    COMPLAINT_SEVERITY_CATEGORY,
    COMPLAINT_TYPE_CATEGORY,
    ComplaintAttachmentCreateSerializer,
    ComplaintAttachmentSerializer,
    ComplaintDictionarySerializer,
    ComplaintEmployeeSerializer,
    ComplaintProgressCreateSerializer,
    ComplaintReadSerializer,
    ComplaintUpdateSerializer,
    ComplaintWriteSerializer,
)


UUID_URL_REGEX = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def complaints_with_context(queryset):
    return queryset.select_related(
        "customer_account",
        "original_customer_account",
        "contact",
        "complaint_type_item",
        "severity_item",
        "owner_employee",
        "created_by_employee",
        "last_updated_by_employee",
    ).prefetch_related(
        "collaborator_employees",
        "attachments__business_file",
        "progress_entries__created_by_employee",
        "progress_entries__attachments__business_file",
    )


class ComplaintActionPermission(BusinessActionPermission):
    """客诉图片既可在创建后补传，也可在处理过程中补传。"""

    def has_permission(self, request, view):
        if getattr(view, "action", None) == "attachments":
            return request.user.has_perm("customers.add_customercomplaint") or request.user.has_perm(
                "customers.process_customer_complaint"
            )
        return super().has_permission(request, view)


class ComplaintViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, HasActiveEmployee, ComplaintActionPermission]
    action_permission_map = {
        "list": "customers.view_customercomplaint",
        "retrieve": "customers.view_customercomplaint",
        "create": "customers.add_customercomplaint",
        "partial_update": "customers.change_customercomplaint",
        "options": "customers.view_customercomplaint",
        "stats": "customers.view_customercomplaint",
        "progress": "customers.process_customer_complaint",
        "attachment_preview": "customers.view_customercomplaint",
    }
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    lookup_value_regex = UUID_URL_REGEX
    queryset = CustomerComplaint.objects.none()
    http_method_names = ["get", "post", "patch", "head", "options"]

    def actor_employee(self):
        return getattr(self.request, "employee", None)

    def get_queryset(self):
        code = sales_policy.action_permission(self.request, self) if sales_policy.enabled() else "view_customeraccount"
        customers = accessible_customers(self.request, code or "view_customercomplaint")
        if sales_policy.enabled() and self.action == "attachments":
            customers = accessible_customers(self.request, "add_customercomplaint") | accessible_customers(self.request, "process_customer_complaint")
        customer_ids = customers.values("pk")
        queryset = CustomerComplaint.objects.filter(customer_account_id__in=customer_ids)
        return complaints_with_context(self._apply_filters(queryset))

    def _apply_filters(self, queryset):
        query = self.request.query_params
        keyword = query.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(complaint_code__icontains=keyword)
                | Q(title__icontains=keyword)
                | Q(issue_description__icontains=keyword)
                | Q(source_order_reference__icontains=keyword)
                | Q(customer_account__account_name__icontains=keyword)
                | Q(customer_account__account_code__icontains=keyword)
            )
        filter_map = {
            "customer_id": "customer_account_id",
            "complaint_type_item_id": "complaint_type_item_id",
            "severity_item_id": "severity_item_id",
            "owner_employee_id": "owner_employee_id",
        }
        for parameter, field_name in filter_map.items():
            value = query.get(parameter)
            if value:
                queryset = queryset.filter(**{field_name: value})
        statuses = [item for item in query.get("status", "").split(",") if item]
        if statuses:
            queryset = queryset.filter(status__in=statuses)
        sla_status = query.get("sla_status")
        now = timezone.now()
        if sla_status == "OVERDUE":
            queryset = queryset.exclude(status__in=[ComplaintStatus.CLOSED, ComplaintStatus.CANCELLED]).filter(
                target_completion_at__lt=now
            )
        elif sla_status == "AT_RISK":
            queryset = queryset.exclude(status__in=[ComplaintStatus.CLOSED, ComplaintStatus.CANCELLED]).filter(
                target_completion_at__gte=now,
                target_completion_at__lte=now + timedelta(hours=24),
            )
        elif sla_status == "NORMAL":
            queryset = queryset.exclude(status__in=[ComplaintStatus.CLOSED, ComplaintStatus.CANCELLED]).filter(
                target_completion_at__gt=now + timedelta(hours=24)
            )
        elif sla_status == "COMPLETED":
            queryset = queryset.filter(status__in=[ComplaintStatus.CLOSED, ComplaintStatus.CANCELLED])
        return queryset

    def get_serializer_class(self):
        if self.action == "create":
            return ComplaintWriteSerializer
        if self.action == "partial_update":
            return ComplaintUpdateSerializer
        return ComplaintReadSerializer

    def _reload(self, complaint):
        return complaints_with_context(CustomerComplaint.objects.filter(pk=complaint.pk)).get()

    def _etag_response(self, complaint, response_status=status.HTTP_200_OK):
        response = Response(
            {"data": ComplaintReadSerializer(complaint, context=self.get_serializer_context()).data},
            status=response_status,
        )
        response["ETag"] = etag_for_instance(complaint)
        return response

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        complaint = create_complaint(
            validated_data=serializer.validated_data,
            actor_employee=self.actor_employee(),
            request=request,
        )
        return self._etag_response(self._reload(complaint), status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        return self._etag_response(self.get_object())

    def partial_update(self, request, *args, **kwargs):
        complaint = self.get_object()
        serializer = self.get_serializer(complaint, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if not serializer.validated_data:
            raise ValidationError({"detail": ["请至少提交一个需要修改的字段。"]})
        complaint = update_complaint(
            complaint=complaint,
            validated_data=serializer.validated_data,
            actor_employee=self.actor_employee(),
            request=request,
        )
        return self._etag_response(self._reload(complaint))

    @action(detail=False, methods=["get"])
    def options(self, request):
        grouped, _config_version = legacy_dictionary_groups(
            [COMPLAINT_TYPE_CATEGORY, COMPLAINT_SEVERITY_CATEGORY]
        )
        def complaint_dictionary_options(category_code):
            return [
                {
                    "id": item["id"],
                    "item_code": item["item_code"],
                    "display_name": item["display_name"],
                    "description": item["description"],
                    "sort_order": item["sort_order"],
                    "extra_data": item["extra_data"],
                }
                for item in grouped[category_code]
            ]
        types = complaint_dictionary_options(COMPLAINT_TYPE_CATEGORY)
        severities = complaint_dictionary_options(COMPLAINT_SEVERITY_CATEGORY)
        employees = active_department_employees("DEPT_BUSINESS")
        return Response(
            {
                "data": {
                    "complaint_types": types,
                    "severities": severities,
                    "statuses": [{"value": value, "label": label} for value, label in ComplaintStatus.choices],
                    "employee_filters": [{"id": str(employee.pk), "employee_code": employee.employee_code, "display_name": employee.display_name} for employee in employee_filter_choices(active_department_employees("DEPT_BUSINESS"), self.get_queryset().values("owner_employee_id"))],
                    "employees": ComplaintEmployeeSerializer(employees, many=True).data,
                }
            }
        )

    @action(detail=False, methods=["get"])
    def stats(self, request):
        queryset = self._apply_filters(
            CustomerComplaint.objects.filter(
                customer_account_id__in=accessible_customers(request, "view_customercomplaint" if sales_policy.enabled() else "view_customeraccount").values("pk")
            )
        )
        now = timezone.now()
        terminal = [ComplaintStatus.CLOSED, ComplaintStatus.CANCELLED]
        total = queryset.count()
        open_count = queryset.exclude(status__in=terminal).count()
        overdue = queryset.exclude(status__in=terminal).filter(target_completion_at__lt=now).count()
        at_risk = queryset.exclude(status__in=terminal).filter(
            target_completion_at__gte=now,
            target_completion_at__lte=now + timedelta(hours=24),
        ).count()
        by_type = queryset.values(
            "complaint_type_item_id",
            "complaint_type_item__item_code",
            "complaint_type_item__display_name",
        ).annotate(count=Count("id")).order_by("complaint_type_item__sort_order")
        by_owner = queryset.values("owner_employee_id", "owner_employee__display_name").annotate(
            count=Count("id")
        ).order_by("-count", "owner_employee__display_name")
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        closed_this_month = queryset.filter(
            status=ComplaintStatus.CLOSED,
            completed_at__gte=month_start,
        ).count()
        waiting_customer_feedback = queryset.filter(
            status=ComplaintStatus.CUSTOMER_CONFIRMATION,
        ).count()
        return Response(
            {
                "data": {
                    "total": total,
                    "open": open_count,
                    "closed": queryset.filter(status=ComplaintStatus.CLOSED).count(),
                    "cancelled": queryset.filter(status=ComplaintStatus.CANCELLED).count(),
                    "waiting_customer_feedback": waiting_customer_feedback,
                    "closed_this_month": closed_this_month,
                    "sla": {
                        "overdue": overdue,
                        "at_risk": at_risk,
                        "normal": max(open_count - overdue - at_risk, 0),
                    },
                    "by_type": list(by_type),
                    "by_owner": list(by_owner),
                }
            }
        )

    @action(detail=True, methods=["post"])
    def progress(self, request, pk=None):
        complaint = self.get_object()
        serializer = ComplaintProgressCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if (
            serializer.validated_data["to_status"] == ComplaintStatus.CLOSED
            and not request.user.has_perm("customers.close_customer_complaint")
        ):
            raise PermissionDenied("当前账号没有关闭客诉的权限。")
        if serializer.validated_data["to_status"] == ComplaintStatus.CLOSED:
            sales_policy.require_customer(request, "customers.close_customer_complaint", complaint.customer_account)
        complaint, progress = add_complaint_progress(
            complaint=complaint,
            validated_data=serializer.validated_data,
            actor_employee=self.actor_employee(),
            request=request,
        )
        response = self._etag_response(self._reload(complaint))
        response["Complaint-Progress-Id"] = str(progress.pk)
        return response

    @action(detail=True, methods=["post"])
    def attachments(self, request, pk=None):
        complaint = self.get_object()
        serializer = ComplaintAttachmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attachment = attach_complaint_image(
            complaint=complaint,
            uploaded_file=serializer.validated_data["file"],
            progress_entry=serializer.validated_data.get("progress_entry"),
            caption=serializer.validated_data.get("caption", ""),
            actor_employee=self.actor_employee(),
            request=request,
        )
        attachment = CustomerComplaintAttachment.objects.select_related("business_file").get(pk=attachment.pk)
        return Response(
            {"data": ComplaintAttachmentSerializer(attachment).data},
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path=rf"attachments/(?P<attachment_id>{UUID_URL_REGEX})/preview",
    )
    def attachment_preview(self, request, pk=None, attachment_id=None):
        complaint = self.get_object()
        attachment = CustomerComplaintAttachment.objects.select_related("business_file").filter(
            pk=attachment_id,
            complaint=complaint,
        ).first()
        if attachment is None:
            raise NotFound("客诉图片不存在。")
        business_file = attachment.business_file
        if business_file.scan_status not in USABLE_FILE_SCAN_STATUSES:
            raise NotFound("客诉图片尚未通过安全扫描。")
        media_root = Path(settings.MEDIA_ROOT).resolve()
        file_path = (media_root / business_file.storage_key).resolve()
        if media_root not in file_path.parents or not file_path.is_file():
            raise NotFound("客诉图片文件不存在。")
        return FileResponse(
            file_path.open("rb"),
            as_attachment=False,
            filename=business_file.original_name,
            content_type=business_file.content_type,
        )
