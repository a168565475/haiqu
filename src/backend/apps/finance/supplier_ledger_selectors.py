from decimal import Decimal

from django.db.models import Count, DecimalField, Exists, F, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.access_control import module_policy, sales_policy
from apps.inventory.selectors import visible_confirmed_material_receipts
from apps.procurement.models import Supplier
from apps.procurement.selectors import active_purchase_orders
from apps.procurement.source_access import purchase_order_access
from apps.production_tasks.selectors import accessible_production_tasks

from .purchase_payable_models import PurchasePayableLine, PurchasePayableStatus
from .supplier_settlement_models import SupplierAllocation, SupplierPayment
from .supplier_settlement_selectors import ACTIVE, active_allocations


INBOUND_DATE = "payable__material_inbound__inbound_date"
CONFIRMED = Q(payable__status=PurchasePayableStatus.WAITING_PAYMENT, payable__confirmed_at__isnull=False)
ZERO = Decimal("0.00")


def ledger_payable_lines():
    return PurchasePayableLine.objects.filter(
        payable__currency_code_snapshot="CNY", payable__supplier__isnull=False,
        payable__status__in=[
            PurchasePayableStatus.WAITING_PRICE, PurchasePayableStatus.WAITING_FINANCE_CONFIRM,
            PurchasePayableStatus.WAITING_PAYMENT,
        ],
    )


def supplier_options():
    return Supplier.objects.filter(
        Q(Exists(ledger_payable_lines().filter(payable__supplier_id=OuterRef("pk"))))
        | Q(Exists(SupplierPayment.objects.filter(supplier_id=OuterRef("pk")))),
    ).order_by("supplier_name", "supplier_number", "id")


def supplier_total(queryset, supplier_field, amount_field="amount"):
    grouped = queryset.order_by().values(supplier_field).annotate(total=Sum(amount_field)).values("total")
    return Coalesce(Subquery(grouped), ZERO, output_field=DecimalField(max_digits=30, decimal_places=2))


def month_summary(start, end, supplier_id=None):
    before = Q(**{f"{INBOUND_DATE}__lt": start})
    current = Q(**{f"{INBOUND_DATE}__range": (start, end)})
    lines = ledger_payable_lines().filter(payable__supplier_id=OuterRef("pk"))
    payments = SupplierPayment.objects.filter(supplier_id=OuterRef("pk"))
    active_payments = payments.filter(status=ACTIVE)
    allocations = SupplierAllocation.objects.filter(offset__payment__supplier_id=OuterRef("pk"))
    active = active_allocations().filter(offset__payment__supplier_id=OuterRef("pk"))
    prepaid = active_payments.filter(nature=SupplierPayment.Nature.PREPAYMENT, business_date__lte=end)
    prepaid_allocations = active.filter(
        offset__payment__nature=SupplierPayment.Nature.PREPAYMENT, offset__business_date__lte=end,
    )
    pending = lines.filter(current, payable__status=PurchasePayableStatus.WAITING_PRICE).order_by().values(
        "payable__supplier_id",
    ).annotate(count=Count("payable_id", distinct=True)).values("count")
    rows = Supplier.objects.all()
    if supplier_id is not None:
        rows = rows.filter(pk=supplier_id)
    return rows.filter(
        Q(Exists(lines.filter(current))) | Q(Exists(lines.filter(before, CONFIRMED)))
        | Q(Exists(payments.filter(business_date__range=(start, end))))
        | Q(Exists(allocations.filter(offset__business_date__range=(start, end))))
        | Q(Exists(prepaid)),
    ).annotate(
        supplier_id=F("pk"),
        opening_amount=supplier_total(lines.filter(before, CONFIRMED), "payable__supplier_id")
        - supplier_total(active.filter(offset__business_date__lt=start), "offset__payment__supplier_id"),
        current_amount=supplier_total(lines.filter(current, CONFIRMED), "payable__supplier_id"),
        paid_amount=supplier_total(active_payments.filter(business_date__range=(start, end)), "supplier_id"),
        offset_amount=supplier_total(active.filter(offset__business_date__range=(start, end)), "offset__payment__supplier_id"),
        unused_prepayment=supplier_total(prepaid, "supplier_id")
        - supplier_total(prepaid_allocations, "offset__payment__supplier_id"),
        pending_count=Coalesce(Subquery(pending), 0, output_field=IntegerField()),
    ).annotate(
        closing_amount=F("opening_amount") + F("current_amount") - F("offset_amount"),
    ).filter(
        Q(Exists(lines.filter(current))) | Q(Exists(payments.filter(business_date__range=(start, end))))
        | Q(Exists(allocations.filter(offset__business_date__range=(start, end))))
        | Q(opening_amount__gt=ZERO) | Q(closing_amount__gt=ZERO) | Q(unused_prepayment__gt=ZERO),
    ).values("supplier_id", "supplier_name", "supplier_number", "opening_amount", "current_amount",
             "paid_amount", "offset_amount", "closing_amount", "unused_prepayment", "pending_count").order_by(
        "supplier_name", "supplier_number", "supplier_id",
    )


def entry_index(queryset, kind, date_field, number_field):
    return queryset.order_by().values(
        row_id=F("pk"), business_day=F(date_field), doc_number=F(number_field), entry_kind=Value(kind),
    )


def month_entries(start, end, supplier_id):
    payable_index = entry_index(ledger_payable_lines().filter(
        payable__supplier_id=supplier_id, **{f"{INBOUND_DATE}__range": (start, end)},
    ), "PAYABLE", INBOUND_DATE, "payable__number")
    payments = entry_index(SupplierPayment.objects.filter(
        supplier_id=supplier_id, business_date__range=(start, end),
    ), "PAYMENT", "business_date", "number")
    offsets = entry_index(SupplierAllocation.objects.filter(
        offset__payment__supplier_id=supplier_id, offset__business_date__range=(start, end),
    ), "OFFSET", "offset__business_date", "offset__number")
    return payable_index.union(payments, offsets, all=True).order_by("business_day", "entry_kind", "doc_number", "row_id")


def _source_permissions(request, rows):
    has_permission = module_policy.has_permission if module_policy.enabled() else sales_policy.has_permission
    if not rows:
        return set(), set(), set(), False
    inbounds = [line.payable.material_inbound for line in rows]
    orders = [inbound.purchase_order for inbound in inbounds if inbound.purchase_order_id]
    purchase_ids, receipt_ids, task_ids = set(), set(), set()
    purchase_permission = "procurement.view_purchaseorder"
    if has_permission(request, purchase_permission):
        allowed_tasks = accessible_production_tasks(request, permission=purchase_permission).filter(
            archived_at__isnull=True,
        ).order_by().values("pk")
        purchase_ids = set(active_purchase_orders().filter(
            purchase_order_access(allowed_tasks, request, permission=purchase_permission),
            pk__in={order.pk for order in orders},
        ).order_by().values_list("pk", flat=True))
    if has_permission(request, "inventory.view_material_receipt"):
        receipt_ids = set(visible_confirmed_material_receipts(request).filter(
            pk__in={inbound.pk for inbound in inbounds},
        ).order_by().values_list("pk", flat=True))
    task_permission = "production_tasks.view_productiontask"
    if has_permission(request, task_permission):
        task_ids = set(accessible_production_tasks(request, permission=task_permission).filter(
            archived_at__isnull=True, pk__in={order.production_task_id for order in orders if order.production_task_id},
        ).order_by().values_list("pk", flat=True))
    return purchase_ids, receipt_ids, task_ids, has_permission(request, "finance.view_purchasepayable")


def payable_entry_rows(request, lines):
    purchase_ids, receipt_ids, task_ids, can_view_payable = _source_permissions(request, lines)
    for line in lines:
        payable = line.payable
        inbound = payable.material_inbound
        order = inbound.purchase_order
        confirmed = payable.status == PurchasePayableStatus.WAITING_PAYMENT and payable.confirmed_at is not None
        yield {
            "id": line.pk,
            "entry_kind": "PAYABLE",
            "type_display": "采购应付",
            "business_date": inbound.inbound_date,
            "payable_id": payable.pk if can_view_payable else None,
            "number": payable.number,
            "status": payable.status,
            "status_display": payable.get_status_display(),
            "amount": line.amount if confirmed else None,
            "inbound_date": inbound.inbound_date,
            "confirmed_date": timezone.localdate(payable.confirmed_at) if confirmed else None,
            "confirmed_by": payable.confirmed_by_employee.display_name if payable.confirmed_by_employee_id else "",
            "purchase_order_id": order.pk if order and order.pk in purchase_ids else None,
            "purchase_order_number": payable.purchase_order_number_snapshot,
            "inbound_id": inbound.pk if inbound.pk in receipt_ids else None,
            "inbound_number": payable.inbound_number_snapshot,
            "production_task_id": order.production_task_id if order and order.production_task_id in task_ids else None,
            "production_task_number": order.production_task_number_snapshot if order else "",
            "material": line.material_snapshot,
            "specification": line.specification_snapshot,
            "quantity": line.accepted_quantity,
            "unit": line.price_unit_text or line.source_unit_text_snapshot,
            "unit_price": line.unit_price,
        }


def entry_rows(request, index):
    ids = {kind: [row["row_id"] for row in index if row["entry_kind"] == kind]
           for kind in ("PAYABLE", "PAYMENT", "OFFSET")}
    payables = PurchasePayableLine.objects.filter(pk__in=ids["PAYABLE"]).select_related(
        "payable__material_inbound__purchase_order", "payable__confirmed_by_employee",
    )
    rows = {row["id"]: row for row in payable_entry_rows(request, list(payables))}
    for payment in SupplierPayment.objects.filter(pk__in=ids["PAYMENT"]):
        rows[payment.pk] = {
            "id": payment.pk, "document_id": payment.pk, "entry_kind": "PAYMENT",
            "type_display": payment.get_nature_display(), "business_date": payment.business_date,
            "number": payment.number, "status": payment.status, "status_display": payment.get_status_display(),
            "paid_amount": payment.amount if payment.status == ACTIVE else None,
        }
    for allocation in SupplierAllocation.objects.filter(pk__in=ids["OFFSET"]).select_related("offset"):
        offset = allocation.offset
        rows[allocation.pk] = {
            "id": allocation.pk, "document_id": offset.pk, "entry_kind": "OFFSET",
            "type_display": "抵账", "business_date": offset.business_date,
            "number": offset.number, "status": offset.status, "status_display": offset.get_status_display(),
            "offset_amount": allocation.amount if offset.status == ACTIVE else None,
        }
    return [rows[row["row_id"]] for row in index]
