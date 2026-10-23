from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from .statement_models import ReceivableStatement
from .statement_selectors import statements
from .statement_serializers import StatementQuerySerializer, StatementResponseSerializer, StatementSerializer, StatementVoidSerializer, StatementWriteSerializer
from . import statement_services


class ReceivableStatementViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = StatementSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    action_permission_map = {"list": "finance.view_receivablestatement", "retrieve": "finance.view_receivablestatement",
        "create": "finance.add_receivablestatement", "partial_update": "finance.change_receivablestatement", "void": "finance.void_receivablestatement",
        "destroy": "finance.delete_receivablestatement"}

    @extend_schema(responses={204: None}, parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    def destroy(self, request, pk=None):
        from .deletion_services import delete_statement
        delete_statement(request, pk)
        return Response(status=204)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ReceivableStatement.objects.none()
        return statements(detail=self.action != "list")

    def statement_response(self, statement, status=200, changed=None):
        from .settlement_selectors import settlement_totals_for_statements
        current = get_object_or_404(statements(detail=True), pk=statement.pk)
        data = StatementSerializer(current, context={"totals": settlement_totals_for_statements([current])}).data
        if changed is not None:
            data["changed"] = changed
        return Response({"data": data}, status=status, headers={"ETag": etag_for_instance(current)})

    @extend_schema(parameters=[StatementQuerySerializer])
    def list(self, request):
        from .settlement_selectors import settlement_totals_for_statements
        query = StatementQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = self.paginate_queryset(statements(query.validated_data))
        return self.get_paginated_response(StatementSerializer(page, many=True, context={"totals": settlement_totals_for_statements(page)}).data)

    @extend_schema(responses=StatementResponseSerializer)
    def retrieve(self, request, pk=None):
        return self.statement_response(get_object_or_404(ReceivableStatement, pk=pk))

    @extend_schema(request=StatementWriteSerializer, responses={201: StatementResponseSerializer, 200: StatementResponseSerializer},
                   parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)])
    def create(self, request):
        statement, replayed = statement_services.create_statement(request)
        response = self.statement_response(statement, 200 if replayed else 201)
        if replayed:
            response["Idempotent-Replayed"] = "true"
        return response

    @extend_schema(request=StatementWriteSerializer, responses=StatementResponseSerializer,
                   parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    def partial_update(self, request, pk=None):
        serializer = StatementWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.statement_response(statement_services.update_statement(request, pk, serializer.validated_data))

    @extend_schema(request=StatementVoidSerializer, responses=StatementResponseSerializer,
                   parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        serializer = StatementVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        statement, changed = statement_services.void_statement(request, pk, serializer.validated_data["reason"])
        return self.statement_response(statement, changed=changed)
