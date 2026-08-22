from django.db import IntegrityError
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.customers.api.views import CustomerApiViewSetBase
from apps.workflow.api.serializers import TaskListSerializer
from apps.workflow.selectors import tasks_with_context

from ..models import SampleItem, SampleRequest, SampleShipment
from ..selectors import accessible_sample_requests, sample_requests_with_context, shipments_with_context
from ..services import (
    create_fee_record,
    create_feedback,
    create_sample_item,
    create_sample_request,
    create_shipment,
    delete_sample_item,
    deliver_sample,
    link_sample_file,
    ship_sample,
    transition_sample_request,
    update_sample_item,
    update_sample_request,
)
from .filters import SampleRequestFilter
from .serializers import (
    SampleActionSerializer,
    SampleFeeRecordCreateSerializer,
    SampleFeeRecordSerializer,
    SampleFeedbackCreateSerializer,
    SampleFeedbackSerializer,
    SampleFileLinkCreateSerializer,
    SampleFileLinkSerializer,
    SampleItemSerializer,
    SampleItemUpdateSerializer,
    SampleReasonSerializer,
    SampleRequestCreateSerializer,
    SampleRequestDetailSerializer,
    SampleRequestListSerializer,
    SampleRequestUpdateSerializer,
    SampleShipmentCreateSerializer,
    SampleShipmentSerializer,
    SampleShipSerializer,
)


class SampleRequestViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = SampleRequestDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = SampleRequestFilter
    search_fields = ["request_number", "purpose", "notes", "customer_account__account_name"]
    ordering_fields = ["requested_at", "requested_due_at", "created_at", "updated_at"]
    ordering = ["-requested_at", "-id"]
    action_permission_map = {
        "list": "samples.view_samplerequest",
        "retrieve": "samples.view_samplerequest",
        "create": "samples.add_samplerequest",
        "partial_update": "samples.change_samplerequest",
        "items.GET": "samples.view_sampleitem",
        "items.POST": "samples.add_sampleitem",
        "submit": "samples.change_samplerequest",
        "start_preparing": "samples.change_samplerequest",
        "fee_records.GET": "samples.view_samplefeerecord",
        "fee_records.POST": "samples.decide_sample_fee",
        "shipments.GET": "samples.view_sampleshipment",
        "shipments.POST": "samples.add_sampleshipment",
        "feedback.GET": "samples.view_samplefeedback",
        "feedback.POST": "samples.add_samplefeedback",
        "files.GET": "samples.view_samplefilelink",
        "files.POST": "samples.add_samplefilelink",
        "tasks": "workflow.view_businesstask",
        "complete": "samples.change_samplerequest",
        "cancel": "samples.change_samplerequest",
    }

    def get_queryset(self):
        permission = self.action_permission_codename("view_samplerequest")
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

    def get_serializer_class(self):
        if self.action == "list":
            return SampleRequestListSerializer
        if self.action == "create":
            return SampleRequestCreateSerializer
        if self.action == "partial_update":
            return SampleRequestUpdateSerializer
        return SampleRequestDetailSerializer

    def create(self, request, *args, **kwargs):
        if self.actor_employee() is None:
            raise PermissionDenied("创建样品申请需要绑定有效员工档案。")
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
            {"data": SampleRequestDetailSerializer(sample_request).data},
            sample_request,
            status.HTTP_201_CREATED,
        )

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
            {"data": SampleRequestDetailSerializer(sample_request).data},
            sample_request,
        )

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
            {"data": SampleRequestDetailSerializer(sample_request).data},
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

    @extend_schema(request=SampleReasonSerializer, responses=SampleRequestDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._transition(request, "CANCELLED", SampleReasonSerializer)

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

    @extend_schema(responses=TaskListSerializer(many=True))
    @action(detail=True, methods=["get"])
    def tasks(self, request, pk=None):
        sample_request = self.get_object()
        task_ids = sample_request.task_links.values_list("business_task_id", flat=True)
        tasks = tasks_with_context().filter(pk__in=task_ids, archived_at__isnull=True)
        return Response({"data": TaskListSerializer(tasks, many=True).data})


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


class SampleShipmentViewSet(CustomerApiViewSetBase):
    http_method_names = ["post", "options"]
    serializer_class = SampleShipmentSerializer
    action_permission_map = {
        "ship": "samples.ship_sample",
        "deliver": "samples.change_sampleshipment",
    }

    def get_queryset(self):
        permission = self.action_permission_codename("change_sampleshipment")
        requests = accessible_sample_requests(self.request, permission).filter(
            archived_at__isnull=True,
            customer_account__archived_at__isnull=True,
        )
        return shipments_with_context(SampleShipment.objects.filter(sample_request__in=requests))

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
