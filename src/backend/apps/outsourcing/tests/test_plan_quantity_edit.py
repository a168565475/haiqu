"""总单计划数量的参数与服务边界；下游用模拟依赖隔离，不访问数据库。"""
from contextlib import ExitStack
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import resolve, reverse
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired
from apps.outsourcing.api.tube_serializers import TubePlanQuantityWriteSerializer
from apps.outsourcing.api.tube_views import TubeOutsourcingOrderViewSet
from apps.outsourcing.plan_services import update_plan_quantity


class PlanQuantityEditTests(SimpleTestCase):
    def setUp(self):
        self.lines = [SimpleNamespace(pk=uuid4(), quantity=100, unit_price=Decimal('1.25'),
            factory_id=uuid4(), snapshot={'part_name': '部件'}, save=Mock()) for _ in range(2)]
        manager = Mock()
        manager.all.return_value = self.lines
        manager.select_for_update.return_value.order_by.return_value = self.lines
        self.order = SimpleNamespace(pk=uuid4(), source_kind='METAL', lines=manager, version=3,
            schedule_product=SimpleNamespace(schedule_id=uuid4()), save=Mock())
        self.request = SimpleNamespace(employee=object())
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.lock = self.stack.enter_context(patch('apps.outsourcing.plan_services._lock_plan', return_value=self.order))
        self.quantities = self.stack.enter_context(patch('apps.outsourcing.plan_services.plan_quantities', return_value={
            str(self.order.pk): {'lines': {str(line.pk): {'dispatched_quantity': '80'} for line in self.lines}}}))
        self.references = {str(line.pk): {'quantity': '240.0000', 'conversion_note': ''} for line in self.lines}
        self.purchases = self.stack.enter_context(patch('apps.outsourcing.plan_selectors.plan_purchase_references', return_value=self.references))
        self.audit = self.stack.enter_context(patch('apps.outsourcing.plan_services.write_audit_log'))

    def payload(self, first=120, second=100):
        return {'lines': [{'order_line_id': line.pk, 'quantity': quantity}
                          for line, quantity in zip(self.lines, [first, second])]}

    def submit(self, data):
        return update_plan_quantity.__wrapped__(order_id=self.order.pk, data=data, request=self.request)

    def test_only_original_line_identifier_and_positive_integer_quantity_are_accepted(self):
        self.assertTrue(TubePlanQuantityWriteSerializer(data=self.payload()).is_valid())
        invalid = [self.payload(value) for value in [0, -1, '1.5', True, None, '']]
        invalid += [{**self.payload(), 'remark': '不能更改'}, {'lines': []},
                    {'lines': [self.payload()['lines'][0]] * 2},
                    {'lines': [{**self.payload()['lines'][0], 'unit_price': '2'}]}]
        for data in invalid:
            with self.subTest(data=data):
                self.assertFalse(TubePlanQuantityWriteSerializer(data=data).is_valid())

    def test_tube_and_cutting_update_only_quantity_and_version_without_purchase_limit(self):
        for kind in ['METAL', 'SEWING']:
            with self.subTest(kind=kind):
                self.order.source_kind = kind
                self.lines[0].quantity = 100
                self.submit(self.payload(240))
                self.assertEqual(self.lines[0].quantity, 240)
                self.assertEqual(self.lines[0].unit_price, Decimal('1.25'))
                self.lines[0].save.assert_called_with(update_fields=['quantity', 'updated_at'])
                self.order.save.assert_called_with(update_fields=['version', 'updated_by_employee', 'updated_at'])
                self.lock.assert_called_with(self.order.pk, self.request, 'outsourcing.change_outsourcingorder')
                self.assertEqual(self.audit.call_args.kwargs['action'], 'PLAN_QUANTITY_UPDATED')
        self.assertEqual(self.order.version, 5)
        self.lines[1].save.assert_not_called()
        self.purchases.assert_not_called()

    def test_changed_quantity_below_dispatched_or_non_positive_is_rejected(self):
        for quantity in [79, 0, -1]:
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValidationError):
                    self.submit(self.payload(quantity))
                self.lines[0].save.assert_not_called()
                self.order.save.assert_not_called()
                self.audit.assert_not_called()
        self.assertEqual(self.lines[0].quantity, 100)

    def test_all_rows_are_validated_before_any_quantity_is_saved(self):
        with self.assertRaises(ValidationError):
            self.submit(self.payload(120, 79))
        self.assertEqual([line.quantity for line in self.lines], [100, 100])
        for line in self.lines:
            line.save.assert_not_called()
        self.audit.assert_not_called()

    def test_unknown_zero_and_less_than_demand_purchase_do_not_block_editing(self):
        for reference in [None, '0', '239.0000']:
            with self.subTest(reference=reference):
                self.lines[0].quantity = 100
                self.references[str(self.lines[0].pk)]['quantity'] = reference
                self.submit(self.payload(240))
                self.assertEqual(self.lines[0].quantity, 240)
                self.purchases.assert_not_called()
        self.lines[1].save.assert_not_called()
        self.assertEqual(self.lines[1].quantity, 100)
        self.assertEqual(len(self.audit.call_args.kwargs['after_data']['lines']), 1)

    def test_no_change_is_a_noop_and_original_line_set_is_required(self):
        self.submit(self.payload(100))
        self.purchases.assert_not_called()
        self.order.save.assert_not_called()
        self.audit.assert_not_called()
        for rows in [self.payload()['lines'][:1], self.payload()['lines'] * 2,
                     [self.payload()['lines'][0], {'order_line_id': uuid4(), 'quantity': 100}]]:
            with self.subTest(rows=rows), self.assertRaises(ValidationError):
                self.submit({'lines': rows})

    def test_permission_and_etag_errors_stop_before_quantity_writes(self):
        for error in [PermissionDenied(), PreconditionRequired(), PreconditionFailed()]:
            with self.subTest(error=error):
                self.lock.side_effect = error
                with self.assertRaises(type(error)):
                    self.submit(self.payload())
        self.order.save.assert_not_called()
        self.purchases.assert_not_called()

    def test_patch_route_requires_existing_change_permission(self):
        path = reverse('tube-outsourcing-order-plan-quantity', kwargs={'pk': self.order.pk})
        self.assertTrue(path.endswith(f'/{self.order.pk}/plan-quantity/'))
        self.assertEqual(resolve(path).func.actions['patch'], 'plan_quantity')
        self.assertEqual(TubeOutsourcingOrderViewSet.action_permission_map['plan_quantity'],
                         'outsourcing.change_outsourcingorder')
