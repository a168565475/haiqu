from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.core.models import DailyBusinessNumberCounter
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.reference_data.models import Currency, ProductionUnit
from apps.finance.models import FinanceMutationKey
from apps.finance.source_selectors import reference_price, source_products, source_revision
from apps.finance.statement_models import ReceivableStatement, ReceivableStatementLine
from apps.finance.statement_services import create_statement

ROOT = "/api/v1/finance/statements/"
SOURCE = "/api/v1/finance/source-tasks/"


def grant_statements(actor, code="FINANCE"):
    role = RoleProfile.objects.create(role_code=code, display_name=code, auth_group=Group.objects.create(name=code))
    permissions = Permission.objects.filter(content_type__app_label="finance", content_type__model="receivablestatement")
    for permission in permissions:
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
    role.auth_group.permissions.add(*permissions)
    EmployeeRoleAssignment.objects.create(employee=actor, role_profile=role, effective_from=timezone.now())
    return role


def create_source(actor, *, quantities=(60, 3, 3, 5), prices=("61.0900", "0.3350", "0.3350", "4.0000"), status="READY"):
    currency = Currency.objects.get_or_create(code="CNY", defaults={"numeric_code": "156", "chinese_name": "人民币"})[0]
    unit = ProductionUnit.objects.get_or_create(unit_code="U03_PCS", defaults={"unit_name": "隔离件"})[0]
    salesperson = Employee.objects.create(employee_code="S" + uuid4().hex[:10].upper(), display_name="隔离业务员（无账号）")
    task = ProductionTask.objects.create(task_number="U03" + uuid4().hex[:12], contract_number="C" + uuid4().hex[:12],
        order_source="NEW", order_number="U03-ISOLATED", order_date=date(2026, 10, 20), delivery_date=date(2026, 10, 30),
        salesperson=salesperson, currency=currency, includes_tax=False, order_tolerance_percent=0,
        is_repeat_order=False, preproduction_sample_required=False, delivery_method="SINGLE", status=status,
        created_by_employee=actor, freight_amount=800, other_fee_amount=100)
    for index, (quantity, price) in enumerate(zip(quantities, prices), 1):
        ProductionTaskProduct.objects.create(production_task=task, line_number=index, product_name_snapshot=f"隔离产品{index}",
            specification_snapshot="隔离规格", item_number_snapshot=f"U03-{index}", quantity=quantity, unit=unit, currency=currency,
            unit_price=price, total_amount=Decimal(price) * quantity, exchange_rate=1, exchange_rate_snapshot={})
    return task


def request_body(task, indices=(0,), price=None):
    products = list(source_products(task.pk))
    by_line = sorted(products, key=lambda item: item.line_number)
    return {"production_task_id": str(task.pk), "source_revision": source_revision(task, products),
            "acknowledge_salesperson_change": False,
            "lines": [{"production_task_product_id": str(by_line[index].pk), "unit_price": price or str(by_line[index].unit_price)} for index in indices]}


def make_receipt(statement, actor, kind="DEPOSIT", amount="1.00"):
    from apps.finance.receipt_models import Receipt
    money = Decimal(amount)
    return Receipt.objects.create(number="U03-R" + uuid4().hex[:12], statement=statement, receipt_type=kind,
        cash_amount=money, deposit_amount=money if kind == "DEPOSIT" else 0, settled_amount=money if kind == "GOODS" else 0,
        created_by_employee=actor, updated_by_employee=actor)


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
    CACHES={key: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "finance-u03-tests-" + key}
            for key in ("default", "configuration", "wecom")})
class StatementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("u03_isolated", password="isolated-test-only")
        self.actor = Employee.objects.create(user=self.user, employee_code="U03_FIN", display_name="隔离财务操作人")
        self.role = grant_statements(self.actor)
        self.task = create_source(self.actor)
        self.client = APIClient()
        self.client.force_login(self.user)

    def create(self, body=None, key=None):
        return self.client.post(ROOT, body or request_body(self.task), format="json", HTTP_IDEMPOTENCY_KEY=str(key or uuid4()))

    def test_partial_whole_lines_snapshot_different_actor_no_production_permission(self):
        self.assertFalse(self.user.has_perm("production_tasks.view_productiontask"))
        self.assertEqual(self.client.get(SOURCE).status_code, 200)
        source = self.client.get(f"{SOURCE}{self.task.pk}/products/")
        self.assertEqual(source.status_code, 200, source.data)
        self.assertEqual(source.data["meta"]["total"], 4)
        self.assertNotIn("customer", str(source.data))
        response = self.create(request_body(self.task, (0, 3)))
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data["data"]
        self.assertEqual(data["amount"], "3685.40")
        self.assertEqual(data["lines"][0]["amount"], "3665.40")
        self.assertEqual(data["lines"][0]["quantity"], "60")
        self.assertEqual(data["salesperson"]["id"], str(self.task.salesperson_id))
        self.assertNotEqual(data["salesperson"]["id"], data["operator"]["id"])
        self.assertEqual(data["source_order_date"], "2026-10-20")
        self.assertRegex(data["number"], r"^YSDZD\d{9,}$")
        second = self.create(request_body(self.task, (1, 2)))
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.data["data"]["amount"], "2.02")
        self.assertEqual(ReceivableStatementLine.objects.filter(is_occupied=True).count(), 4)

    def test_amount_rounding_zero_overflow_and_invalid_input(self):
        for price in ("0", "-1", "1e2", "NaN", "1.00001", "100000000000000", 1.2):
            with self.subTest(price=price):
                body = request_body(self.task); body["lines"][0]["unit_price"] = price
                self.assertEqual(self.create(body).status_code, 400)
        tiny = self.create(request_body(self.task, (1,), "0.0001"))
        self.assertEqual(tiny.status_code, 400)
        self.assertEqual(tiny.data["error"]["code"], "VALIDATION_ERROR")
        for extra in ({"quantity": "30"}, {"amount": "1.00"}, {"currency": "USD"}):
            body = request_body(self.task); body["lines"][0].update(extra)
            self.assertEqual(self.create(body).status_code, 400)
        body = request_body(self.task); body["lines"] *= 2
        self.assertEqual(self.create(body).status_code, 400)
        body["lines"] = []
        self.assertEqual(self.create(body).status_code, 400)
        product = self.task.products.first(); product.quantity = 9223372036854775807; product.save()
        result = self.create(request_body(self.task, (0,), "99999999999999.9999"))
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.data["error"]["code"], "AMOUNT_OUT_OF_RANGE")

    def test_unit_groups_price_override_does_not_write_source(self):
        unit = ProductionUnit.objects.create(unit_code="U03_SET", unit_name="隔离套")
        self.task.products.filter(line_number=4).update(unit=unit)
        response = self.create(request_body(self.task, (0, 3), "2.1234"))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["quantity_totals"], [
            {"unit_code": "U03_PCS", "unit_name": "隔离件", "quantity": "60"},
            {"unit_code": "U03_SET", "unit_name": "隔离套", "quantity": "5"}])
        self.assertEqual(self.task.products.get(line_number=1).unit_price, Decimal("61.09"))

    def test_source_revision_detects_line_only_and_salesperson_changes(self):
        body = request_body(self.task)
        self.task.products.filter(line_number=1).update(quantity=61)
        result = self.create(body)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.data["error"]["code"], "SOURCE_CHANGED")
        self.assertFalse(ReceivableStatement.objects.exists())
        first = self.create()
        previous = self.task.salesperson
        self.task.salesperson = Employee.objects.create(employee_code="U03_NEW_SALES", display_name="新业务员")
        self.task.save()
        changed = request_body(self.task, (1,))
        result = self.create(changed)
        self.assertEqual(result.data["error"]["code"], "SALESPERSON_CONFIRMATION_REQUIRED")
        changed["acknowledge_salesperson_change"] = True
        self.assertEqual(self.create(changed).status_code, 201)
        old = ReceivableStatement.objects.get(pk=first.data["data"]["id"])
        patch_body = request_body(self.task, (0,), "10.0000")
        edited = self.client.patch(f"{ROOT}{old.pk}/", patch_body, format="json", HTTP_IF_MATCH=first["ETag"])
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(edited.data["data"]["salesperson"]["id"], str(previous.pk))
        previous.status = "INACTIVE"; previous.display_name = "离职改名"; previous.save()
        detail = self.client.get(f"{ROOT}{old.pk}/")
        self.assertNotEqual(detail.data["data"]["salesperson"]["name"], "离职改名")

    def test_source_status_archive_currency_and_incomplete_fields(self):
        for status in ("DRAFT", "PENDING_VALIDATION", "CANCELLED"):
            self.task.status = status; self.task.save()
            self.assertEqual(self.create().status_code, 400)
            self.assertEqual(self.client.get(SOURCE).data["meta"]["total"], 0)
        self.task.status = "READY"; self.task.archived_at = timezone.now(); self.task.save()
        self.assertEqual(self.create().status_code, 400)
        self.task.archived_at = None; self.task.save()
        product = self.task.products.get(line_number=1)
        product.currency = Currency.objects.get_or_create(code="USD", defaults={"numeric_code": "840", "chinese_name": "美元"})[0]
        product.exchange_rate = Decimal("7.12345678"); product.save()
        result = self.create()
        self.assertEqual(result.data["error"]["code"], "SOURCE_CNY_BASIS_MISSING")
        source = self.client.get(f"{SOURCE}{self.task.pk}/products/")
        row = next(row for row in source.data["data"] if row["id"] == str(product.pk))
        self.assertFalse(row["selectable"])
        product.exchange_rate_snapshot = {"base_currency_code": "CNY", "quote_currency_code": "USD", "rate": "7.12345678"}; product.save()
        self.assertEqual(self.create().status_code, 400)
        product.exchange_rate_snapshot = {"base_currency_code": "USD", "quote_currency_code": "CNY", "rate": "7.12345678"}; product.save()
        self.assertEqual(reference_price(product), Decimal("435.1719756902").quantize(Decimal("0.0001")))
        self.assertEqual(self.create().status_code, 201)

    def test_edit_atomic_history_occupied_failure_and_void_release(self):
        created = self.create()
        pk = created.data["data"]["id"]; url = ROOT + pk + "/"
        self.assertEqual(self.client.patch(url, request_body(self.task, (1,)), format="json").status_code, 428)
        second = self.create(request_body(self.task, (3,)))
        failed = self.client.patch(url, request_body(self.task, (3,)), format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(failed.data["error"]["code"], "SOURCE_LINE_OCCUPIED")
        self.assertEqual(ReceivableStatement.objects.get(pk=pk).statement_revision, 1)
        edited = self.client.patch(url, request_body(self.task, (1, 2)), format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(edited.data["data"]["statement_revision"], 2)
        self.assertEqual(ReceivableStatementLine.objects.filter(statement_id=pk).count(), 3)
        self.assertEqual(ReceivableStatementLine.objects.filter(statement_id=pk, is_occupied=True).count(), 2)
        self.assertEqual(self.client.post(url + "void/", {"reason": "旧条件"}, format="json", HTTP_IF_MATCH=created["ETag"]).status_code, 412)
        voided = self.client.post(url + "void/", {"reason": "隔离测试作废"}, format="json", HTTP_IF_MATCH=edited["ETag"])
        self.assertEqual(voided.status_code, 200, voided.data)
        self.assertTrue(voided.data["data"]["changed"])
        self.assertEqual(len(voided.data["data"]["lines"]), 2)
        self.assertFalse(ReceivableStatementLine.objects.filter(statement_id=pk, is_occupied=True).exists())
        repeat = self.client.post(url + "void/", {"reason": "重试"}, format="json", HTTP_IF_MATCH=voided["ETag"])
        self.assertFalse(repeat.data["data"]["changed"])
        self.assertEqual(AuditLog.objects.filter(object_id=pk, action="VOID").count(), 1)
        self.assertEqual(self.create(request_body(self.task, (1,))).status_code, 201)
        with self.assertRaises(ProtectedError):
            self.task.products.get(line_number=1).delete()

    def test_all_active_receipts_freeze_even_same_amount_change_and_unlock_after_void(self):
        created = self.create(); pk = created.data["data"]["id"]; url = ROOT + pk + "/"
        statement = ReceivableStatement.objects.get(pk=pk)
        for kind in ("DEPOSIT", "GOODS"):
            receipt = make_receipt(statement, self.actor, kind)
            self.assertFalse(self.client.get(url).data["data"]["can_edit"])
            for path, body, method in ((url, request_body(self.task), self.client.patch), (url + "void/", {"reason": "冻结检查"}, self.client.post)):
                result = method(path, body, format="json", HTTP_IF_MATCH=etag_for_instance(statement))
                self.assertEqual(result.status_code, 409)
                self.assertEqual(result.data["error"]["code"], "STATEMENT_FROZEN")
            receipt.status = "VOID"; receipt.void_reason = "隔离撤销"; receipt.voided_at = timezone.now(); receipt.voided_by = self.actor; receipt.save()
        self.assertTrue(self.client.get(url).data["data"]["can_edit"])

    def test_idempotency_current_state_and_audit_failure_rollback(self):
        body, key = request_body(self.task), uuid4()
        created = self.create(body, key)
        self.assertEqual(self.create(body, key).status_code, 200)
        changed = {**body, "acknowledge_salesperson_change": True}
        self.assertEqual(self.create(changed, key).data["error"]["code"], "IDEMPOTENCY_KEY_REUSED")
        self.client.post(ROOT + created.data["data"]["id"] + "/void/", {"reason": "重放检查"}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(self.create(body, key).data["data"]["status"], "VOID")
        count = FinanceMutationKey.objects.count(); counter = list(DailyBusinessNumberCounter.objects.filter(number_type="RECEIVABLE_STATEMENT").values())
        with patch("apps.finance.statement_services.write_audit_log", side_effect=RuntimeError("injected audit failure")):
            with self.assertRaises(RuntimeError):
                self.create(request_body(self.task, (1,)))
        self.assertEqual(FinanceMutationKey.objects.count(), count)
        self.assertEqual(list(DailyBusinessNumberCounter.objects.filter(number_type="RECEIVABLE_STATEMENT").values()), counter)
        self.assertFalse(ReceivableStatementLine.objects.filter(is_occupied=True).exists())

    def test_pagination_filters_receipt_mode_and_forbidden(self):
        first = self.create(); statement = ReceivableStatement.objects.get(pk=first.data["data"]["id"])
        make_receipt(statement, self.actor, "GOODS", "10.00")
        self.create(request_body(self.task, (1, 2)))
        result = self.client.get(ROOT, {"settlement_status": "PARTIAL", "page_size": 1})
        self.assertEqual(result.data["meta"]["total"], 1)
        self.assertEqual(result.data["data"][0]["outstanding_amount"], "3655.40")
        self.assertEqual(self.client.get(SOURCE, {"mode": "receipt"}).data["meta"]["total"], 1)
        for params in ({"page": 0}, {"page_size": 101}, {"status": "BAD"}, {"task_id": "bad"}):
            self.assertEqual(self.client.get(ROOT, params).status_code, 400)
        # 删除是独立权限；有查看/新增权限不代表可以删除。
        delete_grants = RoleActionGrant.objects.filter(role=self.role, permission__codename="delete_receivablestatement")
        self.role.auth_group.permissions.remove(*delete_grants.values_list("permission_id", flat=True))
        delete_grants.delete()
        self.assertEqual(self.client.delete(ROOT + str(statement.pk) + "/").status_code, 403)
        self.assertTrue(ReceivableStatement.objects.filter(pk=statement.pk).exists())
        self.role.auth_group.permissions.clear(); RoleActionGrant.objects.filter(role=self.role).delete()
        for url in (ROOT, SOURCE, f"{SOURCE}{self.task.pk}/products/"):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertIn(self.client.get(ROOT).status_code, (401, 403))

    def test_csrf_and_four_roles(self):
        client = APIClient(enforce_csrf_checks=True); client.force_login(self.user)
        self.assertEqual(client.post(ROOT, request_body(self.task), format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4())).status_code, 403)
        for code in ("CASHIER", "GENERAL_MANAGER", "FACTORY_MANAGER"):
            user = get_user_model().objects.create_user("U03_" + code)
            actor = Employee.objects.create(user=user, employee_code="U03_" + code, display_name=code)
            grant_statements(actor, code); self.client.force_login(user)
            task = create_source(actor)
            created = self.create(request_body(task))
            self.assertEqual(created.status_code, 201, created.data)
            self.assertEqual(self.client.get(ROOT).status_code, 200)
        self.actor.status = "INACTIVE"; self.actor.save(); self.client.force_login(self.user)
        self.assertIn(self.client.get(ROOT).status_code, (401, 403))


class StatementConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.actor = Employee.objects.create(employee_code="U03_LOCK", display_name="隔离并发")
        self.task = create_source(self.actor)

    def race_create(self, same_key):
        body, key, barrier = request_body(self.task), uuid4(), Barrier(2)
        def writer(_):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                request = SimpleNamespace(employee=self.actor, data=body, headers={"Idempotency-Key": str(key if same_key else uuid4())}, META={})
                try:
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL lock_timeout = '10s'")
                        statement, replay = create_statement(request)
                    return str(statement.pk), replay
                except APIException as exc:
                    return exc.api_error_code, False
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(writer, range(2)))

    def test_same_source_concurrent_only_one_occupancy(self):
        results = self.race_create(False)
        self.assertEqual(sum(result[0] == "SOURCE_LINE_OCCUPIED" for result in results), 1)
        self.assertEqual(ReceivableStatement.objects.count(), 1)
        self.assertEqual(ReceivableStatementLine.objects.filter(is_occupied=True).count(), 1)
        self.assertEqual(FinanceMutationKey.objects.count(), 1)
        self.assertEqual(DailyBusinessNumberCounter.objects.get(number_type="RECEIVABLE_STATEMENT").last_value, 1)

    def test_same_key_concurrent_only_one_document(self):
        results = self.race_create(True)
        self.assertEqual(len({result[0] for result in results}), 1)
        self.assertEqual(sorted(result[1] for result in results), [False, True])
        self.assertEqual(ReceivableStatement.objects.count(), 1)

    def test_database_occupancy_unique(self):
        request = SimpleNamespace(employee=self.actor, data=request_body(self.task), headers={"Idempotency-Key": str(uuid4())}, META={})
        statement, _ = create_statement(request)
        line = statement.lines.first(); line.pk = uuid4(); line.statement_revision = 2
        with self.assertRaises(IntegrityError), transaction.atomic():
            line.save(force_insert=True)
