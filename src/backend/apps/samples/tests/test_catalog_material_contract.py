"""纯输入/输出回归：不连接数据库；不能替代API/Session验收。"""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
from apps.samples.catalog_materials import freeze_sample_selection
from apps.samples.sample_issue_services import _line_payload
from apps.samples.warehouse_stock import candidate_payload


class SampleCatalogMaterialContractTests(SimpleTestCase):
    def selection(self):
        return {'schema_version': 1, 'catalog_id': str(uuid4()), 'catalog_version': 'frozen',
            'category_key': 'HARDWARE', 'template_key': 'HARDWARE', 'name': '五金', 'scope': 'BASE',
            'processing_state': 'RAW', 'processing_stage': 'RAW', 'completed_craft': None, 'semi_kind': None,
            'attributes': {'specification': 'M8'}, 'unit_id': str(uuid4()), 'unit_name': '保存时公斤', 'display_name': '五金 / M8 / 保存时公斤'}

    def test_saved_category_cannot_be_changed_without_new_selection(self):
        selected = self.selection()
        previous = {'key': 'same-key', 'category': 'hardware', 'material_catalog_id': selected['catalog_id'],
            'material_selection_snapshot': selected, 'quantity': '1.25'}
        row = {**deepcopy(previous), 'category': 'tube'}
        before = deepcopy(row)
        with self.assertRaises(ValidationError):
            freeze_sample_selection(row, previous=previous, request=SimpleNamespace(), versions={})
        self.assertEqual(row, before)
        self.assertEqual(previous['material_selection_snapshot'], selected)

    def test_same_category_quantity_edit_keeps_saved_content_without_catalog_lookup(self):
        selected = self.selection()
        previous = {'key': 'same-key', 'category': 'hardware', 'material_catalog_id': selected['catalog_id'],
            'material_selection_snapshot': selected, 'quantity': '1.25'}
        row = {**deepcopy(previous), 'quantity': '2.5'}
        freeze_sample_selection(row, previous=previous, request=SimpleNamespace(), versions={})
        self.assertEqual(row['material_selection_snapshot'], selected)
        self.assertEqual(row['quantity'], '2.5')

    def issue_line(self, selected):
        return SimpleNamespace(material_catalog_id=selected['catalog_id'], material_selection_snapshot=selected,
            id=uuid4(), line_key=uuid4(), category='hardware', name_snapshot='五金', specification_snapshot='M8',
            material_snapshot='', color_snapshot='', unit=SimpleNamespace(unit_name='目录后来改名'),
            requested_quantity=Decimal('1.25'), warehouse_quantity=Decimal('1.25'), arrived_quantity=Decimal('0'),
            available_quantity=Decimal('1.25'), issued_quantity=Decimal('1.25'), shortage_quantity=Decimal('0'))

    def test_issued_label_uses_saved_unit_after_common_unit_rename(self):
        self.assertEqual(_line_payload(self.issue_line(self.selection()))['unitLabel'], '保存时公斤')

    def test_damaged_issue_snapshot_is_rejected_instead_of_current_unit_fallback(self):
        selected = self.selection()
        del selected['unit_name']
        with self.assertRaises(ValidationError):
            _line_payload(self.issue_line(selected))

    def balance(self, selected):
        identity = build_catalog_stock_identity(material_catalog_id=selected['catalog_id'], material_selection_snapshot=selected)
        return SimpleNamespace(**identity, material_catalog_id=selected['catalog_id'], pk=uuid4(),
            unit=SimpleNamespace(unit_name='目录后来改名'), zone=SimpleNamespace(zone_name='一区', warehouse=SimpleNamespace(warehouse_name='材料仓')))

    def test_candidate_label_uses_inventory_saved_unit_after_common_unit_rename(self):
        self.assertEqual(candidate_payload(self.balance(self.selection()), Decimal('1.25'), 'PUBLIC_V2')['unitLabel'], '保存时公斤')

    def test_damaged_inventory_snapshot_is_rejected_instead_of_current_unit_fallback(self):
        balance = self.balance(self.selection())
        del balance.identity_snapshot['material_selection_snapshot']['unit_name']
        with self.assertRaises(ValidationError):
            candidate_payload(balance, Decimal('1.25'), 'PUBLIC_V2')

    def test_legacy_issue_and_candidate_keep_existing_unit_path(self):
        line = self.issue_line(self.selection())
        line.material_catalog_id = None
        line.material_selection_snapshot = {}
        self.assertEqual(_line_payload(line)['unitLabel'], '目录后来改名')
        balance = self.balance(self.selection())
        del balance.material_catalog_id
        balance.raw_material_id = uuid4()
        balance.raw_material = SimpleNamespace(material_number='OLD')
        self.assertEqual(candidate_payload(balance, Decimal('1.25'), 'LEGACY')['unitLabel'], '目录后来改名')
