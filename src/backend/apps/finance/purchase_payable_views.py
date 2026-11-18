from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from .purchase_payable_models import PurchasePayable
from .purchase_payable_selectors import purchase_payables
from .purchase_payable_serializers import (
    PurchasePayablePageSerializer,
    PurchasePayablePricingSerializer,
    PurchasePayableQuerySerializer,
    PurchasePayableResponseSerializer,
    PurchasePayableSerializer,
    PurchasePayableVoidSerializer,
)
from . import purchase_payable_services


class PurchasePayableViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = PurchasePayableSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]
    action_permission_map = {
        "list": "finance.view_purchasepayable",
        "retrieve": "finance.view_purchasepayable",
        "pricing": "finance.change_purchasepayable",
        "confirm": "finance.confirm_purchasepayable",
        "void": "finance.void_purchasepayable",
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PurchasePayable.objects.none()
        query = PurchasePayableQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return purchase_payables(query.validated_data, detail=self.action == "retrieve")

    def payable_response(self, payable, *, status=200):
        current = purchase_payables(detail=True).get(pk=payable.pk)
        return Response(
            {"data": PurchasePayableSerializer(current).data},
            status=status,
            headers={"ETag": etag_for_instance(current)},
        )

    @extend_schema(parameters=[PurchasePayableQuerySerializer], responses=PurchasePayablePageSerializer)
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=PurchasePayableResponseSerializer)
    def retrieve(self, request, *args, **kwargs):
        return self.payable_response(self.get_object())

    @extend_schema(
        request=PurchasePayablePricingSerializer,
        responses=PurchasePayableResponseSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    @action(detail=True, methods=["patch"])
    def pricing(self, request, pk=None):
        serializer = PurchasePayablePricingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payable = purchase_payable_services.update_payable_pricing(request, pk, serializer.validated_data)
        return self.payable_response(payable)

    @extend_schema(
        request=None,
        responses=PurchasePayableResponseSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        payable = purchase_payable_services.confirm_payable(request, pk)
        return self.payable_response(payable)

    @extend_schema(
        request=PurchasePayableVoidSerializer,
        responses=PurchasePayableResponseSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        serializer = PurchasePayableVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payable = purchase_payable_services.void_payable(request, pk, serializer.validated_data["reason"])
        return self.payable_response(payable)
