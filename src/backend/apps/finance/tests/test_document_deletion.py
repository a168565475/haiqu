"""已作废单据物理删除；所有记录、文件及身份仅在隔离测试环境创建。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch

from django.db import close_old_connections
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import TransactionTestCase, override_settings
from rest_framework.exceptions import APIException
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.core.models import DailyBusinessNumberCounter
from apps.files.models import BusinessFile
from apps.finance.allocation_models import DepositAllocation
from apps.finance.deletion_services import delete_receipt
from apps.finance.models import FinanceMutationKey
from apps.finance.receipt_models import Receipt, ReceiptAttachment, FinanceReceiptUpload
from apps.finance.receipt_services import create_receipt
from apps.finance.receipt_uploads import create_receipt_upload, record_new_file, recovery_path
from apps.finance.settlement_selectors import settlement_totals_for
from apps.finance.statement_models import ReceivableStatement, ReceivableStatementLine
from .goods_test_support import GoodsFixture
from .test_statements import create_source, request_body

STATEMENTS = "/api/v1/finance/statements/"
RECEIPTS = "/api/v1/finance/receipts/"


@override_settings(CACHES={key: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "finance-delete-" + key} for key in ("default", "configuration", "wecom")})
class DocumentDeletionTests(GoodsFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.role = self.grant()
        self.client = APIClient()
        self.client.force_login(self.user)

    def delete(self, instance, *, etag=True):
        instance.refresh_from_db()
        root = RECEIPTS if isinstance(instance, Receipt) else STATEMENTS
        headers = {} if etag is None else {"HTTP_IF_MATCH": etag_for_instance(instance) if etag is True else etag}
        return self.client.delete(f"{root}{instance.pk}/", **headers)

    def void_statement(self, instance=None):
        instance = instance or self.statement
        instance.refresh_from_db()
        response = self.client.post(f"{STATEMENTS}{instance.pk}/void/", {"reason": "隔离删除验证"},
            format="json", HTTP_IF_MATCH=etag_for_instance(instance))
        self.assertEqual(response.status_code, 200, response.data)
        instance.refresh_from_db()
        return instance

    def test_active_documents_rejected_and_delete_permission_is_independent(self):
        receipt = self.create(kind="DEPOSIT", cash="100.00")
        for instance in (self.statement, receipt):
            response = self.delete(instance)
            self.assertEqual(response.status_code, 409, response.data)
            self.assertEqual(response.data["error"]["code"], "DELETE_BLOCKED")
        self.void(receipt)
        self.void_statement()
        grants = RoleActionGrant.objects.filter(role=self.role, permission__codename__startswith="delete_")
        permissions = list(grants.values_list("permission_id", flat=True))
        grants.delete()
        self.role.auth_group.permissions.remove(*permissions)
        for instance in (self.statement, receipt):
            self.assertEqual(self.delete(instance).status_code, 403)
        self.assertFalse(AuditLog.objects.filter(action="DELETE_REQUESTED").exists())

    def test_etag_and_csrf_are_required_and_anonymous_is_rejected(self):
        self.void_statement()
        self.assertEqual(self.delete(self.statement, etag=None).status_code, 428)
        self.assertEqual(self.delete(self.statement, etag='"stale"').status_code, 412)
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.delete(f"{STATEMENTS}{self.statement.pk}/",
            HTTP_IF_MATCH=etag_for_instance(self.statement)).status_code, 403)
        self.client.logout()
        self.assertIn(self.delete(self.statement).status_code, (401, 403))
        self.assertTrue(ReceivableStatement.objects.filter(pk=self.statement.pk).exists())

    def test_receipt_deletes_owned_rows_files_but_preserves_audit_and_key(self):
        request = self.request(self.body(kind="DEPOSIT", cash="100.00"))
        receipt, _ = create_receipt(request)
        receipt_id = receipt.pk
        file_ids = list(receipt.attachments.values_list("file_id", flat=True))
        paths = [Path(self.media.name) / key for key in BusinessFile.objects.filter(pk__in=file_ids).values_list("storage_key", flat=True)]
        self.void(receipt)
        counters = list(DailyBusinessNumberCounter.objects.values())
        before = settlement_totals_for(self.statement)
        response = self.delete(receipt)
        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(Receipt.objects.filter(pk=receipt_id).exists())
        self.assertFalse(ReceiptAttachment.objects.filter(receipt_id=receipt_id).exists())
        self.assertFalse(BusinessFile.objects.filter(pk__in=file_ids).exists())
        self.assertFalse(FinanceReceiptUpload.objects.filter(file_id__in=file_ids).exists())
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertEqual(settlement_totals_for(self.statement), before)
        self.assertEqual(list(DailyBusinessNumberCounter.objects.values()), counters)
        self.assertTrue(FinanceMutationKey.objects.exists())
        with self.assertRaises(APIException) as raised:
            create_receipt(request)
        self.assertEqual(raised.exception.status_code, 410)
        actions = set(AuditLog.objects.filter(object_id=receipt_id).values_list("action", flat=True))
        self.assertTrue({"CREATE", "VOID", "DELETE_REQUESTED", "DELETE"}.issubset(actions), actions)
        self.assertEqual(self.client.delete(f"{RECEIPTS}{receipt_id}/", HTTP_IF_MATCH='"gone"').status_code, 404)

    def test_statement_deletes_all_line_revisions_and_unused_upload(self):
        task = create_source(self.actor)
        first = self.client.post(STATEMENTS, request_body(task), format="json", HTTP_IDEMPOTENCY_KEY="11111111-1111-4111-8111-111111111111")
        self.assertEqual(first.status_code, 201, first.data)
        statement = ReceivableStatement.objects.get(pk=first.data["data"]["id"])
        changed = self.client.patch(f"{STATEMENTS}{statement.pk}/", request_body(task, price="60.00"),
            format="json", HTTP_IF_MATCH=etag_for_instance(statement))
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertGreater(ReceivableStatementLine.objects.filter(statement=statement).count(), 1)
        upload = self.upload(statement)
        file_id, path = upload.file_id, Path(self.media.name) / upload.file.storage_key
        self.void_statement(statement)
        self.assertEqual(self.delete(statement).status_code, 204)
        self.assertFalse(ReceivableStatementLine.objects.filter(statement_id=statement.pk).exists())
        self.assertFalse(BusinessFile.objects.filter(pk=file_id).exists())
        self.assertFalse(path.exists())
        self.assertTrue(task.products.exists())

    def test_dependency_order_goods_then_deposit_then_statement(self):
        deposit = self.create(kind="DEPOSIT", cash="100.00")
        goods = self.create(deposits=[deposit])
        self.void(goods)
        self.void(deposit)
        self.void_statement()
        self.assertEqual(self.delete(self.statement).status_code, 409)
        response = self.delete(deposit)
        self.assertEqual(response.status_code, 409, response.data)
        data = self.client.get(f"{RECEIPTS}{deposit.pk}/").data["data"]
        self.assertFalse(data["can_delete"])
        self.assertIn("货款", data["delete_block_reason"])
        self.assertEqual(self.delete(goods).status_code, 204)
        self.assertFalse(DepositAllocation.objects.exists())
        self.assertEqual(self.delete(deposit).status_code, 204)
        self.assertEqual(self.delete(self.statement).status_code, 204)

    def test_shared_file_reference_blocks_before_unlink(self):
        first = self.create(kind="DEPOSIT", cash="100.00")
        file = first.attachments.first().file
        from apps.production_tasks.models import ProductionTaskProductImage
        source = create_source(self.actor)
        # 构造历史跨模块引用；正常业务绑定入口已经禁止复用财务水单。
        ProductionTaskProductImage.objects.create(product_line=source.products.first(), line_number=1, image_file=file)
        self.void(first)
        response = self.delete(first)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertTrue((Path(self.media.name) / file.storage_key).exists())
        self.assertTrue(Receipt.objects.filter(pk=first.pk).exists())

    def test_foreign_storage_namespace_blocks_before_unlink(self):
        receipt = self.create(kind="DEPOSIT", cash="100.00")
        file = receipt.attachments.first().file
        original = Path(self.media.name) / file.storage_key
        file.storage_key = "other-module/foreign.png"
        file.save(update_fields=["storage_key"])
        self.void(receipt)
        self.assertEqual(self.delete(receipt).status_code, 409)
        self.assertTrue(original.exists())
        self.assertTrue(Receipt.objects.filter(pk=receipt.pk).exists())

    def test_deleted_upload_key_rejects_replay_before_file_storage(self):
        upload = self.upload()
        receipt = self.create(kind="DEPOSIT", cash="100.00", uploads=[str(upload.pk)])
        record_new_file(upload.file)
        self.void(receipt)
        self.assertEqual(self.delete(receipt).status_code, 204)
        self.assertFalse(recovery_path(upload.file_id).exists())
        with patch("apps.finance.receipt_uploads.save_scanned_image") as save:
            with self.assertRaises(APIException) as raised:
                create_receipt_upload(actor=self.actor, statement_id=self.statement.pk,
                    upload_key=upload.upload_key, uploaded_file=None)
            self.assertEqual(raised.exception.status_code, 410)
            save.assert_not_called()

    def test_recovery_file_failure_retains_document_until_retry(self):
        receipt = self.create(kind="DEPOSIT", cash="100.00")
        file = receipt.attachments.first().file
        record_new_file(file)
        self.void(receipt)
        real_unlink = Path.unlink

        def fail_recovery(path, *args, **kwargs):
            if path == recovery_path(file.pk):
                raise OSError("isolated recovery cleanup failure")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_recovery):
            self.assertEqual(self.delete(receipt).status_code, 500)
        self.assertTrue(Receipt.objects.filter(pk=receipt.pk).exists())
        self.assertTrue(recovery_path(file.pk).exists())
        self.assertEqual(self.delete(receipt).status_code, 204)
        self.assertFalse(recovery_path(file.pk).exists())

    def test_cross_statement_upload_cannot_recreate_deleted_key(self):
        from uuid import uuid4
        from apps.finance import receipt_uploads
        from .receipt_fixtures import PNG
        key, other_statement = uuid4(), self.new_statement()
        scanning, registered, checked, deleted = (Event() for _ in range(4))
        real_save, real_reject = receipt_uploads.save_scanned_image, receipt_uploads.reject_deleted_upload
        checks = 0

        def delayed_scan(*args, **kwargs):
            scanning.set()
            if not registered.wait(180):
                raise AssertionError("existing upload was not registered")
            return real_save(*args, **kwargs)

        def delayed_check(*args, **kwargs):
            nonlocal checks
            real_reject(*args, **kwargs)
            checks += 1
            if checks == 2:
                checked.set()
                if not deleted.wait(180):
                    raise AssertionError("original upload was not deleted")

        def upload_late():
            close_old_connections()
            try:
                receipt_uploads.create_receipt_upload(actor=self.actor, statement_id=other_statement.pk,
                    upload_key=key, uploaded_file=SimpleUploadedFile("late.png", PNG, content_type="image/png"))
                return 201
            except APIException as exc:
                return exc.status_code
            finally:
                close_old_connections()

        with patch.object(receipt_uploads, "save_scanned_image", delayed_scan), \
             patch.object(receipt_uploads, "reject_deleted_upload", delayed_check), \
             ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(upload_late)
            try:
                self.assertTrue(scanning.wait(180))
                upload = self.upload()
                upload.upload_key = key
                upload.save(update_fields=["upload_key"])
                receipt = self.create(kind="DEPOSIT", cash="100.00", uploads=[str(upload.pk)])
                self.void(receipt)
                registered.set()
                self.assertTrue(checked.wait(180))
                self.assertEqual(self.delete(receipt).status_code, 204)
                deleted.set()
                self.assertEqual(future.result(timeout=180), 410)
            finally:
                registered.set()
                deleted.set()
        self.assertFalse(FinanceReceiptUpload.objects.filter(upload_key=key).exists())
        self.assertFalse(BusinessFile.objects.exists())
        self.assertTrue(FinanceMutationKey.objects.filter(action="DELETE_RECEIPT_UPLOAD", key=key).exists())

    def test_partial_file_failure_keeps_document_and_retry_is_safe(self):
        uploads = [self.upload(), self.upload()]
        receipt = self.create(kind="DEPOSIT", cash="100.00", uploads=[str(item.pk) for item in uploads])
        self.void(receipt)
        files = list(BusinessFile.objects.filter(pk__in=[item.file_id for item in uploads]).order_by("pk"))
        paths = [Path(self.media.name) / item.storage_key for item in files]
        real_unlink = Path.unlink

        def fail_second(path, *args, **kwargs):
            if path == paths[1]:
                raise OSError("isolated cleanup failure")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_second):
            response = self.delete(receipt)
        self.assertEqual(response.status_code, 500, response.data)
        self.assertEqual(response.data["error"]["code"], "FILE_CLEANUP_FAILED")
        self.assertFalse(paths[0].exists())
        self.assertTrue(paths[1].exists())
        self.assertEqual(ReceiptAttachment.objects.filter(receipt=receipt).count(), 2)
        self.assertTrue(AuditLog.objects.filter(object_id=receipt.pk, action="DELETE_CLEANUP_FAILED").exists())
        self.assertEqual(self.delete(receipt).status_code, 204)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_audit_failure_before_file_changes_and_failure_after_unlink_are_not_success(self):
        receipt = self.create(kind="DEPOSIT", cash="100.00")
        file = receipt.attachments.first().file
        path = Path(self.media.name) / file.storage_key
        self.void(receipt)
        from apps.finance import deletion_services
        audit = deletion_services.write_audit_log

        with patch.object(deletion_services, "write_audit_log", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesMessage(RuntimeError, "audit unavailable"):
                self.delete(receipt)
        self.assertTrue(path.exists())

        def fail_completion(**kwargs):
            if kwargs["action"] == "DELETE":
                raise RuntimeError("completion audit unavailable")
            return audit(**kwargs)

        with patch.object(deletion_services, "write_audit_log", side_effect=fail_completion):
            with self.assertRaisesMessage(RuntimeError, "completion audit unavailable"):
                self.delete(receipt)
        self.assertTrue(Receipt.objects.filter(pk=receipt.pk).exists())
        self.assertFalse(path.exists())
        self.assertTrue(AuditLog.objects.filter(object_id=receipt.pk, action="DELETE_REQUESTED").exists())
        self.assertEqual(self.delete(receipt).status_code, 204)

    def test_concurrent_delete_has_one_success_and_no_orphans(self):
        receipt = self.create(kind="DEPOSIT", cash="100.00")
        self.void(receipt)
        request = self.request({}, receipt)
        barrier = Barrier(2)

        def remove():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                delete_receipt(request, receipt.pk)
                return 204
            except APIException as exc:
                return exc.status_code
            except Http404:
                return 404
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: remove(), range(2)))
        self.assertEqual(sorted(statuses), [204, 404])
        self.assertFalse(Receipt.objects.filter(pk=receipt.pk).exists())
        self.assertFalse(ReceiptAttachment.objects.exists())
        self.assertEqual(AuditLog.objects.filter(object_id=receipt.pk, action="DELETE").count(), 1)
