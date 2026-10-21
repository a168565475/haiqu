import hashlib
import json

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.access_control.organization_services import require_organization_manager
from apps.core.api.concurrency import PreconditionFailed, etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.organizations.models import OrganizationUnit
from . import department_mapping_selectors as selectors
from .directory_client import WeComDirectoryClient
from .models import WeComConfig, WeComDepartmentMapping
from .selectors import config_etag, configuration_complete, get_config
from .services import audit, require_etag


PREVIEW_SALT = "wecom.department-mapping.v1"
PREVIEW_MAX_AGE = 600


class DepartmentMappingUnavailable(APIException):
    status_code = 503
    default_detail = "部门映射尚未完成数据库迁移，请联系管理员。"
    default_code = "department_mapping_unavailable"


def require_schema():
    if not selectors.schema_is_ready():
        raise DepartmentMappingUnavailable()


def require_access(request):
    user = get_user_model().objects.filter(pk=request.user.pk).first()
    if user is None:
        raise PermissionDenied("当前账号已失效。")
    request.user = user
    return require_organization_manager(request)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


@sensitive_variables()
def read_source(config):
    if config._state.adding or not config.enabled or not configuration_complete(config):
        raise Conflict("企业微信应用未启用或配置不完整，请联系管理员。")
    return WeComDirectoryClient(config).read_directory()


def lock_configuration_and_root(config):
    locked = WeComConfig.objects.select_for_update().filter(pk=config.pk).first()
    if locked is None:
        raise PreconditionFailed("企业微信配置已变化，请重新读取。")
    require_etag(config_etag(config), config_etag(locked))
    # 与组织维护共用根组织锁，避免核对版本后部门被停用或更名。
    root = OrganizationUnit.objects.select_for_update().filter(unit_code="HAIQU").first()
    if root is None or root.status != "ACTIVE" or root.archived_at is not None:
        raise Conflict("ERP 根组织未就绪，请先维护组织结构。")
    return locked


@sensitive_variables()
def preview_mappings(request):
    require_schema()
    require_access(request)
    config = get_config()
    directory = read_source(config)
    with transaction.atomic():
        locked = lock_configuration_and_root(config)
        require_access(request)
        mappings = selectors.mapping_snapshot(locked.corp_id)
        organizations = selectors.organization_snapshot()
        version = {"actor": str(request.user.pk), "config": config_etag(locked), "directory": digest(directory),
                   "mappings": digest(mappings), "organizations": digest(organizations)}
        token = signing.dumps(version, salt=PREVIEW_SALT, compress=True)
        by_source = {row["wecom_department_id"]: row for row in mappings["mappings"]}
        departments = [{**source, "mapping": by_source.get(source["id"]), "candidates": [
            unit for unit in organizations if unit["status"] == "ACTIVE" and not unit["archived"]
            and unit["unit_name"].strip().casefold() == source["name"].strip().casefold()
        ]} for source in directory["departments"]]
        return {"corp_id": locked.corp_id, "departments": departments, "organizations": organizations,
                "preview_token": token}, f'"{digest(version)}"'


@sensitive_variables()
def update_mapping(request, department_id, data):
    require_schema()
    require_access(request)
    if not 1 <= department_id < 2 ** 32:
        raise ValidationError({"department_id": "企业微信部门 ID 必须是有效的正整数。"})
    try:
        preview = signing.loads(data["preview_token"], salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
    except signing.BadSignature as exc:
        raise ValidationError({"preview_token": "预览已过期或无效，请重新读取并核对。"}) from exc
    if preview["actor"] != str(request.user.pk):
        raise ValidationError({"preview_token": "请使用当前账号重新预览。"})
    require_etag(request.headers.get("If-Match"), f'"{digest(preview)}"')
    config = get_config()
    require_etag(preview["config"], config_etag(config))
    directory = read_source(config)
    if digest(directory) != preview["directory"]:
        raise PreconditionFailed("企业微信通讯录已变化，请重新预览。")
    source = next((row for row in directory["departments"] if row["id"] == department_id), None)
    if source is None:
        raise NotFound("企业微信部门不在当前完整预览中。")
    with transaction.atomic():
        locked = lock_configuration_and_root(config)
        actor = require_access(request)
        if digest(selectors.mapping_snapshot(locked.corp_id)) != preview["mappings"]:
            raise PreconditionFailed("部门映射或对应 ERP 部门已变化，请重新预览。")
        if digest(selectors.organization_snapshot()) != preview["organizations"]:
            raise PreconditionFailed("ERP 组织结构已变化，请重新预览。")
        target = None
        if data["organization_unit_id"] is not None:
            target = OrganizationUnit.objects.select_for_update().filter(pk=data["organization_unit_id"]).first()
            if target is None:
                raise NotFound("所选 ERP 部门不存在。")
            require_etag(data["organization_etag"], etag_for_instance(target))
            if target.status != "ACTIVE" or target.archived_at is not None:
                raise Conflict("只能映射到启用且未归档的 ERP 部门。")
        mapping = WeComDepartmentMapping.objects.filter(corp_id=locked.corp_id, wecom_department_id=department_id).first()
        before = {"organization_unit_id": str(mapping.organization_unit_id) if mapping and mapping.organization_unit_id else None}
        if mapping is None:
            mapping = WeComDepartmentMapping(corp_id=locked.corp_id, wecom_department_id=department_id)
        mapping.wecom_department_name = source["name"]
        mapping.organization_unit = target
        mapping.save()
        audit(request, mapping, "DEPARTMENT_MAPPING_UPDATE", actor=actor, before=before,
              after={"wecom_department_id": department_id, "wecom_department_name": source["name"],
                     "organization_unit_id": str(target.pk) if target else None},
              message="管理员确认部门映射；未改变员工部门、角色或权限。")
        return next(row for row in selectors.mapping_snapshot(locked.corp_id)["mappings"] if row["id"] == str(mapping.pk))
