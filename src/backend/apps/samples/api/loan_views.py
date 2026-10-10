from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, mixins
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.customers.api.views import CustomerApiViewSetBase, UUID_URL_REGEX

from ..loan_filters import SampleInventoryLoanLineFilter
from ..loan_selectors import (
    available_sample_inventory_lines_for_loan,
    sample_inventory_loans_with_detail,
    sample_loan_lines_with_context,
)
from ..loan_services import create_sample_inventory_loan, delete_sample_inventory_loan
from .loan_serializers import (
    SampleLoanCreateSerializer,
    SampleLoanCreatedEnvelopeSerializer,
    SampleLoanDetailEnvelopeSerializer,
    SampleLoanDetailSerializer,
    SampleLoanEligibleEnvelopeSerializer,
    SampleLoanEligibleInventoryLineSerializer,
    SampleInventoryLoanLineSerializer,
    SampleLoanOptionsEnvelopeSerializer,
    SampleLoanSummaryEnvelopeSerializer,
)


class SampleInventoryLoanLineViewSet(mixins.ListModelMixin, CustomerApiViewSetBase):
    serializer_class = SampleInventoryLoanLineSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = SampleInventoryLoanLineFilter
    search_fields = [
        "loan__loan_number",
        "inventory_line__sample_item__sample_request__request_number",
        "inventory_line__product_name_snapshot",
        "borrower_name",
        "purpose_note",
    ]
    ordering_fields = ["loan__operated_at", "loan_quantity", "borrower_name"]
    ordering = ["-loan__operated_at", "-id"]
    action_permission_map = {
        "list": "samples.view_sampleinventoryloanline",
        "summary": "samples.view_sampleinventoryloanline",
        "options": "samples.view_sampleinventoryloanline",
        "eligible": "samples.add_sampleinventoryloan",
        "documents": "samples.add_sampleinventoryloan",
        "document_detail": "samples.view_sampleinventoryloanline",
        "document_detail.DELETE": "samples.delete_sampleinventoryloan",
    }

    def get_queryset(self):
        return sample_loan_lines_with_context()

    @extend_schema(responses=SampleLoanSummaryEnvelopeSerializer)
    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        customer_filter = Q(purpose_note__icontains="客户") | Q(purpose_note__icontains="确认")
        showroom_filter = Q(purpose_note__icontains="展厅") | Q(purpose_note__icontains="拍摄")
        totals = self.get_queryset().aggregate(
            active_documents=Count("loan_id", distinct=True),
            cumulative_borrowed=Coalesce(Sum("loan_quantity"), Value(0)),
            customer_confirmation=Coalesce(Sum("loan_quantity", filter=customer_filter), Value(0)),
            showroom_or_photo=Coalesce(Sum("loan_quantity", filter=showroom_filter), Value(0)),
        )
        return Response({"data": totals})

    @extend_schema(responses=SampleLoanOptionsEnvelopeSerializer)
    @action(detail=False, methods=["get"], url_path="options")
    def options(self, request):
        queryset = self.get_queryset()
        borrower_names = list(
            queryset.exclude(borrower_name="")
            .order_by("borrower_name")
            .values_list("borrower_name", flat=True)
            .distinct()
        )
        categories = list(
            queryset.exclude(inventory_line__category_name_snapshot="")
            .order_by("inventory_line__category_name_snapshot")
            .values_list("inventory_line__category_name_snapshot", flat=True)
            .distinct()
        )
        return Response({"data": {"borrower_names": borrower_names, "product_categories": categories}})

    @extend_schema(responses=SampleLoanEligibleEnvelopeSerializer)
    @action(detail=False, methods=["get"], url_path="eligible")
    def eligible(self, request):
        queryset = available_sample_inventory_lines_for_loan()
        keyword = request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(receipt__receipt_number__icontains=keyword)
                | Q(sample_item__sample_request__request_number__icontains=keyword)
                | Q(product_name_snapshot__icontains=keyword)
            )
        page = self.paginate_queryset(queryset)
        serializer = SampleLoanEligibleInventoryLineSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        request=SampleLoanCreateSerializer,
        responses=SampleLoanCreatedEnvelopeSerializer,
    )
    @action(detail=False, methods=["post"], url_path="documents")
    def documents(self, request):
        serializer = SampleLoanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = create_sample_inventory_loan(
            items=serializer.validated_data["items"],
            actor_employee=self.actor_employee(),
        )
        return Response(
            {
                "data": {
                    "loan_id": loan.pk,
                    "loan_number": loan.loan_number,
                    "operated_by": loan.operated_by_employee.display_name,
                    "operated_at": loan.operated_at,
                    "line_count": loan.created_line_count,
                }
            },
            status=201,
        )

    @extend_schema(responses={200: SampleLoanDetailEnvelopeSerializer, 204: None})
    @action(
        detail=False,
        methods=["get", "delete"],
        url_path=rf"documents/(?P<loan_id>{UUID_URL_REGEX})",
    )
    def document_detail(self, request, loan_id=None):
        if request.method == "DELETE":
            delete_sample_inventory_loan(
                loan_id=loan_id,
                actor_employee=self.actor_employee(),
            )
            return Response(status=204)
        loan = get_object_or_404(sample_inventory_loans_with_detail(), pk=loan_id)
        return Response({"data": SampleLoanDetailSerializer(loan).data})
