"""数据库持久快照：GET 只读；主动刷新完整成功后才替换。"""
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import APIException

from apps.core.api.concurrency import PreconditionFailed, etag_for_instance
from .models import WeComConfig, WeComDirectorySnapshot
from .selectors import config_etag, configuration_complete
from .services import require_etag


SNAPSHOT_TTL = timedelta(hours=24)
READ_ONLY_IMPORT_ETAG = '"wecom-remote-read-only-import-v1"'


def read_only_import_metadata(row):
    if row is None or row.config_etag != READ_ONLY_IMPORT_ETAG or not isinstance(row.directory, dict):
        return None
    metadata = row.directory.get("_local_import")
    if (not isinstance(metadata, dict) or metadata.get("kind") != "REMOTE_READ_ONLY"
            or metadata.get("schema") != "wecom-directory-readonly-copy-v1"
            or not isinstance(metadata.get("source_config_etag"), str) or not metadata["source_config_etag"]):
        return None
    if row.directory.get("corp_id") != row.corp_id:
        return None
    origin = metadata.get("source_origin")
    read_at = metadata.get("source_read_at")
    imported_at = metadata.get("imported_at")
    if not all(isinstance(value, str) for value in (origin, read_at, imported_at)):
        return None
    try:
        parts = urlsplit(origin)
        source_time, import_time = parse_datetime(read_at), parse_datetime(imported_at)
    except ValueError:
        return None
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.path or parts.query or parts.fragment or len(origin) > 255
            or source_time is None or import_time is None or not timezone.is_aware(source_time)
            or not timezone.is_aware(import_time) or source_time != row.fetched_at):
        return None
    return metadata


class DirectorySnapshotUnavailable(APIException):
    status_code = 503
    default_detail = "通讯录本地快照尚未完成数据库迁移，请联系管理员。"
    default_code = "directory_snapshot_unavailable"


def require_schema():
    if not MigrationRecorder.Migration.objects.filter(app="wecom", name="0005_directory_snapshot").exists():
        raise DirectorySnapshotUnavailable()


def lock_read_only_import():
    """调用方须处于事务内；配置表 → 导入互斥锁，保持导入与本地映射的顺序一致。"""
    with connection.cursor() as cursor:
        cursor.execute('LOCK TABLE "wecom_config" IN SHARE MODE')
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["wecom-directory-read-only-import"])


@sensitive_variables()
def load(config):
    require_schema()
    row = WeComDirectorySnapshot.objects.filter(corp_id=config.corp_id).first()
    imported = (read_only_import_metadata(row)
                if config._state.adding and not WeComConfig.objects.exists() else None)
    status, message = "MISSING", "尚无成功读取的本地副本，请主动重新读取。"
    if imported is not None:
        status = "CONFIG_UNAVAILABLE"
        age = "副本已过期；" if row.expires_at <= timezone.now() else ""
        message = f"线上读取结果来自 {imported['source_origin']}；{age}仅供本地查看。本地未配置企业微信，不能刷新、同步或保存映射。"
    elif config._state.adding or not config.enabled or not configuration_complete(config):
        status, message = "CONFIG_UNAVAILABLE", "企业微信应用未启用或配置不完整，不能使用来源副本。"
    elif row is not None:
        if row.config_etag != config_etag(config):
            status, message = "CONFIG_CHANGED", "企业微信配置已变化，请主动重新读取。"
        elif row.expires_at <= timezone.now():
            status, message = "EXPIRED", "本地副本已过期，仅供查看；请主动重新读取后操作。"
        else:
            status, message = "VALID", "已恢复本地副本，并重新核对当前 ERP 状态。"
    usable = status == "VALID"
    metadata = {"status": status, "message": message, "can_submit": usable,
                "fetched_at": row.fetched_at if row else None, "expires_at": row.expires_at if row else None}
    # 配置变化后不回传旧企业/旧应用可见范围的名单。
    directory = row.directory if row and (imported is not None or status in ("VALID", "EXPIRED")) else {
        "corp_id": config.corp_id, "departments": [], "members": [],
    }
    return row, directory, metadata


@sensitive_variables()
def refresh(request, config, read_source, require_access):
    require_schema()
    started_at = timezone.now()
    directory = read_source(config)
    with transaction.atomic():
        locked = WeComConfig.objects.select_for_update().filter(pk=config.pk).first()
        if locked is None:
            raise PreconditionFailed("企业微信配置已变化，请重新读取。")
        require_etag(config_etag(config), config_etag(locked))
        require_access(request)
        current = WeComDirectorySnapshot.objects.filter(corp_id=locked.corp_id).first()
        if current and current.fetched_at > started_at:
            raise PreconditionFailed("已有更新的读取结果，请恢复本地副本。")
        now = timezone.now()
        WeComDirectorySnapshot.objects.update_or_create(corp_id=locked.corp_id, defaults={
            "config_etag": config_etag(locked), "directory": directory,
            "fetched_at": now, "expires_at": now + SNAPSHOT_TTL,
        })


def require_version(config, version):
    row, _, metadata = load(config)
    if not metadata["can_submit"] or etag_for_instance(row) != version:
        raise PreconditionFailed("本地通讯录副本已更新、失效或过期，请重新预览。")
