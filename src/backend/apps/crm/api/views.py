from django.db import IntegrityError
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import SAFE_METHODS

from apps.core.api.concurrency import require_matching_etag
from apps.customers.api.serializers import ArchiveSerializer
from apps.customers.api.views import CustomerApiViewSetBase
from apps.customers.selectors import accessible_customers
from apps.customers.services import archive_resource

from ..models import CustomerCommunication
from ..selectors import communications_with_details
from ..services import create_communication, update_communication
from .filters import CommunicationFilter
from .serializers import (
    CommunicationCreateSerializer,
    CommunicationDetailSerializer,
    CommunicationListSerializer,
    CommunicationUpdateSerializer,
)


class CommunicationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    CustomerApiViewSetBase,
):
    serializer_class = CommunicationDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = CommunicationFilter
    search_fields = ["subject", "content", "customer_account__account_name"]
    ordering_fields = ["occurred_at", "created_at", "updated_at"]
    ordering = ["-occurred_at", "-id"]
    action_permission_map = {
        "list": "crm.view_customercommunication",
        "retrieve": "crm.view_customercommunication",
        "create": "crm.add_customercommunication",
        "partial_update": "crm.change_customercommunication",
        "archive": "crm.change_customercommunication",
    }

    def get_queryset(self):
        scope = self.action_permission_codename("view_customercommunication")
        queryset = CustomerCommunication.objects.filter(
            customer_account__in=accessible_customers(self.request, scope)
        )
        if self.request.method not in SAFE_METHODS:
            queryset = queryset.filter(
                archived_at__isnull=True,
                customer_account__archived_at__isnull=True,
            )
        elif self.request.query_params.get("archived", "false").lower() != "all":
            archived = self.request.query_params.get("archived", "false").lower()
            queryset = queryset.filter(archived_at__isnull=archived != "true")
        return communications_with_details(queryset)

    def get_serializer_class(self):
        if self.action == "list":
            return CommunicationListSerializer
        if self.action == "create":
            return CommunicationCreateSerializer
        if self.action == "partial_update":
            return CommunicationUpdateSerializer
        return CommunicationDetailSerializer

    def create(self, request, *args, **kwargs):
        if self.actor_employee() is None:
            raise PermissionDenied("创建沟通记录需要绑定有效员工档案。")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = serializer.validated_data["customer_account"]
        if not accessible_customers(request, "add_customercommunication").filter(pk=customer.pk).exists():
            raise NotFound("客户不存在或无权访问。")
        try:
            communication = create_communication(
                validated_data=dict(serializer.validated_data),
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        communication = communications_with_details(
            CustomerCommunication.objects.filter(pk=communication.pk)
        ).get()
        output = CommunicationDetailSerializer(communication, context=self.get_serializer_context())
        return self.response_with_etag({"data": output.data}, communication, status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        communication = self.get_object()
        return self.response_with_etag(
            {"data": self.get_serializer(communication).data},
            communication,
        )

    def partial_update(self, request, *args, **kwargs):
        communication = self.get_object()
        require_matching_etag(request, communication)
        serializer = self.get_serializer(communication, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            communication = update_communication(
                communication=communication,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            self.raise_integrity_validation_error(exc)
        communication = communications_with_details(
            CustomerCommunication.objects.filter(pk=communication.pk)
        ).get()
        return self.response_with_etag(
            {"data": CommunicationDetailSerializer(communication).data},
            communication,
        )

    @staticmethod
    def _archive_serializer(request):
        serializer = ArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer

    @extend_schema(request=ArchiveSerializer, responses=CommunicationDetailSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        communication = self.get_object()
        require_matching_etag(request, communication)
        serializer = self._archive_serializer(request)
        communication = archive_resource(
            instance=communication,
            reason=serializer.validated_data["reason"],
            actor_employee=self.actor_employee(),
            request=request,
            object_type="CUSTOMER_COMMUNICATION",
            customer=communication.customer_account,
        )
        return self.response_with_etag(
            {"data": CommunicationDetailSerializer(communication).data},
            communication,
        )
