import copy
import hashlib
import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from unittest import skipUnless

from django.test import SimpleTestCase
from django.utils import timezone

from ..public_stock_activation_backup import ActivationBackupError, validate_activation_backup


class ActivationBackupEvidenceTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory(prefix="activation-backup-test-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.backup = self.folder / "fixture.dump"
        # 仅用于校验器单元测试，不能作为实际备份或恢复验收证据。
        self.backup.write_bytes(b"PGDMP synthetic unit test fixture")
        self.verification = self.folder / "verification.json"
        self.evidence_path = self.folder / "evidence.json"
        self.target = {"host": "isolated", "database": "source", "system_identifier": "123456"}
        start = timezone.now() - timedelta(minutes=10)
        self.control = SimpleNamespace(pk="test-maintenance", state="MAINTENANCE", started_at=start)
        self.evidence = {
            "schema_version": 2, "target": self.target,
            "maintenance": {"control_id": str(self.control.pk), "started_at": start.isoformat()},
            "backup_started_at": (start + timedelta(minutes=1)).isoformat(),
            "backup_completed_at": (start + timedelta(minutes=2)).isoformat(),
            "restore_verified_at": (start + timedelta(minutes=3)).isoformat(),
            "restore_target": {**self.target, "database": "restorecheck"}, "restore_verified": True,
            "backup_file": str(self.backup), "backup_sha256": self.digest(self.backup),
            "backup_bytes": self.backup.stat().st_size, "verification_file": str(self.verification),
            "verification_sha256": "",
        }
        self.report = {key: copy.deepcopy(value) for key, value in self.evidence.items()
            if key not in {"backup_file", "verification_file", "verification_sha256", "restore_verified"}}
        row = "bom_line|2|" + "a" * 32
        self.report.update(table_count=1, source_before=[row], source_after=[row], restored=[row], passed=True)
        self.write_files()
        tables = patch("apps.inventory.public_stock_activation_backup.connection.introspection.table_names", return_value=["bom_line"])
        self.mock_tables = tables.start()
        self.addCleanup(tables.stop)

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_files(self):
        self.verification.write_text(json.dumps(self.report), encoding="utf-8")
        self.evidence["verification_sha256"] = self.digest(self.verification)
        self.evidence_path.write_text(json.dumps(self.evidence), encoding="utf-8")

    def validate(self):
        return validate_activation_backup(self.evidence_path, target=self.target, control=self.control)

    def assert_code(self, code):
        with self.assertRaises(ActivationBackupError) as error:
            self.validate()
        self.assertEqual(error.exception.code, code)

    def test_binds_actual_files_session_times_target_and_complete_restore(self):
        result = self.validate()
        self.assertEqual(result["evidence_sha256"], self.digest(self.evidence_path))
        self.assertEqual(result["verification_sha256"], self.digest(self.verification))
        self.assertEqual(result["backup_sha256"], self.digest(self.backup))
        self.assertEqual(result["maintenance"]["control_id"], str(self.control.pk))
        self.assertEqual(result["table_count"], 1)
        self.assertEqual(result, self.validate())

    def test_old_evidence_cannot_supply_a_guessed_start_time(self):
        self.evidence["schema_version"] = 1
        self.write_files()
        self.assert_code("ACTIVATION_BACKUP_VERSION_REQUIRED")
        self.evidence["schema_version"] = 2
        del self.evidence["backup_started_at"]
        self.write_files()
        self.assert_code("ACTIVATION_BACKUP_INVALID")

    def test_requires_current_maintenance_and_exact_session(self):
        for state in ("PUBLIC", "LEGACY"):
            with self.subTest(state=state):
                self.control.state = state
                self.assert_code("ACTIVATION_BACKUP_MAINTENANCE_REQUIRED")
        self.control.state = "MAINTENANCE"
        self.evidence["maintenance"]["control_id"] = "old-session"
        self.write_files()
        self.assert_code("ACTIVATION_BACKUP_SESSION_MISMATCH")

    def test_rejects_wrong_source_and_restore_over_source_even_with_host_alias(self):
        self.evidence["target"] = {**self.target, "database": "other"}
        self.write_files()
        self.assert_code("ACTIVATION_BACKUP_TARGET_MISMATCH")
        self.evidence["target"] = self.target
        self.evidence["restore_target"] = {**self.target, "host": "another-alias"}
        self.write_files()
        self.assert_code("ACTIVATION_BACKUP_RESTORE_INVALID")

    def test_rejects_premaintenance_reversed_naive_and_future_times(self):
        original = copy.deepcopy(self.evidence)
        changes = [
            ("backup_started_at", (self.control.started_at - timedelta(seconds=1)).isoformat()),
            ("backup_completed_at", self.control.started_at.isoformat()),
            ("restore_verified_at", self.control.started_at.isoformat()),
            ("backup_started_at", "2026-09-28T12:00:00"),
            ("restore_verified_at", (timezone.now() + timedelta(days=1)).isoformat()),
        ]
        for key, value in changes:
            with self.subTest(field=key, value=value):
                self.evidence = copy.deepcopy(original)
                self.evidence[key] = value
                self.write_files()
                self.assert_code("ACTIVATION_BACKUP_TIME_INVALID")

    def test_rejects_changed_backup_and_nonarchive_files(self):
        self.backup.write_bytes(b"PGDMP changed fixture")
        self.assert_code("ACTIVATION_BACKUP_HASH_MISMATCH")
        self.backup.write_bytes(b"not a database archive")
        self.assert_code("ACTIVATION_BACKUP_FORMAT_INVALID")

    def test_rejects_report_tampering_or_wrong_backup_binding(self):
        self.verification.write_text("{}", encoding="utf-8")
        self.assert_code("ACTIVATION_BACKUP_VERIFICATION_CHANGED")
        self.report["backup_sha256"] = "b" * 64
        self.write_files()
        self.assert_code("ACTIVATION_BACKUP_RESTORE_INVALID")

    def test_rejects_missing_duplicate_or_changed_table_content(self):
        original = copy.deepcopy(self.report)
        for changed in ([], [original["restored"][0]] * 2, ["bom_line|3|" + "a" * 32]):
            with self.subTest(rows=changed):
                self.report = copy.deepcopy(original)
                self.report["restored"] = changed
                self.write_files()
                with self.assertRaises(ActivationBackupError):
                    self.validate()
        self.report = copy.deepcopy(original)
        self.write_files()
        self.mock_tables.return_value = ["bom_line", "new_table"]
        self.assert_code("ACTIVATION_BACKUP_TABLE_SET_CHANGED")

    def test_rejects_claimed_success_without_matching_source_after(self):
        self.report["source_after"] = ["bom_line|4|" + "a" * 32]
        self.write_files()
        self.assert_code("ACTIVATION_BACKUP_RESTORE_MISMATCH")

    def test_rejects_booleans_unknown_fields_and_duplicate_json_keys(self):
        original = copy.deepcopy(self.evidence)
        for key, value in (("backup_bytes", True), ("restore_verified", "true"), ("unexpected", "x")):
            with self.subTest(field=key):
                self.evidence = copy.deepcopy(original)
                self.evidence[key] = value
                self.write_files()
                with self.assertRaises(ActivationBackupError):
                    self.validate()
        self.evidence_path.write_text('{"schema_version":2,"schema_version":2}', encoding="utf-8")
        self.assert_code("ACTIVATION_BACKUP_INVALID")

    def test_rejects_missing_or_relative_paths(self):
        self.evidence["backup_file"] = "relative.dump"
        self.write_files()
        self.assert_code("ACTIVATION_BACKUP_INVALID")
        self.evidence["backup_file"] = str(self.folder / "missing.dump")
        self.write_files()
        self.assert_code("ACTIVATION_BACKUP_UNREADABLE")

    @skipUnless(hasattr(os, "mkfifo"), "此平台没有命名管道")
    def test_rejects_named_pipe_without_waiting_for_a_writer(self):
        pipe = self.folder / "not-a-backup.dump"
        os.mkfifo(pipe)
        self.evidence["backup_file"] = str(pipe)
        self.write_files()
        self.assert_code("ACTIVATION_BACKUP_INVALID")
