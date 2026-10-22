"""管理对象删除：有历史引用时归档，无引用时物理删除；不级联业务历史。"""
import hashlib
import json

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core import signing
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired, etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.audit.models import AuditLog
from apps.organizations.models import Employee, OrganizationUnit, RoleProfile
from apps.wecom.models import WeComBinding, OAuthState
from .models import RoleActionGrant, RoleGrantResource
from .services import require_manager

DELETED_REASON = "管理页面删除（保留历史）"
SALT = "access-management.delete.v1"
KINDS = {
    "employees": (Employee, "access_control.manage_accounts", "ACCESS_EMPLOYEE"),
    "roles": (RoleProfile, "access_control.manage_access", "ACCESS_ROLE"),
    "departments": (OrganizationUnit, "organizations.manage_organization", "ACCESS_ORGANIZATION"),
}


def referenced(obj, ignored=()):
    """连 SET_NULL、隐藏反向关系及无外键 UUID 引用也保留，避免改写历史。"""
    # 先检查常见的审计引用，批量处理导入员工时避免逐人扫描全部业务表。
    if not isinstance(obj.pk, int) and AuditLog.objects.filter(Q(object_id=obj.pk) | Q(context_id=obj.pk)).exists():
        return True
    for relation in obj._meta.get_fields(include_hidden=True):
        if not relation.auto_created or relation.concrete or not (relation.one_to_many or relation.one_to_one):
            continue
        model = relation.related_model
        if model in ignored:
            continue
        if model._base_manager.filter(**{relation.field.attname: obj.pk}).exists():
            return True
    if isinstance(obj.pk, int):
        return OAuthState.objects.filter(initiator_user_id=obj.pk).exists()
    for model in apps.get_models():
        fields = [field.name for field in model._meta.concrete_fields
                  if isinstance(field, models.UUIDField) and not field.primary_key]
        if fields:
            query = Q()
            for name in fields:
                query |= Q(**{name: obj.pk})
            if model._base_manager.filter(query).exists():
                return True
    return False


def deletion_mode(obj, kind, actor):
    if kind == "employees":
        if obj.pk == actor.pk:
            return "ARCHIVE"
        binding = WeComBinding.objects.filter(employee=obj).first()
        if binding and referenced(binding):
            return "ARCHIVE"
        if referenced(obj, (WeComBinding,)):
            return "ARCHIVE"
        if obj.user_id and referenced(obj.user, (Employee,)):
            return "ARCHIVE"
    elif kind == "roles":
        if referenced(obj, (RoleActionGrant,)) or obj.auth_group.user_set.exists():
            return "ARCHIVE"
        # 角色授权本身可以随误建角色清理，授权被其他对象使用则保留。
        for grant in obj.action_grants.all():
            if referenced(grant, (RoleGrantResource,)):
                return "ARCHIVE"
    elif referenced(obj):
        return "ARCHIVE"
    return "DELETE"


def rows_for(request, kind, items, *, lock=False):
    model, permission, _ = KINDS[kind]
    actor = require_manager(request, permission)
    ids = [item["id"] for item in items]
    if len(set(ids)) != len(ids):
        raise ValidationError({"items": "选择中不能包含重复记录。"})
    queryset = model.objects.filter(pk__in=ids).exclude(archive_reason=DELETED_REASON).order_by("pk")
    if lock:
        queryset = queryset.select_for_update()
    objects = list(queryset)
    if len(objects) != len(items):
        raise PreconditionFailed("部分记录已删除或不存在，请刷新列表后重新选择。")
    versions = {item["id"]: item["etag"] for item in items}
    rows = []
    for obj in objects:
        if etag_for_instance(obj) != versions[obj.pk]:
            raise PreconditionFailed("所选记录已变化，请重新预览删除影响。")
        if kind == "departments" and obj.unit_code == "HAIQU":
            raise Conflict("公司根组织不是可删除部门。")
        if kind == "employees" and obj.user_id and lock:
            obj.user = get_user_model().objects.select_for_update().get(pk=obj.user_id)
        mode = deletion_mode(obj, kind, actor)
        rows.append({"id": str(obj.pk), "name": obj.unit_name if kind == "departments" else obj.display_name,
                     "etag": etag_for_instance(obj), "mode": mode,
                     "reason": "从列表移除并停止生效，保留历史记录" if mode == "ARCHIVE" else "无历史引用，永久删除",
                     "account": obj.user.username if kind == "employees" and obj.user_id else None,
                     "account_id": obj.user_id if kind == "employees" else None,
                     "group_permissions": sorted(obj.auth_group.permissions.values_list("pk", flat=True)) if kind == "roles" else []})
    return actor, objects, rows


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@transaction.atomic
def preview_deletion(request, kind, items):
    actor, _, rows = rows_for(request, kind, items)
    token = signing.dumps({"actor": str(actor.pk), "kind": kind, "rows": fingerprint(rows)}, salt=SALT, compress=True)
    return {"rows": rows, "token": token}


@transaction.atomic
def delete_selected(request, kind, items, token):
    try:
        preview = signing.loads(token, salt=SALT, max_age=600)
    except signing.BadSignature as exc:
        raise ValidationError({"token": "删除预览已过期或无效，请重新预览。"}) from exc
    # 和部门、角色分配共用根锁；所有目标按主键顺序锁定。
    OrganizationUnit.objects.select_for_update().get(unit_code="HAIQU")
    actor, objects, rows = rows_for(request, kind, items, lock=True)
    if not request.headers.get("If-Match"):
        raise PreconditionRequired()
    if request.headers.get("If-Match") != f'"{fingerprint(rows)}"':
        raise PreconditionFailed("缺少或不匹配删除预览版本，请重新核对。")
    if preview != {"actor": str(actor.pk), "kind": kind, "rows": fingerprint(rows)}:
        raise PreconditionFailed("删除范围或引用已变化，请重新核对影响。")
    now = timezone.now()
    user_ids = {str(obj.user_id) for obj in objects if kind == "employees" and obj.user_id}
    # 先写审计，再停用当前操作者，允许管理员删除自己且保留操作者快照。
    for obj, row in zip(objects, rows):
        write_audit_log(object_type=KINDS[kind][2], object_id=obj.pk,
                        action={"employees": "EMPLOYEE_DELETE", "roles": "ROLE_DELETE", "departments": "DEPARTMENT_DELETE"}[kind],
                        actor_employee=actor, before_data=row, after_data={"deleted": True, "mode": row["mode"]}, request=request)
    for obj, row in zip(objects, rows):
        if row["mode"] == "ARCHIVE":
            obj.archived_at, obj.archived_by_employee, obj.archive_reason = now, actor, DELETED_REASON
            fields = ["archived_at", "archived_by_employee", "archive_reason", "updated_at"]
            if kind in ("employees", "departments"):
                obj.status = "INACTIVE"
                fields.append("status")
            obj.save(update_fields=fields)
            if kind == "employees" and obj.user_id:
                get_user_model().objects.filter(pk=obj.user_id).update(is_active=False)
            if kind == "roles":
                obj.auth_group.permissions.clear()
        else:
            if kind == "employees":
                user = obj.user if obj.user_id else None
                WeComBinding.objects.filter(employee=obj).delete()
                obj.delete()
                if user:
                    user.delete()
            elif kind == "roles":
                group = obj.auth_group
                RoleGrantResource.objects.filter(grant__role=obj).delete()
                RoleActionGrant.objects.filter(role=obj).delete()
                obj.delete()
                group.delete()
            else:
                obj.delete()
    if user_ids:
        keys = [session.session_key for session in Session.objects.filter(expire_date__gt=now).iterator()
                if str(session.get_decoded().get("_auth_user_id")) in user_ids]
        Session.objects.filter(session_key__in=keys).delete()
    return {"rows": rows, "self_deleted": kind == "employees" and any(row["id"] == str(actor.pk) for row in rows)}
