from django.db import IntegrityError
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.core.api.concurrency import require_matching_etag
from apps.customers.api.views import CustomerApiViewSetBase
from apps.customers.selectors import accessible_customers

from ..models import ApprovalRequest, ApprovalStatus, BusinessTask, SlaTracking
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
    TaskUpdateSerializer,
)


class TaskViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
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
        "partial_update": "workflow.change_businesstask",
        "start": "workflow.change_businesstask",
        "complete": "workflow.change_businesstask",
        "cancel": "workflow.change_businesstask",
        "reassign": "workflow.change_businesstask",
    }

    def get_queryset(self):
        queryset = accessible_tasks(self.request)
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
            if not accessible_customers(request, "add_businesstask").filter(pk=customer.pk).exists():
                raise NotFound("任务来源不存在或无权访问。")
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
            {"data": TaskDetailSerializer(task).data},
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
        return self.response_with_etag({"data": TaskDetailSerializer(task).data}, task)

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
        return self.response_with_etag({"data": TaskDetailSerializer(task).data}, task)

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
        return self.response_with_etag({"data": TaskDetailSerializer(task).data}, task)


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
