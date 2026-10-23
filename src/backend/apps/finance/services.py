import hashlib
import json
import uuid

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from apps.core.daily_numbering import next_daily_business_number
from .exceptions import FinanceConflict, OriginalResultDeleted
from .models import FinanceAccount, FinanceMutationKey
from .selectors import account_is_referenced


def account_snapshot(account):
    return {"code": account.code, "account_type": account.account_type, "category": account.category,
            "name": account.name, "currency_id": str(account.currency_id), "status": account.status,
            "account_number": "***" + account.account_number[-4:]}


def audit_account(account, actor, action, before=None, request=None):
    write_audit_log(object_type="FINANCE_ACCOUNT", object_id=account.pk, action=action,
                    actor_employee=actor, before_data=before,
                    after_data={} if action == "DELETE" else account_snapshot(account), request=request)


def validate_currency(currency):
    # 和字典维护共享行锁，防止校验后币种刚好停用。
    from apps.reference_data.models import Currency
    current = Currency.objects.select_for_update().get(pk=currency.pk)
    if current.status != "ACTIVE" or current.archived_at:
        raise ValidationError({"currency_id": "请选择有效币种。"})


def insert_account(data, actor, request=None, resource_id=None):
    validate_currency(data["currency"])
    values = dict(data)
    if not values.get("code"):
        values["code"] = next_daily_business_number("FINANCE_ACCOUNT")
        # 保留的原编码可能占用了当日日流水；跳过已存在编码，避免每次回滚后卡在同一号。
        while FinanceAccount.objects.filter(code=values["code"]).exists():
            values["code"] = next_daily_business_number("FINANCE_ACCOUNT")
    try:
        with transaction.atomic():
            account = FinanceAccount.objects.create(**values, **({"id": resource_id} if resource_id else {}),
                created_by_employee=actor, updated_by_employee=actor)
    except IntegrityError as exc:
        if getattr(exc.__cause__, "diag", None) and exc.__cause__.diag.constraint_name == "finance_account_code_key":
            raise FinanceConflict("DUPLICATE_CODE", "账户编码已存在，请核对后重试。") from exc
        raise
    audit_account(account, actor, "CREATE", request=request)
    return account


def mutation_result(request, action, model):
    try:
        key = uuid.UUID(request.headers.get("Idempotency-Key", ""))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError({"Idempotency-Key": "新增必须携带 UUID 幂等键。"}) from exc
    digest = hashlib.sha256(json.dumps(request.data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    # 唯一键竞争发生在业务写入之前；失败事务不遗留占位或编号。
    mutation, created = FinanceMutationKey.objects.get_or_create(actor_employee=request.employee,
        action=action, key=key, defaults={"request_hash": digest, "resource_id": uuid.uuid4()})
    mutation = FinanceMutationKey.objects.select_for_update().get(pk=mutation.pk)
    if mutation.request_hash != digest:
        raise FinanceConflict("IDEMPOTENCY_KEY_REUSED", "该提交标识已用于不同内容，请勿更改待确认的提交。")
    if not created:
        result = model.objects.filter(pk=mutation.resource_id).first()
        if result is None:
            raise OriginalResultDeleted(mutation.resource_id)
        return mutation, result
    return mutation, None


@transaction.atomic
def create_account(request):
    mutation, result = mutation_result(request, "CREATE_ACCOUNT", FinanceAccount)
    if result is not None:
        return result, True
    from .serializers import AccountWriteSerializer
    serializer = AccountWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return insert_account(serializer.validated_data, request.employee, request, mutation.resource_id), False


@transaction.atomic
def update_account(request, pk, data):
    if "currency" in data:
        validate_currency(data["currency"])
    account = get_object_or_404(FinanceAccount.objects.select_for_update(), pk=pk)
    require_matching_etag(request, account)
    before = account_snapshot(account)
    for field, value in data.items():
        setattr(account, field, value)
    account.updated_by_employee = request.employee
    account.save()
    audit_account(account, request.employee, "UPDATE", before, request)
    return account


@transaction.atomic
def delete_account(request, pk):
    account = get_object_or_404(FinanceAccount.objects.select_for_update(), pk=pk)
    require_matching_etag(request, account)
    if account_is_referenced(account):
        raise FinanceConflict("REFERENCED_RECORD", "账户已被引用，请停用以保留历史记录。")
    audit_account(account, request.employee, "DELETE", account_snapshot(account), request)
    try:
        account.delete()
    except (ProtectedError, RestrictedError) as exc:
        raise FinanceConflict("REFERENCED_RECORD", "账户已被引用，不能删除。") from exc


def require_receipt_account(account):
    """U04调用方须在事务中先锁币种、再锁账户，并传入重新读取的币种状态。"""
    if account.status != "ACTIVE" or account.currency.code != "CNY" or account.currency.status != "ACTIVE" or account.currency.archived_at:
        raise FinanceConflict("ACCOUNT_UNAVAILABLE", "新人民币收款只能选择启用的人民币账户。")
