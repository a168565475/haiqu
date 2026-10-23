from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.core.models import DailyBusinessNumberCounter
from apps.finance.models import FinanceMutationKey
from apps.finance.receipt_models import Receipt, ReceiptAttachment
from apps.finance.settlement_selectors import settlement_totals_for
from apps.organizations.models import Employee
from .receipt_fixtures import ReceiptFixtureMixin, ROOT, UPLOADS, grant_receipts
from .test_statements import request_body


class ReceiptTests(ReceiptFixtureMixin, TestCase):
    def test_deposit_preserves_outstanding_and_snapshots_complete_account(self):
        body = self.body(); body["account_lines"].append({**body["account_lines"][0], "cash_amount": "5.00", "fee_amount": "0.50"})
        response = self.create(body)
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data["data"]
        self.assertRegex(data["number"], r"^SKQRD\d{9,}$")
        self.assertEqual((data["cash_amount"], data["fee_amount"], data["deposit_amount"], data["settled_amount"]), ("30.00", "1.50", "30.00", "0.00"))
        self.assertEqual(data["outstanding_after"], "100.00")
        self.assertEqual(data["account_lines"][0]["account_snapshot"]["account_number"], self.account.account_number)
        self.account.name = "后来改名"; self.account.save()
        detail = self.client.get(ROOT + data["id"] + "/").data["data"]
        self.assertEqual(detail["account_lines"][0]["account_snapshot"]["name"], "隔离账户")
        totals = settlement_totals_for(self.statement)
        self.assertEqual((totals.outstanding_amount, totals.available_deposit_amount, totals.bank_received_amount), (Decimal("100"), Decimal("30"), Decimal("30")))
        audit = str(list(AuditLog.objects.filter(object_type="FINANCE_RECEIPT").values_list("after_data", flat=True)))
        self.assertNotIn(self.account.account_number, audit)

    def test_overcollection_invalid_money_and_foreign_fields_roll_back(self):
        original = self.body()
        for amount in ("101", "0", "-1", "1e2", "NaN", "1.001", "100000000000000000000", 1.2):
            body = deepcopy(original); body["account_lines"][0]["cash_amount"] = amount
            self.assertEqual(self.create(body).status_code, 400, amount)
        for extra in ({"deposit_ids": []}, {"discount_amount": "0.00"}, {"task_id": str(self.task.pk)}, {"settled_amount": "0"}):
            response = self.create({**original, **extra})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["error"]["code"], "RECEIPT_TYPE_FIELDS_INVALID")
            self.assertIn(next(iter(extra)), response.data["error"]["field_errors"])
        overflow = deepcopy(original); overflow["account_lines"][0]["cash_amount"] = "100000000000000000000.00"
        response = self.create(overflow)
        self.assertEqual(response.data["error"]["code"], "AMOUNT_OUT_OF_RANGE")
        self.assertEqual(response.data["error"]["meta"]["recovery_action"], "REVIEW_AMOUNTS")
        for field in ("cash_amount", "fee_amount"):
            overflow = deepcopy(original)
            overflow["account_lines"].append({**overflow["account_lines"][0], field: "100000000000000000000.00"})
            response = self.create(overflow)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["error"]["code"], "AMOUNT_OUT_OF_RANGE")
            self.assertIn(f"account_lines.1.{field}", response.data["error"]["field_errors"])
            self.assertEqual(response.data["error"]["meta"]["row_index"], 1)
            self.assertEqual(response.data["error"]["meta"]["field"], f"account_lines.1.{field}")
        self.assertFalse(Receipt.objects.exists())
        self.assertFalse(FinanceMutationKey.objects.filter(action="CREATE_RECEIPT").exists())
        self.assertFalse(DailyBusinessNumberCounter.objects.filter(number_type="FINANCE_RECEIPT").exists())

    def test_idempotency_current_void_state_and_changed_body(self):
        key = uuid4(); body = self.body(); etag = etag_for_instance(self.statement)
        first = self.create(body, key=key, etag=etag); self.assertEqual(first.status_code, 201, first.data)
        replay = self.create(body, key=key, etag=etag)
        self.assertEqual(replay.status_code, 200); self.assertEqual(replay["Idempotent-Replayed"], "true")
        changed = deepcopy(body); changed["account_lines"][0]["cash_amount"] = "24.00"
        self.assertEqual(self.create(changed, key=key).status_code, 409)
        data = first.data["data"]
        voided = self.client.post(ROOT + data["id"] + "/void/", {"reason": "隔离测试作废"}, format="json", HTTP_IF_MATCH=data["etag"])
        self.assertEqual(voided.status_code, 200, voided.data)
        self.assertEqual(self.create(body, key=key, etag=etag).data["data"]["status"], "VOID")
        self.assertEqual(Receipt.objects.count(), 1); self.assertEqual(ReceiptAttachment.objects.count(), 1)
        self.assertEqual(settlement_totals_for(self.statement).available_deposit_amount, 0)

    def test_active_deposit_freezes_statement_and_void_restores_edit(self):
        result = self.create(); self.assertEqual(result.status_code, 201, result.data)
        self.statement.refresh_from_db()
        path = f"/api/v1/finance/statements/{self.statement.pk}/"
        body = request_body(self.task, (0,), "90.0000")
        frozen = self.client.patch(path, body, format="json", HTTP_IF_MATCH=etag_for_instance(self.statement))
        self.assertEqual(frozen.status_code, 409, frozen.data)
        self.assertEqual(frozen.data["error"]["code"], "STATEMENT_FROZEN")
        data = result.data["data"]
        self.client.post(ROOT + data["id"] + "/void/", {"reason": "隔离解除"}, format="json", HTTP_IF_MATCH=data["etag"])
        self.statement.refresh_from_db()
        restored = self.client.patch(path, body, format="json", HTTP_IF_MATCH=etag_for_instance(self.statement))
        self.assertEqual(restored.status_code, 200, restored.data)

    def test_attachments_ownership_state_and_account_revalidation(self):
        body = self.body(); original = deepcopy(body)
        body["upload_ids"] = []
        self.assertEqual(self.create(body).status_code, 400)
        body["upload_ids"] = [str(uuid4())]
        self.assertEqual(self.create(body).status_code, 404)
        body = deepcopy(original); body["account_lines"][0]["account_etag"] = '"old"'
        self.assertEqual(self.create(body).status_code, 409)
        self.account.status = "INACTIVE"; self.account.save(); body["account_lines"][0]["account_etag"] = etag_for_instance(self.account)
        self.assertEqual(self.create(body).data["error"]["code"], "ACCOUNT_UNAVAILABLE")
        self.account.status = "ACTIVE"; self.account.save(); body["account_lines"][0]["account_etag"] = etag_for_instance(self.account)
        self.task.currency.status = "INACTIVE"; self.task.currency.save()
        self.assertEqual(self.create(body).data["error"]["code"], "ACCOUNT_UNAVAILABLE")

    def test_statement_etag_missing_and_stale(self):
        body = self.body()
        response = self.client.post(ROOT, body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4()))
        self.assertEqual(response.status_code, 428)
        self.assertEqual(self.create(body, etag='"old"').status_code, 412)
        self.assertFalse(Receipt.objects.exists())

    def test_failed_audit_rolls_back_number_receipt_binding_and_key(self):
        upload = self.upload(); body = self.body(upload=upload)
        with patch("apps.finance.deposit_services.audit_receipt", side_effect=RuntimeError("injected audit failure")):
            with self.assertRaisesMessage(RuntimeError, "injected audit failure"):
                self.create(body)
        self.assertFalse(Receipt.objects.exists()); self.assertFalse(ReceiptAttachment.objects.exists())
        upload.refresh_from_db(); self.assertEqual(upload.status, "UNBOUND")
        self.assertFalse(FinanceMutationKey.objects.filter(action="CREATE_RECEIPT").exists())
        self.assertFalse(DailyBusinessNumberCounter.objects.filter(number_type="FINANCE_RECEIPT").exists())

    def test_account_options_requires_both_permissions_and_read_does_not_grant_write(self):
        path = "/api/v1/finance/account-options/"
        for codes, allowed in ((["add_receipt"], False), (["view_financeaccount"], False), (["add_receipt", "view_financeaccount"], True), (["view_receipt"], False)):
            user = get_user_model().objects.create_user("u04_" + uuid4().hex[:12])
            employee = Employee.objects.create(user=user, employee_code=uuid4().hex[:10].upper(), display_name="隔离权限")
            grant_receipts(employee, uuid4().hex[:10].upper(), codes)
            client = APIClient(); client.force_login(user)
            response = client.get(path)
            self.assertEqual(response.status_code, 200 if allowed else 403, response.data)
            if codes == ["view_receipt"]:
                self.assertEqual(client.get(ROOT).status_code, 200)
                self.assertEqual(client.post(ROOT, self.body(), format="json").status_code, 403)
        anonymous = APIClient(); self.assertIn(anonymous.get(ROOT).status_code, (401, 403))

    def test_session_csrf_and_controlled_attachment(self):
        self.assertEqual(self.client.delete(UPLOADS + "bad-id/").status_code, 400)
        csrf = APIClient(enforce_csrf_checks=True); csrf.force_login(self.user)
        self.assertEqual(csrf.post(ROOT, self.body(), format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4()), HTTP_IF_MATCH=etag_for_instance(self.statement)).status_code, 403)
        result = self.create(); data = result.data["data"]
        file_id = data["attachments"][0]["file_id"]
        response = self.client.get(f"{ROOT}{data['id']}/attachments/{file_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content))
        self.assertEqual(self.client.get(f"{ROOT}{data['id']}/attachments/bad-id/").status_code, 404)
        self.assertEqual(self.client.get(f"{ROOT}{data['id']}/attachments/{uuid4()}/").status_code, 404)
        self.assertNotIn("storage_key", str(data))

    def test_database_rejects_invalid_receipt_semantics(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Receipt.objects.create(number="invalid", statement=self.statement, receipt_type="DEPOSIT", cash_amount=10,
                deposit_amount=11, created_by_employee=self.actor, updated_by_employee=self.actor)
