from types import SimpleNamespace
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from django.http import Http404
from rest_framework.test import APITestCase
from rest_framework.exceptions import PermissionDenied

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.access_control.resource_scopes import resource_ids, require_craft, require_workshop
from apps.access_control.selectors import effective_access
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.workshop_config.models import Workshop, Craft


class ScopedActorMixin:
    def scoped_actor(self):
        self.scope_user = get_user_model().objects.create_user('scope-worker')
        self.scope_employee = Employee.objects.create(user=self.scope_user, employee_code='SCOPE-WORKER', display_name='范围员工')
        self.client.force_authenticate(self.scope_user)

    def grant(self, code, scope='MODULE', resources=()):
        app, codename = code.split('.')
        permission = Permission.objects.get(content_type__app_label=app, codename=codename)
        key = "SCOPE_" + uuid4().hex.upper()
        group = Group.objects.create(name=key)
        group.permissions.add(permission)
        role = RoleProfile.objects.create(auth_group=group, role_code=key, display_name='任意角色名称')
        EmployeeRoleAssignment.objects.create(employee=self.scope_employee, role_profile=role, effective_from=timezone.now())
        grant = RoleActionGrant.objects.create(role=role, permission=permission, scope=scope)
        for resource in resources:
            RoleGrantResource.objects.create(grant=grant, **{'workshop' if scope == 'WORKSHOP' else 'craft': resource})
        self.client.force_authenticate(get_user_model().objects.get(pk=self.scope_user.pk))
        return grant

    def scoped_request(self):
        return SimpleNamespace(user=get_user_model().objects.get(pk=self.scope_user.pk), employee=self.scope_employee, META={}, headers={}, method='GET')


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class ResourceScopeTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        self.scoped_actor()
        self.metal = Workshop.objects.get_or_create(name='金工车间')[0]
        self.sewing = Workshop.objects.get_or_create(name='车缝车间')[0]
        self.spray = Craft.objects.create(name='范围喷塑', craft_type='EXTERNAL', outsourcing_code='POWDER_COATING')
        self.cutting = Craft.objects.create(name='范围裁剪', craft_type='EXTERNAL', outsourcing_code='CUTTING')

    def test_read_all_never_expands_edit_and_same_operation_roles_union(self):
        self.grant('workshop_reporting.view_workreport')
        self.grant('workshop_reporting.change_workreport', 'WORKSHOP', [self.metal])
        self.assertIsNone(resource_ids(self.scoped_request(), 'workshop_reporting.view_workreport', 'WORKSHOP'))
        require_workshop(self.scoped_request(), 'workshop_reporting.change_workreport', self.metal.pk)
        with self.assertRaises(PermissionDenied):
            require_workshop(self.scoped_request(), 'workshop_reporting.change_workreport', self.sewing.pk)
        self.grant('workshop_reporting.change_workreport', 'WORKSHOP', [self.sewing])
        require_workshop(self.scoped_request(), 'workshop_reporting.change_workreport', self.sewing.pk)

    def test_empty_resources_are_denied_and_legacy_direct_grant_is_retained(self):
        grant = self.grant('outsourcing.add_outsourcingorder', 'CRAFT')
        with self.assertRaises(PermissionDenied):
            require_craft(self.scoped_request(), 'outsourcing.add_outsourcingorder', self.spray.pk)
        self.scope_user.user_permissions.add(grant.permission)
        require_craft(self.scoped_request(), 'outsourcing.add_outsourcingorder', self.spray.pk)

    def test_selection_uses_actual_craft_id(self):
        second = self.cutting
        self.grant('outsourcing.add_outsourcingorder', 'CRAFT', [self.spray])
        with self.assertRaises(PermissionDenied):
            require_craft(self.scoped_request(), 'outsourcing.add_outsourcingorder', second.pk)

    def test_management_persists_copies_audits_and_replaces_resource_selection(self):
        admin = get_user_model().objects.create_superuser('admin')
        Employee.objects.create(user=admin, employee_code='SCOPE-ADMIN', display_name='管理员')
        self.client.force_authenticate(admin)
        role = self.client.post('/api/v1/access/roles/', {'role_code': 'SCOPED', 'display_name': '可选范围'}, format='json')
        self.assertEqual(role.status_code, 201, role.data)
        url = f"/api/v1/access/roles/{role.data['id']}/grants/"
        rows = [{'permission': 'workshop_reporting.change_workreport', 'scope': 'WORKSHOP', 'resource_ids': [str(self.metal.pk)]}]
        saved = self.client.put(url, {'grants': rows}, format='json', HTTP_IF_MATCH=role['ETag'])
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data['grants'], rows)
        copied = self.client.post(f"/api/v1/access/roles/{role.data['id']}/copy/", {'role_code': 'COPIED', 'display_name': '复制'}, format='json', HTTP_IF_MATCH=saved['ETag'])
        self.assertEqual(copied.status_code, 201, copied.data)
        self.assertEqual(copied.data['grants'], rows)
        profile = RoleProfile.objects.get(pk=role.data['id'])
        EmployeeRoleAssignment.objects.create(employee=self.scope_employee, role_profile=profile, effective_from=timezone.now())
        before = effective_access(self.scope_user)
        self.assertEqual(before['actions'][rows[0]['permission']]['sources'][0]['resource_ids'], [str(self.metal.pk)])
        rows[0]['resource_ids'] = []
        empty = self.client.put(url, {'grants': rows}, format='json', HTTP_IF_MATCH=saved['ETag'])
        self.assertEqual(empty.status_code, 200, empty.data)
        self.assertEqual(resource_ids(self.scoped_request(), rows[0]['permission'], 'WORKSHOP'), set())
        from apps.audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(object_id=profile.pk, after_data__icontains=str(self.metal.pk)).exists())

    def test_management_rejects_wrong_kind_and_unknown_or_duplicate_resources(self):
        from apps.access_control.resource_scopes import validate_resources
        from rest_framework.exceptions import ValidationError
        for code, scope, ids in [
            ('access_control.manage_access', 'WORKSHOP', [self.metal.pk]),
            ('workshop_reporting.view_workreport', 'WORKSHOP', [uuid4()]),
            ('outsourcing.add_outsourcingorder', 'CRAFT', [self.spray.pk, self.spray.pk]),
            ('outsourcing.add_outsourcingorder', 'MODULE', [self.spray.pk]),
            ('material_issues.register_metalprocessingcompletion', 'CRAFT', [self.spray.pk]),
        ]:
            with self.subTest(code=code, scope=scope, ids=ids), self.assertRaises(ValidationError):
                validate_resources([{'permission': code, 'scope': scope, 'resource_ids': ids}])

    def test_flag_off_never_queries_new_resource_table(self):
        self.grant('outsourcing.add_outsourcingorder', 'MODULE')
        with override_settings(ACCESS_RESOURCE_SCOPES_ENABLED=False):
            from django.test.utils import CaptureQueriesContext
            from django.db import connection
            with CaptureQueriesContext(connection) as queries:
                effective_access(self.scope_user)
            self.assertFalse(any('role_grant_resource' in q['sql'] for q in queries))


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class WorkshopResourceApiTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        from apps.workshop_reporting.tests.test_workshop_reporting_api import WorkshopReportingApiTests
        self.fixture = WorkshopReportingApiTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        created = self.client.post('/api/v1/workshop-reporting/wage-schemes/', self.fixture.scheme_payload(), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.created = created
        self.url = f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/"
        self.scoped_actor()

    def test_read_all_and_edit_other_workshop_cannot_modify_metal(self):
        sewing = Workshop.objects.get_or_create(name='车缝车间')[0]
        self.grant('workshop_reporting.view_wagescheme')
        self.grant('workshop_reporting.change_wagescheme', 'WORKSHOP', [sewing])
        self.assertEqual(self.client.get(self.url).status_code, 200)
        response = self.client.patch(self.url, {'remark': '禁止修改'}, format='json', HTTP_IF_MATCH=self.created['ETag'])
        self.assertEqual(response.status_code, 404, response.data)

    def test_context_only_grants_local_summary_without_production_api(self):
        self.grant('workshop_reporting.view_wagescheme', 'WORKSHOP', [self.fixture.workshop])
        response = self.client.get('/api/v1/workshop-reporting/context/', {'schedule_product_id': str(self.fixture.schedule_product.pk)})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['schedule_product']['id'], str(self.fixture.schedule_product.pk))
        self.assertEqual(self.client.get('/api/v1/production-tasks/').status_code, 403)


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class SampleStageResourceTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        from apps.access_control.tests.test_module_policy import ModulePolicyTests
        self.fixture = ModulePolicyTests()
        self.fixture.setUp()
        self.sample = self.fixture.sample(self.fixture.actor, 'STAGE')
        from apps.samples.models import SampleItem, SampleWorkflowRecord
        self.sample.status = 'METALWORK_PENDING'
        self.sample.application_payload_hash = 'a' * 64
        self.sample.save()
        self.item = SampleItem.objects.create(sample_request=self.sample, line_number=1,
            product_description_snapshot='样品', requested_quantity=3, unit_code='PCS', sample_quantity=3)
        SampleWorkflowRecord.objects.create(sample_request=self.sample, stage='MATERIALS_READY', operated_by_employee=self.fixture.actor, operated_at=timezone.now())
        self.scoped_actor()
        self.grant('samples.view_samplerequest')
        self.grant('access_control.metalreport_sample')

    def test_metal_can_report_without_touching_cutting_and_cannot_submit_cutting(self):
        url = f'/api/v1/sample-requests/{self.sample.pk}/production-report/'
        payload = {'items': [{'id': str(self.item.pk), 'metalwork_reported_quantity': 2}]}
        response = self.client.post(url, payload, format='json', HTTP_IF_MATCH=etag_for_instance(self.sample))
        self.assertEqual(response.status_code, 200, response.data)
        self.item.refresh_from_db()
        self.assertEqual((self.item.metalwork_reported_quantity, self.item.cutting_reported_quantity), (2, 0))
        self.sample.refresh_from_db()
        payload['items'][0]['cutting_reported_quantity'] = 1
        denied = self.client.post(url, payload, format='json', HTTP_IF_MATCH=etag_for_instance(self.sample))
        self.assertEqual(denied.status_code, 403, denied.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.cutting_reported_quantity, 0)

    def test_form_item_guard_cannot_bypass_stage_permission(self):
        from apps.access_control.module_policy import require_sample_reporting_changes
        with self.assertRaises(PermissionDenied):
            require_sample_reporting_changes(self.scoped_request(), self.sample,
                [{'id': str(self.item.pk), 'cutting_completed': True}])


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class CraftResourceApiTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        from apps.material_issues.tests.test_metal_processing_p4 import MetalProcessingP4ApiTests
        self.fixture = MetalProcessingP4ApiTests()
        # Reuse historical business fixtures, then enable the new policy for every assertion.
        # 手动调用夹具setUp不会触发其测试类的TUBE开关装饰器。
        with override_settings(MODULE_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False, TUBE_OUTSOURCING_ENABLED=False):
            self.fixture.setUp()
            self.order = self.fixture.create_order()
        self.client = self.fixture.client
        self.scoped_actor()
        self.spray = self.fixture.f.spray
        self.other = Craft.objects.get_or_create(outsourcing_code='SCREEN_PRINTING', defaults={'name': '未授权丝印', 'craft_type': 'EXTERNAL'})[0]

    def test_stock_source_cannot_read_or_dispatch_regular_metal_handoff(self):
        from apps.outsourcing.models import OutsourcingOrder
        from apps.access_control.resource_scopes import can_order
        self.grant('outsourcing.view_outsourcingorder', 'STOCK')
        self.grant('outsourcing.confirm_dispatch_outsourcingorder', 'STOCK')
        url = f'/api/v1/outsourcing-orders/{self.fixture.original_order}/'
        self.assertEqual(self.client.get(url).status_code, 404)
        order = OutsourcingOrder.objects.get(pk=self.fixture.original_order)
        self.assertFalse(can_order(self.scoped_request(), 'outsourcing.confirm_dispatch_outsourcingorder', order))
        metal = Workshop.objects.get(name='金工车间')
        self.grant('outsourcing.view_outsourcingorder', 'WORKSHOP', [metal])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_selected_craft_reads_regular_unified_and_p4_without_independent_production(self):
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [self.spray])
        self.grant('material_issues.view_metalprocessingsource', 'CRAFT', [self.spray])
        for url in [f'/api/v1/outsourcing-orders/{self.fixture.original_order}/',
                    f'/api/v1/metal-processing-external-orders/{self.order.pk}/',
                    f'/api/v1/metal-processing-sources/{self.fixture.line.pk}/']:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, (url, response.data))
        self.assertEqual(self.client.get('/api/v1/production-tasks/').status_code, 403)
        from apps.outsourcing.unified_selectors import unified_order_candidates
        ids = {row['id'] for row in unified_order_candidates(self.scoped_request(), {})}
        self.assertIn(self.order.pk, ids)
        self.order.craft = self.other
        self.order.save(update_fields=['craft'])
        ids = {row['id'] for row in unified_order_candidates(self.scoped_request(), {})}
        self.assertNotIn(self.order.pk, ids)
        self.assertIn(__import__('uuid').UUID(self.fixture.original_order), ids)

    def test_empty_source_scope_denies_list_detail_closure_and_linked_ids(self):
        self.grant('material_issues.view_metalprocessingsource', 'CRAFT')
        listing = self.client.get('/api/v1/metal-processing-sources/')
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(listing.data['data'], [])
        for tail in ['', 'closure-preview/']:
            response = self.client.get(f'/api/v1/metal-processing-sources/{self.fixture.line.pk}/{tail}')
            self.assertEqual(response.status_code, 404, response.data)
        response = self.client.get(f'/api/v1/metal-processing-external-orders/{self.order.pk}/')
        self.assertEqual(response.status_code, 404, response.data)

    def test_read_all_does_not_expand_write_or_idempotent_replay(self):
        self.grant('material_issues.view_metalprocessingsource')
        self.grant('outsourcing.view_outsourcingorder')
        self.grant('material_issues.create_metalprocessingexternalorder', 'CRAFT', [self.other])
        from apps.material_issues.p4_services import create_external_order
        with self.assertRaises((PermissionDenied, Http404)):
            create_external_order(request=self.scoped_request(), rework_id=self.order.rework_id,
                request_id=self.order.client_request_id, factory_id=self.order.factory_id,
                craft_id=self.order.craft_id, allocated_pieces=self.order.allocated_pieces)
        self.grant('outsourcing.cancel_outsourcingorder', 'CRAFT', [self.other])
        response = self.client.post(f'/api/v1/outsourcing-orders/{self.fixture.original_order}/cancel/',
            {'reason': '不可跨工艺'}, format='json')
        self.assertEqual(response.status_code, 404, response.data)

    def test_regular_source_options_and_nested_factory_crafts_are_filtered(self):
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [self.spray])
        response = self.client.get('/api/v1/outsourcing-orders/options/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({row['id'] for row in response.data['data']['crafts']}, {str(self.spray.pk)})
        for factory in response.data['data']['factories']:
            self.assertTrue({row['id'] for row in factory['crafts']} <= {str(self.spray.pk)})
        retired = self.client.get('/api/v1/outsourcing-orders/source-plans/', {'craft_id': str(self.other.pk)})
        self.assertEqual(retired.status_code, 404)

    def test_legacy_plus_empty_craft_does_not_remove_original_task_boundary(self):
        grant = self.grant('outsourcing.view_outsourcingorder', 'CRAFT')
        self.scope_user.user_permissions.add(grant.permission)
        from apps.outsourcing.selectors import accessible_outsourcing_orders
        self.assertFalse(accessible_outsourcing_orders(self.scoped_request()).exists())

    def test_shared_source_cannot_combine_legacy_access_with_new_craft(self):
        grant = self.grant('material_issues.view_metalprocessingsource', 'CRAFT', [self.spray])
        self.scope_user.user_permissions.add(grant.permission)
        self.order.craft = self.other
        self.order.save(update_fields=['craft'])
        self.client.force_authenticate(get_user_model().objects.get(pk=self.scope_user.pk))
        denied = self.client.get(f'/api/v1/metal-processing-external-orders/{self.order.pk}/')
        self.assertEqual(denied.status_code, 404, denied.data)
        response = self.client.get(f'/api/v1/metal-processing-sources/{self.fixture.line.pk}/')
        self.assertEqual(response.status_code, 200, response.data)
        reworks = response.data['data']['original_handoffs'][0]['unsprayed_returns'][0]['reworks']
        self.assertNotIn(str(self.order.pk), reworks[0]['external_order_ids'])

    def test_shared_source_selector_cannot_unlock_other_craft_on_same_schedule(self):
        grant = self.grant('outsourcing.add_outsourcingorder', 'CRAFT', [self.spray])
        self.scope_user.user_permissions.add(grant.permission)
        from apps.outsourcing.selectors import outsourcing_source_schedules
        self.assertTrue(outsourcing_source_schedules(self.scoped_request(),
            'outsourcing.add_outsourcingorder', self.spray.pk).filter(pk=self.order.source.issue_line.issue.product_line.schedule_products.first().schedule_id).exists())
        self.assertFalse(outsourcing_source_schedules(self.scoped_request(),
            'outsourcing.add_outsourcingorder', self.other.pk).exists())

    def test_new_source_scope_does_not_lend_legacy_create_permission_to_other_destination(self):
        grant = self.grant('material_issues.create_metalprocessingexternalorder', 'CRAFT', [self.spray])
        self.scope_user.user_permissions.add(grant.permission)
        from apps.material_issues.p4_services import create_external_order
        with self.assertRaises(PermissionDenied):
            create_external_order(request=self.scoped_request(), rework_id=self.order.rework_id,
                request_id=uuid4(), factory_id=self.order.factory_id,
                craft_id=self.other.pk, allocated_pieces=1)

    def test_source_read_craft_cannot_expand_legacy_completion_or_closure(self):
        self.grant('material_issues.view_metalprocessingsource', 'CRAFT', [self.spray])
        from apps.material_issues.processing_services import record_processing
        for operation, code, action, data in [
            ('completion', 'register_metalprocessingcompletion', 'completions', {'good_pieces': 1, 'completion_date': str(timezone.localdate())}),
            ('close', 'close_metalprocessingsource', 'close', {'remark': '不可借查看范围写入'}),
        ]:
            permission = Permission.objects.get(content_type__app_label='material_issues', codename=code)
            self.scope_user.user_permissions.add(permission)
            self.client.force_authenticate(get_user_model().objects.get(pk=self.scope_user.pk))
            data['request_id'] = str(uuid4())
            with self.subTest(operation=operation):
                response = self.client.post(f'/api/v1/metal-processing-sources/{self.fixture.line.pk}/{action}/', data, format='json')
                self.assertEqual(response.status_code, 404, response.data)
                with self.assertRaises(Http404):
                    record_processing(request=self.scoped_request(), issue_line_id=self.fixture.line.pk, data=data, operation=operation)
