"""正式启用专用备份证据：必须在本次停写后开始备份，并验证完整恢复。"""
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from django.db import connection
from django.utils import timezone
from django.utils.dateparse import parse_datetime


SHA256 = re.compile(r"^[0-9a-f]{64}$")
TABLE_ROW = re.compile(r"^(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\|(?P<count>0|[1-9][0-9]*)\|[0-9a-f]{32}$")
TIME_FIELDS = ("backup_started_at", "backup_completed_at", "restore_verified_at")
SHARED_FIELDS = {"schema_version", "target", "maintenance", "backup_sha256", "backup_bytes", "restore_target", *TIME_FIELDS}
EVIDENCE_FIELDS = SHARED_FIELDS | {"backup_file", "verification_file", "verification_sha256", "restore_verified"}
VERIFICATION_FIELDS = SHARED_FIELDS | {"table_count", "source_before", "source_after", "restored", "passed"}


class ActivationBackupError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _reject(code, message):
    raise ActivationBackupError(code, message)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject("ACTIVATION_BACKUP_INVALID", "备份证据包含重复 JSON 字段。")
        result[key] = value
    return result


def _read_file(value, *, json_file=False):
    if not isinstance(value, (str, Path)) or not str(value).strip() or not Path(value).is_absolute():
        _reject("ACTIVATION_BACKUP_INVALID", "备份及恢复证据必须使用绝对文件路径。")
    try:
        path = Path(value).resolve(strict=True)
        if not stat.S_ISREG(path.stat().st_mode):
            _reject("ACTIVATION_BACKUP_INVALID", "备份和恢复证据必须是普通文件。")
        # 非阻塞打开也覆盖检查后被替换成命名管道的情况，避免工具卡住。
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size <= 0 or (json_file and before.st_size > 1024 * 1024):
                _reject("ACTIVATION_BACKUP_INVALID", "证据必须为非空普通文件，JSON 不得超过 1 MB。")
            digest = hashlib.sha256()
            chunks = []
            size = 0
            header = b""
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                if not header:
                    header = chunk[:5]
                size += len(chunk)
                digest.update(chunk)
                if json_file:
                    chunks.append(chunk)
                if json_file and size > 1024 * 1024:
                    _reject("ACTIVATION_BACKUP_INVALID", "读取中的证据超过 1 MB。")
            after = os.fstat(stream.fileno())
            current = path.stat()
            fingerprint = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
            if size != before.st_size or fingerprint(before) != fingerprint(after) or fingerprint(after) != fingerprint(current):
                _reject("ACTIVATION_BACKUP_CHANGED", "备份或恢复证据在核验期间发生变化。")
        if not json_file and header != b"PGDMP":
            _reject("ACTIVATION_BACKUP_FORMAT_INVALID", "启用备份必须为 PostgreSQL 自定义格式归档。")
        data = json.loads(b"".join(chunks).decode("utf-8-sig"), object_pairs_hook=_object) if json_file else None
        return path, digest.hexdigest(), size, data
    except ActivationBackupError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ActivationBackupError("ACTIVATION_BACKUP_UNREADABLE", "备份或恢复证据不可读取，或不是有效 JSON。") from error


def _time(value, field):
    try:
        parsed = parse_datetime(value) if isinstance(value, str) else None
    except (ValueError, TypeError, OverflowError):
        parsed = None
    if parsed is None or timezone.is_naive(parsed):
        _reject("ACTIVATION_BACKUP_TIME_INVALID", f"{field}必须是带时区的完整时间。")
    return parsed


def _table_map(value, field):
    if not isinstance(value, list) or not value:
        _reject("ACTIVATION_BACKUP_RESTORE_INVALID", f"{field}缺少逐表完整比对。")
    result = {}
    for row in value:
        match = TABLE_ROW.fullmatch(row) if isinstance(row, str) else None
        if match is None or match["name"] in result:
            _reject("ACTIVATION_BACKUP_RESTORE_INVALID", f"{field}存在格式错误或重复表名。")
        result[match["name"]] = row
    return result


def validate_activation_backup(evidence_path, *, target, control):
    """只读核实证据与实际文件，不执行备份、恢复或写入数据库。"""
    if control is None or control.state != "MAINTENANCE":
        _reject("ACTIVATION_BACKUP_MAINTENANCE_REQUIRED", "启用备份必须绑定当前维护会话。")
    if not evidence_path:
        _reject("ACTIVATION_BACKUP_REQUIRED", "缺少本次停写后开始、并已恢复核验的启用备份证据。")
    evidence_path, evidence_hash, _, evidence = _read_file(evidence_path, json_file=True)
    if not isinstance(evidence, dict) or type(evidence.get("schema_version")) is not int or evidence["schema_version"] != 2:
        _reject("ACTIVATION_BACKUP_VERSION_REQUIRED", "启用必须使用版本 2 备份证据；旧证据缺少开始时点，不可推定补写。")
    if set(evidence) != EVIDENCE_FIELDS:
        _reject("ACTIVATION_BACKUP_INVALID", "启用备份证据字段缺失或包含不支持的字段。")
    if evidence["target"] != target:
        _reject("ACTIVATION_BACKUP_TARGET_MISMATCH", "备份目标与实际启用的主机、数据库和实例不一致。")
    maintenance = evidence["maintenance"]
    if (not isinstance(maintenance, dict) or set(maintenance) != {"control_id", "started_at"}
            or maintenance["control_id"] != str(control.pk)
            or _time(maintenance["started_at"], "maintenance.started_at") != control.started_at):
        _reject("ACTIVATION_BACKUP_SESSION_MISMATCH", "备份没有绑定本次维护记录及其开始时点。")
    times = [_time(evidence[key], key) for key in TIME_FIELDS]
    if not (control.started_at <= times[0] <= times[1] <= times[2] <= timezone.now()):
        _reject("ACTIVATION_BACKUP_TIME_INVALID", "必须先停写、再开始备份、完成备份、完成恢复核验，且不能使用未来时间。")
    restore_target = evidence["restore_target"]
    if (not isinstance(restore_target, dict) or set(restore_target) != {"host", "database", "system_identifier"}
            or any(not isinstance(value, str) or not value.strip() for value in restore_target.values())
            or not restore_target["system_identifier"].isdigit()
            or (restore_target["system_identifier"], restore_target["database"]) == (target["system_identifier"], target["database"])):
        _reject("ACTIVATION_BACKUP_RESTORE_INVALID", "恢复验证必须指向另一个数据库，不能覆盖原业务数据库。")
    if evidence["restore_verified"] is not True:
        _reject("ACTIVATION_BACKUP_RESTORE_INVALID", "缺少成功恢复的明确记录。")
    for field in ("backup_sha256", "verification_sha256"):
        if not isinstance(evidence[field], str) or not SHA256.fullmatch(evidence[field]):
            _reject("ACTIVATION_BACKUP_INVALID", f"{field}必须是完整 SHA-256。")
    backup_path, backup_hash, backup_size, _ = _read_file(evidence["backup_file"])
    if (type(evidence["backup_bytes"]) is not int or evidence["backup_bytes"] <= 0
            or evidence["backup_bytes"] != backup_size or evidence["backup_sha256"] != backup_hash):
        _reject("ACTIVATION_BACKUP_HASH_MISMATCH", "实际备份文件摘要或大小与记录不一致。")
    verification_path, verification_hash, _, verification = _read_file(evidence["verification_file"], json_file=True)
    if verification_hash != evidence["verification_sha256"]:
        _reject("ACTIVATION_BACKUP_VERIFICATION_CHANGED", "恢复报告实际 SHA-256 与证据绑定值不一致。")
    if (not isinstance(verification, dict) or set(verification) != VERIFICATION_FIELDS
            or type(verification.get("schema_version")) is not int
            or any(verification.get(key) != evidence[key] for key in SHARED_FIELDS)
            or verification.get("passed") is not True):
        _reject("ACTIVATION_BACKUP_RESTORE_INVALID", "恢复报告没有绑定同一备份、维护会话、目标与实际恢复结果。")
    before = _table_map(verification["source_before"], "source_before")
    after = _table_map(verification["source_after"], "source_after")
    restored = _table_map(verification["restored"], "restored")
    if (type(verification["table_count"]) is not int or verification["table_count"] != len(before)
            or before != after or before != restored):
        _reject("ACTIVATION_BACKUP_RESTORE_MISMATCH", "备份前、备份后及恢复库的逐表行数或内容摘要不一致。")
    current_tables = set(connection.introspection.table_names())
    if set(before) != current_tables:
        _reject("ACTIVATION_BACKUP_TABLE_SET_CHANGED", "恢复报告缺表，或备份后的数据库结构已变化，需要重新备份及恢复核验。")
    return {"schema_version": 2, "evidence_file": str(evidence_path), "evidence_sha256": evidence_hash,
        "target": target, "maintenance": {"control_id": str(control.pk), "started_at": control.started_at.isoformat()},
        "backup_file": str(backup_path), "backup_sha256": backup_hash, "backup_bytes": backup_size,
        **{key: value.isoformat() for key, value in zip(TIME_FIELDS, times)},
        "restore_target": restore_target, "verification_file": str(verification_path),
        "verification_sha256": verification_hash, "table_count": len(before), "restore_verified": True}
