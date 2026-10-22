"""单项增量授权的隔离数据库检查；不代表正式员工身份验收。"""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.access_control.catalog import projected_permission_ids
from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.access_control.services import add_module_grant, assert_managed_projection
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance, PreconditionFailed
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee, RoleProfile
from apps.workshop_config.models import Workshop


CODE = 'inventory.view_finishedgoodsreceipt'


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class AddModuleGrantTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username='admin', email='')
        Employee.objects.create(user=self.admin, employee_code='IO_ADMIN', display_name='隔离授权管理员')
        self.role = RoleProfile.objects.create(role_code='WAREHOUSE_KEEPER', display_name='仓管',
            auth_group=Group.objects.create(name='IO_WAREHOUSE'))
        permission = Permission.objects.get(content_type__app_label='production_scheduling', codename='view_productionschedule')
        self.old = RoleActionGrant.objects.create(role=self.role, permission=permission, scope='WORKSHOP')
        self.resource = RoleGrantResource.objects.create(grant=self.old, workshop=Workshop.objects.filter(status='ACTIVE').first())
        self.role.auth_group.permissions.add(*projected_permission_ids([(permission, 'WORKSHOP')]))

    def request(self, **changes):
        return SimpleNamespace(user=changes.get('user', self.admin), META={},
            headers={'If-Match': changes.get('etag', etag_for_instance(self.role))})

    def test_append_preserves_original_rows_projection_and_records_exact_audit(self):
        role, created = add_module_grant(self.request(), self.role.pk, CODE)
        self.assertTrue(created)
        self.assertTrue(RoleActionGrant.objects.filter(pk=self.old.pk).exists())
        self.assertTrue(RoleGrantResource.objects.filter(pk=self.resource.pk, grant=self.old).exists())
        self.assertTrue(RoleActionGrant.objects.filter(role=role, permission__codename='view_finishedgoodsreceipt', scope='MODULE').exists())
        assert_managed_projection(role)
        audit = AuditLog.objects.get(action='ROLE_GRANT_ADD')
        self.assertEqual(audit.after_data['added_grant']['permission'], CODE)
        self.assertEqual(audit.after_data['added_grant']['resource_ids'], [])

    def test_repeat_has_no_new_grant_audit_or_etag_change(self):
        self.role, _ = add_module_grant(self.request(), self.role.pk, CODE)
        first_etag = etag_for_instance(self.role)
        _, created = add_module_grant(self.request(), self.role.pk, CODE)
        self.assertFalse(created)
        self.role.refresh_from_db()
        self.assertEqual(etag_for_instance(self.role), first_etag)
        self.assertEqual(AuditLog.objects.filter(action='ROLE_GRANT_ADD').count(), 1)
        self.assertEqual(RoleActionGrant.objects.filter(role=self.role).count(), 2)

    def test_wrong_etag_and_unprivileged_actor_cannot_write(self):
        with self.assertRaises(PreconditionFailed):
            add_module_grant(self.request(etag='stale'), self.role.pk, CODE)
        user = get_user_model().objects.create_user(username='io_ordinary')
        Employee.objects.create(user=user, employee_code='IO_ORDINARY', display_name='隔离普通员工')
        with self.assertRaises(PermissionDenied):
            add_module_grant(self.request(user=user), self.role.pk, CODE)
        self.assertEqual(RoleActionGrant.objects.filter(role=self.role).count(), 1)

    def test_archived_role_and_existing_other_scope_are_rejected(self):
        self.role.archived_at = timezone.now()
        self.role.save()
        with self.assertRaises(Conflict):
            add_module_grant(self.request(), self.role.pk, CODE)
        self.role.archived_at = None
        self.role.save()
        # 已有WORKSHOP范围不能被一次MODULE增量静默扩大。
        with self.assertRaises(Conflict):
            add_module_grant(self.request(), self.role.pk, 'production_scheduling.view_productionschedule')
        self.assertEqual(RoleActionGrant.objects.filter(role=self.role).count(), 1)

    def test_audit_failure_rolls_back_grant_projection_and_version(self):
        first_etag = etag_for_instance(self.role)
        with patch('apps.access_control.services.audit', side_effect=RuntimeError('隔离审计失败')):
            with self.assertRaises(RuntimeError):
                add_module_grant(self.request(), self.role.pk, CODE)
        self.role.refresh_from_db()
        self.assertEqual(etag_for_instance(self.role), first_etag)
        self.assertEqual(RoleActionGrant.objects.filter(role=self.role).count(), 1)
        assert_managed_projection(self.role)
        self.assertFalse(AuditLog.objects.filter(action='ROLE_GRANT_ADD').exists())
