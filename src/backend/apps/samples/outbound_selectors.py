from django.db.models import Prefetch

from .models import SampleInventoryOutbound, SampleInventoryOutboundLine
from .inventory_selectors import sample_inventory_lines_with_context


def sample_outbound_lines_with_context(queryset=None):
    if queryset is None:
        queryset = SampleInventoryOutboundLine.objects.all()
    return queryset.select_related(
        "outbound",
        "outbound__operated_by_employee",
        "inventory_line",
        "inventory_line__sample_item",
        "inventory_line__sample_item__sample_request",
    )


def available_sample_inventory_lines(queryset=None):
    return sample_inventory_lines_with_context(queryset).filter(available_quantity__gt=0)


def sample_inventory_outbounds_with_detail(queryset=None):
    if queryset is None:
        queryset = SampleInventoryOutbound.objects.all()
    detail_lines = sample_outbound_lines_with_context().order_by("created_at", "id")
    return queryset.select_related("operated_by_employee").prefetch_related(
        Prefetch("lines", queryset=detail_lines, to_attr="detail_lines")
    )
