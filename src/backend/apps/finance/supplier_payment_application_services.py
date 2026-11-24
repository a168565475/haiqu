from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from apps.core.daily_numbering import next_daily_business_number

from .exceptions import FinanceConflict
from .services import mutation_result
from .supplier_payment_application_models import SupplierPaymentApplication, SupplierPaymentApplicationLine
from .supplier_payment_application_selectors import active_paid_amount, requestable_payables
from .supplier_payment_application_serializers import SupplierApplicationCreateSerializer
from .supplier_settlement_models import SupplierPayment
from .supplier_settlement_selectors import ZERO, application_line_balances, lock_payables, payment_suppliers


def primary_department_name(employee):
    now = timezone.now()
    return employee.organization_assignments.filter(
        is_primary=True, effective_from__lte=now, organization_unit__archived_at__isnull=True, organization_unit__status="ACTIVE",
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now)).values_list("organization_unit__unit_name", flat=True).first() or ""


def audit_application(request, application, action, values):
    write_audit_log(
        object_type="SUPPLIER_PAYMENT_APPLICATION", object_id=application.pk, action=action, actor_employee=request.employee,
        request=request, context_type="SUPPLIER", context_id=application.supplier_id,
        after_data={"number": application.number, "amount": str(application.amount), **values},
    )


@transaction.atomic
def create_application(request):
    mutation, result = mutation_result(request, "CREATE_SUPPLIER_PAYMENT_APPLICATION", SupplierPaymentApplication)
    if result is not None:
        return result, True
    serializer = SupplierApplicationCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    supplier = get_object_or_404(payment_suppliers(), pk=data["supplier_id"])
    amounts = {line["payable_id"]: line["amount"] for line in data["lines"]}
    lock_payables(amounts)
    payables = requestable_payables(supplier.pk).filter(pk__in=amounts).in_bulk()
    if len(payables) != len(amounts):
        raise FinanceConflict("APPLICATION_PAYABLE_UNAVAILABLE", "请选择同一供应商已确认且尚有未抵余额的人民币应付。")
    for payable_id, amount in amounts.items():
        payable = payables[payable_id]
        if amount > payable.requestable_amount:
            raise FinanceConflict("APPLICATION_AMOUNT_EXCEEDED", f"采购应付 {payable.number} 的可申请金额已变化，请刷新后重新选款。")
    employee = request.employee
    application = SupplierPaymentApplication.objects.create(
        pk=mutation.resource_id, number=next_daily_business_number("SUPPLIER_PAYMENT_APPLICATION"),
        applied_on=data["applied_on"], supplier=supplier, supplier_name_snapshot=supplier.supplier_name,
        payee=data["payee"], note=data["note"], amount=data["amount"],
        recorded_by=employee, recorded_by_name_snapshot=employee.display_name,
        department_name_snapshot=primary_department_name(employee),
    )
    SupplierPaymentApplicationLine.objects.bulk_create([
        SupplierPaymentApplicationLine(
            application=application, payable=payable, payable_number=payable.number,
            inbound_date=payable.material_inbound.inbound_date, confirmed_amount=payable.amount,
            offset_amount=payable.allocated_amount, amount=amounts[payable.pk],
        )
        for payable in payables.values()
    ])
    audit_application(request, application, "CREATE", {"payables": {str(pk): str(amount) for pk, amount in amounts.items()}})
    return application, False


def lock_application_payables(application):
    lock_payables(application.lines.values_list("payable_id", flat=True))
    return list(application_line_balances(application.lines.all()))


def application_for_payment(application_id, supplier_id, nature, amount, previous):
    application = get_object_or_404(SupplierPaymentApplication.objects.select_for_update(), pk=application_id)
    if application.supplier_id != supplier_id or nature != SupplierPayment.Nature.GOODS:
        raise FinanceConflict("APPLICATION_PAYMENT_MISMATCH", "申请关联付款须为同一供应商的货款。")
    if application.withdrawn_at and (previous is None or previous.application_id != application.pk):
        raise FinanceConflict("APPLICATION_WITHDRAWN", "此申请已撤回未执行金额。")
    lines = lock_application_payables(application)
    # 其他入口抵账会减少原单余额，关联实付仍须保留同张应付上其他申请的占用。
    balances = dict(requestable_payables(supplier_id, excluding_application=application.pk)
                    .filter(pk__in=[line.payable_id for line in lines]).values_list("id", "requestable_amount"))
    offset = sum((line.linked_offset_amount for line in lines), ZERO)
    paid_unallocated = active_paid_amount(application) - offset
    eligible = sum((min(line.occupied_amount, balances.get(line.payable_id, ZERO)) for line in lines), ZERO)
    if amount > eligible - paid_unallocated:
        raise FinanceConflict("APPLICATION_PAYMENT_AMOUNT_EXCEEDED", "实付金额超出申请剩余金额或所选应付当前可付余额。")
    return application


@transaction.atomic
def withdraw_application(request, application_id, reason):
    application = get_object_or_404(SupplierPaymentApplication.objects.select_for_update(), pk=application_id)
    require_matching_etag(request, application)
    if application.withdrawn_at:
        raise FinanceConflict("APPLICATION_WITHDRAWN", "此申请已撤回。")
    lines = lock_application_payables(application)
    paid = active_paid_amount(application)
    if paid >= application.amount:
        raise FinanceConflict("APPLICATION_FULLY_PAID", "此申请已付清。")
    if paid > sum((line.linked_offset_amount for line in lines), ZERO):
        raise FinanceConflict("APPLICATION_PAYMENT_NOT_ALLOCATED", "已登记的付款仍有未分配金额。请先按原应付单完成抵账，再撤回未执行部分。")
    for line in lines:
        line.released_amount = line.occupied_amount
    SupplierPaymentApplicationLine.objects.bulk_update(lines, ["released_amount"])
    application.withdrawn_at = timezone.now()
    application.withdrawn_by = request.employee
    application.withdrawal_reason = reason
    application.save(update_fields=["withdrawn_at", "withdrawn_by", "withdrawal_reason", "updated_at"])
    audit_application(request, application, "WITHDRAW", {
        "reason": reason, "released_amount": str(sum((line.released_amount for line in lines), ZERO)),
    })
    return application
