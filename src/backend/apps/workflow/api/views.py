from apps.access_control import sales_policy
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Count, F, Q
from django.utils import timezone
from django.http import FileResponse
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.selectors import active_department_employees, employee_filter_choices
from apps.core.api.concurrency import require_matching_etag
from apps.customers.hard_delete import permanently_delete_task
from apps.core.api.permissions import HasActiveEmployee
from apps.crm.models import CustomerCommunication
from apps.files.models import USABLE_FILE_SCAN_STATUSES
from apps.customers.api.views import CustomerApiViewSetBase
from apps.customers.models import CustomerAccount
from apps.customers.selectors import accessible_customers
from apps.organizations.models import Employee
from apps.inquiries.models import Inquiry
from apps.quotations.models import QuotationVersion
from apps.samples.models import SampleRequest

from ..models import ApprovalRequest, ApprovalStatus, BusinessTask, SlaTracking, TaskChecklistItem, TaskStatus, TaskWorkState
from ..selectors import (
    accessible_approvals,
    accessible_sla_trackings,
    accessible_tasks,
    approvals_with_context,
    sla_trackings_with_context,
    tasks_with_context,
)
from ..services import (
    cancel_approval,
    create_task,
    decide_approval,
    reassign_task,
    execute_batch,
    reschedule_conflicts,
    reschedule_task,
    set_task_work_state,
    toggle_checklist_item,
    task_customer_and_source,
    resolve_task_source,
    transition_task,
    update_task,
    validate_task_source_active,
)
from .filters import TaskFilter
from .serializers import (
    ApprovalCancelSerializer,
    ApprovalDecisionSerializer,
    ApprovalDetailSerializer,
    ApprovalListSerializer,
    SlaTrackingSerializer,
    TaskActionSerializer,
    TaskCreateSerializer,
    TaskDetailSerializer,
    TaskListSerializer,
    TaskReassignSerializer,
    ChecklistToggleSerializer,
    TaskBatchSerializer,
    TaskBulkReassignSerializer,
    TaskRescheduleSerializer,
    TaskWorkStateSerializer,
    TaskUpdateSerializer,
)


class TaskViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = TaskDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TaskFilter
    search_fields = ["title", "description"]
    ordering_fields = ["due_at", "created_at", "updated_at", "priority"]
    ordering = ["due_at", "-created_at", "-id"]
    action_permission_map = {
        "list": "workflow.view_businesstask",
        "retrieve": "workflow.view_businesstask",
        "create": "workflow.add_businesstask",
        "destroy": "workflow.delete_businesstask",
        "partial_update": "workflow.change_businesstask",
        "start": "workflow.change_businesstask",
        "complete": "workflow.change_businesstask",
        "cancel": "workflow.change_businesstask",
        "reassign": "workflow.reassign_businesstask",
        "summary": "workflow.view_businesstask",
        "options": "workflow.view_businesstask",
        "activity": "workflow.view_businesstask",
        "wait_customer": "workflow.change_businesstask",
        "block": "workflow.change_businesstask",
        "resume": "workflow.change_businesstask",
        "reschedule_preview": "workflow.change_businesstask",
        "reschedule": "workflow.change_businesstask",
        "toggle_checklist": "workflow.change_businesstask",
        "bulk_complete_preview": "workflow.bulk_change_businesstask",
        "bulk_complete": "workflow.bulk_change_businesstask",
        "bulk_reassign_preview": "workflow.bulk_change_businesstask",
        "bulk_reassign": "workflow.bulk_change_businesstask",
        "attachment": "workflow.view_businesstask",
    }

    def get_queryset(self):
        if self.action == "list":
            # 兼容既有工作台调用；任务中心页面始终显式传 scope=ME。
            scope = self.request.query_params.get("scope", "LEGACY")
        elif self.action in {"summary", "options"}:
            scope = self.request.query_params.get("scope", "ME")
        else:
            scope = "ANY_ACCESS"
        from apps.access_control import module_policy
        permission = module_policy.action_permission(self.request, self) if module_policy.enabled() else 'workflow.view_businesstask'
        queryset = accessible_tasks(self.request, scope=scope, permission=permission)
        if self.request.query_params.get("archived", "false").lower() != "all":
            queryset = queryset.filter(archived_at__isnull=True)
        return tasks_with_context(queryset)

    def get_serializer_class(self):
        if self.action == "list":
            return TaskListSerializer
        if self.action == "create":
            return TaskCreateSerializer
        if self.action == "partial_update":
            return TaskUpdateSerializer
        return TaskDetailSerializer

    def destroy(self, request, *args, **kwargs):
        task = self.get_object()
        require_matching_etag(request, task)
        return Response({"data": permanently_delete_task(task)})

    def _task_or_404(self, pk):
        try:
            return self.get_queryset().get(pk=pk)
        except BusinessTask.DoesNotExist as exc:
            raise NotFound("任务不存在或无权访问。") from exc

    @action(detail=False, methods=["get"])
    def summary(self, request):
        queryset = self.get_queryset().filter(status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS])
        now = timezone.now()
        local_now = timezone.localtime(now)
        today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        future_end = tomorrow_start + timedelta(days=7)
        month_start = today_start.replace(day=1)
        next_month_start = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        completed = self.get_queryset().filter(status=TaskStatus.COMPLETED, completed_at__gte=month_start, completed_at__lt=next_month_start)
        completed_with_due = completed.filter(due_at__isnull=False)
        total_completed = completed_with_due.count()
        timely_completed = completed_with_due.filter(completed_at__lte=F("due_at")).count()
        return Response({"data": {
                "open_count": queryset.count(),
                "due_today_count": queryset.filter(due_at__gte=today_start, due_at__lt=tomorrow_start).count(),
                "overdue_count": queryset.filter(due_at__lt=now).count(),
                "next_7_days_count": queryset.filter(due_at__gte=tomorrow_start, due_at__lt=future_end).count(),
                "month_completed_count": completed.count(),
                "on_time_rate": round(timely_completed / total_completed * 100, 2) if total_completed else None,
            }})

    @action(detail=False, methods=["get"])
    def options(self, request):
        scope = request.query_params.get("scope", "ME")
        source_customers = accessible_customers(request, "view_customeraccount").filter(archived_at__isnull=True)
        return Response({"data": {
            "scopes": [
                {"value": "ME", "label": "我的任务"},
                {"value": "CREATED_BY_ME", "label": "我创建的"},
                *([{ "value": "TEAM", "label": "团队任务"}] if request.user.has_perm("workflow.view_team_businesstask") or request.user.is_superuser or "TEAM" in sales_policy.scopes(request, "workflow.view_businesstask") else []),
                *([{ "value": "ALL", "label": "全部任务"}] if request.user.has_perm("workflow.view_all_businesstask") or request.user.is_superuser or "ALL" in sales_policy.scopes(request, "workflow.view_businesstask") else []),
            ],
            "task_types": [{"value": value, "label": label} for value, label in BusinessTask._meta.get_field("task_type").choices],
            "statuses": [{"value": value, "label": label} for value, label in BusinessTask._meta.get_field("status").choices],
            "priorities": [{"value": value, "label": "中" if value == "NORMAL" else label} for value, label in BusinessTask._meta.get_field("priority").choices],
            "assignee_filters": [{"id": str(employee.pk), "code": employee.employee_code, "name": employee.display_name} for employee in employee_filter_choices(active_department_employees("DEPT_BUSINESS"), self.get_queryset().values("assignee_employee_id"))],
            "assignees": [{"id": str(employee.pk), "code": employee.employee_code, "name": employee.display_name} for employee in active_department_employees("DEPT_BUSINESS").order_by("employee_code")],
            "customer_count": source_customers.count(),
            "selected_scope": scope,
        }})

    def create(self, request, *args, **kwargs):
        if self.actor_employee() is None:
            raise PermissionDenied("创建任务需要绑定有效员工档案。")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = dict(serializer.validated_data)
        source_type = validated_data.get("source_type")
        source_id = validated_data.get("source_id")
        resolved_source = None
        if source_type:
            resolved_source = resolve_task_source(source_type, source_id)
            customer = resolved_source[1]
            source_permission = {"CUSTOMER": "customers.view_customeraccount", "COMMUNICATION": "crm.view_customercommunication", "INQUIRY": "inquiries.view_inquiry", "QUOTATION_VERSION": "quotations.view_quotationversion"}.get(source_type)
            if source_permission:
                sales_policy.require_customer(request, source_permission, customer)
            if not accessible_customers(request, "add_businesstask").filter(pk=customer.pk).exists():
                raise NotFound("任务来源不存在或无权访问。")
            from apps.access_control import module_policy
            if source_type == 'SAMPLE_REQUEST' and module_policy.enabled() and not module_policy.can_sample(request, resolved_source[0], 'samples.view_samplerequest'):
                raise NotFound('任务来源不存在或无权访问。')
            validate_task_source_active(source_type, resolved_source[0], customer)
        try:
            task = create_task(
                validated_data=validated_data,
                actor_employee=self.actor_employee(),
                request=request,
                resolved_source=resolved_source,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        task = tasks_with_context(BusinessTask.objects.filter(pk=task.pk)).get()
        return self.response_with_etag(
            {"data": TaskDetailSerializer(task, context=self.get_serializer_context()).data},
            task,
            status.HTTP_201_CREATED,
        )

    def retrieve(self, request, *args, **kwargs):
        task = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(task).data}, task)

    def partial_update(self, request, *args, **kwargs):
        task = self.get_object()
        require_matching_etag(request, task)
        serializer = self.get_serializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        task = update_task(
            task=task,
            validated_data=serializer.validated_data,
            actor_employee=self.actor_employee(),
            request=request,
        )
        task = tasks_with_context(BusinessTask.objects.filter(pk=task.pk)).get()
        return self.response_with_etag({"data": TaskDetailSerializer(task, context=self.get_serializer_context()).data}, task)

    def _transition(self, request, action_name):
        task = self.get_object()
        require_matching_etag(request, task)
        serializer = TaskActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = transition_task(
            task=task,
            action=action_name,
            note=serializer.validated_data.get("note", ""),
            actor_employee=self.actor_employee(),
            request=request,
        )
        task = tasks_with_context(BusinessTask.objects.filter(pk=task.pk)).get()
        return self.response_with_etag({"data": TaskDetailSerializer(task, context=self.get_serializer_context()).data}, task)

    @extend_schema(request=TaskActionSerializer, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        return self._transition(request, "STARTED")

    @extend_schema(request=TaskActionSerializer, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._transition(request, "COMPLETED")

    @extend_schema(request=TaskActionSerializer, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._transition(request, "CANCELLED")

    @extend_schema(request=TaskReassignSerializer, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def reassign(self, request, pk=None):
        task = self.get_object()
        require_matching_etag(request, task)
        serializer = TaskReassignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = reassign_task(
            task=task,
            assignee_employee=serializer.validated_data["assignee_employee"],
            reason=serializer.validated_data["reason"],
            actor_employee=self.actor_employee(),
            request=request,
        )
        task = tasks_with_context(BusinessTask.objects.filter(pk=task.pk)).get()
        return self.response_with_etag({"data": TaskDetailSerializer(task, context=self.get_serializer_context()).data}, task)

    @action(detail=True, methods=["post"], url_path="wait-customer")
    def wait_customer(self, request, pk=None):
        return self._set_work_state(request, pk, TaskWorkState.WAITING_CUSTOMER)

    @action(detail=True, methods=["post"])
    def block(self, request, pk=None):
        return self._set_work_state(request, pk, TaskWorkState.BLOCKED)

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._set_work_state(request, pk, TaskWorkState.NORMAL)

    def _set_work_state(self, request, pk, work_state):
        task = self._task_or_404(pk)
        serializer = TaskWorkStateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = set_task_work_state(
            task=task,
            work_state=work_state,
            reason=serializer.validated_data.get("reason", ""),
            next_check_at=serializer.validated_data.get("next_check_at"),
            actor_employee=self.actor_employee(),
            request=request,
        )
        task = tasks_with_context(BusinessTask.objects.filter(pk=task.pk)).get()
        return self.response_with_etag({"data": TaskDetailSerializer(task, context=self.get_serializer_context()).data}, task)

    @action(detail=True, methods=["post"], url_path="reschedule-preview")
    def reschedule_preview(self, request, pk=None):
        task = self._task_or_404(pk)
        serializer = TaskRescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conflicts = reschedule_conflicts(task, serializer.validated_data["new_due_at"])
        return Response({"data": {
            "warning": bool(conflicts),
            "warning_code": "SAME_HOUR_HIGH_PRIORITY_DUE" if conflicts else None,
            "conflict_count": conflicts.count(),
            "conflicts": [{"id": str(item.pk), "task_number": item.task_number, "title": item.title, "priority": item.priority, "due_at": item.due_at} for item in conflicts[:20]],
        }})

    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        task = self._task_or_404(pk)
        serializer = TaskRescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task, reminder_count = reschedule_task(
            task=task,
            actor_employee=self.actor_employee(),
            request=request,
            **serializer.validated_data,
        )
        task = tasks_with_context(BusinessTask.objects.filter(pk=task.pk)).get()
        return self.response_with_etag({"data": TaskDetailSerializer(task, context=self.get_serializer_context()).data, "moved_reminder_count": reminder_count}, task)

    @action(detail=True, methods=["patch"], url_path=r"checklist/(?P<item_id>[0-9a-f-]+)")
    def toggle_checklist(self, request, pk=None, item_id=None):
        task = self._task_or_404(pk)
        serializer = ChecklistToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = TaskChecklistItem.objects.get(pk=item_id, business_task=task)
        except TaskChecklistItem.DoesNotExist as exc:
            raise NotFound("检查项不存在。") from exc
        task, item = toggle_checklist_item(
            task=task,
            item=item,
            is_completed=serializer.validated_data["is_completed"],
            actor_employee=self.actor_employee(),
            request=request,
        )
        return self.response_with_etag({"data": {"id": str(item.pk), "is_completed": item.is_completed, "completed_at": item.completed_at}}, task)

    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        task = self._task_or_404(pk)
        from apps.crm.models import CustomerTimelineEvent
        customer, source_type, source_id = task_customer_and_source(task)
        events = [
            {"kind": "TASK", "id": str(event.pk), "event_type": event.event_type, "title": event.event_type, "summary": event.note, "occurred_at": event.occurred_at, "actor": event.actor_employee.display_name if event.actor_employee else None}
            for event in task.events.select_related("actor_employee").order_by("-occurred_at", "-id")
        ]
        if customer and source_type and source_id:
            events.extend(
                {"kind": "SOURCE", "id": str(event.pk), "event_type": event.event_type, "title": event.title, "summary": event.summary, "occurred_at": event.occurred_at, "actor": None}
                for event in CustomerTimelineEvent.objects.filter(customer_account=customer, source_type=source_type, source_id=source_id).order_by("-occurred_at", "-id")
            )
        events.sort(key=lambda item: item["occurred_at"], reverse=True)
        return Response({"data": events})

    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<file_id>[0-9a-f-]+)/(?P<disposition>preview|download)")
    def attachment(self, request, pk=None, file_id=None, disposition=None):
        task = self._task_or_404(pk)
        _, source_type, _ = task_customer_and_source(task)
        source = TaskDetailSerializer(task, context=self.get_serializer_context()).get_source(task)
        if not source or not source_type:
            raise NotFound("来源附件不存在。")
        source_object = None
        for relation_name, field_name in [
            ("primary_customer_links", "customer_account"),
            ("primary_communication_links", "communication"),
            ("primary_inquiry_links", "inquiry"),
            ("primary_quotation_links", "quotation_version"),
            ("primary_sample_links", "sample_request"),
        ]:
            links = getattr(task, relation_name, [])
            if links:
                source_object = getattr(links[0], field_name)
                break
        if not source_object or not hasattr(source_object, "file_links"):
            raise NotFound("来源附件不存在。")
        from apps.access_control import module_policy
        if source_type == 'SAMPLE_REQUEST' and module_policy.enabled() and not module_policy.can_sample(request, source_object, 'samples.view_samplefilelink'):
            raise NotFound('来源附件不存在或无权访问。')
        link = source_object.file_links.filter(
            business_file_id=file_id,
            business_file__scan_status__in=USABLE_FILE_SCAN_STATUSES,
            business_file__archived_at__isnull=True,
        ).select_related("business_file").first()
        if not link:
            raise NotFound("来源附件不存在或尚未通过安全扫描。")
        media_root = Path(settings.MEDIA_ROOT).resolve()
        file_path = (media_root / link.business_file.storage_key).resolve()
        if media_root not in file_path.parents or not file_path.is_file():
            raise NotFound("附件文件不存在。")
        return FileResponse(
            file_path.open("rb"),
            as_attachment=disposition == "download",
            filename=link.business_file.original_name,
            content_type=link.business_file.content_type or "application/octet-stream",
        )

    def _bulk_preview(self, request, serializer_class, action_name):
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = [item["id"] for item in serializer.validated_data["items"]]
        tasks = self.get_queryset().filter(pk__in=ids, status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS])
        from apps.access_control import module_policy
        if module_policy.enabled():
            permission = 'access_control.complete_businesstask' if action_name == 'COMPLETE' else 'workflow.reassign_businesstask'
            tasks = tasks.filter(pk__in=accessible_tasks(request, 'ANY_ACCESS', permission=permission).values('pk'))
        if tasks.count() != len(ids):
            raise ValidationError({"items": ["存在不可操作任务。"]})
        scheduled_reminders = tasks.aggregate(total=Count("reminders", filter=Q(reminders__status="SCHEDULED")))["total"]
        return Response({"data": {"action": action_name, "task_count": tasks.count(), "customer_count": tasks.values("customer_links__customer_account_id").distinct().count(), "overdue_count": tasks.filter(due_at__lt=timezone.now()).count(), "scheduled_reminder_count": scheduled_reminders}})

    @action(detail=False, methods=["post"], url_path="bulk-complete/preview")
    def bulk_complete_preview(self, request):
        return self._bulk_preview(request, TaskBatchSerializer, "COMPLETE")

    @action(detail=False, methods=["post"], url_path="bulk-reassign/preview")
    def bulk_reassign_preview(self, request):
        return self._bulk_preview(request, TaskBulkReassignSerializer, "REASSIGN")

    def _bulk_execute(self, request, serializer_class, action_name):
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["items"]
        accessible_ids = set(self.get_queryset().filter(pk__in=[item["id"] for item in items]).values_list("id", flat=True))
        if len(accessible_ids) != len(items):
            raise NotFound("存在任务不存在或无权访问。")
        result, reused = execute_batch(
            action=action_name,
            items=items,
            event_id=serializer.validated_data["event_id"],
            actor_employee=self.actor_employee(),
            request=request,
            assignee_employee=serializer.validated_data.get("assignee_employee"),
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response({"data": result, "idempotent_replay": reused})

    @action(detail=False, methods=["post"], url_path="bulk-complete")
    def bulk_complete(self, request):
        return self._bulk_execute(request, TaskBatchSerializer, "COMPLETE")

    @action(detail=False, methods=["post"], url_path="bulk-reassign")
    def bulk_reassign(self, request):
        return self._bulk_execute(request, TaskBulkReassignSerializer, "REASSIGN")


class TaskSourceOptionsView(APIView):
    """只返回当前账号有客户数据权限的真实来源对象。"""

    permission_classes = [HasActiveEmployee]

    @extend_schema(responses={200: serializers.DictField()})
    def get(self, request):
        if not request.user.has_perm("workflow.view_businesstask") and not request.user.is_superuser:
            raise PermissionDenied("当前账号没有查看任务来源的权限。")
        source_type = request.query_params.get("source_type")
        keyword = request.query_params.get("q", "").strip()
        customer_id = request.query_params.get("customer_id")
        customers = accessible_customers(request, "view_customeraccount").filter(archived_at__isnull=True)
        if customer_id:
            customers = customers.filter(pk=customer_id)
        rows = []
        if source_type in (None, "CUSTOMER"):
            queryset = customers
            if keyword:
                queryset = queryset.filter(Q(account_code__icontains=keyword) | Q(account_name__icontains=keyword))
            rows.extend({"type": "CUSTOMER", "id": str(item.pk), "customer_id": str(item.pk), "code": item.account_code, "title": item.account_name} for item in queryset.order_by("account_code")[:50])
        if source_type in (None, "COMMUNICATION"):
            queryset = CustomerCommunication.objects.filter(customer_account__in=customers, archived_at__isnull=True).filter(customer_account__in=accessible_customers(request, "view_customercommunication"))
            if keyword:
                queryset = queryset.filter(subject__icontains=keyword)
            rows.extend({"type": "COMMUNICATION", "id": str(item.pk), "customer_id": str(item.customer_account_id), "code": "", "title": item.subject or item.communication_type} for item in queryset.order_by("-occurred_at", "-id")[:50])
        if source_type in (None, "INQUIRY"):
            queryset = Inquiry.objects.filter(customer_account__in=customers, archived_at__isnull=True).filter(customer_account__in=accessible_customers(request, "view_inquiry"))
            if keyword:
                queryset = queryset.filter(Q(inquiry_number__icontains=keyword) | Q(subject__icontains=keyword))
            rows.extend({"type": "INQUIRY", "id": str(item.pk), "customer_id": str(item.customer_account_id), "code": item.inquiry_number, "title": item.subject} for item in queryset.order_by("-created_at", "-id")[:50])
        if source_type in (None, "QUOTATION_VERSION"):
            queryset = QuotationVersion.objects.filter(quotation__customer_account__in=accessible_customers(request, "view_quotationversion")).filter(quotation__customer_account__in=customers, archived_at__isnull=True, quotation__archived_at__isnull=True).select_related("quotation")
            if keyword:
                queryset = queryset.filter(quotation__quotation_number__icontains=keyword)
            rows.extend({"type": "QUOTATION_VERSION", "id": str(item.pk), "customer_id": str(item.quotation.customer_account_id), "code": f"{item.quotation.quotation_number} V{item.version_number}", "title": item.quotation.quotation_number} for item in queryset.order_by("-created_at", "-id")[:50])
        if source_type in (None, "SAMPLE_REQUEST"):
            from apps.access_control import module_policy
            from apps.samples.selectors import accessible_sample_requests
            queryset = accessible_sample_requests(request, 'samples.view_samplerequest') if module_policy.enabled() else SampleRequest.objects.all()
            queryset = queryset.filter(customer_account__in=customers, archived_at__isnull=True)
            if keyword:
                queryset = queryset.filter(Q(request_number__icontains=keyword) | Q(product_description_snapshot__icontains=keyword))
            rows.extend({"type": "SAMPLE_REQUEST", "id": str(item.pk), "customer_id": str(item.customer_account_id), "code": item.request_number, "title": item.product_description_snapshot} for item in queryset.order_by("-created_at", "-id")[:50])
        return Response({"data": rows})


class ApprovalViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = ApprovalDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ["submitted_at", "decided_at", "created_at", "updated_at"]
    ordering = ["-submitted_at", "-id"]
    action_permission_map = {
        "list": "workflow.view_approvalrequest",
        "retrieve": "workflow.view_approvalrequest",
        "approve": "quotations.approve_quotation",
        "reject": "quotations.approve_quotation",
        "cancel": "workflow.change_approvalrequest",
    }

    def get_queryset(self):
        queryset = accessible_approvals(self.request)
        status_value = self.request.query_params.get("status")
        approval_type = self.request.query_params.get("approval_type")
        if status_value:
            queryset = queryset.filter(status=status_value)
        if approval_type:
            queryset = queryset.filter(approval_type=approval_type)
        return approvals_with_context(queryset)

    def get_serializer_class(self):
        if self.action == "list":
            return ApprovalListSerializer
        return ApprovalDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        approval = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(approval).data}, approval)

    def _decide(self, request, target_status):
        approval = self.get_object()
        require_matching_etag(request, approval)
        serializer = ApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval, version = decide_approval(
            approval=approval,
            target_status=target_status,
            note=serializer.validated_data.get("note", ""),
            actor_employee=self.actor_employee(),
            request=request,
        )
        approval = approvals_with_context(ApprovalRequest.objects.filter(pk=approval.pk)).get()
        response = self.response_with_etag({"data": ApprovalDetailSerializer(approval).data}, approval)
        if version:
            from apps.core.api.concurrency import etag_for_instance

            response["Quotation-Version-ETag"] = etag_for_instance(version)
        return response


    @extend_schema(request=ApprovalDecisionSerializer, responses=ApprovalDetailSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, ApprovalStatus.APPROVED)

    @extend_schema(request=ApprovalDecisionSerializer, responses=ApprovalDetailSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, ApprovalStatus.REJECTED)

    @extend_schema(request=ApprovalCancelSerializer, responses=ApprovalDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        approval = self.get_object()
        require_matching_etag(request, approval)
        serializer = ApprovalCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval, version = cancel_approval(
            approval=approval,
            reason=serializer.validated_data["reason"],
            actor_employee=self.actor_employee(),
            request=request,
        )
        approval = approvals_with_context(ApprovalRequest.objects.filter(pk=approval.pk)).get()
        response = self.response_with_etag({"data": ApprovalDetailSerializer(approval).data}, approval)
        if version:
            from apps.core.api.concurrency import etag_for_instance

            response["Quotation-Version-ETag"] = etag_for_instance(version)
        return response


class SlaTrackingViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = SlaTrackingSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ["next_deadline_at", "started_at", "completed_at", "created_at"]
    ordering = ["next_deadline_at", "-started_at", "-id"]
    action_permission_map = {
        "list": "workflow.view_slatracking",
        "retrieve": "workflow.view_slatracking",
    }

    def get_queryset(self):
        queryset = accessible_sla_trackings(self.request)
        status_value = self.request.query_params.get("status")
        target_type = self.request.query_params.get("target_type")
        if status_value:
            queryset = queryset.filter(status=status_value)
        if target_type:
            queryset = queryset.filter(sla_policy__target_type=target_type)
        return sla_trackings_with_context(queryset)

    def retrieve(self, request, *args, **kwargs):
        tracking = self.get_object()
        return self.response_with_etag({"data": self.get_serializer(tracking).data}, tracking)
