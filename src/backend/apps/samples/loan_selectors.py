from django.db.models import Prefetch

from .models import SampleInventoryLoan, SampleInventoryLoanLine
from .inventory_selectors import sample_inventory_lines_with_context


def sample_loan_lines_with_context(queryset=None):
    if queryset is None:
        queryset = SampleInventoryLoanLine.objects.all()
    return queryset.select_related(
        "loan",
        "loan__operated_by_employee",
        "inventory_line",
        "inventory_line__sample_item",
        "inventory_line__sample_item__sample_request",
    )


def available_sample_inventory_lines_for_loan(queryset=None):
    return sample_inventory_lines_with_context(queryset).filter(available_quantity__gt=0)


def sample_inventory_loans_with_detail(queryset=None):
    if queryset is None:
        queryset = SampleInventoryLoan.objects.all()
    detail_lines = sample_loan_lines_with_context().order_by("created_at", "id")
    return queryset.select_related("operated_by_employee").prefetch_related(
        Prefetch("lines", queryset=detail_lines, to_attr="detail_lines")
    )
