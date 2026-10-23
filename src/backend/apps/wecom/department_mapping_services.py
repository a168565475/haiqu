import hashlib
import json

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.access_control.organization_services import require_organization_manager
from apps.core.api.concurrency import PreconditionFailed, etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.organizations.models import OrganizationUnit
from . import department_mapping_selectors as selectors
from . import directory_snapshots
from .directory_client import WeComDirectoryClient
from .models import WeComConfig, WeComDepartmentMapping, WeComDirectorySnapshot
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


@sensitive_variables()
def mapping_source(config):
    snapshot, directory, metadata = directory_snapshots.load(config)
    imported = directory_snapshots.read_only_import_metadata(snapshot)
    imported_visible = bool(config._state.adding and imported and directory.get("_local_import") == imported
                            and directory.get("corp_id") == config.corp_id)
    can_save = metadata["can_submit"] or bool(imported_visible and snapshot.expires_at > timezone.now())
    if imported_visible:
        capability = "可绑定本地 ERP 部门" if can_save else "副本已过期，不能保存部门映射"
        metadata = {**metadata, "message": f"线上副本来自 {imported['source_origin']}；{capability}。"
                    "本地未配置企业微信，不能重新读取或同步员工。"}
    mode = "IMPORTED" if imported_visible else "CONFIGURED"
    return snapshot, directory, metadata, can_save, mode


@sensitive_variables()
def require_mapping_source(config, preview, department_id=None):
    snapshot, directory, metadata, can_save, mode = mapping_source(config)
    saved_ids = preview.get("saved_mapping_ids", [])
    # 过期副本仅支持本次预览已存在的映射；不能借维护入口新增绑定。
    maintaining = (department_id in saved_ids and (mode == "IMPORTED" or metadata["status"] == "EXPIRED"))
    if ((not can_save and not maintaining) or (saved_ids and department_id not in saved_ids)
            or preview.get("corp_id") != config.corp_id or preview.get("source_mode") != mode
            or preview.get("snapshot_version") != etag_for_instance(snapshot)
            or preview["directory"] != digest(directory)):
        raise PreconditionFailed("部门来源副本已变化、失效或过期，请重新预览。")
    return directory


def lock_configuration_and_root(config, *, imported=False):
    if imported:
        directory_snapshots.lock_read_only_import()
        locked = get_config()
        if not locked._state.adding or locked.corp_id != config.corp_id:
            raise PreconditionFailed("本地企业微信配置已变化，请重新预览。")
    else:
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
def preview_mappings(request, *, refresh=False):
    require_schema()
    require_access(request)
    config = get_config()
    if refresh:
        directory_snapshots.refresh(request, config, read_source, require_access)
    with transaction.atomic():
        locked = (WeComConfig.objects.select_for_update().filter(pk=config.pk).first()
                  if not config._state.adding else config)
        if locked is None:
            raise PreconditionFailed("企业微信配置已变化，请重新读取。")
        require_etag(config_etag(config), config_etag(locked))
        require_access(request)
        snapshot, directory, metadata, can_save, mode = mapping_source(locked)
        mappings = selectors.mapping_snapshot(locked.corp_id)
        organizations = selectors.organization_snapshot()
        source_ids = {row["id"] for row in directory["departments"]}
        saved_ids = sorted(row["wecom_department_id"] for row in mappings["mappings"]
                           if row["wecom_department_id"] in source_ids) if (
            not can_save and (mode == "IMPORTED" or metadata["status"] == "EXPIRED")) else []
        can_edit_saved = bool(saved_ids)
        if can_edit_saved:
            metadata = {**metadata, "message": "来源副本已过期；可更换或清除已有映射，新增绑定须重新读取。"}
        version = {"actor": str(request.user.pk), "corp_id": locked.corp_id, "source_mode": mode,
                   "config": config_etag(locked), "directory": digest(directory),
                   "mappings": digest(mappings), "organizations": digest(organizations),
                   "snapshot_version": etag_for_instance(snapshot) if can_save or can_edit_saved else None,
                   "saved_mapping_ids": saved_ids}
        token = signing.dumps(version, salt=PREVIEW_SALT, compress=True) if can_save or can_edit_saved else ""
        by_source = {row["wecom_department_id"]: row for row in mappings["mappings"]}
        departments = [{**source, "mapping": by_source.get(source["id"]), "candidates": [
            unit for unit in organizations if unit["status"] == "ACTIVE" and not unit["archived"]
            and unit["unit_name"].strip().casefold() == source["name"].strip().casefold()
        ]} for source in directory["departments"]]
        return {"corp_id": locked.corp_id, "departments": departments, "organizations": organizations,
                "preview_token": token, "can_save_mapping": can_save,
                "can_edit_saved_mappings": can_edit_saved, "snapshot": metadata}, f'"{digest(version)}"'


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
    directory = require_mapping_source(config, preview, department_id)
    imported = preview["source_mode"] == "IMPORTED"
    # 绑定的是管理员刚核对的来源副本，不在每次选部门时重读全部成员。
    # 副本有效期、配置、映射及目标组织版本仍在加锁后再次核对。
    source = next((row for row in directory["departments"] if row["id"] == department_id), None)
    if source is None:
        raise NotFound("企业微信部门不在当前完整预览中。")
    with transaction.atomic():
        locked = lock_configuration_and_root(config, imported=imported)
        actor = require_access(request)
        WeComDirectorySnapshot.objects.select_for_update().filter(corp_id=locked.corp_id).first()
        require_mapping_source(locked, preview, department_id)
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
        if preview.get("saved_mapping_ids") and mapping is None:
            raise PreconditionFailed("原部门映射已不存在，请重新预览。")
        before = {"organization_unit_id": str(mapping.organization_unit_id) if mapping and mapping.organization_unit_id else None}
        if mapping is None:
            mapping = WeComDepartmentMapping(corp_id=locked.corp_id, wecom_department_id=department_id)
        mapping.wecom_department_name = source["name"]
        mapping.organization_unit = target
        require_mapping_source(locked, preview, department_id)
        actor = require_access(request)
        mapping.save()
        audit(request, mapping, "DEPARTMENT_MAPPING_UPDATE", actor=actor, before=before,
              after={"wecom_department_id": department_id, "wecom_department_name": source["name"],
                     "organization_unit_id": str(target.pk) if target else None},
              message="管理员确认部门映射；未改变员工部门、角色或权限。")
        return next(row for row in selectors.mapping_snapshot(locked.corp_id)["mappings"] if row["id"] == str(mapping.pk))
