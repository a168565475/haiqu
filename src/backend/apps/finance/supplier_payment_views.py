from calendar import monthrange
from datetime import date

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access_control import module_policy, sales_policy
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee

from . import supplier_payment_application_services as application_services
from . import supplier_settlement_services as settlements
from .supplier_ledger_serializers import (
    SupplierLedgerEntryQuerySerializer, SupplierLedgerOptionSerializer, SupplierLedgerOptionsResponseSerializer,
    SupplierLedgerPageMetaSerializer, SupplierLedgerQuerySerializer,
)
from .supplier_ledger_views import IDEMPOTENCY, MATCH, PAY, SupplierLedgerPagination, document_response, envelope, supplier_payment_options
from .supplier_payment_application_models import SupplierPaymentApplication
from .supplier_payment_application_selectors import (
    application_details, applications, due_payables_by_supplier, due_requestable_payables, payable_months,
)
from .supplier_payment_application_serializers import (
    SupplierApplicationCreateSerializer, SupplierApplicationDetailSerializer, SupplierApplicationMonthSerializer,
    SupplierApplicationPayablesQuerySerializer, SupplierApplicationRowSerializer,
    SupplierDuePayableDetailSerializer, SupplierDuePayablesSummarySerializer,
)
from .supplier_settlement_models import SupplierPayment
from .supplier_settlement_selectors import payment_documents, payment_suppliers
from .supplier_settlement_serializers import (
    PaymentOptionsSerializer, SettlementVoidSerializer, SupplierPaymentRegistrationSerializer, SupplierPaymentSerializer,
)


VIEW = "finance.view_supplierpayment"
APPLY = "finance.add_supplierpaymentapplication"
WITHDRAW = "finance.withdraw_supplierpaymentapplication"
VOID_PAYMENT = "finance.void_supplierpayment"


class SupplierPaymentRecordSerializer(SupplierPaymentSerializer):
    application_id = serializers.UUIDField(allow_null=True)
    application_number = serializers.CharField(source="application.number", allow_null=True)


PAYMENT = envelope("SupplierPaymentRecordResponse", SupplierPaymentRecordSerializer())
APPLICATION = envelope("SupplierPaymentApplicationResponse", SupplierApplicationDetailSerializer())


class SupplierPaymentViewBase(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    pagination_class = SupplierLedgerPagination
    lookup_value_regex = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"

    def check_permissions(self, request):
        super().check_permissions(request)
        policy = module_policy if module_policy.enabled() else sales_policy
        if not policy.has_permission(request, VIEW):
            raise PermissionDenied("当前账号没有供应商付款查看权限。")

    def list_documents(self, request, queryset, date_field):
        query = SupplierLedgerQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        start = date.fromisoformat(f"{query.validated_data['month']}-01")
        end = start.replace(day=monthrange(start.year, start.month)[1])
        filters = {f"{date_field}__range": (start, end)}
        if supplier_id := query.validated_data.get("supplier_id"):
            filters["supplier_id"] = supplier_id
        rows = self.paginate_queryset(queryset.filter(**filters))
        return self.get_paginated_response(self.get_serializer(rows, many=True).data)


class SupplierPaymentViewSet(SupplierPaymentViewBase):
    queryset = SupplierPayment.objects.none()
    serializer_class = SupplierPaymentRecordSerializer
    action_permission_map = {
        **dict.fromkeys(("list", "retrieve", "suppliers", "due_payables", "due_payable_details", "metadata"), VIEW),
        "payment_options": PAY, "create": PAY, "void": VOID_PAYMENT,
    }

    def documents(self):
        return payment_documents().select_related("application")

    @extend_schema(parameters=[SupplierLedgerQuerySerializer], responses=inline_serializer(
        "SupplierPaymentRecordPage", fields={"data": SupplierPaymentRecordSerializer(many=True), "meta": SupplierLedgerPageMetaSerializer()},
    ))
    def list(self, request):
        rows = self.documents().order_by("-business_date", "-number", "-id")
        return self.list_documents(request, rows, "business_date")

    @extend_schema(responses=PAYMENT)
    def retrieve(self, request, pk=None):
        return document_response(get_object_or_404(self.documents(), pk=pk), self.serializer_class)

    @extend_schema(request=SupplierPaymentRegistrationSerializer, parameters=[MATCH, IDEMPOTENCY],
                   responses={200: PAYMENT, 201: PAYMENT})
    def create(self, request):
        payment, replayed = settlements.create_payment(request, allow_application=True)
        return document_response(self.documents().get(pk=payment.pk), self.serializer_class,
                                 status=200 if replayed else 201, replayed=replayed)

    @extend_schema(responses=SupplierLedgerOptionsResponseSerializer)
    @action(detail=False, methods=["get"], pagination_class=None)
    def suppliers(self, request):
        return Response({"data": SupplierLedgerOptionSerializer(payment_suppliers(), many=True).data})

    @extend_schema(parameters=[SupplierLedgerQuerySerializer], responses=inline_serializer(
        "SupplierDuePayablesPage",
        fields={"data": SupplierDuePayablesSummarySerializer(many=True), "meta": SupplierLedgerPageMetaSerializer()},
    ))
    @action(detail=False, methods=["get"], url_path="due-payables")
    def due_payables(self, request):
        query = SupplierLedgerQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        month = date.fromisoformat(f"{query.validated_data['month']}-01")
        rows = self.paginate_queryset(due_payables_by_supplier(month, query.validated_data.get("supplier_id")))
        return self.get_paginated_response(SupplierDuePayablesSummarySerializer(rows, many=True).data)

    @extend_schema(parameters=[SupplierLedgerEntryQuerySerializer], responses=inline_serializer(
        "SupplierDuePayableDetailsPage",
        fields={"data": SupplierDuePayableDetailSerializer(many=True), "meta": SupplierLedgerPageMetaSerializer()},
    ))
    @action(detail=False, methods=["get"], url_path="due-payable-details")
    def due_payable_details(self, request):
        query = SupplierLedgerEntryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        supplier = get_object_or_404(payment_suppliers(), pk=query.validated_data["supplier_id"])
        month = date.fromisoformat(f"{query.validated_data['month']}-01")
        rows = self.paginate_queryset(due_requestable_payables(month, supplier.pk))
        return self.get_paginated_response(SupplierDuePayableDetailSerializer(rows, many=True).data)

    @extend_schema(responses=envelope("SupplierPaymentStandaloneOptions", PaymentOptionsSerializer()))
    @action(detail=False, methods=["get"], url_path="payment-options", pagination_class=None)
    def payment_options(self, request):
        return Response({"data": supplier_payment_options()})

    @extend_schema(request=SettlementVoidSerializer, parameters=[MATCH], responses=PAYMENT)
    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        body = SettlementVoidSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        payment = settlements.void_payment(request, pk, body.validated_data["reason"])
        return document_response(self.documents().get(pk=payment.pk), self.serializer_class)


class SupplierPaymentApplicationViewSet(SupplierPaymentViewBase):
    queryset = SupplierPaymentApplication.objects.none()
    serializer_class = SupplierApplicationRowSerializer
    action_permission_map = {
        **dict.fromkeys(("list", "retrieve", "metadata"), VIEW),
        "eligible_payables": APPLY, "create": APPLY, "withdraw": WITHDRAW,
    }

    @extend_schema(parameters=[SupplierLedgerQuerySerializer], responses=inline_serializer(
        "SupplierPaymentApplicationPage", fields={"data": SupplierApplicationRowSerializer(many=True), "meta": SupplierLedgerPageMetaSerializer()},
    ))
    def list(self, request):
        return self.list_documents(request, applications(), "applied_on")

    @extend_schema(responses=APPLICATION)
    def retrieve(self, request, pk=None):
        application = get_object_or_404(application_details(), pk=pk)
        return document_response(application, SupplierApplicationDetailSerializer)

    @extend_schema(request=SupplierApplicationCreateSerializer, parameters=[IDEMPOTENCY],
                   responses={200: APPLICATION, 201: APPLICATION})
    def create(self, request):
        application, replayed = application_services.create_application(request)
        return document_response(application_details().get(pk=application.pk), SupplierApplicationDetailSerializer,
                                 status=200 if replayed else 201, replayed=replayed)

    @extend_schema(parameters=[SupplierApplicationPayablesQuerySerializer],
                   responses=envelope("SupplierApplicationPayableMonths", SupplierApplicationMonthSerializer(many=True)))
    @action(detail=False, methods=["get"], url_path="eligible-payables", pagination_class=None)
    def eligible_payables(self, request):
        query = SupplierApplicationPayablesQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        supplier = get_object_or_404(payment_suppliers(), pk=query.validated_data["supplier_id"])
        months = payable_months(supplier.pk, query.validated_data.get("due_through_month"))
        return Response({"data": SupplierApplicationMonthSerializer(months, many=True).data})

    @extend_schema(request=SettlementVoidSerializer, parameters=[MATCH], responses=APPLICATION)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        body = SettlementVoidSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        application = application_services.withdraw_application(request, pk, body.validated_data["reason"])
        return document_response(application_details().get(pk=application.pk), SupplierApplicationDetailSerializer)
