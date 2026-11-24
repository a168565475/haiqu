from django.db.models import Exists, F, OuterRef, Prefetch, Q, Subquery, Sum
from django.db.models.functions import Coalesce, Least

from .supplier_payment_application_models import SupplierPaymentApplication
from .supplier_settlement_models import SupplierPayment
from .supplier_settlement_selectors import ACTIVE, ZERO, application_line_balances, payable_balances, payment_amounts


def requestable_payables(supplier_id=None, *, excluding_application=None):
    pending_payments = payment_amounts().filter(application_id=OuterRef("application_id"), status=ACTIVE, available_amount__gt=0)
    lines = application_line_balances().filter(payable_id=OuterRef("pk")).filter(
        Q(application__withdrawn_at__isnull=True) | Exists(pending_payments),
    )
    if excluding_application is not None:
        lines = lines.exclude(application_id=excluding_application)
    occupied = lines.order_by().values("payable_id").annotate(
        total=Sum("occupied_amount"),
    ).values("total")
    return payable_balances(supplier_id).filter(available_amount__gt=0).annotate(
        occupied_amount=Least(F("available_amount"), Coalesce(Subquery(occupied), ZERO)),
        requestable_amount=F("available_amount") - F("occupied_amount"),
    )


def due_requestable_payables(through_month, supplier_id=None):
    return requestable_payables(supplier_id).filter(
        supplier_id__isnull=False, due_month__lte=through_month, requestable_amount__gt=0,
    ).order_by("due_month", "material_inbound__inbound_date", "number", "id")


def due_payables_by_supplier(through_month, supplier_id=None):
    return due_requestable_payables(through_month, supplier_id).order_by().values(
        "supplier_id", "supplier__supplier_name",
    ).annotate(
        overdue_amount=Sum("requestable_amount", filter=Q(due_month__lt=through_month), default=ZERO),
        current_due_amount=Sum("requestable_amount", filter=Q(due_month=through_month), default=ZERO),
        due_total=Sum("requestable_amount"),
    ).order_by("supplier__supplier_name", "supplier_id")


def payable_months(supplier_id, due_through_month=None):
    if due_through_month is None:
        payables = requestable_payables(supplier_id)
    else:
        payables = due_requestable_payables(due_through_month, supplier_id).order_by(
            "material_inbound__inbound_date", "number", "id",
        )
    months = {}
    for payable in payables:
        month = payable.material_inbound.inbound_date.strftime("%Y-%m")
        bucket = months.setdefault(month, {
            "month": month, "current_balance": ZERO, "occupied_amount": ZERO, "requestable_amount": ZERO, "payables": [],
        })
        bucket["current_balance"] += payable.available_amount
        bucket["occupied_amount"] += payable.occupied_amount
        bucket["requestable_amount"] += payable.requestable_amount
        bucket["payables"].append(payable)
    return list(months.values())


def applications():
    return SupplierPaymentApplication.objects.annotate(
        paid_amount=Sum("payments__amount", filter=Q(payments__status=ACTIVE), default=ZERO),
    ).order_by("-applied_on", "-number", "-id")


def application_details():
    payment_rows = SupplierPayment.objects.filter(status=ACTIVE).order_by("-business_date", "-number")
    return applications().prefetch_related("lines", Prefetch("payments", queryset=payment_rows, to_attr="active_payments"))


def active_paid_amount(application):
    return application.payments.filter(status=ACTIVE).aggregate(total=Sum("amount", default=ZERO))["total"]
