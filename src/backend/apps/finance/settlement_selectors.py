"""仅聚合真实有效 Receipt；不依赖抵扣表提前生成，也不缓存历史余额。"""
from django.db.models import Case, CharField, DecimalField, F, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce

from .settlement_totals import ZERO, calculate_settlement_totals


def annotate_settlement_totals(queryset):
    """分页前筛选结清状态的SQL等价式；相关子查询不与产品/附件JOIN相乘。"""
    from .receipt_models import Receipt

    active = Receipt.objects.filter(statement_id=OuterRef("pk"), status="ACTIVE").order_by()

    def total(field, receipt_type=None):
        rows = active.filter(receipt_type=receipt_type) if receipt_type else active
        query = rows.values("statement_id").annotate(total=Sum(field)).values("total")
        money = DecimalField(max_digits=22, decimal_places=2)
        return Coalesce(Subquery(query, output_field=money), Value(ZERO), output_field=money)

    return queryset.annotate(
        _finance_goods_cash=total("cash_amount", "GOODS"),
        _finance_allocated=total("allocated_deposit_amount", "GOODS"),
        _finance_deposits=total("deposit_amount", "DEPOSIT"),
        _finance_deposit_cash=total("cash_amount", "DEPOSIT"),
        discount_amount=total("discount_amount", "GOODS"), fee_amount=total("fee_amount"),
    ).annotate(
        settled_amount=F("_finance_goods_cash") + F("_finance_allocated"),
        outstanding_amount=F("amount") - F("_finance_goods_cash") - F("_finance_allocated") - F("discount_amount"),
        available_deposit_amount=F("_finance_deposits") - F("_finance_allocated"),
        bank_received_amount=F("_finance_deposit_cash") + F("_finance_goods_cash"),
    ).annotate(settlement_status=Case(
        When(outstanding_amount=ZERO, then=Value("SETTLED")),
        When(outstanding_amount=F("amount"), then=Value("UNSETTLED")),
        default=Value("PARTIAL"), output_field=CharField(),
    ))


def settlement_totals_for_statements(statements):
    """一页账单一次分组查询，避免列表逐条查询金额。"""
    from .receipt_models import Receipt

    statements = list(statements)
    if not statements:
        return {}
    rows = Receipt.objects.filter(statement_id__in=[item.pk for item in statements], status="ACTIVE")
    goods = Q(receipt_type="GOODS")
    deposits = Q(receipt_type="DEPOSIT")
    aggregated = rows.order_by().values("statement_id").annotate(
        goods_cash_amount=Sum("cash_amount", filter=goods, default=ZERO),
        allocated_deposit_amount=Sum("allocated_deposit_amount", filter=goods, default=ZERO),
        discount_amount=Sum("discount_amount", filter=goods, default=ZERO),
        deposit_amount=Sum("deposit_amount", filter=deposits, default=ZERO),
        deposit_cash_amount=Sum("cash_amount", filter=deposits, default=ZERO),
        fee_amount=Sum("fee_amount", default=ZERO),
    )
    values = {row.pop("statement_id"): row for row in aggregated}
    return {item.pk: calculate_settlement_totals(amount=item.amount, **values.get(item.pk, {})) for item in statements}


def settlement_totals_for(statement):
    """写入方先持有账单行锁；只读调用返回当前有效记录快照。"""
    return settlement_totals_for_statements([statement])[statement.pk]


def settlement_summary(totals):
    return {field: str(getattr(totals, field)) for field in (
        "amount", "settled_amount", "discount_amount", "outstanding_amount",
        "available_deposit_amount", "bank_received_amount", "fee_amount",
    )} | {"settlement_status": totals.settlement_status}
