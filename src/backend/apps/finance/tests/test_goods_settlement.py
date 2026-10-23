from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.core.models import DailyBusinessNumberCounter
from apps.organizations.models import Employee
from apps.finance.allocation_models import DepositAllocation
from apps.finance.goods_selectors import deposit_option_data, deposit_options
from apps.finance.models import FinanceMutationKey
from apps.finance.receipt_models import FinanceReceiptUpload, Receipt, ReceiptAccountLine, ReceiptAttachment
from apps.finance.receipt_read_serializers import ReceiptSerializer
from apps.finance.receipt_services import create_receipt
from apps.finance.settlement_selectors import annotate_settlement_totals, settlement_totals_for, settlement_totals_for_statements
from apps.finance.settlement_totals import MAX_AMOUNT
from apps.finance.statement_models import ReceivableStatement
from apps.finance.statement_services import require_mutable_statement, update_statement, void_statement
from .goods_test_support import GoodsFixture


class GoodsSettlementTests(GoodsFixture, TestCase):
    def assert_error(self, code, operation):
        with self.assertRaises(APIException) as caught:
            operation()
        self.assertEqual(getattr(caught.exception, "api_error_code", caught.exception.status_code), code)

    def test_m04_m05_m06_later_goods_survive_earlier_void(self):
        deposit = self.create(kind="DEPOSIT", cash="200.00")
        totals = settlement_totals_for(self.statement)
        self.assertEqual((totals.outstanding_amount, totals.available_deposit_amount, totals.bank_received_amount),
            (Decimal("1000"), Decimal("200"), Decimal("200")))
        first = self.create(cash="500.00", deposits=[deposit], discount="20.00", fee="5.00")
        self.assertEqual(first.settled_amount, Decimal("700"))
        self.assertEqual(first.statement_snapshot["outstanding_after"], "280.00")
        later = self.create(cash="280.00")
        later_snapshot = dict(later.statement_snapshot)
        self.assertEqual(settlement_totals_for(self.statement).outstanding_amount, Decimal("0"))
        self.assertEqual(settlement_totals_for(self.statement).settlement_status, "SETTLED")
        old_etag = etag_for_instance(first)
        result, changed = self.void(first)
        self.assertTrue(changed)
        totals = settlement_totals_for(self.statement)
        self.assertEqual((totals.outstanding_amount, totals.available_deposit_amount, totals.bank_received_amount,
            totals.discount_amount, totals.fee_amount), (Decimal("720"), Decimal("200"), Decimal("480"), Decimal("0"), Decimal("0")))
        later.refresh_from_db()
        self.assertEqual(later.status, "ACTIVE")
        self.assertEqual(later.statement_snapshot, later_snapshot)
        allocation = DepositAllocation.objects.get(goods_receipt=first)
        self.assertFalse(allocation.is_active)
        self.assertIsNotNone(allocation.voided_at)
        self.assert_error(412, lambda: self.void(result, old_etag))
        before = AuditLog.objects.filter(object_type="FINANCE_RECEIPT", object_id=first.pk).count()
        _, changed = self.void(result)
        self.assertFalse(changed)
        self.assertEqual(AuditLog.objects.filter(object_type="FINANCE_RECEIPT", object_id=first.pk).count(), before)

    def test_m07_fee_is_separate_from_settlement(self):
        receipt = self.create(cash="990.00", fee="10.00")
        totals = settlement_totals_for(self.statement)
        self.assertEqual((receipt.cash_amount, receipt.fee_amount, totals.settled_amount, totals.outstanding_amount),
            (Decimal("990"), Decimal("10"), Decimal("990"), Decimal("10")))

    def test_m08_pure_deposit_has_no_new_cash_line_or_attachment(self):
        self.statement = self.new_statement(amount="300.00")
        deposit = self.create(kind="DEPOSIT", cash="300.00")
        file_id = deposit.attachments.get().file_id
        goods = self.create(deposits=[deposit])
        self.assertFalse(goods.account_lines.exists())
        self.assertFalse(goods.attachments.exists())
        data = ReceiptSerializer(goods).data
        self.assertEqual(data["inherited_attachments"][0]["file_id"], str(file_id))
        self.assertEqual(data["inherited_attachments"][0]["deposit_receipt_id"], str(deposit.pk))
        self.assertEqual(data["inherited_attachments"][0]["scan_status"], "SKIPPED")
        self.assertEqual(settlement_totals_for(self.statement).bank_received_amount, Decimal("300"))
        self.assertEqual(settlement_totals_for(self.statement).outstanding_amount, Decimal("0"))
        self.assertEqual(settlement_totals_for(self.statement).settlement_status, "SETTLED")
        self.void(goods)
        goods.refresh_from_db()
        self.assertEqual(ReceiptSerializer(goods).data["inherited_attachments"][0]["file_id"], str(file_id))
        self.assertEqual(ReceiptAttachment.objects.count(), 1)

    def test_m09_whole_deposit_cannot_be_clipped_to_remaining(self):
        deposit = self.create(kind="DEPOSIT", cash="300.00")
        # 仅隔离测试库构造历史异常：当前未付250、未用订金300。
        ReceivableStatement.objects.filter(pk=self.statement.pk).update(amount=Decimal("250"))
        self.statement.refresh_from_db()
        self.assert_error("OVER_SETTLEMENT", lambda: self.create(deposits=[deposit]))
        self.assertFalse(DepositAllocation.objects.exists())
        self.assertFalse(Receipt.objects.filter(receipt_type="GOODS").exists())
        option = deposit_option_data(deposit_options(self.statement).get(), settlement_totals_for(self.statement))
        self.assertFalse(option["can_select"])
        self.assertEqual(option["available_amount"], "300.00")

    def test_m10_m11_over_settlement_and_stranded_deposit_rejected(self):
        limited = self.new_statement(amount="100.00")
        self.assert_error("OVER_SETTLEMENT", lambda: self.create(statement=limited, cash="80.00", discount="30.00"))
        deposit = self.create(kind="DEPOSIT", cash="300.00")
        self.assert_error("DEPOSIT_EXCESS_AFTER_SETTLEMENT", lambda: self.create(cash="800.00"))
        self.assert_error("OVER_SETTLEMENT", lambda: self.create(cash="800.00", deposits=[deposit]))
        self.assertEqual(Receipt.objects.count(), 1)
        self.assertFalse(DepositAllocation.objects.exists())

    def test_m12_forbidden_totals_partial_amount_and_empty_funds(self):
        self.assert_error("FUNDS_REQUIRED", lambda: self.create(discount="20.00"))
        for changes in ({"allocated_deposit_amount": "1.00"}, {"allocations": [{"amount": "1.00"}]},
                        {"settled_amount": "1.00"}, {"deposit_amount": "1.00"}):
            with self.subTest(changes=changes):
                data = {**self.body(), **changes}
                self.assert_error("RECEIPT_TYPE_FIELDS_INVALID", lambda: create_receipt(self.request(data)))
        deposit_data = self.body(kind="DEPOSIT", cash="10.00")
        self.assert_error("RECEIPT_TYPE_FIELDS_INVALID", lambda: create_receipt(self.request({**deposit_data, "discount_amount": "0.00"})))
        self.assert_error("RECEIPT_TYPE_FIELDS_INVALID", lambda: create_receipt(self.request({
            **self.body(kind="DEPOSIT", cash="12600.00"), "deposit_amount": "10800.00"})))
        self.assertFalse(FinanceMutationKey.objects.exists())

    def test_m13_used_deposit_void_blocked_until_goods_void(self):
        deposit = self.create(kind="DEPOSIT", cash="200.00")
        goods = self.create(deposits=[deposit])
        self.assert_error("DEPOSIT_UNAVAILABLE", lambda: self.void(deposit))
        self.void(goods)
        self.void(deposit)
        totals = settlement_totals_for(self.statement)
        self.assertEqual((totals.outstanding_amount, totals.available_deposit_amount, totals.bank_received_amount),
            (Decimal("1000"), Decimal("0"), Decimal("0")))

    def test_m14_any_active_receipt_freezes_all_statement_mutations(self):
        deposit = self.create(kind="DEPOSIT", cash="200.00")
        goods = self.create(deposits=[deposit])
        for operation in (
            lambda: update_statement(self.request({}), self.statement.pk, {"production_task_id": self.statement.production_task_id}),
            lambda: void_statement(self.request({}), self.statement.pk, "隔离作废"),
        ):
            self.assert_error("STATEMENT_FROZEN", operation)
        self.void(goods)
        self.statement.refresh_from_db()
        self.assert_error("STATEMENT_FROZEN", lambda: require_mutable_statement(self.statement))
        self.void(deposit)
        self.statement.refresh_from_db()
        require_mutable_statement(self.statement)
        result, changed = void_statement(self.request({}), self.statement.pk, "隔离作废")
        self.assertTrue(changed)
        self.assertEqual(result.status, "VOID")

    def test_cross_statement_cross_task_used_void_and_duplicate_deposits(self):
        same_task = self.new_statement(task=self.statement.production_task)
        other_task = self.new_statement()
        for statement in (same_task, other_task):
            deposit = self.create(statement=statement, kind="DEPOSIT", cash="100.00")
            self.assert_error("DEPOSIT_UNAVAILABLE", lambda: self.create(deposits=[deposit]))
        deposit = self.create(kind="DEPOSIT", cash="100.00")
        data = self.body(deposits=[deposit, deposit])
        with self.assertRaises(APIException):
            create_receipt(self.request(data))
        goods = self.create(deposits=[deposit])
        self.assert_error("DEPOSIT_UNAVAILABLE", lambda: self.create(deposits=[deposit]))
        self.void(goods)
        self.void(deposit)
        self.assert_error("DEPOSIT_UNAVAILABLE", lambda: self.create(deposits=[deposit]))
        self.assertFalse(DepositAllocation.objects.filter(is_active=True).exists())

    def test_audit_failure_rolls_back_receipt_allocation_upload_key_and_number(self):
        deposit = self.create(kind="DEPOSIT", cash="200.00")
        data = self.body(cash="500.00", deposits=[deposit], discount="20.00")
        request = self.request(data)
        before_numbers = list(DailyBusinessNumberCounter.objects.values())
        before_keys = FinanceMutationKey.objects.count()
        statement_etag = etag_for_instance(self.statement)
        with patch("apps.finance.goods_services.audit_receipt", side_effect=RuntimeError("isolated audit failure")):
            with self.assertRaisesRegex(RuntimeError, "isolated audit failure"):
                create_receipt(request)
        self.assertEqual(Receipt.objects.count(), 1)
        self.assertFalse(DepositAllocation.objects.exists())
        self.assertEqual(ReceiptAccountLine.objects.count(), 1)
        self.assertEqual(ReceiptAttachment.objects.count(), 1)
        self.assertEqual(FinanceReceiptUpload.objects.get(pk=data["upload_ids"][0]).status, "UNBOUND")
        self.assertEqual(FinanceMutationKey.objects.count(), before_keys)
        self.assertEqual(list(DailyBusinessNumberCounter.objects.values()), before_numbers)
        self.statement.refresh_from_db()
        self.assertEqual(etag_for_instance(self.statement), statement_etag)
        result, replayed = create_receipt(request)
        self.assertFalse(replayed)
        self.assertEqual(result.settled_amount, Decimal("700"))

    def test_void_audit_failure_keeps_allocation_and_receipt_active(self):
        deposit = self.create(kind="DEPOSIT", cash="200.00")
        goods = self.create(deposits=[deposit])
        with patch("apps.finance.goods_services.audit_receipt", side_effect=RuntimeError("isolated void failure")):
            with self.assertRaisesRegex(RuntimeError, "isolated void failure"):
                self.void(goods)
        goods.refresh_from_db()
        self.assertEqual(goods.status, "ACTIVE")
        self.assertTrue(DepositAllocation.objects.get(goods_receipt=goods).is_active)
        self.assertEqual(settlement_totals_for(self.statement).outstanding_amount, Decimal("800"))

    def test_account_changed_and_missing_upload_leave_no_goods(self):
        data = self.body(cash="10.00")
        self.account.name = "资料已变化"
        self.account.save()
        self.assert_error("ACCOUNT_CHANGED", lambda: create_receipt(self.request(data)))
        self.assert_error("ATTACHMENT_REQUIRED", lambda: self.create(cash="10.00", uploads=[]))
        self.assertFalse(Receipt.objects.exists())
        self.assertFalse(FinanceMutationKey.objects.exists())

    def test_sql_and_batch_totals_match_without_equal_amount_deduplication(self):
        deposit = self.create(kind="DEPOSIT", cash="200.00")
        self.create(cash="100.00", deposits=[deposit], discount="20.00", fee="1.00")
        self.create(cash="100.00", fee="2.00")
        voided = self.create(cash="100.00")
        self.void(voided)
        other = self.new_statement(amount="100.00")
        self.create(statement=other, cash="100.00")
        empty = self.new_statement()
        statements = [self.statement, other, empty]
        with self.assertNumQueries(1):
            batch = settlement_totals_for_statements(statements)
        rows = list(annotate_settlement_totals(ReceivableStatement.objects.all()))
        for row in rows:
            totals = batch[row.pk]
            for field in ("settled_amount", "discount_amount", "outstanding_amount", "available_deposit_amount", "bank_received_amount", "fee_amount", "settlement_status"):
                self.assertEqual(getattr(row, field), getattr(totals, field), field)
        self.assertEqual(batch[self.statement.pk].outstanding_amount, Decimal("580"))
        filtered = annotate_settlement_totals(ReceivableStatement.objects.all()).filter(settlement_status="SETTLED")
        self.assertEqual(filtered.count(), 1)
        self.assertEqual(list(filtered[:1])[0].pk, other.pk)

    def test_database_rejects_duplicate_active_allocation_and_invalid_lifecycle(self):
        deposit = self.create(kind="DEPOSIT", cash="100.00")
        goods = self.create(deposits=[deposit])
        for values in (
            {"goods_receipt": goods, "deposit_receipt": deposit, "amount": Decimal("100")},
            {"goods_receipt": goods, "deposit_receipt": goods, "amount": Decimal("100")},
            {"goods_receipt": goods, "deposit_receipt": deposit, "amount": Decimal("0"), "is_active": False, "voided_at": timezone.now()},
            {"goods_receipt": goods, "deposit_receipt": deposit, "amount": Decimal("100"), "is_active": False},
        ):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                DepositAllocation.objects.create(**values)
        self.assertEqual(DepositAllocation.objects.count(), 1)


class GoodsApiTests(GoodsFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.role = self.grant()
        self.client = APIClient()
        self.client.force_login(self.user)

    def post_goods(self, data, key=None, etag=None):
        self.statement.refresh_from_db()
        return self.client.post("/api/v1/finance/receipts/", data, format="json",
            HTTP_IDEMPOTENCY_KEY=str(key or uuid4()), HTTP_IF_MATCH=etag or etag_for_instance(self.statement))

    def test_api_pure_deposit_history_download_and_replay(self):
        deposit = self.create(kind="DEPOSIT", cash="200.00")
        data, key = self.body(deposits=[deposit]), uuid4()
        created = self.post_goods(data, key)
        self.assertEqual(created.status_code, 201, created.data)
        goods = created.data["data"]
        self.assertEqual(goods["account_lines"], [])
        self.assertEqual(goods["attachments"], [])
        self.assertEqual(goods["settled_amount"], "200.00")
        self.assertEqual(goods["outstanding_after"], "800.00")
        replay = self.post_goods(data, key, '"stale-original-etag"')
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(replay["Idempotent-Replayed"], "true")
        self.assertEqual(replay.data["data"]["id"], goods["id"])
        file_id = goods["inherited_attachments"][0]["file_id"]
        downloaded = self.client.get(f'/api/v1/finance/receipts/{goods["id"]}/attachments/{file_id}/')
        self.assertEqual(downloaded.status_code, 200)
        self.assertTrue(b"".join(downloaded.streaming_content).startswith(b"\x89PNG"))
        # 未开放的写动作先被BusinessActionPermission拒绝，不会进入405分派。
        self.assertEqual(self.client.patch(f'/api/v1/finance/receipts/{goods["id"]}/', {}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(f'/api/v1/finance/receipts/{goods["id"]}/').status_code, 403)
        unchanged = Receipt.objects.get(pk=goods["id"])
        self.assertEqual((unchanged.status, unchanged.settled_amount), ("ACTIVE", Decimal("200.00")))
        self.assertEqual(DepositAllocation.objects.filter(goods_receipt=unchanged, is_active=True).count(), 1)

    def test_selector_filters_paginates_and_reports_actual_unavailable_state(self):
        deposits = [self.create(kind="DEPOSIT", cash="100.00") for _ in range(3)]
        goods = self.create(deposits=[deposits[0]])
        self.void(deposits[1])
        other = self.new_statement(task=self.statement.production_task)
        self.create(statement=other, kind="DEPOSIT", cash="100.00")
        url = f"/api/v1/finance/statements/{self.statement.pk}/available-deposits/"
        response = self.client.get(url, {"include_unavailable": True, "page_size": 1})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 3)
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["available_deposit_amount"], "100.00")
        search = self.client.get(url, {"q": deposits[0].number, "include_unavailable": True})
        self.assertEqual(search.data["meta"]["total"], 1)
        self.assertEqual(search.data["data"][0]["allocated_goods_id"], str(goods.pk))
        self.assertFalse(search.data["data"][0]["can_select"])
        self.assertEqual(self.client.get(url).data["meta"]["total"], 1)

    def test_cumulative_fee_across_deposit_and_goods_is_atomic(self):
        used = self.create(kind="DEPOSIT", cash="1.00", fee=str(MAX_AMOUNT - Decimal("0.01")))
        available = self.create(kind="DEPOSIT", cash="1.00")
        self.create(cash="1.00", deposits=[used], fee="0.01")
        self.assertEqual(settlement_totals_for(self.statement).fee_amount, MAX_AMOUNT)
        data = self.body(cash="1.00", deposits=[available], fee="0.01")
        before = (Receipt.objects.count(), ReceiptAccountLine.objects.count(), ReceiptAttachment.objects.count(),
            DepositAllocation.objects.count(), AuditLog.objects.count(), FinanceMutationKey.objects.count(),
            list(DailyBusinessNumberCounter.objects.values_list("pk", "last_value")))
        response = self.post_goods(data)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["error"]["code"], "AMOUNT_OUT_OF_RANGE")
        self.assertEqual(before, (Receipt.objects.count(), ReceiptAccountLine.objects.count(), ReceiptAttachment.objects.count(),
            DepositAllocation.objects.count(), AuditLog.objects.count(), FinanceMutationKey.objects.count(),
            list(DailyBusinessNumberCounter.objects.values_list("pk", "last_value"))))
        self.assertFalse(DepositAllocation.objects.filter(deposit_receipt=available).exists())
        pending_upload = FinanceReceiptUpload.objects.get(pk=data["upload_ids"][0])
        self.assertEqual(pending_upload.status, "UNBOUND")
        self.assertIsNone(pending_upload.bound_at)
        readback = self.client.get(f"/api/v1/finance/statements/{self.statement.pk}/")
        self.assertEqual(readback.status_code, 200, readback.data)
        self.assertEqual(readback.data["data"]["fee_amount"], str(MAX_AMOUNT))

    def test_api_no_permission_anonymous_and_csrf(self):
        data = self.body(cash="10.00")
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        denied = csrf_client.post("/api/v1/finance/receipts/", data, format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()), HTTP_IF_MATCH=etag_for_instance(self.statement))
        self.assertEqual(denied.status_code, 403)
        from apps.access_control.models import RoleActionGrant
        RoleActionGrant.objects.filter(role=self.role).delete()
        self.role.auth_group.permissions.clear()
        self.assertEqual(self.post_goods(data).status_code, 403)
        self.client.logout()
        self.assertIn(self.post_goods(data).status_code, (401, 403))
        self.assertFalse(Receipt.objects.exists())

    def test_inactive_employee_with_valid_grants_is_denied(self):
        deposit = self.create(kind="DEPOSIT", cash="200.00")
        self.assertEqual(self.post_goods(self.body(deposits=[deposit])).status_code, 201)
        available = self.create(kind="DEPOSIT", cash="100.00")
        data = self.body(deposits=[available])
        self.assertEqual(self.client.get("/api/v1/finance/receipts/").status_code, 200)
        self.actor.status = "INACTIVE"
        self.actor.save(update_fields=["status", "updated_at"])
        self.assertTrue(self.role.auth_group.permissions.filter(codename="add_receipt").exists())
        self.assertIn(self.client.get("/api/v1/finance/receipts/").status_code, (401, 403))
        self.assertIn(self.post_goods(data).status_code, (401, 403))
        self.assertFalse(DepositAllocation.objects.filter(deposit_receipt=available).exists())

    def test_four_ordinary_roles_can_create_and_void_goods(self):
        for code in ("FINANCE", "CASHIER", "FACTORY_MANAGER", "GENERAL_MANAGER"):
            if code == "FINANCE":
                user = self.user
            else:
                user = get_user_model().objects.create_user("goods_" + code)
                actor = Employee.objects.create(user=user, employee_code="GOODS_" + code, display_name=code)
                self.grant(code, actor)
            self.assertFalse(user.is_superuser)
            self.client.force_login(user)
            deposit = self.create(kind="DEPOSIT", cash="100.00")
            response = self.post_goods(self.body(deposits=[deposit]))
            self.assertEqual(response.status_code, 201, response.data)
            goods = response.data["data"]
            voided = self.client.post(f'/api/v1/finance/receipts/{goods["id"]}/void/', {"reason": "隔离角色验证"},
                format="json", HTTP_IF_MATCH=goods["etag"])
            self.assertEqual(voided.status_code, 200, voided.data)
            self.assertEqual(voided.data["data"]["status"], "VOID")
