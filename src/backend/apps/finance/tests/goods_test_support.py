"""仅用于隔离测试库的合成业务记录，不作为生产初始化或页面演示数据。"""
import base64
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone

from apps.access_control.models import RoleActionGrant
from apps.core.api.concurrency import etag_for_instance
from apps.files.models import BusinessFile
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_tasks.models import ProductionTask
from apps.reference_data.models import Currency
from apps.finance.models import FinanceAccount
from apps.finance.receipt_models import FinanceReceiptUpload
from apps.finance.receipt_services import create_receipt, void_receipt
from apps.finance.statement_models import ReceivableStatement


class GoodsFixture:
    def setUp(self):
        super().setUp()
        root = os.environ.get("FINANCE_GOODS_TEST_ROOT")
        self.media = tempfile.TemporaryDirectory(prefix="goods-", dir=root)
        self.addCleanup(self.media.cleanup)
        settings = override_settings(MEDIA_ROOT=self.media.name, FILE_VIRUS_SCAN_ENABLED=False,
            ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True)
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = get_user_model().objects.create_user("goods_isolated", password="isolated-only")
        self.actor = Employee.objects.create(user=self.user, employee_code="GOODS_ISOLATED", display_name="隔离货款测试")
        self.currency = Currency.objects.get_or_create(code="CNY", defaults={"numeric_code": "156", "chinese_name": "人民币"})[0]
        self.account = FinanceAccount.objects.create(code="GOODS-TEST", account_type="银行账户", category="基本户",
            name="隔离合成账户", account_number="000000000001", currency=self.currency,
            created_by_employee=self.actor, updated_by_employee=self.actor)
        self.statement = self.new_statement()

    def new_statement(self, amount="1000.00", task=None):
        token = uuid4().hex[:12].upper()
        if task is None:
            task = ProductionTask.objects.create(task_number="GT-" + token, contract_number="GC-" + token,
                order_source="NEW", order_number="GO-" + token, order_date=date(2026, 10, 23),
                delivery_date=date(2026, 10, 24), salesperson=self.actor, currency=self.currency,
                includes_tax=False, order_tolerance_percent=Decimal("0"), is_repeat_order=False,
                preproduction_sample_required=False, delivery_method="SINGLE", status="READY")
        return ReceivableStatement.objects.create(number="GS-" + token, production_task=task,
            salesperson=self.actor, task_number_snapshot=task.task_number,
            salesperson_code_snapshot=self.actor.employee_code, salesperson_name_snapshot=self.actor.display_name,
            source_order_date=task.order_date, source_revision="isolated-source", amount=Decimal(amount),
            created_by_employee=self.actor, updated_by_employee=self.actor)

    def upload(self, statement=None):
        statement = statement or self.statement
        # 真实磁盘实体及外键；扫描跳过明确标记，仅验证货款绑定/追溯，不冒充病毒扫描。
        content = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1cAAAAASUVORK5CYII=")
        storage_key = f"finance/receipt_uploads/{uuid4()}.png"
        path = Path(self.media.name) / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        file = BusinessFile.objects.create(uploaded_by_employee=self.actor, original_name="隔离水单.png",
            storage_key=storage_key, content_type="image/png", size_bytes=len(content), scan_status="SKIPPED")
        return FinanceReceiptUpload.objects.create(file=file, statement=statement,
            owner_employee=self.actor, upload_key=uuid4())

    def body(self, *, statement=None, cash="0.00", deposits=(), discount="0.00", fee="0.00", kind="GOODS", uploads=None):
        statement = statement or self.statement
        lines = [] if Decimal(cash) == 0 else [{"account_id": str(self.account.pk),
            "account_etag": etag_for_instance(self.account), "cash_amount": cash,
            "fee_amount": fee, "received_on": "2026-10-23"}]
        if uploads is None:
            uploads = [str(self.upload(statement).pk)] if lines else []
        result = {"receipt_type": kind, "statement_id": str(statement.pk), "account_lines": lines, "upload_ids": uploads}
        if kind == "GOODS":
            result.update(deposit_ids=[str(item.pk) for item in deposits], discount_amount=discount)
        return result

    def request(self, data, instance=None, key=None, etag=None):
        instance = instance or self.statement
        instance.refresh_from_db()
        return SimpleNamespace(data=data, employee=self.actor, META={},
            headers={"Idempotency-Key": str(key or uuid4()), "If-Match": etag or etag_for_instance(instance)})

    def create(self, **kwargs):
        statement = kwargs.get("statement") or self.statement
        return create_receipt(self.request(self.body(**kwargs), statement))[0]

    def void(self, receipt, etag=None):
        return void_receipt(self.request({"reason": "隔离验证作废"}, receipt, etag=etag), receipt.pk)

    def grant(self, role_code="FINANCE", actor=None):
        actor = actor or self.actor
        role = RoleProfile.objects.create(role_code=role_code, display_name=role_code,
            auth_group=Group.objects.create(name=role_code))
        permissions = list(Permission.objects.filter(content_type__app_label="finance",
            content_type__model__in=["receipt", "receivablestatement"]))
        if not permissions:
            raise AssertionError("财务迁移/权限注册未就绪，不能伪造API通过")
        for permission in permissions:
            RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
        role.auth_group.permissions.add(*permissions)
        EmployeeRoleAssignment.objects.create(employee=actor, role_profile=role, effective_from=timezone.now())
        return role
