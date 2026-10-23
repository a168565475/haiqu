from django.db.models import Exists, F, OuterRef, Prefetch, Q

from .statement_models import ReceivableStatement, ReceivableStatementLine


def statements(filters=None, *, detail=False):
    from .receipt_models import Receipt
    from .settlement_selectors import annotate_settlement_totals

    filters = filters or {}
    queryset = ReceivableStatement.objects.select_related("created_by_employee").annotate(
        _has_receipts=Exists(Receipt.objects.filter(statement_id=OuterRef("pk"))),
        _has_occupied_lines=Exists(ReceivableStatementLine.objects.filter(statement_id=OuterRef("pk"), is_occupied=True)),
        has_active_receipts=Exists(Receipt.objects.filter(statement_id=OuterRef("pk"), status="ACTIVE")))
    if detail:
        queryset = queryset.prefetch_related(Prefetch("lines", queryset=ReceivableStatementLine.objects.filter(
            statement_revision=F("statement__statement_revision")).order_by("line_number"), to_attr="current_lines"))
    if filters.get("q"):
        queryset = queryset.filter(Q(number__icontains=filters["q"]) | Q(task_number_snapshot__icontains=filters["q"])
            | Q(salesperson_name_snapshot__icontains=filters["q"]) | Q(salesperson_code_snapshot__icontains=filters["q"]))
    for key, field in (("task_id", "production_task_id"), ("salesperson_id", "salesperson_id"), ("status", "status")):
        if filters.get(key):
            queryset = queryset.filter(**{field: filters[key]})
    if filters.get("settlement_status"):
        queryset = annotate_settlement_totals(queryset).filter(status="ACTIVE", settlement_status=filters["settlement_status"])
    return queryset.order_by("-created_at", "-id")
