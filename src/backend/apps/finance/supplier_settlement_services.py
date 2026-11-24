from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import PreconditionRequired, require_matching_etag
from apps.core.audit import write_audit_log
from apps.core.daily_numbering import next_daily_business_number

from .exceptions import FinanceConflict
from .receipt_common import lock_receipt_accounts, receipt_account_snapshot
from .services import mutation_result
from .supplier_payment_application_models import SupplierPaymentApplication
from .supplier_payment_application_services import application_for_payment
from .supplier_settlement_models import SupplierAllocation, SupplierOffset, SupplierPayment
from .supplier_settlement_selectors import (
    ACTIVE, VOID, ZERO, active_allocations, confirmed_payables, eligible_payables, lock_payables, payment_suppliers,
)
from .supplier_settlement_serializers import (
    SupplierOffsetCreateSerializer, SupplierPaymentCreateSerializer, SupplierPaymentRegistrationSerializer,
)


def checked_replacement(model, previous_id):
    if previous_id is None:
        return None
    previous = get_object_or_404(model.objects.select_for_update(), pk=previous_id)
    if previous.status != VOID or model.objects.filter(replaces_id=previous_id).exists():
        raise FinanceConflict("REPLACEMENT_UNAVAILABLE", "请选择尚未重新登记的已更正原单。")
    return previous


def audit_document(document, request, kind, supplier_id, action, amounts):
    write_audit_log(
        object_type=kind, object_id=document.pk, action=action,
        actor_employee=request.employee, request=request,
        context_type="SUPPLIER", context_id=supplier_id,
        after_data={"number": document.number, "status": document.status,
                    "business_date": document.business_date.isoformat(), "amounts": amounts,
                    "replaces_id": str(document.replaces_id) if document.replaces_id else None,
                    "void_reason": document.void_reason},
    )


@transaction.atomic
def create_payment(request, *, allow_application=False):
    if not allow_application and "application_id" in request.data:
        raise ValidationError({"application_id": "请在供应商付款页关联付款申请。"})
    mutation, result = mutation_result(request, "CREATE_SUPPLIER_PAYMENT", SupplierPayment)
    if result is not None:
        return result, True
    serializer_class = SupplierPaymentRegistrationSerializer if allow_application else SupplierPaymentCreateSerializer
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    supplier = get_object_or_404(payment_suppliers(), pk=data["supplier_id"])
    account_id = data["account_id"]
    if not request.headers.get("If-Match"):
        raise PreconditionRequired()
    # 复用收款账户锁序和快照，选择器与入账共用人民币账户边界。
    account = lock_receipt_accounts([{"account_id": account_id, "account_etag": request.headers.get("If-Match")}])[account_id]
    previous = checked_replacement(SupplierPayment, data.get("replaces_id"))
    application_id = data.get("application_id")
    if previous and previous.application_id:
        if application_id and application_id != previous.application_id:
            raise FinanceConflict("APPLICATION_REPLACEMENT_MISMATCH", "重新登记须保留原付款关联的申请。")
        application_id = previous.application_id
    application = application_for_payment(application_id, supplier.pk, data["nature"], data["amount"], previous) if application_id else None
    payment = SupplierPayment.objects.create(
        pk=mutation.resource_id, number=next_daily_business_number("SUPPLIER_PAYMENT"),
        business_date=data["paid_on"], recorded_by=request.employee, replaces=previous,
        supplier=supplier, supplier_name_snapshot=supplier.supplier_name, nature=data["nature"], application=application,
        account=account, account_snapshot=receipt_account_snapshot(account),
        payee=data["payee"], amount=data["amount"], voucher=data["voucher"],
    )
    if application is not None:
        application.save(update_fields=["updated_at"])
    audit_document(payment, request, "SUPPLIER_PAYMENT", supplier.pk, "CREATE", {"amount": str(payment.amount)})
    return payment, False


def offset_amounts(offset):
    return {str(row.payable_id): str(row.amount) for row in offset.allocations.all()}


@transaction.atomic
def create_offset(request):
    mutation, result = mutation_result(request, "CREATE_SUPPLIER_OFFSET", SupplierOffset)
    if result is not None:
        return result, True
    serializer = SupplierOffsetCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    # 先锁付款，再按主键排序锁应付。不同付款抵同一应付时仍使用共同的应付锁。
    payment = get_object_or_404(SupplierPayment.objects.select_for_update(), pk=data["payment_id"])
    require_matching_etag(request, payment)
    if payment.status != ACTIVE or data["offset_on"] < payment.business_date:
        raise FinanceConflict("PAYMENT_UNAVAILABLE", "请选择有效付款，抵账日期不得早于付款日期。")
    amounts = {row["payable_id"]: row["amount"] for row in data["allocations"]}
    lock_payables(amounts)
    payables = confirmed_payables().filter(pk__in=amounts, supplier_id=payment.supplier_id).in_bulk()
    if len(payables) != len(amounts):
        raise FinanceConflict("PAYABLE_UNAVAILABLE", "抵账应付必须是同一供应商已确认的人民币应付。")
    if any(data["offset_on"] < timezone.localdate(row.confirmed_at) for row in payables.values()):
        raise FinanceConflict("OFFSET_DATE_INVALID", "抵账日期不得早于应付确认日期。")
    used = active_allocations().filter(offset__payment=payment).aggregate(total=Sum("amount", default=ZERO))["total"]
    if sum(amounts.values(), ZERO) > payment.amount - used:
        raise FinanceConflict("PAYMENT_AMOUNT_EXCEEDED", "抵账金额超出付款可用额。")
    capacities = dict(eligible_payables(payment).filter(pk__in=amounts).values_list("id", "available_amount"))
    if any(amount > capacities.get(payable_id, ZERO) for payable_id, amount in amounts.items()):
        raise FinanceConflict("PAYABLE_AMOUNT_EXCEEDED", "所选应付的可抵账金额不足，请刷新选项。")
    previous = checked_replacement(SupplierOffset, data.get("replaces_id"))
    offset = SupplierOffset.objects.create(
        pk=mutation.resource_id, number=next_daily_business_number("SUPPLIER_OFFSET"),
        business_date=data["offset_on"], recorded_by=request.employee, payment=payment, replaces=previous,
    )
    SupplierAllocation.objects.bulk_create([
        SupplierAllocation(offset=offset, payable_id=payable_id, amount=amount) for payable_id, amount in amounts.items()
    ])
    payment.save(update_fields=["updated_at"])
    audit_document(offset, request, "SUPPLIER_OFFSET", payment.supplier_id, "CREATE", offset_amounts(offset))
    return offset, False


def mark_void(document, request, reason):
    document.status = VOID
    document.void_reason = reason
    document.voided_at = timezone.now()
    document.voided_by = request.employee
    document.save(update_fields=["status", "void_reason", "voided_at", "voided_by", "updated_at"])


@transaction.atomic
def void_payment(request, pk, reason):
    payment = get_object_or_404(SupplierPayment.objects.select_for_update(), pk=pk)
    require_matching_etag(request, payment)
    if payment.status != ACTIVE:
        raise FinanceConflict("PAYMENT_VOID", "付款单已更正。")
    if payment.offsets.filter(status=ACTIVE).exists():
        raise FinanceConflict("ACTIVE_OFFSETS", "请先更正该付款的全部有效抵账。")
    mark_void(payment, request, reason)
    if payment.application_id:
        SupplierPaymentApplication.objects.filter(pk=payment.application_id).update(updated_at=timezone.now())
    audit_document(payment, request, "SUPPLIER_PAYMENT", payment.supplier_id, "VOID", {"amount": str(payment.amount)})
    return payment


@transaction.atomic
def void_offset(request, pk, reason):
    target = get_object_or_404(SupplierOffset.objects.only("payment_id"), pk=pk)
    payment = SupplierPayment.objects.select_for_update().get(pk=target.payment_id)
    lock_payables(target.allocations.values_list("payable_id", flat=True))
    offset = SupplierOffset.objects.select_for_update().get(pk=pk)
    require_matching_etag(request, offset)
    if offset.status != ACTIVE:
        raise FinanceConflict("OFFSET_VOID", "抵账单已更正。")
    mark_void(offset, request, reason)
    payment.save(update_fields=["updated_at"])
    audit_document(offset, request, "SUPPLIER_OFFSET", payment.supplier_id, "VOID", offset_amounts(offset))
    return offset
