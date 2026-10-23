from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.exceptions import APIException, NotFound

from apps.files.models import BusinessFile
from apps.finance.receipt_models import FinanceReceiptUpload
from apps.finance.receipt_uploads import (compensate_upload_file, create_receipt_upload, discard_receipt_upload,
    read_recovery_record, receipt_file_path, record_new_file, recovery_path, require_usable_file, upload_digest)
from apps.imports.security import ScannerUnavailable
from apps.organizations.models import Employee
from .receipt_fixtures import PNG, UPLOADS, ReceiptFixtureMixin


class ReceiptUploadTests(ReceiptFixtureMixin, TransactionTestCase):
    def send(self, key=None, content=PNG, *, actor=None, statement=None):
        return create_receipt_upload(actor=actor or self.actor, statement_id=(statement or self.statement).pk,
            upload_key=key or uuid4(), uploaded_file=SimpleUploadedFile("隔离水单.png", content, content_type="image/png"))

    def test_independent_upload_replay_preview_and_discard_preserve_metadata(self):
        key = uuid4(); upload, repeated = self.send(key)
        self.assertFalse(repeated); self.assertEqual(upload.file.scan_status, "SKIPPED")
        self.assertFalse(recovery_path(upload.file_id).exists())
        replay, repeated = self.send(key); self.assertTrue(repeated); self.assertEqual(replay.pk, upload.pk)
        response = self.client.get(f"{UPLOADS}{upload.pk}/content/")
        self.assertEqual(response.status_code, 200); response.close()
        response = self.client.get(UPLOADS, {"statement_id": str(self.statement.pk)})
        self.assertEqual(response.data["data"][0]["scan_label"], "未扫描（当前配置跳过）")
        result = discard_receipt_upload(upload.pk, actor=self.actor)
        self.assertEqual(result.status, "DISCARDED"); self.assertFalse(receipt_file_path(upload.file).exists())
        self.assertTrue(BusinessFile.objects.filter(pk=upload.file_id).exists())
        self.assertEqual(discard_receipt_upload(upload.pk, actor=self.actor).status, "DISCARDED")
        self.assertEqual(self.send(key)[0].status, "DISCARDED")
        self.assertEqual(self.client.get(f"{UPLOADS}{upload.pk}/content/").status_code, 404)

    def test_cross_owner_statement_and_different_bytes_rejected(self):
        key = uuid4(); upload, _ = self.send(key)
        other = Employee.objects.create(employee_code="U04_OTHER", display_name="隔离他人")
        with self.assertRaises(NotFound): self.send(key, actor=other)
        with self.assertRaises(APIException) as changed: self.send(key, content=PNG + b"different")
        self.assertEqual(changed.exception.api_error_code, "IDEMPOTENCY_KEY_REUSED")
        with self.assertRaises(NotFound): discard_receipt_upload(upload.pk, actor=other)
        self.assertEqual(BusinessFile.objects.count(), 1)

    def test_invalid_signature_size_scanner_failure_and_skip_policy(self):
        for name, content in (("a.gif", b"GIF89a"), ("a.png", b"bad"), ("a.png", b""), ("a.png", PNG + b"0" * (20 * 1024 * 1024))):
            with self.subTest(name=name, size=len(content)), self.assertRaises(APIException):
                upload_digest(SimpleUploadedFile(name, content))
        with patch("apps.files.uploads.scan_upload", side_effect=ScannerUnavailable("injected unavailable")):
            with self.assertRaises(APIException) as error: self.send()
        self.assertEqual(error.exception.api_error_code, "SCANNER_UNAVAILABLE")
        failed = BusinessFile.objects.get(); self.assertEqual(failed.scan_status, "FAILED")
        self.assertFalse((Path(self.temp.name) / failed.storage_key).exists())
        upload, _ = self.send()
        with override_settings(FILE_VIRUS_SCAN_ENABLED=True), self.assertRaises(APIException): require_usable_file(upload.file)
        for status in ("PENDING", "FAILED", "INFECTED"):
            upload.file.scan_status = status
            with self.assertRaises(APIException): require_usable_file(upload.file)

    def test_registration_audit_and_upload_create_failures_compensate_only_new_file(self):
        preserved, _ = self.send()
        with patch("apps.finance.receipt_uploads.audit_upload_file", side_effect=RuntimeError("registration failed")):
            with self.assertRaisesMessage(RuntimeError, "registration failed"): self.send()
        with patch("apps.finance.receipt_uploads.FinanceReceiptUpload.objects.create", side_effect=RuntimeError("voucher failed")):
            with self.assertRaisesMessage(RuntimeError, "voucher failed"): self.send()
        self.assertEqual(list(BusinessFile.objects.values_list("pk", flat=True)), [preserved.file_id])
        self.assertTrue(receipt_file_path(preserved.file).exists())
        self.assertFalse(list((Path(self.temp.name) / "finance/receipt_cleanup").glob("*.json")))

    def test_compensation_json_failure_retries_through_official_command(self):
        file = self.file(); file_id = file.pk; path = receipt_file_path(file)
        record_new_file(file); exact = recovery_path(file_id)
        unrelated = self.file(); record_new_file(unrelated); untouched = recovery_path(unrelated.pk).read_bytes()
        original = Path.unlink
        def fail_exact(current, *args, **kwargs):
            if current == exact: raise OSError("injected JSON delete failure")
            return original(current, *args, **kwargs)
        with patch.object(Path, "unlink", fail_exact), self.assertRaises(APIException) as error:
            compensate_upload_file(file_id, actor=self.actor)
        self.assertEqual(error.exception.api_error_code, "FILE_CLEANUP_FAILED")
        self.assertFalse(path.exists()); self.assertFalse(BusinessFile.objects.filter(pk=file_id).exists()); self.assertTrue(exact.exists())
        preview = StringIO(); call_command("cleanup_finance_uploads", orphan_file_ids=[file_id], stdout=preview)
        self.assertTrue(exact.exists()); self.assertIn("metadata=MISSING", preview.getvalue())
        with patch.object(Path, "unlink", fail_exact), self.assertRaises(APIException):
            call_command("cleanup_finance_uploads", orphan_file_ids=[file_id], apply=True, stdout=StringIO())
        call_command("cleanup_finance_uploads", orphan_file_ids=[file_id], apply=True, stdout=StringIO())
        self.assertFalse(exact.exists()); self.assertEqual(recovery_path(unrelated.pk).read_bytes(), untouched)
        self.assertTrue(receipt_file_path(unrelated).exists())
        with self.assertRaises(NotFound):
            call_command("cleanup_finance_uploads", orphan_file_ids=[uuid4()], apply=True, stdout=StringIO())

    def test_pending_discard_retry_missing_entity_and_bound_denial(self):
        upload, _ = self.send(); path = receipt_file_path(upload.file); original = Path.unlink
        def fail_entity(current, *args, **kwargs):
            if current == path: raise OSError("injected entity failure")
            return original(current, *args, **kwargs)
        with patch.object(Path, "unlink", fail_entity), self.assertRaises(APIException): discard_receipt_upload(upload.pk, actor=self.actor)
        upload.refresh_from_db(); self.assertEqual(upload.status, "DISCARD_PENDING")
        self.assertEqual(self.create(self.body(upload=upload)).status_code, 409)
        call_command("cleanup_finance_uploads", ids=[upload.pk], apply=True, stdout=StringIO())
        upload.refresh_from_db(); self.assertEqual(upload.status, "DISCARDED"); self.assertFalse(path.exists())
        bound, _ = self.send(); created = self.create(self.body(upload=bound)); self.assertEqual(created.status_code, 201, created.data)
        with self.assertRaises(APIException): discard_receipt_upload(bound.pk, actor=self.actor)
        self.assertTrue(receipt_file_path(bound.file).exists())
        missing, _ = self.send(); receipt_file_path(missing.file).unlink()
        self.assertEqual(self.create(self.body(upload=missing)).status_code, 404)

    def test_outer_atomic_rejected_and_manifest_traversal_denied(self):
        upload, _ = self.send()
        with transaction.atomic():
            with self.assertRaises(RuntimeError): self.send()
            with self.assertRaises(RuntimeError): discard_receipt_upload(upload.pk, actor=self.actor)
            with self.assertRaises(RuntimeError): compensate_upload_file(upload.file_id, actor=self.actor)
        file = self.file(); record_new_file(file)
        import json
        recovery_path(file.pk).write_text(json.dumps({"file_id": str(file.pk), "owner_id": str(self.actor.pk), "storage_key": "../../outside"}), encoding="utf-8")
        with self.assertRaises(APIException): read_recovery_record(file.pk)

    def test_concurrent_same_upload_key_compensates_loser(self):
        import apps.finance.receipt_uploads as service
        key = uuid4(); barrier = Barrier(2); real = service.save_scanned_image
        def synchronized(*args, **kwargs):
            result = real(*args, **kwargs); barrier.wait(timeout=20); return result
        def worker():
            close_old_connections()
            try:
                upload, replayed = self.send(key)
                return upload.pk, replayed
            finally: close_old_connections()
        with patch.object(service, "save_scanned_image", synchronized), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            results = [future.result(timeout=35) for future in futures]
        self.assertEqual(results[0][0], results[1][0]); self.assertEqual(sorted(x[1] for x in results), [False, True])
        self.assertEqual(BusinessFile.objects.count(), 1); self.assertEqual(FinanceReceiptUpload.objects.count(), 1)
        self.assertEqual(len(list((Path(self.temp.name) / "finance/receipt_uploads").rglob("*.png"))), 1)

    def test_historical_non_receipt_reference_blocks_cleanup(self):
        # 历史非法复用可能来自旧代码；清理仍检查所有反向引用。
        from apps.production_tasks.models import ProductionTaskProduct, ProductionTaskProductImage
        upload, _ = self.send()
        product = ProductionTaskProduct.objects.filter(production_task=self.task).first()
        ProductionTaskProductImage.objects.create(product_line=product, image_file=upload.file, line_number=1)
        with self.assertRaises(APIException): discard_receipt_upload(upload.pk, actor=self.actor)
        self.assertTrue(receipt_file_path(upload.file).exists())
