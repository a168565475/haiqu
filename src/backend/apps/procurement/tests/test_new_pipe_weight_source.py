"""新采购必须使用重量来源；历史米单履约不走此新建门禁。"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from apps.core.api.exceptions import Conflict
from apps.procurement.group_services import create_purchase_batch
from apps.procurement.services import _source_quantity


class NewPipeWeightSourceTests(SimpleTestCase):
    def test_new_source_without_bom_weight_is_missing_instead_of_meter_ready(self):
        line = SimpleNamespace(section=SimpleNamespace(section_type='PROFILE', title='管材'), material_catalog_id=None)
        with patch('apps.procurement.services.pipe_source_snapshot', return_value={'suggested_purchase_meters': '18'}):
            quantity, field, text, unit, status = _source_quantity(line, None)
        self.assertIsNone(quantity)
        self.assertEqual((field, text, unit, status), ('suggested_purchase_weight_kg', '', 'KG', 'MISSING'))

    def test_new_weight_source_uses_saved_suggestion(self):
        line = SimpleNamespace(section=SimpleNamespace(section_type='PROFILE', title='管材'), material_catalog_id=None)
        with patch('apps.procurement.services.pipe_source_snapshot', return_value={
                'measurement_unit': 'kg', 'raw_bar_weight_kg': '2.5', 'suggested_purchase_weight_kg': '835'}):
            quantity, _, _, unit, status = _source_quantity(line, None)
        self.assertEqual((quantity, unit, status), (Decimal('835'), 'KG', 'READY'))

    def test_legacy_group_or_invalid_weight_blocks_new_batch_before_writes(self):
        task_id, group_id, source_id = uuid4(), uuid4(), uuid4()
        data = {'request_id': uuid4(), 'batch_type': 'NORMAL', 'currency_id': uuid4(),
                'lines': [{'purchase_group_line_id': source_id, 'actual_purchase_quantity': Decimal('5')}]}
        group = SimpleNamespace(pk=group_id, compatibility_issues=[], batches=Mock(), lines=Mock())
        group.batches.filter.return_value.first.return_value = None
        source = SimpleNamespace(pk=source_id, source_unit_text='米', source_snapshot={})
        group.lines.select_for_update.return_value.order_by.return_value = [source]
        task = SimpleNamespace(archived_at=None, status='READY')
        for unit, weight in (('米', '2.5'), ('KG', None), ('KG', '0'), ('KG', 'NaN')):
            source.source_unit_text = unit
            source.source_snapshot = {'section_type_snapshot': 'PROFILE', 'raw_bar_weight_kg': weight,
                'calculation_snapshot': {'measurement_unit': 'kg', 'raw_bar_weight_kg': weight}}
            with self.subTest(unit=unit, weight=weight), \
                    patch('apps.procurement.group_services.PurchaseGroup.objects') as groups, \
                    patch('apps.procurement.group_services.ProductionTask.objects') as tasks, \
                    patch('apps.procurement.group_services.require_matching_etag'), \
                    patch('apps.procurement.group_services.PurchaseOrder.objects.create') as create:
                groups.filter.return_value.values_list.return_value.first.return_value = task_id
                groups.select_for_update.return_value.get.return_value = group
                tasks.select_for_update.return_value.get.return_value = task
                with self.assertRaises(Conflict):
                    create_purchase_batch.__wrapped__(group_id=group_id, validated_data=data,
                        allowed_task_ids=[task_id], actor_employee=None, request=None)
                create.assert_not_called()

