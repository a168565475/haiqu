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

from ..models import Quotation, QuotationLine, QuotationTemplate, QuotationVersion
from ..selectors import accessible_quotations, quotations_with_context, versions_with_context
from ..services import (
    create_line,
    create_quotation,
    create_tier,
    create_version,
    delete_line,
    dispatch_version,
    issue_version,
    lock_version,
    register_formal_document,
    submit_version_approval,
    transition_quotation,
    update_line,
    update_quotation,
    update_version,
    void_version,
)
from .filters import QuotationFilter
from .serializers import (
    EmptyActionSerializer,
    QuotationAcceptSerializer,
    QuotationApprovalSubmitSerializer,
    QuotationCreateSerializer,
    QuotationDetailSerializer,
    QuotationDispatchCreateSerializer,
    QuotationDispatchSerializer,
    QuotationDocumentCreateSerializer,
    QuotationDocumentSerializer,
    QuotationLineSerializer,
    QuotationLineUpdateSerializer,
    QuotationListSerializer,
    QuotationLockSerializer,
    QuotationQuantityTierSerializer,
    QuotationReasonSerializer,
    QuotationTemplateSerializer,
    QuotationUpdateSerializer,
    QuotationVersionCreateSerializer,
    QuotationVersionDetailSerializer,
    QuotationVersionListSerializer,
    QuotationVersionUpdateSerializer,
)


class QuotationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = QuotationDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = QuotationFilter
    search_fields = ["quotation_number", "subject", "customer_account__account_name"]
    ordering_fields = ["created_at", "updated_at", "quotation_number"]
    ordering = ["-updated_at", "-id"]
    action_permission_map = {
        "list": "quotations.view_quotation",
        "retrieve": "quotations.view_quotation",
        "create": "quotations.add_quotation",
        "partial_update": "quotations.change_quotation",
        "versions.GET": "quotations.view_quotationversion",
        "versions.POST": "quotations.add_quotationversion",
        "accept": "quotations.accept_quotation",
        "lose": "quotations.change_quotation",
        "cancel": "quotations.change_quotation",
    }

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
        return quotations_with_context(queryset)

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
            {"data": QuotationDetailSerializer(quotation).data},
            quotation,
            status.HTTP_201_CREATED,
        )

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
        return self.response_with_etag({"data": QuotationDetailSerializer(quotation).data}, quotation)

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
            {"data": QuotationVersionDetailSerializer(version).data},
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
        )
        quotation = quotations_with_context(Quotation.objects.filter(pk=quotation.pk)).get()
        return self.response_with_etag({"data": QuotationDetailSerializer(quotation).data}, quotation)

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
    }


class QuotationVersionViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    CustomerApiViewSetBase,
):
    http_method_names = ["get", "patch", "post", "options"]
    serializer_class = QuotationVersionDetailSerializer
    action_permission_map = {
        "retrieve": "quotations.view_quotationversion",
        "partial_update": "quotations.change_quotationversion",
        "lines.GET": "quotations.view_quotationline",
        "lines.POST": "quotations.add_quotationline",
        "lock": "quotations.change_quotationversion",
        "submit_approval": "quotations.change_quotationversion",
        "issue": "quotations.issue_quotation",
        "generate_document": "quotations.issue_quotation",
        "dispatch_quote": "quotations.dispatch_quotation",
        "documents": "quotations.view_quotationdocument",
        "dispatches": "quotations.view_quotationdispatchrecord",
        "tasks": "workflow.view_businesstask",
        "void": "quotations.change_quotationversion",
    }

    def get_queryset(self):
        permission = self.action_permission_codename("view_quotationversion")
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
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version).data}, version)

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
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version).data}, version)

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
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version).data}, version)

    @extend_schema(request=EmptyActionSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        return self._simple_action(request, issue_version, EmptyActionSerializer)

    @extend_schema(request=QuotationDocumentCreateSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"], url_path="generate-document")
    def generate_document(self, request, pk=None):
        return self._simple_action(request, register_formal_document, QuotationDocumentCreateSerializer)

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
        return self.response_with_etag({"data": QuotationVersionDetailSerializer(version).data}, version)

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
        tasks = tasks_with_context().filter(pk__in=task_ids, archived_at__isnull=True)
        return Response({"data": TaskListSerializer(tasks, many=True).data})

    @extend_schema(request=QuotationReasonSerializer, responses=QuotationVersionDetailSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        return self._simple_action(request, void_version, QuotationReasonSerializer)


class QuotationLineViewSet(
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    CustomerApiViewSetBase,
):
    http_method_names = ["patch", "delete", "get", "post", "options"]
    serializer_class = QuotationLineUpdateSerializer
    action_permission_map = {
        "partial_update": "quotations.change_quotationline",
        "destroy": "quotations.delete_quotationline",
        "quantity_tiers.GET": "quotations.view_quotationquantitytier",
        "quantity_tiers.POST": "quotations.add_quotationquantitytier",
    }

    def get_queryset(self):
        permission = self.action_permission_codename("change_quotationline")
        quotations = accessible_quotations(self.request, permission).filter(
            archived_at__isnull=True,
            customer_account__archived_at__isnull=True,
        )
        return QuotationLine.objects.filter(
            quotation_version__quotation__in=quotations
        ).select_related("quotation_version", "quotation_version__quotation").prefetch_related("quantity_tiers")

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
