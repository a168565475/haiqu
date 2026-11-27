from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.access_control.selectors import effective_access
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.workshop_config.models import Craft, Workshop

from ..models import InternalSemiFinishedReceipt, PublicStockBalance, PublicStockMovement
from .test_assembly_receipts import AssemblyFixture


@override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class WorkshopReceiptRecordTests(AssemblyFixture, APITestCase):
    def setUp(self):
        self.prepare()
        self.sewing, _ = Workshop.objects.get_or_create(name='车缝车间')
        self.metal, _ = Workshop.objects.get_or_create(name='金工车间')

    def sign_in_reader(self, workshop, *codenames):
        key = uuid4().hex[:10].upper()
        user = get_user_model().objects.create_user(username=f'receipt-reader-{key}')
        employee = Employee.objects.create(user=user, employee_code=f'REC-{key}', display_name='入库只读测试')
        group = Group.objects.create(name=f'receipt-reader-{key}')
        role = RoleProfile.objects.create(role_code=f'REC_{key}', display_name='入库只读测试', auth_group=group)
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
                                              effective_from=timezone.now() - timedelta(days=1))
        scope = 'WORKSHOP' if workshop else 'MODULE'
        for codename in codenames:
            permission = Permission.objects.get(content_type__app_label='inventory', codename=codename)
            grant = RoleActionGrant.objects.create(role=role, permission=permission, scope=scope)
            if workshop:
                RoleGrantResource.objects.create(grant=grant, workshop=workshop)
            group.permissions.add(permission)
        access = effective_access(user)
        self.assertEqual(access['legacy_sources'], [])
        for codename in codenames:
            self.assertEqual(access['actions'][f'inventory.{codename}']['scopes'], [scope])
        self.client.force_authenticate(user)

    def add_stage(self, workshop, category):
        craft = Craft.objects.create(workshop=workshop, craft_type='INTERNAL', plan_category=category,
                                     name=f'测试{category}入库工艺', status='ACTIVE')
        ProductionScheduleProductCraft.objects.create(
            schedule_product=self.plan, craft=craft, craft_type_snapshot='INTERNAL',
            craft_name_snapshot=craft.name, plan_category=category,
        )
        return craft

    def test_semi_records_scope_applies_to_pending_confirmed_and_direct_details(self):
        url = '/api/v1/semi-finished-receipts/'
        cutting = self.add_stage(self.sewing, 'CUTTING')
        sewing = self.add_stage(self.sewing, 'SEWING')
        metal = self.add_stage(self.metal, 'METAL')
        own, own_confirmed, other = [
            InternalSemiFinishedReceipt.objects.create(
                receipt_number=f'TEST-{craft.plan_category}', request_id=uuid4(), request_payload_hash='test',
                schedule_product=self.plan, completed_craft=craft, plan_category=craft.plan_category,
                receipt_date=timezone.localdate(), status='CONFIRMED' if craft == sewing else 'PENDING',
                zone_id=self.zone_id if craft == sewing else None, actor_employee=self.employee,
                submitted_by_employee=self.employee, source_revision_hash='test', source_snapshot={},
            )
            for craft in (cutting, sewing, metal)
        ]
        stock = PublicStockBalance.objects.create(
            stock_kind='SEMI', identity_key='workshop-receipt-test', identity_snapshot={},
            unit=self.line.unit, zone_id=self.zone_id, quantity=2,
        )
        PublicStockMovement.objects.create(
            balance=stock, stock_kind_snapshot='SEMI', direction='IN', quantity=2, before_quantity=0, after_quantity=2,
            source_type='INTERNAL_SEMI_RECEIPT', source_id=own_confirmed.pk, source_line_id=uuid4(),
            production_task=self.task, product_line=self.line, actor_employee=self.employee,
            snapshot={'receipt_number': own_confirmed.receipt_number},
        )

        self.sign_in_reader(self.sewing, 'view_internalsemifinishedreceipt')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertSetEqual({row['id'] for row in response.data['data']['items']}, {str(own.pk), str(own_confirmed.pk)})
        self.assertEqual(self.client.get(f'{url}{own_confirmed.pk}/').status_code, 200)
        self.assertEqual(self.client.get(f'{url}{other.pk}/').status_code, 404)
        self.assertEqual(self.client.post(f'{url}{own.pk}/confirm/', {}, format='json').status_code, 403)

        self.sign_in_reader(None, 'view_internalsemifinishedreceipt')
        warehouse_response = self.client.get(url)
        self.assertEqual(warehouse_response.status_code, 200, warehouse_response.data)
        self.assertEqual(warehouse_response.data['data']['total'], 3)

    def test_finished_records_follow_assembly_source_and_do_not_open_warehouse_stock(self):
        self.add_stage(self.sewing, 'SEWING')
        created = self.post(self.payload(received_quantity=3))
        self.assertEqual(created.status_code, 201, created.data)
        receipt_id = created.data['data']['id']
        url = '/api/v1/finished-goods-records/'

        self.sign_in_reader(self.craft.workshop, 'view_finishedgoodsreceipt')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row['id'] for row in response.data['data']['items']], [receipt_id])
        self.assertEqual(self.client.get('/api/v1/finished-goods-inventory/').status_code, 403)
        self.assertEqual(self.client.post(f'/api/v1/assembly-finished-receipts/{receipt_id}/confirm/', {},
                                          format='json').status_code, 403)

        self.sign_in_reader(self.sewing, 'view_finishedgoodsreceipt')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['items'], [])
        self.assertEqual(self.client.get(f'{url}{receipt_id}/').status_code, 404)

        self.sign_in_reader(None, 'view_finishedgoodsreceipt')
        self.assertEqual(self.client.get(f'{url}{receipt_id}/').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/finished-goods-inventory/').status_code, 200)
