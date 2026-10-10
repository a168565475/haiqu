"""既有入库入口和公共记账不能吃掉已保存直发预留。"""
import uuid
from unittest.mock import patch
from django.test import override_settings
from rest_framework.test import APITestCase
from apps.outsourcing.tests.test_tube_orders_api import TubeApiFixture
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.stock_services import InventoryStockValidationError
from apps.inventory.models import PublicStockMovement
from apps.inventory.tube_outsourcing_limits import tube_source_context


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeReservationReceiptGuardTests(TubeApiFixture, APITestCase):
    def test_public_credit_rejects_output_that_consumes_saved_direct_dispatch(self):
        self.post_order(self.order_payload('METAL', '60'))
        identity = build_semi_finished_identity(bom_line=self.metal_bom_line,
            completed_craft=self.craft, unit=self.piece_unit)
        before = PublicStockMovement.objects.count()
        with self.assertRaises(InventoryStockValidationError) as captured:
            credit_public_stock(identity=identity, zone=self.semi_zone, quantity=41,
                source_type='INTERNAL_SEMI_RECEIPT', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
                actor_employee=self.employee, production_task=self.task,
                product_line=self.product_line, bom_line=self.metal_bom_line)
        self.assertEqual(captured.exception.api_error_code, 'TUBE_OUTSOURCING_OUTPUT_RESERVED')
        self.assertEqual(PublicStockMovement.objects.count(), before)

    def test_public_credit_allows_unreserved_reported_output(self):
        self.post_order(self.order_payload('METAL', '60'))
        identity = build_semi_finished_identity(bom_line=self.metal_bom_line,
            completed_craft=self.craft, unit=self.piece_unit)
        movement = credit_public_stock(identity=identity, zone=self.semi_zone, quantity=40,
            source_type='INTERNAL_SEMI_RECEIPT', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee, production_task=self.task,
            product_line=self.product_line, bom_line=self.metal_bom_line)
        self.assertEqual(movement.quantity, 40)

    def test_historical_requirement_identity_cannot_open_a_second_allowance(self):
        from apps.material_issues.material_flow import pipe_specs
        specs, blockers = pipe_specs(self.task.pk, self.product_line.pk)
        self.assertFalse(blockers)
        specs[0]['id'] = uuid.uuid4()
        with patch('apps.inventory.tube_outsourcing_limits.pipe_specs', return_value=(specs, [])):
            context = tube_source_context(schedule_product=self.schedule_product,
                source_kind='RAW_PIPE', zone=self.raw_zone)
        self.assertFalse(context['ready'])
        self.assertEqual(context['rows'][0]['max_quantity'], '0')
        self.assertIn('历史管材需求编号', context['rows'][0]['blockers'][0])

    def test_metal_source_context_reads_profile_powder_coating_color(self):
        """型材新字段应展示为外发喷塑颜色，不再依赖原料颜色。"""
        values = dict(self.metal_bom_line.raw_values or {})
        values['tube_coating_color'] = ''
        values['powder_coating_color'] = '铁-中光'
        self.metal_bom_line.raw_values = values
        self.metal_bom_line.save(update_fields=['raw_values'])

        context = tube_source_context(schedule_product=self.schedule_product,
            source_kind='METAL')

        self.assertTrue(context['ready'], context)
        self.assertEqual(context['rows'][0]['spray_color'], '铁-中光')
