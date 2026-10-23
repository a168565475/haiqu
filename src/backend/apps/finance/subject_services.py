from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from .exceptions import FinanceConflict
from .models import AccountingSubject
from .services import mutation_result
from .subject_selectors import ancestors, descendants, subjects
from .subject_serializers import SubjectWriteSerializer


def lock_subjects():
    # 固定三级小型主数据：所有CRUD和导入使用同一事务锁，先幂等键、再科目锁。
    # 不混用父/子反向行锁；读取仍可并发。锁在事务结束时自动释放。
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(20261023, 2)")


def snapshot(subject):
    return {"parent_id": str(subject.parent_id) if subject.parent_id else None, "level": subject.level,
            "name": subject.name, "status": subject.status}


def audit(subject, actor, action, before=None, request=None):
    write_audit_log(object_type="ACCOUNTING_SUBJECT", object_id=subject.pk, action=action,
                   actor_employee=actor, before_data=before,
                   after_data={} if action == "DELETE" else snapshot(subject), request=request)


def touch_ancestors(subject):
    AccountingSubject.objects.filter(pk__in=[node.pk for node in ancestors(subject)]).update(updated_at=timezone.now())


def save_unique(subject):
    try:
        with transaction.atomic():
            subject.save()
    except IntegrityError as exc:
        if getattr(exc.__cause__, "diag", None) and exc.__cause__.diag.constraint_name in (
            "finance_subject_root_unique", "finance_subject_sibling_unique",
        ):
            raise FinanceConflict("DUPLICATE_SUBJECT_PATH", "同一上级下的科目名称已存在。") from exc
        raise


def insert_subject(data, actor, request=None, resource_id=None):
    # 调用方已持有科目事务锁；数据库约束再次防止重复路径和错误层级。
    values = dict(data)
    parent_id = values.pop("parent_id")
    parent = get_object_or_404(AccountingSubject.objects.select_related("parent__parent"), pk=parent_id) if parent_id else None
    if (parent is None and values["level"] != 1) or (parent and values["level"] != parent.level + 1):
        raise ValidationError({"parent_id": "费用类型无上级，一级科目属于费用类型，二级科目属于一级科目。"})
    if parent and (parent.status == "INACTIVE" or any(node.status == "INACTIVE" for node in ancestors(parent))):
        raise FinanceConflict("SUBJECT_UNAVAILABLE", "上级科目已停用，不能新增下级。")
    subject = AccountingSubject(**values, parent=parent, created_by_employee=actor, updated_by_employee=actor,
                                **({"id": resource_id} if resource_id else {}))
    save_unique(subject)
    touch_ancestors(subject)
    audit(subject, actor, "CREATE", request=request)
    return subject


@transaction.atomic
def create_subject(request):
    mutation, result = mutation_result(request, "CREATE_SUBJECT", AccountingSubject)
    if result is not None:
        return result, True
    serializer = SubjectWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    lock_subjects()
    return insert_subject(serializer.validated_data, request.employee, request, mutation.resource_id), False


@transaction.atomic
def update_subject(request, pk, data):
    lock_subjects()
    subject = get_object_or_404(subjects(), pk=pk)
    require_matching_etag(request, subject)
    before = snapshot(subject)
    for field, value in data.items():
        setattr(subject, field, value)
    subject.updated_by_employee = request.employee
    save_unique(subject)
    # 祖先名称/状态改变会改变后代的可见路径/有效状态，旧ETag必须失效。
    descendants(subject.pk).update(updated_at=timezone.now())
    touch_ancestors(subject)
    audit(subject, request.employee, "UPDATE", before, request)
    return subject


@transaction.atomic
def delete_subject(request, pk):
    lock_subjects()
    subject = get_object_or_404(subjects(), pk=pk)
    require_matching_etag(request, subject)
    if subject.child_count:
        raise FinanceConflict("SUBJECT_HAS_CHILDREN", "含下级科目，不能级联删除；请先处理下级。")
    audit(subject, request.employee, "DELETE", snapshot(subject), request)
    touch_ancestors(subject)
    try:
        subject.delete()
    except (ProtectedError, RestrictedError) as exc:
        raise FinanceConflict("REFERENCED_RECORD", "科目已被引用，请停用以保留历史。") from exc
