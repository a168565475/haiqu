from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from . import selectors, services
from .serializers import AccountQuerySerializer, AccountResponseSerializer, AccountSerializer, AccountWriteSerializer


class FinanceAccountViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = AccountSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    action_permission_map = {
        "list": "finance.view_financeaccount", "retrieve": "finance.view_financeaccount",
        "create": "finance.add_financeaccount", "partial_update": "finance.change_financeaccount",
        "destroy": "finance.delete_financeaccount",
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return selectors.accounts().none()
        query = AccountQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return selectors.accounts(query.validated_data if self.action == "list" else {})

    def get_serializer_class(self):
        return AccountWriteSerializer if self.action in ("create", "partial_update") else AccountSerializer

    def account_response(self, account, status=200):
        return Response({"data": AccountSerializer(account).data}, status=status, headers={"ETag": etag_for_instance(account)})

    @extend_schema(parameters=[AccountQuerySerializer])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=AccountResponseSerializer)
    def retrieve(self, request, *args, **kwargs):
        return self.account_response(self.get_object())

    @extend_schema(request=AccountWriteSerializer, responses={201: AccountResponseSerializer, 200: AccountResponseSerializer},
                   parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)])
    def create(self, request):
        account, replayed = services.create_account(request)
        response = self.account_response(account, 200 if replayed else 201)
        if replayed:
            response["Idempotent-Replayed"] = "true"
        return response

    @extend_schema(request=AccountWriteSerializer, responses=AccountResponseSerializer,
                   parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    def partial_update(self, request, pk=None):
        serializer = AccountWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return self.account_response(services.update_account(request, pk, serializer.validated_data))

    @extend_schema(responses={204: None}, parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    def destroy(self, request, pk=None):
        services.delete_account(request, pk)
        return Response(status=204)
