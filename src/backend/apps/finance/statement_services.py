from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from apps.core.daily_numbering import next_daily_business_number
from apps.production_tasks.models import ProductionTask
from .exceptions import FinanceConflict
from .services import mutation_result
from .settlement_totals import SettlementAmountError, statement_line_amount, sum_money
from .source_selectors import PRODUCT_SNAPSHOT_FIELDS, SourceValidationError, occupied_products, reference_price, require_source_task, salesperson_changes, source_products, source_revision
from .statement_locks import lock_statement
from .statement_models import ReceivableStatement, ReceivableStatementLine


def statement_has_receipts(statement_id):
    # 运行时读取U04唯一Receipt模型。不得以无模型/无表当作“没有收款”。
    from .receipt_common import statement_has_active_receipts
    return statement_has_active_receipts(statement_id)


def require_mutable_statement(statement):
    if statement.status != "ACTIVE":
        raise FinanceConflict("STATEMENT_VOID", "对账单已作废，不能修改。")
    if statement_has_receipts(statement.pk):
        raise FinanceConflict("STATEMENT_FROZEN", "存在有效订金或货款，请先处理关联收款；不能调整或作废对账单。")


def line_amount(quantity, price):
    try:
        return statement_line_amount(quantity, price)
    except SettlementAmountError as exc:
        raise SourceValidationError(exc.code, str(exc), meta=exc.meta) from exc


def statement_snapshot(statement):
    return {"number": statement.number, "production_task_id": str(statement.production_task_id),
            "task_number": statement.task_number_snapshot, "salesperson_id": str(statement.salesperson_id),
            "salesperson_code": statement.salesperson_code_snapshot, "salesperson_name": statement.salesperson_name_snapshot,
            "source_order_date": statement.source_order_date, "source_revision": statement.source_revision,
            "statement_revision": statement.statement_revision, "status": statement.status, "amount": statement.amount,
            "void_reason": statement.void_reason, "voided_by_id": statement.voided_by_id, "voided_at": statement.voided_at,
            "lines": list(statement.lines.filter(statement_revision=statement.statement_revision).values())}


def audit_statement(statement, request, action, before=None):
    write_audit_log(object_type="RECEIVABLE_STATEMENT", object_id=statement.pk, action=action,
                    actor_employee=request.employee, before_data=before, after_data=statement_snapshot(statement), request=request)


def lock_tasks(task_ids):
    return {task.pk: task for task in ProductionTask.objects.select_for_update(of=("self",)).select_related("salesperson")
            .filter(pk__in=task_ids).order_by("id")}


def prepare_lines(task, data, statement=None):
    require_source_task(task)
    products = list(source_products(task.pk).select_for_update(of=("self",)))
    revision = source_revision(task, products)
    if data["source_revision"] != revision:
        raise FinanceConflict("SOURCE_CHANGED", "生产来源已变化，请查看最新来源并比较，当前输入已保留。", meta={"source_revision": revision})
    changing_task = statement is None or statement.production_task_id != task.pk
    changes = salesperson_changes(task, statement.pk if statement else None) if changing_task else []
    if changes and not data["acknowledge_salesperson_change"]:
        raise FinanceConflict("SALESPERSON_CONFIRMATION_REQUIRED", "当前任务业务员与已有对账快照不一致，请明确确认归属。", meta={"previous_statements": changes})
    by_id = {product.pk: product for product in products}
    occupied = occupied_products([line["production_task_product_id"] for line in data["lines"]])
    values, total = [], Decimal("0.00")
    for index, line in enumerate(data["lines"], 1):
        product_id = line["production_task_product_id"]
        product = by_id.get(product_id)
        if product is None:
            raise ValidationError({"lines": {index - 1: {"production_task_product_id": "该产品行不属于所选生产任务。"}}})
        used = occupied.get(product_id)
        if used and (statement is None or used.statement_id != statement.pk):
            raise FinanceConflict("SOURCE_LINE_OCCUPIED", f"产品行已被对账单 {used.statement.number} 占用。", meta={"source_line_id": str(product_id), "statement_number": used.statement.number})
        price = reference_price(product)
        amount = line_amount(product.quantity, line["unit_price"])
        values.append({"production_task_product": product, "line_number": index,
                       **{field: getattr(product, field) for field in PRODUCT_SNAPSHOT_FIELDS},
                       "unit_code_snapshot": product.unit.unit_code, "unit_name_snapshot": product.unit.unit_name,
                       "quantity": product.quantity, "reference_unit_price_cny": price, "unit_price": line["unit_price"],
                       "amount": amount, "source_currency_code": product.currency.code, "exchange_rate_snapshot": product.exchange_rate_snapshot})
    try:
        total = sum_money(value["amount"] for value in values)
    except SettlementAmountError as exc:
        raise SourceValidationError(exc.code, str(exc), meta=exc.meta) from exc
    if total <= 0:
        raise SourceValidationError("VALIDATION_ERROR", "逐行舍入后的对账总额须大于零，请核对单价。")
    return values, total, revision


def replace_lines(statement, values):
    statement.lines.filter(is_occupied=True).update(is_occupied=False, updated_at=timezone.now())
    try:
        with transaction.atomic():
            ReceivableStatementLine.objects.bulk_create([ReceivableStatementLine(statement=statement,
                statement_revision=statement.statement_revision, **value) for value in values])
    except IntegrityError as exc:
        if getattr(exc.__cause__, "diag", None) and exc.__cause__.diag.constraint_name == "finance_statement_source_occupied":
            raise FinanceConflict("SOURCE_LINE_OCCUPIED", "产品行刚被另一张对账单占用，请刷新来源后重试。") from exc
        raise


def task_snapshot(task):
    return {"production_task": task, "task_number_snapshot": task.task_number, "salesperson": task.salesperson,
            "salesperson_code_snapshot": task.salesperson.employee_code, "salesperson_name_snapshot": task.salesperson.display_name,
            "source_order_date": task.order_date}


@transaction.atomic
def create_statement(request):
    mutation, replay = mutation_result(request, "CREATE_STATEMENT", ReceivableStatement)
    if replay is not None:
        return replay, True
    from .statement_serializers import StatementWriteSerializer
    serializer = StatementWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    tasks = lock_tasks([data["production_task_id"]])
    task = tasks.get(data["production_task_id"])
    if task is None:
        get_object_or_404(ProductionTask, pk=data["production_task_id"])
    values, total, revision = prepare_lines(task, data)
    statement = ReceivableStatement.objects.create(id=mutation.resource_id,
        number=next_daily_business_number("RECEIVABLE_STATEMENT"), **task_snapshot(task), amount=total,
        source_revision=revision, created_by_employee=request.employee, updated_by_employee=request.employee)
    replace_lines(statement, values)
    audit_statement(statement, request, "CREATE")
    return statement, False


@transaction.atomic
def update_statement(request, pk, data):
    current = get_object_or_404(ReceivableStatement, pk=pk)
    tasks = lock_tasks([current.production_task_id, data["production_task_id"]])
    statement = lock_statement(pk)
    require_matching_etag(request, statement)
    require_mutable_statement(statement)
    task = tasks.get(data["production_task_id"])
    if task is None:
        get_object_or_404(ProductionTask, pk=data["production_task_id"])
    before = statement_snapshot(statement)
    values, total, revision = prepare_lines(task, data, statement)
    if statement.production_task_id != task.pk:
        for field, value in task_snapshot(task).items():
            setattr(statement, field, value)
    # 同任务编辑保留建立时业务员/来源日期；产品与来源版本必须重新核对。
    statement.amount = total
    statement.source_revision = revision
    statement.statement_revision += 1
    statement.updated_by_employee = request.employee
    statement.save()
    replace_lines(statement, values)
    audit_statement(statement, request, "UPDATE", before)
    return statement


@transaction.atomic
def void_statement(request, pk, reason):
    current = get_object_or_404(ReceivableStatement, pk=pk)
    lock_tasks([current.production_task_id])
    statement = lock_statement(pk)
    require_matching_etag(request, statement)
    if statement.status == "VOID":
        return statement, False
    require_mutable_statement(statement)
    before = statement_snapshot(statement)
    statement.status = "VOID"
    statement.void_reason = reason
    statement.voided_by = request.employee
    statement.voided_at = timezone.now()
    statement.updated_by_employee = request.employee
    statement.save()
    statement.lines.filter(is_occupied=True).update(is_occupied=False, updated_at=timezone.now())
    audit_statement(statement, request, "VOID", before)
    return statement, True
