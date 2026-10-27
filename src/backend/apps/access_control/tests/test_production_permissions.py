from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APITestCase

from apps.access_control.models import RoleGrantResource
from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.access_control.production_role_templates import templates
from apps.access_control.resource_scopes import require_workshop
from apps.organizations.models import EmployeeRoleAssignment
from apps.workshop_config.models import Workshop


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class ProductionPermissionTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        self.scoped_actor()
        self.metal = Workshop.objects.get(name='金工车间')
        self.sewing = Workshop.objects.get(name='车缝车间')

    def test_purchase_request_all_actions_closed_and_open(self):
        url = '/api/v1/purchase-requests/'
        routes = [('get', ''), ('get', 'options/'), ('get', f'{uuid4()}/'),
            ('post', ''), ('patch', f'{uuid4()}/'), ('post', f'{uuid4()}/submit/'),
            ('post', f'{uuid4()}/allocate/'), ('post', f'{uuid4()}/cancel-allocation/'),
            ('get', f'{uuid4()}/supplier-order-options/'), ('post', f'{uuid4()}/generate-supplier-order/')]
        for flag in (False, True):
            with override_settings(MODULE_ACCESS_ENABLED=flag):
                for method, suffix in routes:
                    with self.subTest(flag=flag, method=method, suffix=suffix):
                        response = getattr(self.client, method)(url + suffix, {}, format='json')
                        self.assertEqual(response.status_code, 403, response.data)

    def test_purchase_request_read_does_not_allow_write_in_either_mode(self):
        self.grant('procurement.view_purchaserequest')
        for flag in (False, True):
            with override_settings(MODULE_ACCESS_ENABLED=flag):
                self.assertEqual(self.client.get('/api/v1/purchase-requests/').status_code, 200)
                self.assertEqual(self.client.post('/api/v1/purchase-requests/', {}, format='json').status_code, 403)
                self.assertEqual(self.client.post(f'/api/v1/purchase-requests/{uuid4()}/submit/').status_code, 403)

    def test_purchase_request_create_grant_reaches_validation_in_either_mode(self):
        self.grant('procurement.add_purchaserequest')
        for flag in (False, True):
            with override_settings(MODULE_ACCESS_ENABLED=flag):
                self.assertEqual(self.client.post('/api/v1/purchase-requests/', {}, format='json').status_code, 400)
                self.assertEqual(self.client.patch(f'/api/v1/purchase-requests/{uuid4()}/', {}, format='json').status_code, 403)

    def test_management_directory_is_available_without_grant_write_or_wecom(self):
        self.grant('organizations.manage_organization')
        for url in ('catalog/', 'roles/', 'employees/', 'departments/'):
            response = self.client.get('/api/v1/access/' + url)
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.client.post('/api/v1/access/roles/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.get(reverse('wecom-config')).status_code, 403)

    def test_administration_attendance_is_read_only_for_both_modes(self):
        self.grant('attendance.view_attendance')
        for flag in (False, True):
            with override_settings(MODULE_ACCESS_ENABLED=flag):
                response = self.client.get(reverse('attendance-overview'), {'month': '2026-10'})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(self.client.post(reverse('attendance-sync-start'), {}, format='json').status_code, 403)
                self.assertEqual(self.client.put(reverse('attendance-schedule') + '?month=2026-10', {}, format='json').status_code, 403)
                self.assertEqual(self.client.get(reverse('attendance-rules') + '?month=2026-10').status_code, 403)

    def test_ordinary_manager_codes_are_independent_of_module_switch(self):
        from apps.access_control.permissions import CanManageAccess, CanManageAccounts, CanManageWeCom
        self.grant('access_control.manage_access')
        self.grant('access_control.manage_accounts')
        self.grant('access_control.manage_wecom')
        for flag in (False, True):
            with override_settings(MODULE_ACCESS_ENABLED=flag):
                for permission in (CanManageAccess, CanManageAccounts, CanManageWeCom):
                    self.assertTrue(permission().has_permission(self.scoped_request(), None))
        user = get_user_model().objects.get(pk=self.scope_user.pk)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertEqual(self.client.get('/api/v1/access/roles/').status_code, 200)
        self.assertEqual(self.client.get(reverse('wecom-config')).status_code, 200)
        from apps.organizations.models import Employee
        from apps.core.api.concurrency import etag_for_instance
        target = Employee.objects.create(employee_code='U03-ACCOUNT-TARGET', display_name='隔离账号目标')
        response = self.client.post(f'/api/v1/access/employees/{target.pk}/account/',
            {'username': 'u03-ordinary-account', 'password': 'Unit03StrongSecret835!'},
            format='json', HTTP_IF_MATCH=etag_for_instance(target))
        self.assertEqual(response.status_code, 201, response.data)

    def test_direct_legacy_management_grant_does_not_make_manager(self):
        from django.contrib.auth.models import Permission
        from apps.access_control.permissions import CanManageAccess
        self.scope_user.user_permissions.add(Permission.objects.get(codename='manage_access'))
        self.assertFalse(CanManageAccess().has_permission(self.scoped_request(), None))

    def test_management_revocation_expiry_and_employee_disabled(self):
        from apps.access_control.permissions import CanManageAccess
        grant = self.grant('access_control.manage_access')
        self.assertTrue(CanManageAccess().has_permission(self.scoped_request(), None))
        EmployeeRoleAssignment.objects.filter(role_profile=grant.role).update(effective_to=timezone.now())
        self.assertFalse(CanManageAccess().has_permission(self.scoped_request(), None))
        EmployeeRoleAssignment.objects.filter(role_profile=grant.role).update(effective_to=None)
        grant.role.archived_at = timezone.now(); grant.role.save()
        self.assertFalse(CanManageAccess().has_permission(self.scoped_request(), None))
        grant.role.archived_at = None; grant.role.save()
        self.scope_employee.status = 'INACTIVE'; self.scope_employee.save()
        self.assertFalse(CanManageAccess().has_permission(self.scoped_request(), None))

    def test_workshop_actions_do_not_borrow_other_operation_resources(self):
        self.grant('material_issues.view_materialissue')
        self.grant('material_issues.add_materialissue', 'WORKSHOP', [self.metal])
        require_workshop(self.scoped_request(), 'material_issues.add_materialissue', self.metal.pk)
        with self.assertRaises(PermissionDenied):
            require_workshop(self.scoped_request(), 'material_issues.add_materialissue', self.sewing.pk)
        self.grant('material_issues.add_materialissue', 'WORKSHOP', [self.sewing])
        require_workshop(self.scoped_request(), 'material_issues.add_materialissue', self.sewing.pk)

    def test_empty_workshop_selection_never_grants_all(self):
        self.grant('material_issues.add_materialissue', 'WORKSHOP')
        with self.assertRaises(PermissionDenied):
            require_workshop(self.scoped_request(), 'material_issues.add_materialissue', self.metal.pk)

    def test_disabling_rollout_flags_never_widens_existing_scoped_roles(self):
        self.grant('material_issues.add_materialissue', 'WORKSHOP', [self.metal])
        for flags in ({'MODULE_ACCESS_ENABLED': False}, {'ACCESS_RESOURCE_SCOPES_ENABLED': False},
                      {'MODULE_ACCESS_ENABLED': False, 'ACCESS_RESOURCE_SCOPES_ENABLED': False}):
            with override_settings(**flags), self.assertRaises(PermissionDenied):
                require_workshop(self.scoped_request(), 'material_issues.add_materialissue', self.sewing.pk)

    def test_outsourcing_stock_direct_sources_and_multi_role_union(self):
        from apps.outsourcing.source_access import allowed_source_kinds, require_source
        code = 'outsourcing.confirm_dispatch_outsourcingorder'
        self.grant(code, 'STOCK')
        self.assertEqual(allowed_source_kinds(self.scoped_request(), code), {'RAW_PIPE', 'PUBLIC_SEMI', 'PUBLIC_CUTTING'})
        for source in ('METAL', 'SEWING'):
            with self.assertRaises(PermissionDenied):
                require_source(self.scoped_request(), code, source)
        self.grant(code, 'WORKSHOP', [self.metal])
        require_source(self.scoped_request(), code, 'METAL')
        with self.assertRaises(PermissionDenied):
            require_source(self.scoped_request(), code, 'SEWING')
        self.grant(code, 'WORKSHOP', [self.sewing])
        require_source(self.scoped_request(), code, 'SEWING')

    def test_full_template_tracks_catalog_and_keeps_private_preferences_own(self):
        from apps.access_control.catalog import PERMISSION_CODES, validate_grants
        ids = dict(Workshop.objects.values_list('name', 'pk'))
        rows = templates(ids)
        self.assertEqual(len(rows), 20)
        for role in ('FACTORY_MANAGER', 'GENERAL_MANAGER'):
            self.assertEqual({row['permission'] for row in rows[role]}, set(PERMISSION_CODES))
            validate_grants(rows[role])
            self.assertTrue(all(row['scope'] == 'OWN' for row in rows[role] if row['permission'].startswith('preferences.')))
        attendance = {row['permission'] for row in rows['ADMINISTRATION'] if row['permission'].startswith('attendance.')}
        self.assertEqual(attendance, {'attendance.view_attendance'})

    def test_warehouse_template_can_read_pending_and_confirmed_finished_receipts(self):
        ids = dict(Workshop.objects.values_list('name', 'pk'))
        rows = {row['permission'] for row in templates(ids)['WAREHOUSE_KEEPER']}
        self.assertIn('inventory.view_internalsemifinishedreceipt', rows)
        self.assertIn('inventory.view_finishedgoodsreceipt', rows)

    def test_warehouse_template_confirms_saved_outsourcing_orders_for_all_sources(self):
        ids = dict(Workshop.objects.values_list('name', 'pk'))
        rows = templates(ids)
        warehouse = {row['permission']: row['scope'] for row in rows['WAREHOUSE_KEEPER']}
        for code in ('outsourcing.confirm_dispatch_outsourcingorder',
                     'material_issues.create_metalprocessingoriginalhandoff',
                     'material_issues.confirm_metalprocessingexternalhandoff',
                     'material_issues.confirm_metalprocessingexternalreturn'):
            self.assertEqual(warehouse[code], 'MODULE')
        for role in ('METAL_DIRECTOR', 'SEWING_DIRECTOR', 'ASSEMBLY_DIRECTOR'):
            permissions = {row['permission'] for row in rows[role]}
            self.assertNotIn('outsourcing.confirm_dispatch_outsourcingorder', permissions)
            self.assertNotIn('material_issues.confirm_metalprocessingexternalhandoff', permissions)

    def test_purchasing_template_can_execute_quality_generated_returns(self):
        ids = dict(Workshop.objects.values_list('name', 'pk'))
        rows = {row['permission'] for row in templates(ids)['PURCHASING']}
        self.assertIn('access_control.confirm_purchasereturn', rows)
        self.assertIn('access_control.complete_purchasereturn', rows)

    def test_warehouse_template_only_tracks_quality_generated_returns(self):
        ids = dict(Workshop.objects.values_list('name', 'pk'))
        rows = {row['permission'] for row in templates(ids)['WAREHOUSE_KEEPER']}
        self.assertNotIn('access_control.confirm_purchasereturn', rows)
        self.assertNotIn('access_control.complete_purchasereturn', rows)

    def test_pending_receipt_deletion_grants_follow_confirmed_roles(self):
        ids = dict(Workshop.objects.values_list('name', 'pk'))
        rows = templates(ids)
        for code, expected in (
            ('inventory.delete_internalsemifinishedreceipt',
             {'WAREHOUSE_KEEPER', 'FACTORY_MANAGER', 'GENERAL_MANAGER', 'METAL_DIRECTOR', 'SEWING_DIRECTOR'}),
            ('inventory.delete_finishedgoodsreceipt',
             {'WAREHOUSE_KEEPER', 'FACTORY_MANAGER', 'GENERAL_MANAGER', 'ASSEMBLY_DIRECTOR'}),
        ):
            actual = {role for role, grants in rows.items() if any(row['permission'] == code for row in grants)}
            self.assertEqual(actual, expected)

    def test_administration_self_confirmation_exception_is_role_and_action_bound(self):
        from apps.access_control.production_approval import check_production_approval
        from apps.core.audit import write_audit_log
        task = SimpleNamespace(pk=uuid4())
        write_audit_log(object_type='PRODUCTION_TASK', object_id=task.pk, action='SUBMITTED', actor_employee=self.scope_employee)
        grant = self.grant('production_tasks.confirm_productiontask')
        with self.assertRaises(PermissionDenied):
            check_production_approval(self.scope_employee, task)
        grant.role.role_code = 'ADMINISTRATION'; grant.role.save()
        check_production_approval(self.scope_employee, task)
        grant.delete()
        with self.assertRaises(PermissionDenied):
            check_production_approval(self.scope_employee, task)

    def test_administration_does_not_bypass_wage_self_approval(self):
        from apps.access_control.module_policy import prohibit_self_approval
        grant = self.grant('workshop_reporting.approve_wagescheme')
        grant.role.role_code = 'ADMINISTRATION'; grant.role.save()
        with self.assertRaises(PermissionDenied):
            prohibit_self_approval(self.scope_employee, self.scope_employee.pk)


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class ProductionConfirmationApiTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        from apps.production_tasks.tests.test_production_task_api import ProductionTaskApiTests
        self.fixture = ProductionTaskApiTests()
        self.fixture.setUp()
        self.created = self.fixture.create_task()
        self.scoped_actor()
        self.grant('production_tasks.view_productiontask')
        self.grant('production_tasks.submit_productiontask')
        grant = self.grant('production_tasks.confirm_productiontask')
        grant.role.role_code = 'ADMINISTRATION'; grant.role.save()
        self.url = f"/api/v1/production-tasks/{self.created.data['data']['id']}/"
        self.submitted = self.client.post(self.url + 'submit/', {}, format='json', HTTP_IF_MATCH=self.created['ETag'])
        self.assertEqual(self.submitted.status_code, 200, self.submitted.data)

    def test_same_administration_confirms_via_confirm(self):
        self._confirm('confirm/')

    def test_same_administration_confirms_via_pmc_decision(self):
        self._confirm('pmc-decision/')

    def _confirm(self, suffix):
        today = timezone.localdate().isoformat()
        payload = {'decision': 'CONFIRM', 'follower_ids': [str(self.fixture.follower.pk)],
            'planned_start_date': today, 'planned_end_date': today}
        missing = self.client.post(self.url + suffix, payload, format='json')
        self.assertEqual(missing.status_code, 428, missing.data)
        stale = self.client.post(self.url + suffix, payload, format='json', HTTP_IF_MATCH='"stale"')
        self.assertEqual(stale.status_code, 412, stale.data)
        confirmed = self.client.post(self.url + suffix, payload, format='json', HTTP_IF_MATCH=self.submitted['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data['data']['status'], 'READY')

    def test_same_administration_confirms_legacy_transition_service(self):
        from apps.production_tasks.models import ProductionTask
        from apps.production_tasks.services import transition_production_task
        task = ProductionTask.objects.get(pk=self.created.data['data']['id'])
        result = transition_production_task(task=task, target_status='READY', actor_employee=self.scope_employee,
            request=self.scoped_request())
        self.assertEqual(result.status, 'READY')


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class WageSelfApprovalApiTests(ScopedActorMixin, APITestCase):
    def test_authorized_submitter_is_denied_by_self_approval_rule(self):
        from apps.workshop_reporting.tests.test_workshop_reporting_api import WorkshopReportingApiTests
        fixture = WorkshopReportingApiTests()
        fixture.setUp()
        self.scoped_actor()
        for code in ('view_wagescheme', 'add_wagescheme', 'submit_wagescheme', 'approve_wagescheme'):
            self.grant('workshop_reporting.' + code)
        created = self.client.post('/api/v1/workshop-reporting/wage-schemes/', fixture.scheme_payload(), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        url = f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/"
        submitted = self.client.post(url + 'submit/', {}, format='json', HTTP_IF_MATCH=created['ETag'])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        denied = self.client.post(url + 'approve/', {}, format='json', HTTP_IF_MATCH=submitted['ETag'])
        self.assertEqual(denied.status_code, 403, denied.data)
        self.assertIn('提交人不能', str(denied.data))


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class WorkshopBoundaryApiTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        from apps.workshop_reporting.tests.test_workshop_reporting_api import WorkshopReportingApiTests
        self.fixture = WorkshopReportingApiTests()
        self.fixture.setUp()
        self.scoped_actor()
        self.metal = self.fixture.workshop
        self.sewing = Workshop.objects.get(name='车缝车间')

    def test_legacy_read_sources_keep_original_task_boundary(self):
        from django.contrib.auth.models import Permission
        from apps.material_issues.models import MaterialIssue
        MaterialIssue.objects.create(issue_number='U03-LEGACY', client_request_id=uuid4(),
            request_payload_hash='l' * 64, created_by_employee=self.fixture.employee,
            updated_by_employee=self.fixture.employee, production_task=self.fixture.task,
            product_line=self.fixture.product_line, workshop=self.metal)
        self.scope_user.user_permissions.add(*Permission.objects.filter(codename__in=[
            'view_productiontask', 'view_productionschedule', 'view_materialissue']))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.scope_user.pk))
        for route in ('production-tasks', 'production-schedules', 'material-issues'):
            response = self.client.get('/api/v1/' + route + '/')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['data'], [], response.data)
        # 其他模块的MODULE角色不能扩张生产任务旧直授的数据范围。
        self.grant('inventory.view_materialinbound')
        response = self.client.get('/api/v1/production-tasks/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data'], [])

    def test_plan_category_and_object_use_the_operation_workshop(self):
        self.grant('production_scheduling.view_productionschedule', 'WORKSHOP', [self.metal])
        self.grant('production_scheduling.change_productionschedule', 'WORKSHOP', [self.sewing])
        for category, count in (('METAL', 1), ('SEWING', 0)):
            response = self.client.get('/api/v1/production-schedule-items/', {'category': category})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(len(response.data['data']), count)
        url = f'/api/v1/production-schedules/{self.fixture.schedule_product.schedule_id}/'
        detail = self.client.get(url)
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data['data']['audit_timeline'], [])
        self.assertEqual(self.client.patch(url, {}, format='json').status_code, 404)

    def test_material_list_detail_submit_options_and_requirements_do_not_cross_workshop(self):
        from apps.material_issues.models import MaterialIssue
        issue = MaterialIssue.objects.create(issue_number='U03-CROSS', client_request_id=uuid4(),
            request_payload_hash='x' * 64, created_by_employee=self.fixture.employee,
            updated_by_employee=self.fixture.employee, production_task=self.fixture.task,
            product_line=self.fixture.product_line, workshop=self.sewing)
        for code in ('view_materialissue', 'change_materialissue', 'submit_materialissue'):
            self.grant('material_issues.' + code, 'WORKSHOP', [self.metal])
        url = f'/api/v1/material-issues/{issue.pk}/'
        self.assertEqual(self.client.get(url).status_code, 404)
        from django.contrib.auth.models import Permission
        self.scope_user.user_permissions.add(Permission.objects.get(
            content_type__app_label='material_issues', codename='view_materialissue'))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.scope_user.pk))
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url + 'submit/', {}, format='json').status_code, 404)
        options = self.client.get('/api/v1/material-issues/options/')
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual({row['id'] for row in options.data['data']['workshops']}, {str(self.metal.pk)})
        response = self.client.get('/api/v1/material-issues/requirements/', {
            'production_task_id': str(self.fixture.task.pk), 'product_line_id': str(self.fixture.product_line.pk),
            'workshop_id': str(self.sewing.pk)})
        self.assertEqual(response.status_code, 403, response.data)

        # 服务持有对象锁后再次校验，覆盖列表读取后车间变化的竞争窗口。
        from apps.material_issues.services import submit_issue, return_issue, confirm_issue
        self.grant('material_issues.review_materialissue', 'WORKSHOP', [self.metal])
        for operation in (
            lambda: submit_issue(issue_id=issue.pk, actor_employee=self.scope_employee, request=self.scoped_request()),
            lambda: return_issue(issue_id=issue.pk, reason='范围检查', actor_employee=self.scope_employee, request=self.scoped_request()),
            lambda: confirm_issue(issue_id=issue.pk, request_id=uuid4(), actor_employee=self.scope_employee, request=self.scoped_request()),
        ):
            with self.assertRaises(PermissionDenied):
                operation()


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class ParameterDeletionApiTests(ScopedActorMixin, APITestCase):
    def test_metal_grant_deletes_only_actual_metal_image_without_generic_change(self):
        from apps.access_control.tests.test_module_policy import ModulePolicyTests
        from apps.samples.models import SampleParameterImage
        from apps.files.models import BusinessFile
        from apps.core.api.concurrency import etag_for_instance
        fixture = ModulePolicyTests(); fixture.setUp()
        sample = fixture.sample(fixture.actor, 'DELETE-STAGE')
        sample.status = 'METALWORK_PENDING'; sample.save()
        images = {}
        for stage in ('METALWORK', 'CUTTING'):
            file = BusinessFile.objects.create(uploaded_by_employee=fixture.actor,
                original_name=stage + '.png', storage_key='tests/' + stage + '.png', content_type='image/png',
                size_bytes=10, scan_status='SKIPPED')
            images[stage] = SampleParameterImage.objects.create(sample_request=sample,
                parameter_type=stage, business_file=file, uploaded_by_employee=fixture.actor, uploaded_at=timezone.now())
        self.scoped_actor()
        self.grant('access_control.metalwork_sample')
        url = f'/api/v1/sample-requests/{sample.pk}/parameter-images/'
        denied = self.client.delete(url + str(images['CUTTING'].pk) + '/', HTTP_IF_MATCH=etag_for_instance(sample))
        self.assertEqual(denied.status_code, 403, denied.data)
        allowed = self.client.delete(url + str(images['METALWORK'].pk) + '/', HTTP_IF_MATCH=etag_for_instance(sample))
        self.assertEqual(allowed.status_code, 200, allowed.data)
        images['CUTTING'].refresh_from_db(); images['METALWORK'].refresh_from_db()
        self.assertIsNone(images['CUTTING'].archived_at)
        self.assertIsNotNone(images['METALWORK'].archived_at)


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class RoleConfigurationTests(APITestCase):
    def test_preview_apply_reread_is_idempotent_and_keeps_pending_roles_empty(self):
        import json
        from io import StringIO
        from django.core.management import call_command
        from django.db import connection
        from apps.access_control.management.commands.initialize_access_roles import INITIAL_ROLES
        from apps.access_control.management.commands.configure_production_roles import role_plan
        from apps.access_control.models import RoleActionGrant
        from django.contrib.auth.models import Group
        from apps.organizations.models import Employee, RoleProfile
        admin = get_user_model().objects.create_superuser('admin')
        Employee.objects.create(user=admin, employee_code='U03-CONFIG', display_name='测试配置操作者')
        for code, name in INITIAL_ROLES:
            RoleProfile.objects.create(auth_group=Group.objects.create(name='U03-' + code), role_code=code, display_name=name)
        plan = role_plan()
        kwargs = {'apply': True, 'database_name': connection.settings_dict['NAME'], 'actor_username': 'admin',
            'expected_digest': plan['digest']}
        output = StringIO()
        call_command('configure_production_roles', stdout=output, **kwargs)
        result = json.loads(output.getvalue())
        self.assertTrue(result['applied'])
        self.assertTrue(all(not row['added'] for row in result['roles']))
        self.assertTrue(all(not row['after'] for row in result['roles'] if row['role_code'] in (
            'PMC', 'MERCHANDISER', 'OUTSOURCING', 'COATING_MATERIALS', 'SALESPERSON', 'ACCOUNT_MANAGER')))
        for row in result['roles']:
            if row['role_code'] in ('FINANCE', 'CASHIER'):
                self.assertEqual({grant['permission'] for grant in row['after']}, {f'finance.{action}_{resource}' for resource in ('financeaccount', 'accountingsubject') for action in ('view', 'add', 'change', 'delete')})
        count = RoleActionGrant.objects.count()
        kwargs['expected_digest'] = result['digest']
        call_command('configure_production_roles', stdout=StringIO(), **kwargs)
        self.assertEqual(RoleActionGrant.objects.count(), count)
