"""待入库原单删除：权限归属、并发版本、额度释放及历史保护。"""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client, SimpleTestCase, override_settings
from django.urls import Resolver404, resolve
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.wecom.models import NotificationEvent
from ..models import AssemblyReceiptSource, FinishedGoodsReceipt, InternalSemiFinishedReceipt, PublicStockMovement
from ..notification_events import current_inventory_object
from .test_assembly_receipts import AssemblyFixture
from .test_tube_d1_receipts import D1Fixture


class PendingReceiptDeleteRouteTests(SimpleTestCase):
    def test_pending_receipt_routes_support_delete(self):
        for prefix in ['semi-finished-receipts', 'assembly-finished-receipts']:
            with self.subTest(prefix=prefix):
                try:
                    match = resolve(f'/api/v1/{prefix}/{uuid.uuid4()}/')
                except Resolver404:
                    raise AssertionError(f'{prefix} 缺少原单 DELETE 路由') from None
                self.assertEqual(match.func.actions.get('delete'), 'destroy')


class DeletePermissionFixture:
    def assign_role(self, employee, code, *, expired=False):
        group, _ = Group.objects.get_or_create(name=f'pending-delete-{code}')
        role, _ = RoleProfile.objects.get_or_create(role_code=code,
            defaults={'display_name': code, 'auth_group': group})
        return EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
            effective_from=timezone.now() - timedelta(days=2),
            effective_to=timezone.now() - timedelta(days=1) if expired else None)

    def other_actor(self, code, *, expired=False, permissions=True):
        identifier = uuid.uuid4().hex[:12].upper()
        user = get_user_model().objects.create_user(username=f'delete-{identifier}')
        employee = Employee.objects.create(user=user, employee_code=f'DEL-{identifier}', display_name='删除边界测试')
        self.assign_role(employee, code, expired=expired)
        if permissions:
            user.user_permissions.set(Permission.objects.filter(content_type__app_label='inventory',
                codename__in=['delete_internalsemifinishedreceipt', 'delete_finishedgoodsreceipt',
                             'view_internalsemifinishedreceipt', 'view_finishedgoodsreceipt']))
        self.client.force_authenticate(user)
        return user

    def warehouse_with_template(self):
        from apps.access_control.models import RoleActionGrant
        from apps.access_control.production_role_templates import templates
        from apps.workshop_config.models import Workshop
        user = self.other_actor('WAREHOUSE_KEEPER', permissions=False)
        role = RoleProfile.objects.get(role_code='WAREHOUSE_KEEPER')
        workshops = {name: Workshop.objects.get_or_create(name=name)[0].pk
                     for name in ['金工车间', '装配车间', '车缝车间']}
        for row in templates(workshops)['WAREHOUSE_KEEPER']:
            app, code = row['permission'].split('.')
            permission = Permission.objects.get(content_type__app_label=app, codename=code)
            RoleActionGrant.objects.get_or_create(role=role, permission=permission, scope=row['scope'])
            role.auth_group.permissions.add(permission)
        user.groups.add(role.auth_group)
        self.assertFalse(user.has_perm('production_scheduling.view_productionschedule'))
        return user


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class InternalPendingDeletionTests(DeletePermissionFixture, D1Fixture, APITestCase):
    url = '/api/v1/semi-finished-receipts/'

    def setUp(self):
        super().setUp()
        self.assign_role(self.employee, 'METAL_DIRECTOR')
        self.user.is_superuser = False
        self.user.save(update_fields=['is_superuser'])
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label__in=[
            'inventory', 'production_tasks', 'production_scheduling']))
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)

    def pending(self):
        response = self.d1_post()
        receipt = InternalSemiFinishedReceipt.objects.get(pk=response.data['data']['receipt_id'])
        detail = self.client.get(f'{self.url}{receipt.pk}/')
        self.assertEqual(detail.status_code, 200, detail.data)
        return receipt, detail.data['data']

    def test_owner_delete_removes_lines_releases_quota_and_hides_notification(self):
        before = self.d1_preview()['lines'][0]['can_receive']
        receipt, data = self.pending()
        self.assertTrue(data['can_delete'])
        line_ids = list(receipt.lines.values_list('id', flat=True))
        event = NotificationEvent.objects.get(event_code='SEMI_FINISHED_RECEIPT_SUBMITTED', object_id=receipt.pk)
        response = self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag'])
        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(InternalSemiFinishedReceipt.objects.filter(pk=receipt.pk).exists())
        from ..models import InternalSemiFinishedReceiptLine
        self.assertFalse(InternalSemiFinishedReceiptLine.objects.filter(pk__in=line_ids).exists())
        self.assertFalse(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').exists())
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], before)
        self.assertIsNone(current_inventory_object(event.event_code, event.object_id, event.object_version))
        self.assertEqual(self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag']).status_code, 404)

    def test_deleted_request_cannot_recreate_pending_receipt(self):
        payload = self.d1_payload()
        preview = self.d1_preview()
        created = self.d1_post(payload, etag=preview['etag'])
        receipt_id = created.data['data']['receipt_id']
        detail = self.client.get(f'{self.url}{receipt_id}/').data['data']
        self.d1_post(payload, etag=preview['etag'], expected=200)
        self.other_actor('WAREHOUSE_KEEPER')
        deleted = self.client.delete(f'{self.url}{receipt_id}/', HTTP_IF_MATCH=detail['etag'])
        self.assertEqual(deleted.status_code, 204, deleted.data)
        self.client.force_authenticate(self.user)
        event_count = NotificationEvent.objects.count()
        replay = self.d1_post(payload, etag=preview['etag'], expected=409)
        self.assertEqual(replay.data['error']['code'], 'RECEIPT_REQUEST_DELETED')
        self.assertIn('已删除', replay.data['error']['message'])
        self.assertFalse(InternalSemiFinishedReceipt.objects.filter(request_id=payload['request_id']).exists())
        self.assertFalse(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').exists())
        self.assertEqual(NotificationEvent.objects.count(), event_count)
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], preview['lines'][0]['can_receive'])
        self.d1_post({**payload, 'request_id': str(uuid.uuid4())})

    def test_other_director_expired_manager_and_missing_permission_are_denied(self):
        receipt, data = self.pending()
        for code, expired, permissions in [('METAL_DIRECTOR', False, True),
                ('WAREHOUSE_KEEPER', True, True), ('WAREHOUSE_KEEPER', False, False)]:
            with self.subTest(code=code, expired=expired, permissions=permissions):
                self.other_actor(code, expired=expired, permissions=permissions)
                response = self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag'])
                self.assertEqual(response.status_code, 403, response.data)
                self.assertTrue(InternalSemiFinishedReceipt.objects.filter(pk=receipt.pk).exists())

    def test_warehouse_factory_and_general_manager_delete_without_plan_permission(self):
        for code in ['WAREHOUSE_KEEPER', 'FACTORY_MANAGER', 'GENERAL_MANAGER']:
            with self.subTest(role=code):
                self.client.force_authenticate(self.user)
                receipt, data = self.pending()
                self.other_actor(code)
                response = self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag'])
                self.assertEqual(response.status_code, 204, response.data)

    def test_missing_and_stale_etag_preserve_pending(self):
        receipt, data = self.pending()
        self.assertEqual(self.client.delete(f'{self.url}{receipt.pk}/').status_code, 428)
        self.assertEqual(self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH='"stale"').status_code, 412)
        self.assertTrue(InternalSemiFinishedReceipt.objects.filter(pk=receipt.pk).exists())

    def test_confirmed_receipt_cannot_be_deleted_by_admin(self):
        receipt, data = self.pending()
        confirm = self.client.post(f'{self.url}{receipt.pk}/confirm/', HTTP_IF_MATCH=data['etag'])
        self.assertEqual(confirm.status_code, 200, confirm.data)
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        self.client.force_authenticate(self.user)
        response = self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag'])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertTrue(InternalSemiFinishedReceipt.objects.filter(pk=receipt.pk).exists())
        rows = self.client.get(self.url).data['data']['items']
        self.assertTrue(rows)
        self.assertTrue(all(row['can_delete'] is False for row in rows))

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_warehouse_template_confirms_and_deletes_without_plan_view(self):
        # 先按原提交人准备原单，再切换到没有作业计划权限的真实仓管职责模板。
        with override_settings(MODULE_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False):
            first, data = self.pending()
        warehouse = self.warehouse_with_template()
        confirm = self.client.post(f'{self.url}{first.pk}/confirm/', HTTP_IF_MATCH=data['etag'])
        self.assertEqual(confirm.status_code, 200, confirm.data)
        self.client.force_authenticate(self.user)
        with override_settings(MODULE_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False):
            second, data = self.pending()
        self.client.force_authenticate(warehouse)
        response = self.client.delete(f'{self.url}{second.pk}/', HTTP_IF_MATCH=data['etag'])
        self.assertEqual(response.status_code, 204, response.data)


class AssemblyPendingDeletionTests(DeletePermissionFixture, AssemblyFixture, APITestCase):
    url = '/api/v1/assembly-finished-receipts/'

    def setUp(self):
        self.prepare()
        self.assign_role(self.employee, 'ASSEMBLY_DIRECTOR')

    def pending(self):
        response = self.post(self.payload(received_quantity=3))
        self.assertEqual(response.status_code, 201, response.data)
        receipt = FinishedGoodsReceipt.objects.get(pk=response.data['data']['id'])
        detail = self.client.get(f'/api/v1/finished-goods-records/{receipt.pk}/')
        self.assertEqual(detail.status_code, 200, detail.data)
        return receipt, detail.data['data']

    def test_owner_delete_removes_source_releases_quota_and_hides_notification(self):
        before = self.preview()['remaining_receivable']
        receipt, data = self.pending()
        self.assertTrue(data['can_delete'])
        event = NotificationEvent.objects.get(event_code='ASSEMBLY_FINISHED_RECEIPT_SUBMITTED', object_id=receipt.pk)
        response = self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag'])
        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(FinishedGoodsReceipt.objects.filter(pk=receipt.pk).exists())
        self.assertFalse(AssemblyReceiptSource.objects.filter(receipt_id=receipt.pk).exists())
        self.assertEqual(self.preview()['remaining_receivable'], before)
        self.assertIsNone(current_inventory_object(event.event_code, event.object_id, event.object_version))
        self.assertEqual(self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag']).status_code, 404)

    def test_deleted_request_cannot_recreate_pending_receipt(self):
        payload = self.payload(received_quantity=3)
        preview = self.preview()
        created = self.post(payload, etag=preview['etag'])
        self.assertEqual(created.status_code, 201, created.data)
        receipt_id = created.data['data']['id']
        detail = self.client.get(f'/api/v1/finished-goods-records/{receipt_id}/').data['data']
        self.assertEqual(self.post(payload, etag=preview['etag']).status_code, 200)
        self.other_actor('WAREHOUSE_KEEPER')
        deleted = self.client.delete(f'{self.url}{receipt_id}/', HTTP_IF_MATCH=detail['etag'])
        self.assertEqual(deleted.status_code, 204, deleted.data)
        self.client.force_authenticate(self.user)
        event_count = NotificationEvent.objects.count()
        replay = self.post(payload, etag=preview['etag'])
        self.assertEqual(replay.status_code, 409, replay.data)
        self.assertEqual(replay.data['error']['code'], 'RECEIPT_REQUEST_DELETED')
        self.assertIn('已删除', replay.data['error']['message'])
        self.assertFalse(AssemblyReceiptSource.objects.filter(request_id=payload['request_id']).exists())
        self.assertFalse(FinishedGoodsReceipt.objects.filter(production_task_product=self.line).exists())
        self.assertEqual(NotificationEvent.objects.count(), event_count)
        self.assertEqual(self.preview()['remaining_receivable'], preview['remaining_receivable'])
        replacement = self.post({**payload, 'request_id': str(uuid.uuid4())})
        self.assertEqual(replacement.status_code, 201, replacement.data)

    def test_other_director_expired_manager_and_missing_permission_are_denied(self):
        receipt, data = self.pending()
        for code, expired, permissions in [('ASSEMBLY_DIRECTOR', False, True),
                ('WAREHOUSE_KEEPER', True, True), ('WAREHOUSE_KEEPER', False, False)]:
            with self.subTest(code=code, expired=expired, permissions=permissions):
                self.other_actor(code, expired=expired, permissions=permissions)
                response = self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag'])
                self.assertEqual(response.status_code, 403, response.data)
                self.assertTrue(FinishedGoodsReceipt.objects.filter(pk=receipt.pk).exists())

    def test_warehouse_factory_and_general_manager_delete_without_plan_permission(self):
        for code in ['WAREHOUSE_KEEPER', 'FACTORY_MANAGER', 'GENERAL_MANAGER']:
            with self.subTest(role=code):
                self.client.force_authenticate(self.user)
                receipt, data = self.pending()
                self.other_actor(code)
                response = self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag'])
                self.assertEqual(response.status_code, 204, response.data)

    def test_missing_and_stale_etag_preserve_pending(self):
        receipt, data = self.pending()
        self.assertEqual(self.client.delete(f'{self.url}{receipt.pk}/').status_code, 428)
        self.assertEqual(self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH='"stale"').status_code, 412)
        self.assertTrue(FinishedGoodsReceipt.objects.filter(pk=receipt.pk).exists())

    def test_session_delete_requires_real_csrf_cookie_and_header(self):
        receipt, data = self.pending()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        csrf_response = client.get('/api/auth/me/')
        self.assertEqual(csrf_response.status_code, 200)
        self.assertIn('csrftoken', client.cookies)
        response = client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag'])
        self.assertEqual(response.status_code, 403)
        self.assertTrue(FinishedGoodsReceipt.objects.filter(pk=receipt.pk).exists())
        response = client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag'],
                                 HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(FinishedGoodsReceipt.objects.filter(pk=receipt.pk).exists())

    def test_confirmed_receipt_cannot_be_deleted_by_admin(self):
        receipt, data = self.pending()
        confirm = self.client.post(f'{self.url}{receipt.pk}/confirm/')
        self.assertEqual(confirm.status_code, 200, confirm.data)
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        self.client.force_authenticate(self.user)
        response = self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=data['etag'])
        self.assertEqual(response.status_code, 409, response.data)
        detail = self.client.get(f'/api/v1/finished-goods-records/{receipt.pk}/')
        self.assertFalse(detail.data['data']['can_delete'])
        receipt.refresh_from_db()
        self.assertEqual(receipt.remaining_quantity, 3)

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_warehouse_template_confirms_and_deletes_without_plan_view(self):
        with override_settings(MODULE_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False):
            first, data = self.pending()
        warehouse = self.warehouse_with_template()
        confirm = self.client.post(f'{self.url}{first.pk}/confirm/')
        self.assertEqual(confirm.status_code, 200, confirm.data)
        self.client.force_authenticate(self.user)
        with override_settings(MODULE_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False):
            second, data = self.pending()
        self.client.force_authenticate(warehouse)
        response = self.client.delete(f'{self.url}{second.pk}/', HTTP_IF_MATCH=data['etag'])
        self.assertEqual(response.status_code, 204, response.data)
