"""独占 PostgreSQL 与真实 HTTP 的合成页面验证，不代表正式员工验收。"""
import json
import os
import secrets
import time
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.organizations.models import EmployeeRoleAssignment, RoleProfile
from apps.procurement.models import PurchaseOrder
from .test_dashboard_api import DashboardFixture


@skipUnless(os.environ.get('ORDER_COST_BROWSER') == '1', '仅显式启动隔离页面验证')
@override_settings(ALLOWED_HOSTS=['*'], CSRF_TRUSTED_ORIGINS=['http://127.0.0.1:18862'],
                   DEV_AUTO_LOGIN_ENABLED=False, MODULE_ACCESS_ENABLED=True)
class CostBrowserTests(DashboardFixture, LiveServerTestCase):
    host = '0.0.0.0'
    port = 18861
    client_class = APIClient

    def test_saved_amounts_and_expense_browser(self):
        self.assertEqual(connection.settings_dict['NAME'], 'test_order_cost_20261026_397c')
        root = Path('/app/_tmp/order-cost-browser-397c')
        self.assertFalse(root.exists(), '控制目录已存在，拒绝覆盖来源不明的资源')
        ready, done = root / 'ready.json', root / 'done.json'
        password = secrets.token_urlsafe(24)
        self.user.set_password(password)
        self.user.save(update_fields=['password'])
        codes = ['view_productiontask', 'view_productiontaskcost', 'manage_productiontaskexpense']
        permissions = Permission.objects.filter(content_type__app_label='production_tasks', codename__in=codes)
        self.assertEqual(permissions.count(), 3)
        role = RoleProfile.objects.create(role_code='COST_QA', display_name='成本隔离测试',
                                           auth_group=Group.objects.create(name='cost-qa'))
        role.auth_group.permissions.add(*permissions)
        for permission in permissions:
            RoleActionGrant.objects.create(role=role, permission=permission, scope='MODULE')
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=role, effective_from=timezone.now())
        task = self.task('COST-BROWSER')
        task.products.update(unit_price=100, total_amount=10000)
        PurchaseOrder.objects.create(order_number='CGDD261026989', production_task=task,
                                     currency=self.currency, currency_code_snapshot='CNY', total_amount=4000)
        root.mkdir(parents=True)
        try:
            pending_ready = root / 'ready.tmp'
            pending_ready.write_text(json.dumps({'database': connection.settings_dict['NAME'], 'task_id': str(task.pk),
                'username': self.user.username, 'password': password}), encoding='utf-8')
            pending_ready.replace(ready)
            deadline = time.monotonic() + 600
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(0.25)
            self.assertTrue(done.exists(), '页面验证超时')
            self.assertTrue(json.loads(done.read_text(encoding='utf-8'))['passed'], '页面验证失败，见脱敏报告')
        finally:
            ready.unlink(missing_ok=True)
            done.unlink(missing_ok=True)
            (root / 'ready.tmp').unlink(missing_ok=True)
            (root / 'done.tmp').unlink(missing_ok=True)
            root.rmdir()
