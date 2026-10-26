"""打印只读字段的冻结来源；不创建测试库或业务记录。"""
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from ..api.serializers import OutsourcingOrderDetailSerializer
from ..tube_selectors import saved_order_data


def related(rows):
    return SimpleNamespace(all=lambda: rows)


class OutsourcingPrintFieldsTests(SimpleTestCase):
    def tube_order(self, snapshot):
        stamp = datetime(2026, 10, 26, 1, 22, tzinfo=timezone.utc)
        task = SimpleNamespace(pk='task', task_number='SC-1', order_number='HT26170')
        product = SimpleNamespace(pk='product', product_number_snapshot='P-1', item_number_snapshot='XY-108-1',
            product_name_snapshot='扶手椅', quantity=901, unit=SimpleNamespace(unit_name='套'),
            color_name_snapshot='大红色', specification_snapshot='50*50*80', material_snapshot='钢管')
        schedule = SimpleNamespace(pk='schedule', schedule_number='PC-1', production_task=task)
        scheduled = SimpleNamespace(pk='scheduled', schedule=schedule, product_line=product, planned_quantity=450)
        line = SimpleNamespace(pk='line', component_identity='component', factory_id='factory',
            quantity=120, stock_quantity=None, unit_price=Decimal('1.25'), snapshot=snapshot)
        return SimpleNamespace(pk='order', source_kind='METAL', status='COMPLETED', product_line=product,
            actions=related([]), lines=related([line]), materials=related([]), schedule_product=scheduled,
            order_number='WF-1', version=1, client_request_id='request', zone_id=None, craft_id='craft',
            craft=SimpleNamespace(name='喷塑'), remark='', created_at=stamp, updated_at=stamp,
            created_by_employee=SimpleNamespace(display_name='制单人'), schedule_product_id='scheduled',
            product_line_id='product', planned_dispatch_date=date(2026, 10, 24),
            expected_return_date=date(2026, 10, 26))

    def test_tube_print_uses_frozen_consumption_and_diameter_not_partial_dispatch_quantity(self):
        order = self.tube_order({'pieces_per_product': 2, 'order_required': '1802',
            'specification': '圆管16*0.6', 'cutting_length_mm': '800',
            'public_output_identity': {'identity_snapshot': {'tube_diameter': '16'}}})
        data = saved_order_data(order)
        self.assertEqual(data['lines'][0].get('pieces_per_product'), '2')
        self.assertEqual(data['lines'][0].get('tube_diameter'), '16')
        self.assertEqual(data['lines'][0]['order_required'], '1802')
        self.assertEqual(data['lines'][0]['quantity'], '120')

    def test_tube_missing_frozen_fields_remain_unknown_despite_parseable_specification(self):
        for snapshot in ({'specification': '圆管16*0.6', 'order_required': '1802'},
                         {'public_output_identity': None}, {'public_output_identity': []}):
            with self.subTest(snapshot=snapshot):
                line = saved_order_data(self.tube_order(snapshot))['lines'][0]
                self.assertIn('pieces_per_product', line)
                self.assertIn('tube_diameter', line)
                self.assertIsNone(line['pieces_per_product'])
                self.assertIsNone(line['tube_diameter'])

    def test_tube_plan_quantity_is_separate_from_order_quantity_and_plain_product_specification(self):
        order = self.tube_order({})
        data = saved_order_data(order)
        self.assertEqual(data.get('planned_quantity'), '450')
        self.assertEqual(data['quantity'], '901')
        self.assertEqual(data.get('specification'), '50*50*80')
        self.assertEqual(data.get('material'), '钢管')
        self.assertEqual(data.get('updated_at'), order.updated_at.isoformat())

    def original_material(self, snapshot, consumption):
        material = SimpleNamespace(pk='material', bom_material_line_id='bom-material', material_snapshot=snapshot,
            unit_text='支', reference_required_quantity=Decimal('1802'), planned_issue_quantity=Decimal('120'),
            planned_piece_count=120, planned_meters=None, conversion_snapshot={}, difference_reason='', remark='',
            consumption_per_set=consumption)
        allocation = SimpleNamespace(pk='allocation', factory_id='factory', factory=SimpleNamespace(name='加工厂'),
            factory_snapshot={'name': '加工厂'}, allocated_quantity=Decimal('120'), unit_price=Decimal('1'),
            input_quantity=None, input_unit_snapshot='', conversion_snapshot={}, remark='',
            prefetched_material_items=[material], prefetched_return_lines=[])
        item = SimpleNamespace(pk='item', bom_line_id='bom-line', component_snapshot={}, quantity=Decimal('120'),
            unit_snapshot='支', processing_requirement='', prefetched_allocations=[allocation])
        product = SimpleNamespace(pk='product', schedule_product_id='scheduled',
            schedule_product=SimpleNamespace(image_file_id=None, unit_name_snapshot='套'), bom_id='bom',
            bom_number_snapshot='BOM-1', bom_version_snapshot=1, product_snapshot={},
            order_quantity_snapshot=901, planned_quantity_snapshot=450, prefetched_processing_items=[item])
        task = SimpleNamespace(task_number='SC-1', order_number='HT26170', customer_account_id=None,
            order_date=date(2026, 10, 24))
        stamp = datetime(2026, 10, 26, 1, 22, tzinfo=timezone.utc)
        order = SimpleNamespace(pk='order', order_number='WF-1', stock_mode='PUBLIC_V2', schedule_id='schedule',
            schedule=SimpleNamespace(source_snapshot={}, production_task=task, production_task_id='task',
                schedule_number='PC-1'), prefetched_products=[product], prefetched_return_records=[],
            craft_id='craft', craft_name_snapshot='喷塑', craft_code_snapshot='POWDER_COATING',
            delivery_date=date(2026, 10, 26), status='PROCESSING', get_status_display=lambda: '加工中', remark='',
            version=1, created_by_employee_id='employee', created_by_employee=SimpleNamespace(display_name='制单人'),
            created_at=stamp, updated_at=stamp, completed_at=None)
        with patch('apps.material_issues.p4_services.has_original_direct_handoff', return_value=False):
            data = OutsourcingOrderDetailSerializer(order).data
        return data['products'][0]['processing_items'][0]['allocations'][0]['materials'][0]

    def test_original_material_print_preserves_frozen_usage_and_material_attribute(self):
        material = self.original_material({'unit_consumption': '2',
            'bom_attributes': [{'key': 'material', 'label': '材质', 'value': '铁-硬管'}]}, Decimal('9'))
        self.assertEqual(material.get('unit_consumption'), '2')
        self.assertEqual(material.get('material'), '铁-硬管')
        self.assertEqual(material['planned_issue_quantity'], '120')

    def test_original_material_usage_uses_saved_consumption_when_snapshot_text_missing(self):
        material = self.original_material({}, Decimal('2.5'))
        self.assertEqual(material.get('unit_consumption'), '2.5')
        unknown = self.original_material({}, None)
        self.assertIn('unit_consumption', unknown)
        self.assertIsNone(unknown['unit_consumption'])
        self.assertEqual(unknown.get('material'), '')
