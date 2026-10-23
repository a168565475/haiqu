"""U04隔离测试夹具；合成身份与文件不能充当主库业务验收。"""
import base64
import hashlib
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.core.api.concurrency import etag_for_instance
from apps.files.models import BusinessFile
from apps.finance.models import FinanceAccount
from apps.finance.receipt_models import FinanceReceiptUpload
from apps.finance.statement_models import ReceivableStatement
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from .test_statements import create_source, request_body

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII=")
ROOT = "/api/v1/finance/receipts/"
UPLOADS = "/api/v1/finance/receipt-uploads/"


def grant_receipts(actor, code="FINANCE", codenames=None):
    role = RoleProfile.objects.create(role_code=code, display_name=code, auth_group=Group.objects.create(name=code))
    permissions = Permission.objects.filter(content_type__app_label="finance")
    if codenames is not None:
        permissions = permissions.filter(codename__in=codenames)
    for permission in permissions:
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
    role.auth_group.permissions.add(*permissions)
    EmployeeRoleAssignment.objects.create(employee=actor, role_profile=role, effective_from=timezone.now())
    return role


class ReceiptFixtureMixin:
    def setUp(self):
        super().setUp()
        base = Path(os.environ.get("FINANCE_RECEIPT_TEST_ROOT", "/app/_tmp/finance_u04_20261023"))
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="case-", dir=base)
        self.addCleanup(self.temp.cleanup)
        config = override_settings(MEDIA_ROOT=self.temp.name, FILE_VIRUS_SCAN_ENABLED=False,
            ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True)
        config.enable(); self.addCleanup(config.disable)
        self.user = get_user_model().objects.create_user("u04_isolated", password="isolated-test-only")
        self.actor = Employee.objects.create(user=self.user, employee_code="U04_FIN", display_name="隔离收款操作人")
        self.role = grant_receipts(self.actor)
        self.client = APIClient(); self.client.force_login(self.user)
        self.task = create_source(self.actor, quantities=(1, 1), prices=("100.0000", "100.0000"))
        response = self.client.post("/api/v1/finance/statements/", request_body(self.task, (0,)), format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4()))
        self.assertEqual(response.status_code, 201, response.data)
        self.statement = ReceivableStatement.objects.get(pk=response.data["data"]["id"])
        self.account = FinanceAccount.objects.create(account_type="银行账户", code="U04_ACCOUNT", category="基本户",
            name="隔离账户", account_number="00001234567890123456", currency=self.task.currency,
            created_by_employee=self.actor, updated_by_employee=self.actor)

    def file(self, *, actor=None, storage_key=None):
        key = storage_key or f"finance/receipt_uploads/test/{uuid4()}.png"
        path = Path(self.temp.name) / key
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(PNG)
        return BusinessFile.objects.create(uploaded_by_employee=actor or self.actor, original_name="隔离水单.png",
            storage_key=key, content_type="image/png", size_bytes=len(PNG), content_hash=hashlib.sha256(PNG).hexdigest(), scan_status="SKIPPED")

    def upload(self, *, actor=None, statement=None):
        return FinanceReceiptUpload.objects.create(file=self.file(actor=actor), owner_employee=actor or self.actor,
            statement=statement or self.statement, upload_key=uuid4())

    def body(self, amount="25.00", fee="1.00", *, upload=None):
        return {"receipt_type": "DEPOSIT", "statement_id": str(self.statement.pk),
            "account_lines": [{"account_id": str(self.account.pk), "account_etag": etag_for_instance(self.account),
                "cash_amount": amount, "fee_amount": fee, "received_on": "2026-10-23"}],
            "upload_ids": [str((upload or self.upload()).pk)]}

    def create(self, body=None, *, key=None, etag=None):
        self.statement.refresh_from_db()
        return self.client.post(ROOT, body or self.body(), format="json", HTTP_IDEMPOTENCY_KEY=str(key or uuid4()),
            HTTP_IF_MATCH=etag or etag_for_instance(self.statement))
