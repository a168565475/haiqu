from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import SimpleTestCase, override_settings

from apps.access_control.catalog import PERMISSION_CODES, catalog
from apps.access_control.presentation import presentation
from apps.core.views import user_payload
from apps.organizations.models import Employee, EmployeeRoleAssignment


PRODUCTION_OPERATIONS = (
    ('edit_productionplan', 'productionplan', '生产计划', '修改生产计划日期、优先级和跟单员'),
    ('pause_productiontask', 'productiontask', '生产订单', '暂停生产任务'),
    ('resume_productiontask', 'productiontask', '生产订单', '恢复生产任务'),
    ('void_productiontaskexpense', 'productiontaskexpense', '生产零星费用', '作废'),
)


def declared_permissions():
    # 从当前模型声明构造未保存对象，覆盖目录真实模型名而不读取或创建权限记录。
    permissions = {}
    for model in apps.get_models():
        options = model._meta
        content_type = ContentType(app_label=options.app_label, model=options.model_name)
        names = [(f'{action}_{options.model_name}', f'Can {action} {options.verbose_name_raw}')
                 for action in options.default_permissions]
        for codename, name in (*names, *options.permissions):
            permissions[f'{options.app_label}.{codename}'] = Permission(
                codename=codename, name=name, content_type=content_type,
            )
    return permissions


class PresentationCatalogTests(SimpleTestCase):
    def test_new_production_operations_have_labels_before_permission_migration(self):
        for codename, model, resource_name, action_name in PRODUCTION_OPERATIONS:
            with self.subTest(codename=codename):
                result = presentation(f'access_control.{codename}', None, 'production_tasks')
                self.assertEqual(result['resource'], f'production_tasks.{model}')
                self.assertEqual(result['resource_name'], resource_name)
                self.assertEqual(result['action'], 'special')
                self.assertEqual(result['action_name'], action_name)
                self.assertEqual(result['label'], f'{resource_name} · {action_name}')

    def test_existing_specific_chinese_permission_names_are_preserved(self):
        content_type = ContentType(app_label='access_control', model='roleactiongrant')
        for codename, _model, _resource_name, _action_name in PRODUCTION_OPERATIONS[:3]:
            with self.subTest(codename=codename):
                name = '已配置的生产专项操作中文说明'
                permission = Permission(codename=codename, name=name, content_type=content_type)
                result = presentation(f'access_control.{codename}', permission, 'production_tasks')
                self.assertEqual(result['action_name'], name)
                self.assertEqual(result['action'], 'special')

    def test_whole_catalog_builds_before_and_after_new_permissions_are_available(self):
        permissions = declared_permissions()
        new_codes = {f'access_control.{row[0]}' for row in PRODUCTION_OPERATIONS}
        self.assertTrue(new_codes.issubset(PERMISSION_CODES))
        for migrated in (False, True):
            with self.subTest(migrated=migrated):
                available = {code: permission for code, permission in permissions.items()
                             if migrated or code not in new_codes}
                with patch('apps.access_control.catalog.permission_map', return_value=available), \
                        patch('apps.access_control.catalog.scopes_for', return_value=('MODULE',)):
                    rows = catalog()
                self.assertEqual({row['code'] for row in rows}, set(PERMISSION_CODES))
                self.assertTrue(all(row['resource_name'] and row['action_name'] and row['label'] for row in rows))
                for row in rows:
                    if row['code'] in new_codes:
                        self.assertEqual(row['available'], migrated)

    @override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False)
    def test_login_user_payload_builds_effective_access_before_production_permissions_exist(self):
        permissions = declared_permissions()
        for codename, *_rest in PRODUCTION_OPERATIONS:
            permissions.pop(f'access_control.{codename}')
        user = get_user_model()(pk=1, username='catalog-unit-admin', is_active=True, is_superuser=True)
        employee = Employee(user=user, employee_code='CATALOG-UNIT', display_name='权限目录单元测试', status='ACTIVE')
        with patch('apps.access_control.catalog.permission_map', return_value=permissions), \
                patch('apps.access_control.catalog.scopes_for', return_value=('MODULE',)), \
                patch('apps.access_control.selectors.Employee.objects.filter') as employees, \
                patch('apps.access_control.selectors.current_assignments', return_value=EmployeeRoleAssignment.objects.none()), \
                patch.object(user, 'get_all_permissions', return_value=set(permissions)), \
                patch('apps.wecom.selectors.waiting_for_role', return_value=False):
            employees.return_value.first.return_value = employee
            payload = user_payload(user)
        self.assertTrue(payload['effective_access']['active'])
        self.assertTrue(payload['effective_access']['is_superuser'])
        self.assertEqual(set(payload['effective_access']['actions']), set(PERMISSION_CODES) & permissions.keys())
        self.assertNotIn('access_control.edit_productionplan', payload['effective_access']['actions'])

    def test_unknown_resource_still_raises_instead_of_hiding_catalog_errors(self):
        with self.assertRaisesMessage(ValueError, 'Missing access catalog resource label'):
            presentation('access_control.edit_unknownresource', None, 'production_tasks')
