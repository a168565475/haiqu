from calendar import monthrange
from datetime import date

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access_control import module_policy, sales_policy
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.pagination import StandardPageNumberPagination
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee

from .supplier_ledger_selectors import entry_rows, month_entries, month_summary, supplier_options
from .supplier_ledger_serializers import (
    SupplierLedgerEntryPageSerializer,
    SupplierLedgerEntryQuerySerializer,
    SupplierLedgerEntrySerializer,
    SupplierLedgerOptionSerializer,
    SupplierLedgerOptionsResponseSerializer,
    SupplierLedgerQuerySerializer,
    SupplierLedgerSummaryPageSerializer,
    SupplierLedgerSummarySerializer,
)
from . import supplier_settlement_services as settlements
from .selectors import available_cny_accounts
from .supplier_settlement_selectors import (
    ACTIVE, eligible_payables, offset_documents, payment_amounts, payment_documents, payment_suppliers,
)
from .supplier_settlement_serializers import (
    PayablePickQuerySerializer, PayablePickSerializer, PaymentAccountOptionSerializer, PaymentOptionsSerializer,
    PaymentPickSerializer, SettlementVoidSerializer, SupplierOffsetCreateSerializer, SupplierOffsetSerializer,
    SupplierPaymentCreateSerializer, SupplierPaymentSerializer,
)


VIEW = "finance.view_supplierledger"
PAY = "finance.add_supplierpayment"
OFFSET = "finance.add_supplieroffset"
MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
DOC_ID = r"(?P<document_id>[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})"
DOC_PARAMETER = OpenApiParameter("document_id", OpenApiTypes.UUID, OpenApiParameter.PATH)


def envelope(name, serializer):
    return inline_serializer(name=name, fields={"data": serializer})


PAYMENT_RESPONSE = envelope("SupplierPaymentResponse", SupplierPaymentSerializer())
OFFSET_RESPONSE = envelope("SupplierOffsetResponse", SupplierOffsetSerializer())


def document_response(record, serializer, *, status=200, replayed=False):
    headers = {"ETag": etag_for_instance(record)}
    if replayed:
        headers["Idempotent-Replayed"] = "true"
    return Response({"data": serializer(record).data}, headers=headers, status=status)


def supplier_payment_options():
    accounts = [{"id": row.pk, "name": row.name, "code": row.code, "etag": etag_for_instance(row)}
                for row in available_cny_accounts().order_by("name", "id")]
    return {
        "suppliers": SupplierLedgerOptionSerializer(payment_suppliers(), many=True).data,
        "accounts": PaymentAccountOptionSerializer(accounts, many=True).data,
    }


class SupplierLedgerPagination(StandardPageNumberPagination):
    page_size = 50


class SupplierLedgerViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        **dict.fromkeys(("list", "entries", "suppliers", "payment", "offset"), VIEW),
        "payment_options": PAY, "payments": PAY,
        "offset_options": OFFSET, "offset_payables": OFFSET, "offsets": OFFSET,
        "void_payment": "finance.void_supplierpayment", "void_offset": "finance.void_supplieroffset",
    }
    pagination_class = SupplierLedgerPagination
    serializer_class = SupplierLedgerSummarySerializer

    def check_permissions(self, request):
        super().check_permissions(request)
        has_permission = module_policy.has_permission if module_policy.enabled() else sales_policy.has_permission
        if not has_permission(request, VIEW):
            raise PermissionDenied("当前账号没有供应商往来查看权限。")

    def filters(self, query_serializer):
        query = query_serializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        start = date.fromisoformat(f"{query.validated_data['month']}-01")
        end = start.replace(day=monthrange(start.year, start.month)[1])
        return start, end, query.validated_data.get("supplier_id")

    @extend_schema(parameters=[SupplierLedgerQuerySerializer], responses=SupplierLedgerSummaryPageSerializer)
    def list(self, request):
        rows = self.paginate_queryset(month_summary(*self.filters(SupplierLedgerQuerySerializer)))
        return self.get_paginated_response(SupplierLedgerSummarySerializer(rows, many=True).data)

    @extend_schema(parameters=[SupplierLedgerEntryQuerySerializer], responses=SupplierLedgerEntryPageSerializer)
    @action(detail=False, methods=["get"])
    def entries(self, request):
        start, end, supplier_id = self.filters(SupplierLedgerEntryQuerySerializer)
        supplier = get_object_or_404(supplier_options(), pk=supplier_id)
        lines = self.paginate_queryset(month_entries(start, end, supplier_id))
        response = self.get_paginated_response(SupplierLedgerEntrySerializer(list(entry_rows(request, lines)), many=True).data)
        response.data["meta"]["supplier_name"] = supplier.supplier_name
        return response

    @extend_schema(responses=SupplierLedgerOptionsResponseSerializer)
    @action(detail=False, methods=["get"], pagination_class=None)
    def suppliers(self, request):
        return Response({"data": SupplierLedgerOptionSerializer(supplier_options(), many=True).data})

    @extend_schema(responses=envelope("SupplierPaymentOptionsResponse", PaymentOptionsSerializer()))
    @action(detail=False, methods=["get"], url_path="payment-options")
    def payment_options(self, request):
        return Response({"data": supplier_payment_options()})

    @extend_schema(request=SupplierPaymentCreateSerializer, parameters=[MATCH, IDEMPOTENCY],
                   responses={200: PAYMENT_RESPONSE, 201: PAYMENT_RESPONSE})
    @action(detail=False, methods=["post"])
    def payments(self, request):
        payment, replayed = settlements.create_payment(request)
        return document_response(payment_documents().get(pk=payment.pk), SupplierPaymentSerializer,
                                 status=200 if replayed else 201, replayed=replayed)

    @extend_schema(parameters=[DOC_PARAMETER], responses=PAYMENT_RESPONSE)
    @action(detail=False, methods=["get"], url_path=rf"payments/{DOC_ID}")
    def payment(self, request, document_id):
        return document_response(get_object_or_404(payment_documents(), pk=document_id), SupplierPaymentSerializer)

    @extend_schema(request=SettlementVoidSerializer, parameters=[DOC_PARAMETER, MATCH], responses=PAYMENT_RESPONSE)
    @action(detail=False, methods=["post"], url_path=rf"payments/{DOC_ID}/void")
    def void_payment(self, request, document_id):
        body = SettlementVoidSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        payment = settlements.void_payment(request, document_id, body.validated_data["reason"])
        return document_response(payment_documents().get(pk=payment.pk), SupplierPaymentSerializer)

    @extend_schema(responses=envelope("SupplierOffsetOptionsResponse", PaymentPickSerializer(many=True)))
    @action(detail=False, methods=["get"], url_path="offset-options")
    def offset_options(self, request):
        payments = payment_amounts().filter(status=ACTIVE, available_amount__gt=0).order_by("-business_date", "-number")
        for row in payments:
            row.etag = etag_for_instance(row)
        return Response({"data": PaymentPickSerializer(payments, many=True).data})

    @extend_schema(parameters=[PayablePickQuerySerializer],
                   responses=envelope("SupplierOffsetPayablesResponse", PayablePickSerializer(many=True)))
    @action(detail=False, methods=["get"], url_path="offset-payables")
    def offset_payables(self, request):
        query = PayablePickQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        payment = get_object_or_404(payment_amounts().filter(status=ACTIVE, available_amount__gt=0),
                                    pk=query.validated_data["payment_id"])
        payables = eligible_payables(payment)
        for row in payables:
            row.confirmed_date = timezone.localdate(row.confirmed_at)
        return Response({"data": PayablePickSerializer(payables, many=True).data})

    @extend_schema(request=SupplierOffsetCreateSerializer, parameters=[MATCH, IDEMPOTENCY],
                   responses={200: OFFSET_RESPONSE, 201: OFFSET_RESPONSE})
    @action(detail=False, methods=["post"])
    def offsets(self, request):
        offset, replayed = settlements.create_offset(request)
        return document_response(offset_documents().get(pk=offset.pk), SupplierOffsetSerializer,
                                 status=200 if replayed else 201, replayed=replayed)

    @extend_schema(parameters=[DOC_PARAMETER], responses=OFFSET_RESPONSE)
    @action(detail=False, methods=["get"], url_path=rf"offsets/{DOC_ID}")
    def offset(self, request, document_id):
        return document_response(get_object_or_404(offset_documents(), pk=document_id), SupplierOffsetSerializer)

    @extend_schema(request=SettlementVoidSerializer, parameters=[DOC_PARAMETER, MATCH], responses=OFFSET_RESPONSE)
    @action(detail=False, methods=["post"], url_path=rf"offsets/{DOC_ID}/void")
    def void_offset(self, request, document_id):
        body = SettlementVoidSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        offset = settlements.void_offset(request, document_id, body.validated_data["reason"])
        return document_response(offset_documents().get(pk=offset.pk), SupplierOffsetSerializer)
