import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core.database_backup import validate_database_backup


class DatabaseBackupValidationTests(SimpleTestCase):
    identity = {
        "source_database": "haiqu_erp",
        "source_database_user": "haiqu",
        "source_database_host": "postgres",
        "source_database_port": "5432",
        "source_system_identifier": "123456789",
    }

    def _files(self, directory, *, identity=None):
        backup_path = Path(directory) / "database.dump"
        backup_path.write_bytes(b"PGDMP-test-backup")
        attestation = {
            **(identity or self.identity),
            "backup_sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest().upper(),
            "backup_size_bytes": backup_path.stat().st_size,
            "pg_restore_list_verified": True,
            "restore_rehearsal_verified": True,
        }
        attestation_path = Path(directory) / "attestation.json"
        attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
        return backup_path, attestation_path

    @patch("apps.core.database_backup.database_identity")
    def test_accepts_matching_backup_and_database_identity(self, database_identity):
        database_identity.return_value = self.identity
        with tempfile.TemporaryDirectory() as directory:
            backup_path, attestation_path = self._files(directory)
            result = validate_database_backup(backup_path, attestation_path)
        self.assertEqual(result["source_system_identifier"], "123456789")

    @patch("apps.core.database_backup.database_identity")
    def test_rejects_backup_from_another_database_instance(self, database_identity):
        database_identity.return_value = self.identity
        with tempfile.TemporaryDirectory() as directory:
            wrong_identity = {**self.identity, "source_system_identifier": "987654321"}
            backup_path, attestation_path = self._files(directory, identity=wrong_identity)
            with self.assertRaisesMessage(ValueError, "数据库实例身份不匹配"):
                validate_database_backup(backup_path, attestation_path)
