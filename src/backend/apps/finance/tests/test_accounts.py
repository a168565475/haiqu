import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO, StringIO
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.core.models import DailyBusinessNumberCounter
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.reference_data.models import Currency
from apps.finance.importing import read_account_workbook, apply_account_import, account_import_plan
from apps.finance.models import FinanceAccount, FinanceMutationKey
from apps.finance.selectors import available_cny_accounts
from apps.finance import importing, services
from apps.finance.services import create_account, require_receipt_account

ROOT = "/api/v1/finance/accounts/"


def currency(code="CNY"):
    return Currency.objects.get_or_create(code=code, defaults={"numeric_code": "156" if code == "CNY" else "840",
        "chinese_name": "人民币" if code == "CNY" else "美元"})[0]


def body(**changes):
    return {"account_type": "银行账户", "category": "基本户", "name": "隔离合成账户",
            "account_number": "0000000000000000101", "currency_id": str(currency().pk), "status": "ACTIVE", **changes}


def grant(employee, role_code):
    role = RoleProfile.objects.create(role_code=role_code, display_name=role_code,
                                     auth_group=Group.objects.create(name=role_code))
    permissions = Permission.objects.filter(content_type__app_label="finance", content_type__model="financeaccount")
    for permission in permissions:
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
    role.auth_group.permissions.add(*permissions)
    EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
    return role


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True)
class AccountTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("finance_isolated", password="isolated-test-only")
        self.actor = Employee.objects.create(user=self.user, employee_code="FIN_ISOLATED", display_name="隔离测试")
        self.role = grant(self.actor, "FINANCE")
        self.client = APIClient()
        self.client.force_login(self.user)

    def create(self, data=None, key=None):
        return self.client.post(ROOT, body() if data is None else data, format="json", HTTP_IDEMPOTENCY_KEY=str(key or uuid4()))

    def test_create_list_search_detail_and_text_preserved(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.data)
        account = response.data["data"]
        self.assertEqual(account["account_number"], "0000000000000000101")
        self.assertRegex(account["code"], r"^ZH\d{9,}$")
        listed = self.client.get(ROOT, {"q": "0000000000000000101", "status": "ACTIVE", "currency": "CNY", "page_size": 1})
        self.assertEqual(listed.data["meta"]["total"], 1)
        detail = self.client.get(ROOT + account["id"] + "/")
        self.assertEqual(detail["ETag"], response["ETag"])
        self.assertNotIn("0000000000000000101", json.dumps(list(AuditLog.objects.filter(object_type="FINANCE_ACCOUNT").values_list("after_data", flat=True))))

    def test_etag_update_disable_delete_and_deleted_replay(self):
        data, key = body(), uuid4()
        original = self.create(data, key)
        url = ROOT + original.data["data"]["id"] + "/"
        self.assertEqual(self.client.patch(url, {"status": "INACTIVE"}, format="json").status_code, 428)
        response = self.client.patch(url, {"status": "INACTIVE"}, format="json", HTTP_IF_MATCH=original["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.client.delete(url, HTTP_IF_MATCH=original["ETag"]).status_code, 412)
        replay = self.create(data, key)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.data["data"]["status"], "INACTIVE")
        self.assertEqual(self.client.delete(url, HTTP_IF_MATCH=response["ETag"]).status_code, 204)
        deleted = self.create(data, key)
        self.assertEqual(deleted.status_code, 410)
        self.assertEqual(deleted.data["error"]["code"], "ORIGINAL_RESULT_DELETED")
        self.assertFalse(FinanceAccount.objects.exists())

    def test_duplicate_code_and_same_key_different_body(self):
        key, data = uuid4(), body(code="ORIGINAL-CODE")
        self.assertEqual(self.create(data, key).status_code, 201)
        self.assertEqual(self.create(data, key)["Idempotent-Replayed"], "true")
        conflict = self.create({**data, "name": "不同内容"}, key)
        self.assertEqual(conflict.data["error"]["code"], "IDEMPOTENCY_KEY_REUSED")
        duplicate = self.create(data)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.data["error"]["code"], "DUPLICATE_CODE")
        self.assertEqual(FinanceMutationKey.objects.count(), 1)

    def test_auto_number_skips_preserved_code(self):
        from zoneinfo import ZoneInfo
        today = timezone.localdate(timezone=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(self.create(body(code=f"ZH{today:%y%m%d}001")).status_code, 201)
        created = self.create()
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["data"]["code"], f"ZH{today:%y%m%d}002")

    def test_invalid_input_and_query(self):
        for changes in ({"account_number": 123}, {"account_number": " "}, {"name": ""}, {"category": "x" * 81},
                        {"customer_id": str(uuid4())}, {"currency_id": str(uuid4())}, {"status": "OTHER"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.create(body(**changes)).status_code, 400)
        self.assertEqual(self.client.post(ROOT, body(), format="json").status_code, 400)
        for params in ({"page": 0}, {"page_size": 101}, {"status": "OTHER"}, {"currency": "bad"}):
            self.assertEqual(self.client.get(ROOT, params).status_code, 400)
        response = self.create()
        self.assertEqual(self.client.patch(ROOT + response.data["data"]["id"] + "/", {"code": "x"}, format="json", HTTP_IF_MATCH=response["ETag"]).status_code, 400)
        self.assertEqual(self.client.get(ROOT + "not-a-uuid/").status_code, 404)

    def test_selector_only_active_cny_and_inactive_currency_replay(self):
        key, data = uuid4(), body()
        created = self.create(data, key)
        self.create(body(currency_id=str(currency("USD").pk)))
        self.create(body(status="INACTIVE"))
        self.assertEqual(available_cny_accounts().count(), 1)
        for account in FinanceAccount.objects.exclude(pk=created.data["data"]["id"]):
            with self.assertRaises(APIException):
                require_receipt_account(account)
        Currency.objects.filter(code="CNY").update(status="INACTIVE")
        self.assertEqual(available_cny_accounts().count(), 0)
        self.assertEqual(self.create(data, key).status_code, 200)
        # 仅有账户权限不足以使用收款选单，还需登记收款权限。
        self.assertEqual(self.client.get("/api/v1/finance/account-options/").status_code, 403)

    def test_four_roles_and_denials(self):
        for code in ("CASHIER", "FACTORY_MANAGER", "GENERAL_MANAGER"):
            user = get_user_model().objects.create_user("isolated_" + code)
            employee = Employee.objects.create(user=user, employee_code="ISO_" + code, display_name=code)
            grant(employee, code)
            self.client.force_login(user)
            created = self.create()
            self.assertEqual(created.status_code, 201)
            self.assertEqual(self.client.get(ROOT).status_code, 200)
            url = ROOT + created.data["data"]["id"] + "/"
            changed = self.client.patch(url, {"status": "INACTIVE"}, format="json", HTTP_IF_MATCH=created["ETag"])
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(self.client.delete(url, HTTP_IF_MATCH=changed["ETag"]).status_code, 204)
        self.client.force_login(self.user)
        RoleActionGrant.objects.filter(role=self.role).delete()
        self.role.auth_group.permissions.clear()
        self.assertEqual(self.client.get(ROOT).status_code, 403)
        self.assertEqual(self.create().status_code, 403)
        self.actor.status = "INACTIVE"
        self.actor.save()
        self.assertIn(self.client.get(ROOT).status_code, (401, 403))
        self.client.logout()
        self.assertIn(self.client.get(ROOT).status_code, (401, 403))

    def test_session_csrf_required(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(ROOT, body(), format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4())).status_code, 403)

    def test_audit_failure_rolls_back_account_key_and_number(self):
        before = DailyBusinessNumberCounter.objects.filter(number_type="FINANCE_ACCOUNT").count()
        with patch("apps.finance.services.write_audit_log", side_effect=RuntimeError("isolated audit failure")):
            with self.assertRaises(RuntimeError):
                self.create()
        self.assertFalse(FinanceAccount.objects.exists())
        self.assertFalse(FinanceMutationKey.objects.exists())
        self.assertEqual(DailyBusinessNumberCounter.objects.filter(number_type="FINANCE_ACCOUNT").count(), before)

    def workbook(self, account_number="0000000000000000101"):
        book = Workbook()
        sheet = book.active
        sheet.title = "账户信息"
        sheet.append(["账户类型", "账户编码", "账户类别", "账户名称", "账户账号", "账户状态", "币种"])
        sheet.append(["银行账户", "IMPORT-1", "基本户", "合成账户", account_number, "启用", "人民币"])
        sheet.append(["银行账户", "IMPORT-2", "外币户", "合成美元", "0000000000000000202", "启用", "美元"])
        stream = BytesIO()
        book.save(stream)
        book.close()
        return stream.getvalue()

    def test_import_exact_idempotent_and_conflict_whole_batch(self):
        currency(); currency("USD")
        content = self.workbook()
        rows = read_account_workbook(content, hashlib.sha256(content).hexdigest())
        self.assertEqual([item["action"] for item in apply_account_import(rows, self.actor)], ["CREATE", "CREATE"])
        self.assertEqual([item["action"] for item in apply_account_import(rows, self.actor)], ["UNCHANGED", "UNCHANGED"])
        self.assertEqual(FinanceAccount.objects.count(), 2)
        rows[0][1]["code"] = "NEW-CODE"
        rows[1][1]["name"] = "不同内容"
        with self.assertRaises(APIException):
            apply_account_import(rows, self.actor)
        self.assertFalse(FinanceAccount.objects.filter(code="NEW-CODE").exists())
        self.assertNotIn("0000000000000000101", json.dumps(account_import_plan(rows)))

    def test_import_rejects_wrong_hash_numeric_and_formula(self):
        currency(); currency("USD")
        for number in (1234567890123456789, "=1+2"):
            content = self.workbook(number)
            with self.assertRaises(ValidationError):
                read_account_workbook(content, hashlib.sha256(content).hexdigest())
        with self.assertRaises(ValidationError):
            read_account_workbook(self.workbook(), "0" * 64)

    def test_grant_command_preserves_other_grants_and_assignments(self):
        old_permission = Permission.objects.get(content_type__app_label="reference_data", codename="view_currency")
        old_grant = RoleActionGrant.objects.create(role=self.role, permission=old_permission, scope="MODULE")
        self.role.auth_group.permissions.add(old_permission)
        for code in ("CASHIER", "FACTORY_MANAGER", "GENERAL_MANAGER"):
            RoleProfile.objects.create(role_code=code, display_name=code, auth_group=Group.objects.create(name=code))
        admin = get_user_model().objects.create_superuser("admin", email="")
        actor = Employee.objects.create(user=admin, employee_code="ISO_ADMIN", display_name="隔离管理员")
        before = list(EmployeeRoleAssignment.objects.values())
        params = {"database_name": connection.settings_dict["NAME"], "actor_employee_id": str(actor.pk), "stdout": StringIO()}
        call_command("grant_finance_account_roles", **params)
        self.assertEqual(RoleActionGrant.objects.filter(permission__content_type__app_label="finance").count(), 4)
        call_command("grant_finance_account_roles", apply=True, **params)
        call_command("grant_finance_account_roles", apply=True, **params)
        self.assertEqual(RoleActionGrant.objects.filter(permission__content_type__app_label="finance").count(), 16)
        self.assertEqual(list(EmployeeRoleAssignment.objects.values()), before)
        self.assertTrue(RoleActionGrant.objects.filter(pk=old_grant.pk, permission=old_permission, scope="MODULE").exists())
        self.assertTrue(self.role.auth_group.permissions.filter(pk=old_permission.pk).exists())


class AccountConcurrencyTests(TransactionTestCase):
    def test_import_and_create_lock_order_same_code_different_content(self):
        actor = Employee.objects.create(employee_code="FIN_LOCK", display_name="隔离锁验证")
        data = body(code="LOCK-CODE")
        currency_locked, import_attempt = Event(), Event()
        original_validate = services.validate_currency
        rows = [(2, {"account_type": data["account_type"], "code": data["code"], "category": data["category"],
                     "name": "导入不同内容", "account_number": data["account_number"], "status": "ACTIVE", "currency": currency()})]

        def create_validate(value):
            original_validate(value)
            currency_locked.set()
            if not import_attempt.wait(10):
                raise AssertionError("导入未进入币种锁阶段")

        def import_validate(value):
            import_attempt.set()
            original_validate(value)

        def writer(kind):
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                        cursor.execute("SELECT pg_backend_pid()")
                        pid = cursor.fetchone()[0]
                    if kind == "create":
                        request = SimpleNamespace(employee=actor, data=data, headers={"Idempotency-Key": str(uuid4())}, META={})
                        account, _ = create_account(request)
                        return pid, "created", str(account.pk)
                    if not currency_locked.wait(10):
                        raise AssertionError("新增未持有币种锁")
                    try:
                        apply_account_import(rows, actor)
                    except APIException as exc:
                        return pid, exc.api_error_code, None
                    return pid, "imported", None
            finally:
                close_old_connections()

        with patch.object(services, "validate_currency", create_validate), patch.object(importing, "validate_currency", import_validate), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, ("create", "import")))
        self.assertEqual(len({item[0] for item in results}), 2)
        self.assertEqual([item[1] for item in results], ["created", "DUPLICATE_CODE"])
        self.assertEqual(FinanceAccount.objects.get(code=data["code"]).name, data["name"])
        self.assertEqual(FinanceAccount.objects.count(), 1)

    def test_same_key_concurrent_requests_only_create_once(self):
        user = get_user_model().objects.create_user("concurrent_finance")
        actor = Employee.objects.create(user=user, employee_code="FIN_CONCURRENT", display_name="隔离并发")
        data, key, barrier = body(), uuid4(), Barrier(2)

        def submit():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                request = SimpleNamespace(employee=actor, data=data, headers={"Idempotency-Key": str(key)}, META={})
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '10s'")
                    account, replayed = create_account(request)
                return str(account.pk), replayed
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(len({result[0] for result in results}), 1)
        self.assertEqual(sorted(result[1] for result in results), [False, True])
        self.assertEqual(FinanceAccount.objects.count(), 1)
