from django.db import models
from django.db.models import Q

from .models import FinanceAccount


def accounts(filters=None):
    filters = filters or {}
    queryset = FinanceAccount.objects.select_related("currency").order_by("-created_at", "-id")
    if filters.get("q"):
        term = filters["q"]
        queryset = queryset.filter(Q(code__icontains=term) | Q(name__icontains=term) | Q(account_number__icontains=term))
    if filters.get("status"):
        queryset = queryset.filter(status=filters["status"])
    if filters.get("currency"):
        queryset = queryset.filter(currency__code=filters["currency"])
    return queryset


def available_cny_accounts():
    """U04接入公共选单；写入仍须先锁币种、再锁账户并重新核验。"""
    return accounts().filter(status="ACTIVE", currency__code="CNY", currency__status="ACTIVE", currency__archived_at__isnull=True)


def account_is_referenced(account):
    # 后续真实 PROTECT 外键自动纳入；不创建虚假的收款引用表。
    return any(
        relation.related_model.objects.filter(**{relation.field.name: account}).exists()
        for relation in account._meta.related_objects
        if relation.on_delete in (models.PROTECT, models.RESTRICT)
    )
