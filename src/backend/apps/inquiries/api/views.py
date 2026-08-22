from django.db import IntegrityError
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.core.api.concurrency import require_matching_etag
from apps.customers.api.views import CustomerApiViewSetBase
from apps.workflow.api.serializers import TaskListSerializer
from apps.workflow.selectors import tasks_with_context

from ..models import Inquiry, InquiryItem
from ..selectors import accessible_inquiries, inquiries_with_context
from ..services import (
    create_inquiry,
    create_inquiry_item,
    delete_inquiry_item,
    link_inquiry_file,
    transition_inquiry,
    update_inquiry,
    update_inquiry_item,
)
from .filters import InquiryFilter
from .serializers import (
    InquiryActionSerializer,
    InquiryCreateSerializer,
    InquiryDetailSerializer,
    InquiryFileLinkCreateSerializer,
    InquiryFileLinkSerializer,
    InquiryItemSerializer,
    InquiryItemUpdateSerializer,
    InquiryListSerializer,
    InquiryReasonSerializer,
    InquiryUpdateSerializer,
)


class InquiryViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = InquiryDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = InquiryFilter
    search_fields = ["inquiry_number", "subject", "description", "customer_account__account_name"]
    ordering_fields = ["received_at", "requested_due_at", "submitted_at", "created_at", "updated_at"]
    ordering = ["-received_at", "-id"]
    action_permission_map = {
        "list": "inquiries.view_inquiry",
        "retrieve": "inquiries.view_inquiry",
        "create": "inquiries.add_inquiry",
        "partial_update": "inquiries.change_inquiry",
        "submit": "inquiries.change_inquiry",
        "start": "inquiries.change_inquiry",
        "mark_quoted": "inquiries.change_inquiry",
        "close": "inquiries.change_inquiry",
        "cancel": "inquiries.change_inquiry",
        "items.GET": "inquiries.view_inquiryitem",
        "items.POST": "inquiries.add_inquiryitem",
        "files.GET": "inquiries.view_inquiryfilelink",
        "files.POST": "inquiries.add_inquiryfilelink",
        "tasks": "workflow.view_businesstask",
    }

    def get_queryset(self):
        scope = self.action_permission_codename("view_inquiry")
        queryset = accessible_inquiries(self.request, scope)
        if self.request.method not in SAFE_METHODS:
            queryset = queryset.filter(
                archived_at__isnull=True,
                customer_account__archived_at__isnull=True,
            )
        elif self.request.query_params.get("archived", "false").lower() != "all":
            archived = self.request.query_params.get("archived", "false").lower()
            queryset = queryset.filter(archived_at__isnull=archived != "true")
        return inquiries_with_context(queryset)

    def get_serializer_class(self):
        if self.action == "list":
            return InquiryListSerializer
        if self.action == "create":
            return InquiryCreateSerializer
        if self.action == "partial_update":
            return InquiryUpdateSerializer
        return InquiryDetailSerializer

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
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk)).get()
        return self.response_with_etag(
            {"data": InquiryDetailSerializer(inquiry).data},
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
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk)).get()
        return self.response_with_etag({"data": InquiryDetailSerializer(inquiry).data}, inquiry)

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
        inquiry = inquiries_with_context(Inquiry.objects.filter(pk=inquiry.pk)).get()
        return self.response_with_etag({"data": InquiryDetailSerializer(inquiry).data}, inquiry)

    @extend_schema(request=InquiryActionSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._transition(request, "SUBMITTED")

    @extend_schema(request=InquiryActionSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        return self._transition(request, "STARTED")

    @extend_schema(request=InquiryActionSerializer, responses=InquiryDetailSerializer)
    @action(detail=True, methods=["post"], url_path="mark-quoted")
    def mark_quoted(self, request, pk=None):
        return self._transition(request, "MARKED_QUOTED")

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
            response = self.response_with_etag(
                {"data": InquiryItemSerializer(inquiry.items.all(), many=True).data},
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

    @extend_schema(responses=TaskListSerializer(many=True))
    @action(detail=True, methods=["get"])
    def tasks(self, request, pk=None):
        inquiry = self.get_object()
        task_ids = inquiry.task_links.values_list("business_task_id", flat=True)
        tasks = tasks_with_context().filter(pk__in=task_ids, archived_at__isnull=True)
        return Response({"data": TaskListSerializer(tasks, many=True).data})


class InquiryItemViewSet(
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    http_method_names = ["patch", "delete", "options"]
    serializer_class = InquiryItemUpdateSerializer
    action_permission_map = {
        "partial_update": "inquiries.change_inquiryitem",
        "destroy": "inquiries.delete_inquiryitem",
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
