import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Exists, OuterRef, Q
from rest_framework.exceptions import APIException

from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from .statement_models import ReceivableStatement, ReceivableStatementLine

ALLOWED_TASK_STATUSES = ("READY", "IN_PRODUCTION", "PAUSED", "COMPLETED")
PRODUCT_SNAPSHOT_FIELDS = ("item_number_snapshot", "product_number_snapshot", "product_code_snapshot", "product_name_snapshot", "specification_snapshot")


class SourceValidationError(APIException):
    status_code = 400

    def __init__(self, code, message, *, meta=None):
        self.api_error_code = code
        self.error_meta = meta
        super().__init__(message)


def source_tasks(filters=None):
    filters = filters or {}
    tasks = ProductionTask.objects.select_related("salesperson").order_by("-created_at", "-id")
    if filters.get("mode") == "receipt":
        tasks = tasks.filter(Exists(ReceivableStatement.objects.filter(production_task_id=OuterRef("pk"), status="ACTIVE")))
    else:
        tasks = tasks.filter(archived_at__isnull=True, status__in=ALLOWED_TASK_STATUSES)
    if filters.get("q"):
        tasks = tasks.filter(Q(task_number__icontains=filters["q"]) | Q(salesperson__employee_code__icontains=filters["q"]) | Q(salesperson__display_name__icontains=filters["q"]))
    for field in ("status", "salesperson_id"):
        if filters.get(field):
            tasks = tasks.filter(**{field: filters[field]})
    return tasks


def source_products(task_id):
    return ProductionTaskProduct.objects.filter(production_task_id=task_id).select_related("unit", "currency").order_by("id")


def salesperson_data(task):
    return {"id": str(task.salesperson_id), "code": task.salesperson.employee_code, "name": task.salesperson.display_name}


def source_revision(task, products):
    payload = {"id": task.pk, "task_number": task.task_number, "status": task.status, "archived_at": task.archived_at,
               "salesperson": salesperson_data(task), "order_date": task.order_date,
               "products": [{"id": product.pk, "updated_at": product.updated_at, "quantity": str(product.quantity),
                             "unit_id": product.unit_id, "unit_code": product.unit.unit_code, "unit_name": product.unit.unit_name,
                             "currency": product.currency.code, "unit_price": str(product.unit_price),
                             "exchange_rate": str(product.exchange_rate), "exchange_rate_snapshot": product.exchange_rate_snapshot,
                             **{field: getattr(product, field) for field in PRODUCT_SNAPSHOT_FIELDS}}
                            for product in sorted(products, key=lambda product: str(product.pk))]}
    encoded = json.dumps(payload, cls=DjangoJSONEncoder, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def require_source_task(task):
    if task.archived_at or task.status not in ALLOWED_TASK_STATUSES:
        raise SourceValidationError("SOURCE_DATA_INCOMPLETE", "该生产任务的状态或归档状态不允许新建、调整对账。")
    if not task.order_date or not task.salesperson_id or not task.salesperson.employee_code or not task.salesperson.display_name:
        raise SourceValidationError("SOURCE_DATA_INCOMPLETE", "来源日期或业务员资料缺失，请先核对生产任务。")


def reference_price(product):
    if not product.unit_id or not product.unit.unit_code or not product.unit.unit_name or product.quantity <= 0 or not product.product_name_snapshot:
        raise SourceValidationError("SOURCE_DATA_INCOMPLETE", "来源产品的名称、单位或完整数量缺失。", meta={"source_line_id": str(product.pk)})
    rate = Decimal("1")
    if product.currency.code != "CNY":
        snapshot = product.exchange_rate_snapshot
        try:
            rate = Decimal(str(snapshot.get("rate", ""))) if isinstance(snapshot, dict) else Decimal("NaN")
        except InvalidOperation:
            rate = Decimal("NaN")
        if (not rate.is_finite() or rate <= 0 or rate != product.exchange_rate or
                snapshot.get("base_currency_code") != product.currency.code or snapshot.get("quote_currency_code") != "CNY"):
            raise SourceValidationError("SOURCE_CNY_BASIS_MISSING", "该外币来源缺少可靠人民币汇率快照，不能用于对账。", meta={"source_line_id": str(product.pk)})
    with localcontext() as context:
        context.prec = 60
        value = (product.unit_price * rate).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if value < 0 or value >= Decimal("100000000000000"):
        raise SourceValidationError("AMOUNT_OUT_OF_RANGE", "来源人民币参考单价超过可保存范围。")
    return value


def salesperson_changes(task, excluding_statement_id=None):
    previous = ReceivableStatement.objects.filter(production_task=task).exclude(
        salesperson_id=task.salesperson_id, salesperson_code_snapshot=task.salesperson.employee_code,
        salesperson_name_snapshot=task.salesperson.display_name)
    if excluding_statement_id:
        previous = previous.exclude(pk=excluding_statement_id)
    return list(previous.values("id", "number", "salesperson_id", "salesperson_code_snapshot", "salesperson_name_snapshot")[:20])


def product_option(product, occupied=None, editing_statement_id=None):
    reason, code, price = None, None, None
    try:
        price = reference_price(product)
    except SourceValidationError as exc:
        reason, code = str(exc.detail), exc.api_error_code
    if occupied and str(occupied.statement_id) != str(editing_statement_id):
        reason, code = f"已被对账单 {occupied.statement.number} 占用。", "SOURCE_LINE_OCCUPIED"
    return {"id": str(product.pk), **{field: getattr(product, field) for field in PRODUCT_SNAPSHOT_FIELDS},
            "quantity": str(product.quantity), "unit_code": product.unit.unit_code, "unit_name": product.unit.unit_name,
            "reference_unit_price_cny": str(price) if price is not None else None,
            "selectable": reason is None, "reason": reason, "error_code": code,
            "occupied_statement_number": occupied.statement.number if occupied else None}


def occupied_products(product_ids):
    return {line.production_task_product_id: line for line in ReceivableStatementLine.objects.filter(
        production_task_product_id__in=product_ids, is_occupied=True).select_related("statement")}
