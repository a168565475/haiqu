from decimal import Decimal

from django.db.models import Exists, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce, Greatest, Least

from apps.procurement.models import Supplier, SupplierType

from .purchase_payable_models import PurchasePayable, PurchasePayableStatus
from .supplier_payment_application_models import SupplierPaymentApplicationLine
from .supplier_settlement_models import SupplierAllocation, SupplierOffset, SupplierPayment, SupplierSettlementDocument


ZERO = Decimal("0.00")
ACTIVE = SupplierSettlementDocument.Status.ACTIVE
VOID = SupplierSettlementDocument.Status.VOID


def payment_suppliers():
    history = PurchasePayable.objects.filter(supplier_id=OuterRef("pk"), currency_code_snapshot="CNY")
    payments = SupplierPayment.objects.filter(supplier_id=OuterRef("pk"))
    return Supplier.objects.filter(
        Q(supplier_type=SupplierType.MATERIAL, archived_at__isnull=True) | Q(Exists(history)) | Q(Exists(payments)),
    ).order_by("supplier_name", "supplier_number", "id")


def confirmed_payables():
    return PurchasePayable.objects.filter(
        status=PurchasePayableStatus.WAITING_PAYMENT, confirmed_at__isnull=False,
        currency_code_snapshot="CNY", amount__isnull=False,
    )


def active_allocations():
    return SupplierAllocation.objects.filter(offset__status=ACTIVE, offset__payment__status=ACTIVE)


def lock_payables(ids):
    list(PurchasePayable.objects.filter(pk__in=ids).order_by("pk").select_for_update().values_list("pk", flat=True))


def application_line_balances(lines=None):
    if lines is None:
        lines = SupplierPaymentApplicationLine.objects.all()
    linked_offsets = active_allocations().filter(
        payable_id=OuterRef("payable_id"), offset__payment__application_id=OuterRef("application_id"),
    ).order_by().values("payable_id").annotate(total=Sum("amount")).values("total")
    return lines.annotate(
        linked_offset_amount=Coalesce(Subquery(linked_offsets), ZERO),
        occupied_amount=Greatest(F("amount") - F("released_amount") - F("linked_offset_amount"), ZERO),
    )


def payment_amounts():
    return SupplierPayment.objects.annotate(
        allocated_amount=Sum("offsets__allocations__amount", filter=Q(offsets__status=ACTIVE), default=ZERO),
        available_amount=F("amount") - F("allocated_amount"),
    )


def payable_balances(supplier_id=None):
    payables = confirmed_payables()
    if supplier_id is not None:
        payables = payables.filter(supplier_id=supplier_id)
    allocations = active_allocations().filter(payable_id=OuterRef("pk")).order_by().values("payable_id").annotate(
        total=Sum("amount"),
    ).values("total")
    return payables.select_related("material_inbound").annotate(
        allocated_amount=Coalesce(Subquery(allocations), ZERO),
        available_amount=F("amount") - F("allocated_amount"),
    ).order_by("material_inbound__inbound_date", "number", "id")


def pending_payment_holds(excluding_application):
    paid = SupplierPayment.objects.filter(application_id=OuterRef("application_id"), status=ACTIVE).order_by().values(
        "application_id",
    ).annotate(total=Sum("amount")).values("total")
    offset = active_allocations().filter(offset__payment__application_id=OuterRef("application_id")).order_by().values(
        "offset__payment__application_id",
    ).annotate(total=Sum("amount")).values("total")
    lines = application_line_balances().filter(payable_id=OuterRef("pk"))
    if excluding_application:
        lines = lines.exclude(application_id=excluding_application)
    # 实付尚未分配时，保留每张可能用来抵账的原单额度，待分配后按实际金额重算。
    return lines.annotate(
        pending=Greatest(Coalesce(Subquery(paid), ZERO) - Coalesce(Subquery(offset), ZERO), ZERO),
        held=Least(F("occupied_amount"), F("pending")),
    ).order_by().values("payable_id").annotate(total=Sum("held")).values("total")


def eligible_payables(payment):
    payables = payable_balances(payment.supplier_id).annotate(available_amount=Greatest(
        F("available_amount") - Coalesce(Subquery(pending_payment_holds(payment.application_id)), ZERO), ZERO,
    ))
    if payment.application_id:
        capacity = application_line_balances().filter(
            application_id=payment.application_id, payable_id=OuterRef("pk"),
        ).order_by().values("occupied_amount")
        payables = payables.annotate(available_amount=Least(F("available_amount"), Coalesce(Subquery(capacity), ZERO)))
    return payables.filter(available_amount__gt=0)


def payment_documents():
    return payment_amounts().select_related("recorded_by", "voided_by", "replaces", "replacement")


def offset_documents():
    return SupplierOffset.objects.select_related(
        "payment", "recorded_by", "voided_by", "replaces", "replacement",
    ).prefetch_related("allocations__payable")
