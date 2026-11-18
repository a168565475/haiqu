from django.db.models import Prefetch, Q

from .purchase_payable_models import PurchasePayable, PurchasePayableLine


def purchase_payables(filters=None, *, detail=False):
    filters = filters or {}
    queryset = PurchasePayable.objects.select_related(
        "supplier", "material_inbound", "confirmed_by_employee", "voided_by_employee",
    ).prefetch_related(
        Prefetch(
            "lines",
            queryset=PurchasePayableLine.objects.select_related("payable", "material_inbound_line"),
        ),
    )
    if filters.get("q"):
        term = filters["q"]
        queryset = queryset.filter(
            Q(number__icontains=term)
            | Q(supplier_number_snapshot__icontains=term)
            | Q(supplier_name_snapshot__icontains=term)
            | Q(purchase_order_number_snapshot__icontains=term)
            | Q(inbound_number_snapshot__icontains=term)
        )
    if filters.get("status"):
        queryset = queryset.filter(status=filters["status"])
    if filters.get("supplier_id"):
        queryset = queryset.filter(supplier_id=filters["supplier_id"])
    if filters.get("inbound_id"):
        queryset = queryset.filter(material_inbound_id=filters["inbound_id"])
    if filters.get("inbound_date_from"):
        queryset = queryset.filter(material_inbound__inbound_date__gte=filters["inbound_date_from"])
    if filters.get("inbound_date_to"):
        queryset = queryset.filter(material_inbound__inbound_date__lte=filters["inbound_date_to"])
    return queryset.order_by("-created_at", "-id")


def payable_detail(payable_id):
    return purchase_payables({"id": payable_id}, detail=True).filter(pk=payable_id).first()
