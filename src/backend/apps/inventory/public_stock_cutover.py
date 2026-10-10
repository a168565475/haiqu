"""公共库存切换的数据库身份、持久停写及事务互斥控制。"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from .models import PublicStockCutoverControl
from .stock_services import InventoryStockValidationError


LOCK_KEY = 2026092860
_UNSET = object()
_request_control = ContextVar("public_stock_request_control", default=_UNSET)
_opening_credit = ContextVar("public_stock_opening_credit", default=False)


def _error(message, code):
    raise InventoryStockValidationError({"detail": message}, code=code)


def current_cutover_target():
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), system_identifier::text FROM pg_control_system()")
        database, system_identifier = cursor.fetchone()
    return {"host": str(connection.settings_dict["HOST"]), "database": database,
            "system_identifier": system_identifier}


def assert_cutover_target(expected_target=None):
    target = current_cutover_target()
    allowed = getattr(settings, "PUBLIC_STOCK_CUTOVER_ALLOWED_TARGETS", [])
    if target not in allowed or (expected_target is not None and target != expected_target):
        _error("当前数据库不在切换工具允许的目标清单内，或与确认目标不一致。", "PUBLIC_STOCK_CUTOVER_TARGET_INVALID")
    return target


def get_cutover_control():
    cached = _request_control.get()
    if cached is not _UNSET:
        return cached
    return PublicStockCutoverControl.objects.filter(key="PUBLIC_STOCK").first()


@contextmanager
def cache_request_control():
    token = _request_control.set(PublicStockCutoverControl.objects.filter(key="PUBLIC_STOCK").first())
    try:
        yield
    finally:
        _request_control.reset(token)


def lock_stock_writes(*, exclusive=False):
    if not connection.in_atomic_block:
        _error("切换锁必须在数据库事务中取得。", "PUBLIC_STOCK_CUTOVER_TRANSACTION_REQUIRED")
    function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    with connection.cursor() as cursor:
        if exclusive:
            cursor.execute("SELECT set_config('lock_timeout', '10s', true)")
        cursor.execute(f"SELECT {function}(%s)", [LOCK_KEY])


def require_cutover_operator(actor_employee):
    actor = Employee.objects.select_related("user").filter(
        pk=getattr(actor_employee, "pk", None), status="ACTIVE", archived_at__isnull=True,
        user__is_active=True, user__is_superuser=True,
    ).first()
    if actor is None:
        _error("库存切换操作须由关联有效管理员账号的在职员工执行。", "PUBLIC_STOCK_CUTOVER_OPERATOR_INVALID")
    return actor


def require_transition_maintenance():
    lock_stock_writes(exclusive=True)
    assert_cutover_target()
    control = PublicStockCutoverControl.objects.select_for_update().filter(key="PUBLIC_STOCK").first()
    if control is None or control.state != "MAINTENANCE":
        _error("请先进入库存切换停写状态，再执行期初导入或旧单接续。", "PUBLIC_STOCK_CUTOVER_MAINTENANCE_REQUIRED")
    return control


@transaction.atomic
def begin_cutover_maintenance(*, actor_employee, reason, expected_target):
    actor = require_cutover_operator(actor_employee)
    reason = str(reason or "").strip()
    if not reason:
        _error("进入切换停写状态必须填写原因。", "PUBLIC_STOCK_CUTOVER_REASON_REQUIRED")
    assert_cutover_target(expected_target)
    lock_stock_writes(exclusive=True)
    control = PublicStockCutoverControl.objects.select_for_update().filter(key="PUBLIC_STOCK").first()
    if control:
        if control.state == "PUBLIC":
            _error("公共库存已经正式启用，不能再次执行首次切换。", "PUBLIC_STOCK_CUTOVER_ALREADY_PUBLIC")
        return control
    control = PublicStockCutoverControl.objects.create(state="MAINTENANCE", reason=reason, started_by=actor)
    AuditLog.objects.create(actor_employee=actor, actor_employee_code_snapshot=actor.employee_code,
                            actor_name_snapshot=actor.display_name, object_type="PUBLIC_STOCK_CUTOVER",
                            object_id=control.pk, action="MAINTENANCE_STARTED", occurred_at=timezone.now(),
                            after_data={"state": control.state, "reason": reason, "target": expected_target})
    return control


@transaction.atomic
def require_business_stock_write(*, source_type=None, direction=None):
    # 接口事务先取共享锁；直接调用库存服务时此锁同样随外层事务持有。
    lock_stock_writes()
    control = get_cutover_control()
    if control and control.state == "MAINTENANCE":
        if _opening_credit.get() and source_type == "PUBLIC_STOCK_OPENING" and direction == "IN":
            return
        _error("库存正在切换核对，暂不能新增或修改收发料及相关生产资料，请稍后再试。", "PUBLIC_STOCK_CUTOVER_MAINTENANCE")


def stock_write_transaction(function):
    """业务服务入口先取切换共享锁，再取得任何业务行锁。"""
    @wraps(function)
    @transaction.atomic
    def guarded(*args, **kwargs):
        require_business_stock_write()
        return function(*args, **kwargs)
    return guarded


@contextmanager
def allow_opening_stock_credit():
    require_transition_maintenance()
    token = _opening_credit.set(True)
    try:
        yield
    finally:
        _opening_credit.reset(token)
