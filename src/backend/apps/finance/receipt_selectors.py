from django.db.models import Exists, OuterRef, Prefetch, Q

from .receipt_models import Receipt, ReceiptAttachment


def receipts(filters=None):
    from .allocation_models import DepositAllocation
    filters = filters or {}
    allocations = DepositAllocation.objects.select_related("deposit_receipt").prefetch_related("deposit_receipt__attachments__file").order_by("pk")
    queryset = Receipt.objects.select_related("statement", "created_by_employee").annotate(
        _has_deposit_references=Exists(DepositAllocation.objects.filter(deposit_receipt_id=OuterRef("pk"))),
        _has_active_allocations=Exists(DepositAllocation.objects.filter(goods_receipt_id=OuterRef("pk"), is_active=True)),
        _deposit_used=Exists(DepositAllocation.objects.filter(deposit_receipt_id=OuterRef("pk"), is_active=True))).prefetch_related(
        "account_lines", Prefetch("attachments", queryset=ReceiptAttachment.objects.select_related("file")),
        Prefetch("allocations", queryset=allocations, to_attr="_receipt_allocations"))
    if filters.get("q"):
        term = filters["q"]
        queryset = queryset.filter(Q(number__icontains=term) | Q(statement__number__icontains=term)
            | Q(statement__task_number_snapshot__icontains=term))
    for field in ("receipt_type", "status", "statement_id"):
        if filters.get(field):
            queryset = queryset.filter(**{field: filters[field]})
    return queryset.order_by("-created_at", "-id")


def used_deposit_allocations(receipt_id):
    # Allocation 由 U05 唯一维护；未注册/未迁移不能解释为“未使用”。
    from .allocation_models import DepositAllocation
    return DepositAllocation.objects.filter(deposit_receipt_id=receipt_id, is_active=True)
