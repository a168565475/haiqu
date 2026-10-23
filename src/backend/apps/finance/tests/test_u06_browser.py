"""U06隔离HTTP/页面夹具，合成身份不代表主库真实员工。"""
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone

from apps.access_control.models import RoleActionGrant
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from .test_statements import create_source


@skipUnless(os.environ.get("FINANCE_U06_BROWSER") == "1", "U06 explicit isolated browser only")
@override_settings(ALLOWED_HOSTS=["*"], CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:18756"],
    MEDIA_ROOT="/app/_tmp/finance_u06_01a166b7/media", FILE_VIRUS_SCAN_ENABLED=False,
    ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
    CACHES={name: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "finance-u06-browser-" + name}
        for name in ("default", "configuration", "wecom")})
class U06BrowserTests(LiveServerTestCase):
    host = "0.0.0.0"
    port = 18755

    def test_cross_unit_normal_sessions(self):
        self.assertEqual(connection.settings_dict["NAME"], "test_finance_u06_01a166b7")
        root = Path("/app/_tmp/finance_u06_01a166b7")
        media = tempfile.TemporaryDirectory(prefix="http-case-", dir=root / "media")
        self.addCleanup(media.cleanup)
        media_settings = override_settings(MEDIA_ROOT=media.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        ready, done = root / "browser-ready.json", root / "browser-done.json"
        self.assertFalse(ready.exists() or done.exists())
        identities, actors = {}, {}
        for code in ("FINANCE", "CASHIER", "GENERAL_MANAGER", "FACTORY_MANAGER", "DENIED", "INACTIVE"):
            password = secrets.token_urlsafe(24)
            user = get_user_model().objects.create_user("u06_" + code.lower(), password=password)
            actor = Employee.objects.create(user=user, employee_code="U06_" + code,
                display_name="U06隔离" + code, status="INACTIVE" if code == "INACTIVE" else "ACTIVE")
            actors[code] = actor
            if code != "DENIED":
                role = RoleProfile.objects.create(role_code=code, display_name=code,
                    auth_group=Group.objects.create(name="U06_" + code))
                permissions = list(Permission.objects.filter(content_type__app_label="finance",
                    content_type__model__in=("financeaccount", "accountingsubject", "receivablestatement", "receipt")))
                self.assertEqual(len(permissions), 15)
                for permission in permissions:
                    RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
                role.auth_group.permissions.add(*permissions)
                EmployeeRoleAssignment.objects.create(employee=actor, role_profile=role, effective_from=timezone.now())
            identities[code] = {"username": user.username, "password": password}
        task = create_source(actors["FINANCE"], quantities=(1, 1, 1, 1), prices=("1000.0000", "300.0000", "25.0000", "50.0000"))
        try:
            ready.write_text(json.dumps({"isolated": True, "database": connection.settings_dict["NAME"],
                "identities": identities, "task_id": str(task.pk), "task_number": task.task_number,
                "currency_id": str(task.currency_id), "salesperson_id": str(task.salesperson_id)}), encoding="utf-8")
            deadline = time.monotonic() + 600
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(0.25)
            self.assertTrue(done.exists(), "U06 browser timeout")
            self.assertTrue(json.loads(done.read_text(encoding="utf-8"))["passed"], "U06 browser failed; see independent report")
        finally:
            ready.unlink(missing_ok=True)
            done.unlink(missing_ok=True)
