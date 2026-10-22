"""从受控来源封套导入仅供本地查看的目录，不复制企微配置。"""
from datetime import timedelta
import re
from urllib.parse import urlsplit

from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import ValidationError

from .client import WeComError, _valid_text
from .directory_client import _member, _uint32
from .directory_snapshots import (
    READ_ONLY_IMPORT_ETAG, SNAPSHOT_TTL, lock_read_only_import, read_only_import_metadata, require_schema,
)
from .models import WeComConfig, WeComDirectorySnapshot
from .selectors import get_config


COPY_SCHEMA = "wecom-directory-readonly-copy-v1"


def source_origin(value):
    if not isinstance(value, str) or len(value) > 255 or any(char.isspace() for char in value):
        raise ValidationError("来源地址必须是完整的 HTTPS origin。")
    try:
        parts = urlsplit(value)
        valid_port = parts.port is None or 1 <= parts.port <= 65535
    except ValueError as exc:
        raise ValidationError("来源地址无效。") from exc
    if (parts.scheme != "https" or not parts.hostname or not valid_port or parts.username or parts.password
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise ValidationError("来源地址只允许不含凭据、路径或查询参数的 HTTPS origin。")
    return f"https://{parts.netloc}"


@sensitive_variables()
def validated_directory(data, expected_corp_id):
    if not isinstance(data, dict) or set(data) != {"corp_id", "departments", "members"}:
        raise ValidationError("目录字段不完整或包含不支持字段。")
    if not _valid_text(data["corp_id"], 100) or data["corp_id"] != expected_corp_id:
        raise ValidationError("目录CorpID与本次明确指定的企业不一致。")
    departments, members = data["departments"], data["members"]
    if not isinstance(departments, list) or not isinstance(members, list) or not departments or not members:
        raise ValidationError("完整读取副本必须包含部门和成员列表。")
    by_id = {}
    for row in departments:
        if (not isinstance(row, dict) or set(row) != {"id", "parentid", "name"}
                or not _uint32(row["id"], 1) or not _uint32(row["parentid"])
                or not _valid_text(row["name"], 768) or row["id"] in by_id):
            raise ValidationError("来源部门字段无效或ID重复。")
        by_id[row["id"]] = {**row, "name": row["name"].strip()}
    if 1 not in by_id or by_id[1]["parentid"] != 0:
        raise ValidationError("来源部门树缺少有效根部门。")
    for department_id in by_id:
        seen, current = set(), department_id
        while current != 1:
            if current not in by_id or current in seen:
                raise ValidationError("来源部门树不完整或存在循环。")
            seen.add(current)
            current = by_id[current]["parentid"]
    normalized, seen_members = [], set()
    for row in members:
        if not isinstance(row, dict) or set(row) != {
            "userid", "name", "department", "main_department", "status", "status_label",
        }:
            raise ValidationError("来源成员字段不完整或包含不支持字段。")
        try:
            member = _member(row)
        except WeComError as exc:
            raise ValidationError("来源成员字段无效。") from exc
        key = member["userid"].lower()
        if (key in seen_members or not set(member["department"]).issubset(by_id)
                or row["status_label"] != member["status_label"]):
            raise ValidationError("来源成员重复、引用未知部门或状态说明不一致。")
        seen_members.add(key)
        normalized.append(member)
    return {"corp_id": expected_corp_id, "departments": sorted(by_id.values(), key=lambda row: row["id"]),
            "members": sorted(normalized, key=lambda row: row["userid"].lower())}


@sensitive_variables()
def import_directory_copy(envelope, *, database_name, expected_corp_id, expected_source_origin, apply=False):
    if database_name != connection.settings_dict["NAME"]:
        raise ValidationError("必须明确指定当前目标数据库完整名称。")
    if (not isinstance(envelope, dict) or set(envelope) != {
        "schema", "source_origin", "fetched_at", "source_config_etag", "directory",
    } or envelope["schema"] != COPY_SCHEMA):
        raise ValidationError("来源封套格式无效。")
    origin = source_origin(envelope["source_origin"])
    if origin != source_origin(expected_source_origin):
        raise ValidationError("来源地址与本次明确指定的线上来源不一致。")
    if not isinstance(envelope["source_config_etag"], str) or not re.fullmatch(
        r'"[a-f0-9]{64}"', envelope["source_config_etag"],
    ):
        raise ValidationError("来源配置版本无效。")
    try:
        fetched_at = parse_datetime(envelope["fetched_at"]) if isinstance(envelope["fetched_at"], str) else None
    except ValueError as exc:
        raise ValidationError("来源读取时间无效。") from exc
    now = timezone.now()
    if (fetched_at is None or not timezone.is_aware(fetched_at)
            or fetched_at > now + timedelta(minutes=5) or fetched_at + SNAPSHOT_TTL <= now):
        raise ValidationError("来源读取时间必须带时区、未过期且不能晚于当前时间。")
    directory = validated_directory(envelope["directory"], expected_corp_id)
    require_schema()
    with transaction.atomic():
        # 先阻止配置并发创建/修改，再串行受控导入；不修改配置或组织/权限记录。
        lock_read_only_import()
        if WeComConfig.objects.exists() or get_config().corp_id != expected_corp_id:
            raise ValidationError("只读导入仅适用于没有本地企微配置且CorpID与当前本地选择一致的环境。")
        current = WeComDirectorySnapshot.objects.select_for_update().filter(corp_id=expected_corp_id).first()
        if current and (not read_only_import_metadata(current) or current.fetched_at >= fetched_at):
            raise ValidationError("不能覆盖普通快照、来源不明副本或相同/更新的读取结果。")
        expires_at = fetched_at + SNAPSHOT_TTL
        if expires_at <= timezone.now():
            raise ValidationError("等待期间来源副本已过期，未保存。")
        if apply:
            WeComDirectorySnapshot.objects.update_or_create(corp_id=expected_corp_id, defaults={
                "config_etag": READ_ONLY_IMPORT_ETAG, "fetched_at": fetched_at, "expires_at": expires_at,
                "directory": {**directory, "_local_import": {
                    "kind": "REMOTE_READ_ONLY", "schema": COPY_SCHEMA, "source_origin": origin,
                    "source_config_etag": envelope["source_config_etag"],
                    "source_read_at": fetched_at.isoformat(), "imported_at": now.isoformat(),
                }},
            })
    return {"applied": apply, "corp_id": expected_corp_id, "source_origin": origin,
            "fetched_at": fetched_at.isoformat(), "expires_at": expires_at.isoformat(),
            "department_count": len(directory["departments"]), "member_count": len(directory["members"]),
            "can_submit": False}
