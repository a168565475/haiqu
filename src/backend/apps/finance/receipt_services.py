from django.db import transaction
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from .deposit_services import create_deposit_receipt_locked, void_deposit_receipt_locked
from .exceptions import FinanceConflict
from .receipt_models import Receipt
from .receipt_serializers import ReceiptCreateSerializer, ReceiptVoidSerializer
from .services import mutation_result
from .statement_locks import lock_statement


@transaction.atomic
def create_receipt(request):
    mutation, result = mutation_result(request, "CREATE_RECEIPT", Receipt)
    if result is not None:
        return result, True
    serializer = ReceiptCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    statement = lock_statement(data["statement_id"])
    require_matching_etag(request, statement)
    if statement.status != "ACTIVE":
        raise FinanceConflict("STATEMENT_VOID", "已作废对账单不能登记收款。")
    if data["receipt_type"] == "DEPOSIT":
        receipt = create_deposit_receipt_locked(request=request, statement=statement, data=data, resource_id=mutation.resource_id)
    else:
        from .goods_services import create_goods_receipt
        receipt = create_goods_receipt(request=request, statement=statement, data=data, resource_id=mutation.resource_id)
    return receipt, False


@transaction.atomic
def void_receipt(request, pk):
    serializer = ReceiptVoidSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    # 只读定位；不能在账单之前锁货款或订金。
    target = get_object_or_404(Receipt.objects.only("statement_id", "receipt_type"), pk=pk)
    statement = lock_statement(target.statement_id)
    if target.receipt_type == "DEPOSIT":
        return void_deposit_receipt_locked(request=request, statement=statement, receipt_id=target.pk, reason=serializer.validated_data["reason"])
    from .goods_services import void_goods_receipt
    return void_goods_receipt(request=request, statement=statement, receipt_id=target.pk, reason=serializer.validated_data["reason"])
