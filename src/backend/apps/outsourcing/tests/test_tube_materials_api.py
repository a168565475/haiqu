"""管材同单五金：独立加工厂、预留、整单发出与一次回货的隔离数据库验证。"""
import copy
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.boms.models import BomLine, BomSection
from apps.inventory.models import MaterialStockBalance, MaterialStockMovement, PublicStockMovement
from apps.inventory.stock_services import InventoryStockValidationError, credit_material_stock, debit_material_stock
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, OrderMaterialRequirement
from apps.material_issues.public_issue_services import public_issue_quantity_context, public_line_quantities
from apps.material_issues.services import pending_issue_quantities
from apps.organizations.models import Employee
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit
from ..models import OutsourcingFactory, OutsourcingFactoryCraft, TubeOutsourcingMaterial, TubeOutsourcingOrder
from . import test_tube_orders_api as order_tests
from .test_tube_receipts_api import TubeReceiptFixture


class TubeMaterialFixture(TubeReceiptFixture):
    @transaction.atomic
    def setUp(self):
        super().setUp()
        self.hardware_unit, _ = ProductionUnit.objects.get_or_create(
            unit_name='个', defaults={'unit_code': 'TUBE-HARDWARE-COUNT'})
        category, _ = ProductCategory.objects.get_or_create(
            category_name='五金', defaults={'item_type': 'MATERIAL'})
        self.hardware_raw = RawMaterialInformation.objects.create(
            material_number='TUBE-HARDWARE-RIVET', item_type='MATERIAL', category=category,
            material_name='同单铆钉', specification='M6', material='铁', unit=self.hardware_unit,
            color_snapshot='本色')
        section = BomSection.objects.create(
            bom=self.bom, line_number=2, section_type='ACCESSORY', title='五金件')
        self.hardware = BomLine.objects.create(
            section=section, line_number=1, part_name='同单铆钉', material='铁', specification='M6',
            unit='个', unit_consumption='8', total_consumption='800',
            raw_values={'source_inventory_material_id': str(self.hardware_raw.pk)})
        self.hardware_balance = credit_material_stock(
            raw_material=self.hardware_raw, unit=self.hardware_unit, zone=self.raw_zone, quantity=500,
            source_type='TEST_TUBE_HARDWARE_OPENING', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee).balance
        self.hardware_factory = OutsourcingFactory.objects.create(
            factory_number='TUBE-HARDWARE-FACTORY', name='五金独立加工厂', processing_type='喷塑',
            contact_name='测试', contact_phone='123', address='隔离环境',
            created_by_employee=self.employee, updated_by_employee=self.employee)
        OutsourcingFactoryCraft.objects.create(
            factory=self.hardware_factory, craft=self.spray, craft_name_snapshot=self.spray.name)

    def material_row(self, context=None):
        context = self.context() if context is None else context
        return next(row for row in context['material_rows'] if row['bom_line_id'] == str(self.hardware.pk))

    def hardware_payload(self, quantity='40', *, source='RAW_PIPE', zone=None):
        payload = self.order_payload(source)
        context = self.context(source)
        payload.update(material_source_revision=context['material_source_revision'], materials=[{
            'bom_line_id': str(self.hardware.pk), 'factory_id': str(self.hardware_factory.pk),
            'quantity': quantity, 'zone_id': str((zone or self.raw_zone).pk),
        }])
        return payload

    def material_snapshot(self):
        self.hardware_balance.refresh_from_db()
        return (self.hardware_balance.quantity, MaterialStockMovement.objects.count(),
                list(OrderMaterialRequirement.objects.filter(raw_material=self.hardware_raw)
                     .values_list('outsourcing_issued_quantity', flat=True)))


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeMaterialsApiTests(TubeMaterialFixture, APITestCase):
    def test_source_materials_keep_original_units_and_are_read_only(self):
        before = (TubeOutsourcingOrder.objects.count(), OrderMaterialRequirement.objects.count(),
                  MaterialStockMovement.objects.count(), AuditLog.objects.count())
        context = self.context()
        row = self.material_row(context)
        self.assertEqual(row['unit'], '个')
        self.assertEqual(Decimal(row['required_quantity']), 800)
        self.assertEqual(Decimal(row['max_quantity']), 500)
        self.assertFalse(row['blockers'])
        self.assertIn(str(self.raw_zone.pk), [zone['zone_id'] for zone in row['zones']])
        self.assertEqual(len(context['material_source_revision']), 64)
        self.assertEqual(before, (TubeOutsourcingOrder.objects.count(), OrderMaterialRequirement.objects.count(),
                                 MaterialStockMovement.objects.count(), AuditLog.objects.count()))

    def test_save_independent_factory_reserves_once_and_cancel_releases_without_debit(self):
        payload = self.hardware_payload()
        before_stock = self.hardware_balance.quantity
        before_movements = MaterialStockMovement.objects.count()
        order = self.post_order(payload).data['data']
        material = TubeOutsourcingMaterial.objects.get(order_id=order['id'])
        self.assertIsNone(material.order_line_id)
        self.assertEqual(material.factory_id, self.hardware_factory.pk)
        self.assertNotEqual(material.factory_id, material.order.lines.get().factory_id)
        self.assertEqual(order['materials'][0]['factory_id'], str(self.hardware_factory.pk))
        self.assertEqual((material.raw_material_id, material.unit_id, material.zone_id, material.quantity),
                         (self.hardware_raw.pk, self.hardware_unit.pk, self.raw_zone.pk, Decimal('40')))
        self.post_order(payload, 200)
        self.assertEqual(TubeOutsourcingMaterial.objects.count(), 1)
        reserved = self.material_row()
        self.assertEqual(Decimal(reserved['available_stock']), 460)
        self.assertEqual(Decimal(reserved['order_remaining']), 760)
        self.act(order, 'cancel')
        released = self.material_row()
        self.assertEqual(Decimal(released['available_stock']), 500)
        self.assertEqual(Decimal(released['order_remaining']), 800)
        self.hardware_balance.refresh_from_db()
        self.assertEqual(self.hardware_balance.quantity, before_stock)
        self.assertEqual(MaterialStockMovement.objects.count(), before_movements)
        self.assertEqual(TubeOutsourcingMaterial.objects.count(), 1)

    def test_material_must_use_current_hardware_bom_and_an_explicit_factory(self):
        payload = self.hardware_payload()
        payload['materials'][0]['bom_line_id'] = str(self.metal_bom_line.pk)
        self.post_order(payload, 400)
        for factory_id in [None, '', str(uuid.uuid4())]:
            with self.subTest(factory_id=factory_id):
                payload = self.hardware_payload()
                payload['materials'][0]['factory_id'] = factory_id
                self.post_order(payload, 400)
        payload = self.hardware_payload()
        payload['materials'][0].pop('factory_id')
        self.post_order(payload, 400)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())
        self.assertFalse(TubeOutsourcingMaterial.objects.exists())

    def test_invalid_quantity_and_forged_unit_or_component_are_rejected(self):
        for quantity in ['0', '', None, '-1', 'NaN', 'Infinity', True, '1.00001', '999999999999999']:
            with self.subTest(quantity=quantity):
                self.post_order(self.hardware_payload(quantity), 400)
        for field in ['unit', 'component_identity']:
            with self.subTest(field=field):
                payload = self.hardware_payload()
                payload['materials'][0][field] = '米' if field == 'unit' else str(uuid.uuid4())
                self.post_order(payload, 400)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())
        payload = self.hardware_payload('0.1250')
        self.post_order(payload)
        material = TubeOutsourcingMaterial.objects.get()
        self.assertEqual((material.quantity, material.unit.unit_name), (Decimal('0.1250'), '个'))

    def test_duplicate_factory_material_zone_and_missing_material_revision_are_rejected(self):
        payload = self.hardware_payload()
        payload['materials'].append(dict(payload['materials'][0]))
        self.post_order(payload, 400)
        payload = self.hardware_payload()
        payload.pop('material_source_revision')
        self.post_order(payload, 400)
        self.assertFalse(TubeOutsourcingMaterial.objects.exists())

    def test_same_hardware_may_be_sent_to_different_factories(self):
        payload = self.hardware_payload()
        second = dict(payload['materials'][0], factory_id=str(self.factory.pk), quantity='10')
        payload['materials'].append(second)
        order = self.post_order(payload).data['data']
        self.assertEqual(TubeOutsourcingMaterial.objects.filter(order_id=order['id']).count(), 2)
        self.assertEqual({row['factory_id'] for row in order['materials']},
                         {str(self.factory.pk), str(self.hardware_factory.pk)})
        self.assertEqual(Decimal(self.material_row()['available_stock']), 450)

    def test_inactive_or_wrong_craft_hardware_factory_is_rejected_at_save(self):
        payload = self.hardware_payload()
        self.hardware_factory.status = 'DISABLED'
        self.hardware_factory.save(update_fields=['status'])
        self.post_order(payload, 400)
        self.hardware_factory.status = 'ACTIVE'
        self.hardware_factory.save(update_fields=['status'])
        OutsourcingFactoryCraft.objects.filter(factory=self.hardware_factory).delete()
        self.post_order(payload, 400)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())

    def test_hardware_factory_is_rechecked_at_dispatch_and_cancel_still_releases(self):
        order = self.post_order(self.hardware_payload()).data['data']
        self.hardware_factory.status = 'DISABLED'
        self.hardware_factory.save(update_fields=['status'])
        before_material, before_tube = self.material_snapshot(), self.snapshot()
        self.act(order, expected=400)
        self.assertEqual(self.material_snapshot(), before_material)
        self.assertEqual(self.snapshot(), before_tube)
        self.act(order, 'cancel')
        self.assertEqual(Decimal(self.material_row()['available_stock']), 500)

    def test_material_factory_does_not_bypass_order_action_permissions(self):
        payload = self.hardware_payload()
        outsider = get_user_model().objects.create_user(username='tube-hardware-outsider')
        Employee.objects.create(user=outsider, employee_code='TUBE-HW-OUTSIDER', display_name='无操作权限')
        client = APIClient()
        client.force_authenticate(outsider)
        self.post_order(payload, 403, client=client)
        order = self.post_order(payload).data['data']
        before_material, before_tube = self.material_snapshot(), self.snapshot()
        self.act(order, expected=403, client=client)
        self.assertEqual(self.material_snapshot(), before_material)
        self.assertEqual(self.snapshot(), before_tube)

    def test_stock_is_checked_in_selected_zone_and_does_not_borrow_other_zone(self):
        other_zone = self.make_zone('HARDWARE-OTHER', 'MATERIAL')
        other_balance = credit_material_stock(
            raw_material=self.hardware_raw, unit=self.hardware_unit, zone=other_zone, quantity=10,
            source_type='TEST_TUBE_HARDWARE_OTHER', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee).balance
        self.post_order(self.hardware_payload('11', zone=other_zone), 409)
        order = self.post_order(self.hardware_payload('10', zone=other_zone)).data['data']
        self.act(order)
        other_balance.refresh_from_db()
        self.hardware_balance.refresh_from_db()
        self.assertEqual((other_balance.quantity, self.hardware_balance.quantity), (0, 500))

    def test_invalid_or_disabled_material_zone_cannot_be_reserved(self):
        self.post_order(self.hardware_payload(zone=self.semi_zone), 400)
        payload = self.hardware_payload()
        self.raw_zone.status = 'DISABLED'
        self.raw_zone.save(update_fields=['status'])
        self.post_order(payload, 400)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())

    def test_fresh_context_cannot_reserve_more_than_remaining_hardware_stock(self):
        self.post_order(self.hardware_payload('300'))
        row = self.material_row()
        self.assertEqual(Decimal(row['max_quantity']), 200)
        self.post_order(self.hardware_payload('201'), 409)
        self.assertEqual(TubeOutsourcingOrder.objects.count(), 1)

    def test_existing_stock_debit_cannot_take_pending_tube_hardware_reservation(self):
        self.post_order(self.hardware_payload('300'))
        before = self.material_snapshot()
        inputs = {'raw_material': self.hardware_raw, 'unit': self.hardware_unit, 'zone': self.raw_zone,
                  'source_type': 'TEST_OTHER_MATERIAL_ISSUE', 'source_id': uuid.uuid4(),
                  'source_line_id': uuid.uuid4(), 'actor_employee': self.employee, 'production_task': self.task}
        with self.assertRaises(InventoryStockValidationError):
            debit_material_stock(quantity=201, **inputs)
        self.assertEqual(self.material_snapshot(), before)
        debit_material_stock(quantity=200, **inputs)
        self.hardware_balance.refresh_from_db()
        self.assertEqual(self.hardware_balance.quantity, 300)
        self.assertEqual(Decimal(self.material_row()['available_stock']), 0)

    def test_existing_issue_quantity_context_counts_tube_hardware_reservation_once(self):
        self.post_order(self.hardware_payload('300'))
        material = TubeOutsourcingMaterial.objects.get()
        pending, _ = pending_issue_quantities(requirement_ids=[material.requirement_id])
        self.assertEqual(pending[material.requirement_id], 300)
        issue = MaterialIssue(production_task=self.task, stock_mode='PUBLIC_V2')
        line = MaterialIssueLine(issue=issue, requirement=material.requirement, raw_material=self.hardware_raw,
                                 unit=self.hardware_unit, requested_quantity=1, conversion_snapshot={'kind': 'OTHER'})
        context = public_issue_quantity_context(issue, lines=[line])
        quantities = public_line_quantities(line, context=context)
        self.assertEqual(Decimal(quantities['pending_issue_quantity']), 300)
        self.assertEqual(Decimal(quantities['public_pending_quantity']), 300)
        self.assertEqual(Decimal(quantities['order_remaining']), 500)
        self.assertEqual(Decimal(quantities['max_issue_quantity']), 200)

    def test_material_changes_participate_in_request_idempotency(self):
        payload = self.hardware_payload()
        self.post_order(payload)
        for field, value in [('quantity', '41'), ('factory_id', str(self.factory.pk))]:
            changed = copy.deepcopy(payload)
            changed['materials'][0][field] = value
            self.post_order(changed, 409)
        self.assertEqual(TubeOutsourcingMaterial.objects.get().quantity, 40)

    def test_changed_material_stock_requires_refresh_before_reserving(self):
        payload = self.hardware_payload()
        credit_material_stock(
            raw_material=self.hardware_raw, unit=self.hardware_unit, zone=self.raw_zone, quantity=1,
            source_type='TEST_TUBE_HARDWARE_REFRESH', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee)
        self.post_order(payload, 412)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())
        self.post_order(self.hardware_payload())

    def test_dispatch_rechecks_hardware_stock_and_preserves_whole_order_on_shortage(self):
        order = self.post_order(self.hardware_payload()).data['data']
        # 故障注入：保存后余额意外缩减，整单发出必须重新校验且不能先扣管材。
        MaterialStockBalance.objects.filter(pk=self.hardware_balance.pk).update(quantity=39)
        before_material, before_tube = self.material_snapshot(), self.snapshot()
        self.act(order, expected=409)
        self.assertEqual(self.material_snapshot(), before_material)
        self.assertEqual(self.snapshot(), before_tube)
        self.assertEqual(self.detail(order).data['data']['status'], 'PENDING_DISPATCH')

    def test_dispatch_debits_once_and_receipt_does_not_return_or_debit_hardware(self):
        order = self.post_order(self.hardware_payload()).data['data']
        dispatch_payload = self.action_payload()
        dispatched = self.act(order, payload=dispatch_payload).data['data']
        material = TubeOutsourcingMaterial.objects.get(order_id=order['id'])
        material.requirement.refresh_from_db()
        self.assertEqual(material.requirement.outsourcing_issued_quantity, 40)
        self.hardware_balance.refresh_from_db()
        self.assertEqual(self.hardware_balance.quantity, 460)
        movement = MaterialStockMovement.objects.get(source_id=order['id'], direction='OUT')
        self.assertEqual((movement.quantity, movement.balance.unit_id, movement.balance.zone_id),
                         (40, self.hardware_unit.pk, self.raw_zone.pk))
        self.assertEqual(movement.snapshot['factory_id'], str(self.hardware_factory.pk))
        self.assertEqual(dispatched['materials'][0]['factory_name'], self.hardware_factory.name)
        after_dispatch = self.material_snapshot()
        self.act(order, payload=dispatch_payload)
        self.assertEqual(self.material_snapshot(), after_dispatch)
        receipt_payload = self.receipt_payload(dispatched, '20', '')
        receipt = self.receive_final(dispatched, receipt_payload).data['data']
        self.assertEqual(len(receipt['lines']), 1)
        self.assertEqual(receipt['lines'][0]['order_line_id'], dispatched['lines'][0]['id'])
        self.assertEqual(self.material_snapshot(), after_dispatch)
        self.receive_final(dispatched, receipt_payload, expected=200)
        self.assertEqual(self.material_snapshot(), after_dispatch)

    def test_audit_failure_rolls_back_tube_and_hardware_debits_together(self):
        order = self.post_order(self.hardware_payload()).data['data']
        before_material, before_tube = self.material_snapshot(), self.snapshot()
        payload = self.action_payload()
        with patch('apps.outsourcing.tube_action_services.write_audit_log',
                   side_effect=RuntimeError('测试整单扣库后审计失败')):
            with self.assertRaises(RuntimeError):
                self.act(order, payload=payload)
        self.assertEqual(self.material_snapshot(), before_material)
        self.assertEqual(self.snapshot(), before_tube)
        self.assertEqual(self.detail(order).data['data']['status'], 'PENDING_DISPATCH')
        self.act(order, payload=payload)
        self.assertEqual(MaterialStockMovement.objects.filter(source_id=order['id'], direction='OUT').count(), 1)
        self.assertEqual(PublicStockMovement.objects.filter(source_id=order['id'], direction='OUT').count(), 1)

    def test_old_payload_without_materials_still_dispatches_and_receives(self):
        payload = self.order_payload()
        self.assertNotIn('materials', payload)
        before = self.material_snapshot()
        order = self.post_order(payload).data['data']
        dispatched = self.act(order).data['data']
        self.receive_final(dispatched, self.receipt_payload(dispatched, '20', ''))
        self.assertFalse(TubeOutsourcingMaterial.objects.exists())
        self.assertEqual(self.material_snapshot(), before)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeMaterialsConcurrencyTests(TubeMaterialFixture, TransactionTestCase):
    concurrent_posts = order_tests.TubeOrdersConcurrencyTests.concurrent_posts

    def test_concurrent_same_request_reserves_hardware_only_once(self):
        payload = self.hardware_payload('300')
        self.assertCountEqual(self.concurrent_posts([payload, copy.deepcopy(payload)]), [201, 200])
        self.assertEqual(TubeOutsourcingMaterial.objects.count(), 1)
        self.assertEqual(Decimal(self.material_row()['available_stock']), 200)

    def test_concurrent_requests_cannot_reserve_the_same_stock_version_twice(self):
        payload = self.hardware_payload('300')
        other = copy.deepcopy(payload)
        other['client_request_id'] = str(uuid.uuid4())
        self.assertCountEqual(self.concurrent_posts([payload, other]), [201, 412])
        self.assertEqual(TubeOutsourcingOrder.objects.count(), 1)
        self.assertEqual(TubeOutsourcingMaterial.objects.get().quantity, 300)
        self.assertEqual(Decimal(self.material_row()['available_stock']), 200)
