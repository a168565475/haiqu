"""独占测试库真实HTTP与普通隔离角色页面检查，不代替生产员工验收。"""
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

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.organizations.models import EmployeeRoleAssignment, RoleProfile
from apps.workshop_reporting.models import WorkReportLine
from .test_tube_orders_api import TubeApiFixture


@skipUnless(os.environ.get('OUTSOURCING_PLAN_BROWSER') == '1', '仅显式启动登记的隔离页面检查')
@override_settings(ALLOWED_HOSTS=['*'], CSRF_TRUSTED_ORIGINS=['http://127.0.0.1:18872'],
    DEV_AUTO_LOGIN_ENABLED=False, MODULE_ACCESS_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True,
    SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True,
    TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class PlanBrowserTests(TubeApiFixture, LiveServerTestCase):
    host = '0.0.0.0'
    port = 18871
    client_class = APIClient

    def test_create_dispatch_receive_existing_pages(self):
        self.assertEqual(connection.settings_dict['NAME'], 'test_outsourcing_plan_01a1851e_20261029')
        root = Path('/app/_tmp/outsourcing-plan-browser-01a1851e')
        self.assertFalse(root.exists(), '控制目录已存在，拒绝覆盖来源不明的资源')
        ready, done = root / 'ready.json', root / 'done.json'
        password = secrets.token_urlsafe(24)
        self.user.is_superuser = False
        self.user.is_staff = False
        self.user.set_password(password)
        self.user.save(update_fields=['password', 'is_superuser', 'is_staff'])
        WorkReportLine.objects.all().delete()
        role = RoleProfile.objects.create(role_code='OUTSOURCING_PLAN_BROWSER', display_name='委外隔离页面角色',
            auth_group=Group.objects.create(name='outsourcing-plan-browser-01a1851e'))
        codes = ['view_outsourcingorder', 'add_outsourcingorder', 'cancel_outsourcingorder',
            'confirm_dispatch_outsourcingorder', 'confirm_return_outsourcingorder']
        permissions = list(Permission.objects.filter(content_type__app_label='outsourcing', codename__in=codes))
        self.assertEqual(len(permissions), len(codes))
        role.auth_group.permissions.add(*permissions)
        for permission in permissions:
            grant = RoleActionGrant.objects.create(role=role, permission=permission, scope='CRAFT')
            RoleGrantResource.objects.create(grant=grant, craft=self.spray)
        # 页面导航和库存明细只读入口，写权限仍限定当前喷塑工艺。
        for app, code in [('production_tasks', 'view_productiontask'),
                ('production_scheduling', 'view_productionschedule'), ('outsourcing', 'view_outsourcingfactory'),
                ('inventory', 'view_internalsemifinishedreceipt')]:
            permission = Permission.objects.get(content_type__app_label=app, codename=code)
            role.auth_group.permissions.add(permission)
            RoleActionGrant.objects.create(role=role, permission=permission, scope='MODULE')
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=role, effective_from=timezone.now())
        root.mkdir(parents=True)
        try:
            pending_ready = root / 'ready.tmp'
            pending_ready.write_text(json.dumps({'database': connection.settings_dict['NAME'],
                'username': self.user.username, 'password': password, 'taskId': str(self.task.pk),
                'scheduleProductId': str(self.schedule_product.pk), 'componentIdentity': self.component,
                'factoryId': str(self.factory.pk), 'factoryName': self.factory.name,
                'partName': self.metal_bom_line.part_name, 'bomQuantity': 200, 'craftId': str(self.spray.pk),
                'warehouseId': str(self.semi_zone.warehouse_id), 'warehouseName': self.semi_zone.warehouse.warehouse_name,
                'zoneId': str(self.semi_zone.pk), 'zoneName': self.semi_zone.zone_name}), encoding='utf-8')
            pending_ready.replace(ready)
            deadline = time.monotonic() + 600
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(0.25)
            self.assertTrue(done.exists(), '页面检查超时')
            self.assertTrue(json.loads(done.read_text(encoding='utf-8'))['passed'], '页面检查失败，见脱敏报告')
        finally:
            for path in (ready, done, root / 'ready.tmp', root / 'done.tmp'):
                path.unlink(missing_ok=True)
            root.rmdir()
