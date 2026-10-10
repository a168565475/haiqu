"""已结束读取只用冻结凭证；非终态仍沿用当前加工依据。"""
from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.inventory.tube_processing_services import metal_component_limits
from apps.workshop_config.models import Craft

from .test_tube_orders_api import BASE
from .test_tube_receipts_api import TubeReceiptFixture


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeEndedReadTests(TubeReceiptFixture, APITestCase):
    def test_completed_metal_detail_and_preview_never_read_current_reports(self):
        order = self.dispatched('METAL')
        receipt = self.receive_final(order).data['data']
        before = self.receipt_snapshot()
        with patch('apps.inventory.tube_processing_services.metal_component_limits',
                   wraps=metal_component_limits) as current_basis:
            detail = self.detail(order).data['data']
            preview = self.preview(order)
            current_basis.assert_not_called()
        self.assertEqual(detail['status'], 'COMPLETED')
        self.assertIsNone(detail['lines'][0]['current_reported_minimum'])
        self.assertEqual(detail['lines'][0]['operations'], [])
        self.assertEqual(preview['receipt']['id'], receipt['id'])
        self.assertEqual(before, self.receipt_snapshot())

    def test_pending_and_processing_metal_detail_keep_current_reports(self):
        order = self.saved_order('METAL')
        for status in ('PENDING_DISPATCH', 'PROCESSING'):
            with self.subTest(status=status):
                before = self.receipt_snapshot()
                with patch('apps.inventory.tube_processing_services.metal_component_limits',
                           wraps=metal_component_limits) as current_basis:
                    detail = self.detail(order).data['data']
                    current_basis.assert_called_once_with(self.product_line)
                self.assertEqual(detail['status'], status)
                self.assertEqual(detail['lines'][0]['current_reported_minimum'], '100')
                self.assertTrue(detail['lines'][0]['operations'])
                self.assertEqual(before, self.receipt_snapshot())
            if status == 'PENDING_DISPATCH':
                order = self.act(order).data['data']

    def test_cancelled_metal_detail_keeps_current_reports(self):
        order = self.act(self.saved_order('METAL'), 'cancel').data['data']
        with patch('apps.inventory.tube_processing_services.metal_component_limits',
                   wraps=metal_component_limits) as current_basis:
            detail = self.detail(order).data['data']
            current_basis.assert_called_once_with(self.product_line)
        self.assertEqual(detail['status'], 'CANCELLED')
        self.assertEqual(detail['lines'][0]['current_reported_minimum'], '100')


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
                   ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
                   SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class TubeEndedReadScopeTests(ScopedActorMixin, TubeReceiptFixture, APITestCase):
    def test_completed_preview_allows_return_scope_without_view_scope(self):
        order = self.dispatched('METAL')
        receipt = self.receive_final(order).data['data']
        self.scoped_actor()
        unrelated = Craft.objects.create(name='已结束无关工艺', craft_type='EXTERNAL', outsourcing_code='SEWING')
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [unrelated])
        self.grant('outsourcing.confirm_return_outsourcingorder', 'CRAFT', [self.spray])
        before = self.receipt_snapshot()
        with patch('apps.inventory.tube_processing_services.metal_component_limits',
                   wraps=metal_component_limits) as current_basis:
            preview = self.preview(order)
            self.detail(order, expected=403)
            current_basis.assert_not_called()
        self.assertEqual(preview['receipt']['id'], receipt['id'])
        self.assertFalse(preview['can_receive'])
        self.assertEqual(before, self.receipt_snapshot())
