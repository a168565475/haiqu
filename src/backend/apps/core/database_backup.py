import hashlib
import json
from pathlib import Path

from django.db import connection


def database_identity():
    """返回足以区分数据库实例与目标库的稳定身份。"""
    settings_dict = connection.settings_dict
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                current_database(),
                current_user,
                system_identifier::text
            FROM pg_control_system()
            """
        )
        database_name, database_user, system_identifier = cursor.fetchone()
    return {
        "source_database": str(database_name),
        "source_database_user": str(database_user),
        "source_database_host": str(settings_dict.get("HOST") or ""),
        "source_database_port": str(settings_dict.get("PORT") or ""),
        "source_system_identifier": str(system_identifier),
    }


def backup_sha256(backup_path):
    digest = hashlib.sha256()
    with Path(backup_path).open("rb") as backup_source:
        for chunk in iter(lambda: backup_source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def validate_database_backup(backup_path, attestation_path):
    """验证备份本体、恢复演练凭据和当前数据库实例身份。"""
    backup_path = Path(backup_path).resolve()
    attestation_path = Path(attestation_path).resolve()
    if not backup_path.is_file() or backup_path.stat().st_size <= 0:
        raise ValueError("未找到非空数据库备份。")
    with backup_path.open("rb") as backup_source:
        if backup_source.read(5) != b"PGDMP":
            raise ValueError("数据库备份不是 PostgreSQL custom-format 文件。")
    if not attestation_path.is_file():
        raise ValueError("缺少备份验证 JSON。")
    try:
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"备份验证 JSON 无法读取：{exc}") from exc

    actual_identity = database_identity()
    required_identity = {
        key: str(attestation.get(key) or "")
        for key in actual_identity
    }
    if (
        str(attestation.get("backup_sha256") or "").upper() != backup_sha256(backup_path)
        or attestation.get("backup_size_bytes") != backup_path.stat().st_size
        or attestation.get("pg_restore_list_verified") is not True
        or attestation.get("restore_rehearsal_verified") is not True
        or required_identity != actual_identity
    ):
        raise ValueError("备份哈希、大小、恢复演练凭据或当前数据库实例身份不匹配。")
    return attestation
