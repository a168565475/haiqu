"""新目录车缝投入与产出冻结；仅由统一测试批次在隔离数据库运行。"""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.material_catalog.models import MaterialCatalog
from apps.material_issues.catalog_requirements import catalog_requirement_specs, sync_catalog_requirements
from apps.material_issues.models import MaterialIssue
from ..models import InternalSemiFinishedReceipt, InternalSemiFinishedReceiptLine, PublicStockMovement
from ..public_stock_identity import build_semi_finished_identity
from ..public_stock_services import credit_public_stock
from . import test_sewing_processing_services as sewing_tests


def prepare_catalog_sewing(fixture):
    """只准备已保存选料事实；不依赖当前目录选项重建历史快照。"""
    fabric_catalog = MaterialCatalog.objects.create(category_key='FABRIC', template_key='FABRIC', name='目录面布')
    cutting_catalog = MaterialCatalog.objects.create(category_key='FABRIC_SEMI', template_key='FABRIC_SEMI', name='目录裁片')
    selected = {'schema_version': 1, 'catalog_id': str(fabric_catalog.pk),
        'catalog_version': fabric_catalog.updated_at.isoformat(), 'category_key': 'FABRIC', 'template_key': 'FABRIC',
        'name': fabric_catalog.name, 'scope': 'BASE', 'processing_state': 'RAW', 'processing_stage': 'RAW',
        'completed_craft': None, 'semi_kind': None, 'attributes': {'material': '600D', 'fabric_spec': '150cm',
            'width': '150cm', 'color': '蓝色'}, 'unit_id': str(fixture.meter.pk), 'unit_name': '米',
        'display_name': '目录面布 / 米'}
    fixture.fabric.material_catalog = fabric_catalog
    fixture.fabric.material_selection_snapshot = selected
    fixture.fabric.raw_values = {'fabric_color_name': '蓝色', 'fabric_color_code': '5865C'}
    fixture.fabric.total_consumption = '500'
    fixture.fabric.save(update_fields=['material_catalog', 'material_selection_snapshot', 'raw_values', 'total_consumption'])
    for part in fixture.parts:
        part.material_catalog = cutting_catalog
        part.material_selection_snapshot = {**selected, 'catalog_id': str(cutting_catalog.pk),
            'catalog_version': cutting_catalog.updated_at.isoformat(), 'category_key': 'FABRIC_SEMI',
            'template_key': 'FABRIC_SEMI', 'name': cutting_catalog.name, 'attributes': {'material': '600D', 'size': '50*40', 'color': '蓝色'},
            'processing_state': 'PROCESSED', 'processing_stage': 'SEWING', 'semi_kind': 'CUTTING',
            'completed_craft': {'id': str(fixture.external_sewing.pk), 'craft_type': 'EXTERNAL', 'code': 'SEWING'},
            'unit_id': str(fixture.set_unit.pk), 'unit_name': '套', 'display_name': '目录裁片 / 套'}
        part.save(update_fields=['material_catalog', 'material_selection_snapshot'])
    return fabric_catalog, cutting_catalog


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True,
    MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class CatalogSewingInputTests(sewing_tests.SewingProcessingFixture, TestCase):
    url = '/api/v1/semi-finished-receipts/'

    def setUp(self):
        super().setUp()
        self.fabric_catalog, self.cutting_catalog = prepare_catalog_sewing(self)
        self.requirement.contributions.update(is_current=False)
        specs, blockers = catalog_requirement_specs(self.task.pk, self.product_line.pk)
        self.assertFalse(blockers, blockers)
        self.catalog_requirement = sync_catalog_requirements(MaterialIssue(production_task=self.task,
            product_line=self.product_line, stock_mode='PUBLIC_V2'), [spec['id'] for spec in specs])[0]

    def preview(self):
        response = self.client.get(self.url + 'preview/', {
            'schedule_product_id': str(self.schedule_product.pk), 'plan_category': 'SEWING'})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def submit(self, quantity, expected=201):
        preview = self.preview()
        response = self.client.post(self.url, {'request_id': str(uuid4()),
            'schedule_product_id': str(self.schedule_product.pk), 'plan_category': 'SEWING',
            'zone_id': str(self.semi_zone.pk), 'receipt_date': str(timezone.localdate()),
            'lines': [{'bom_line_id': str(self.parts[0].pk), 'quantity': str(quantity)}]},
            format='json', HTTP_IF_MATCH=preview['etag'])
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def confirm(self, receipt, expected=200):
        response = self.client.post(self.url + str(receipt.pk) + '/confirm/', {}, format='json',
            HTTP_IF_MATCH=f'"{receipt.source_revision_hash}"')
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def test_saved_fabric_input_and_sewing_output_survive_catalog_edit_and_confirmation(self):
        preview = self.preview()
        row = next(row for row in preview['lines'] if row['bom_line_id'] == str(self.parts[0].pk))
        self.assertEqual(row['input_material_selection_snapshot'], self.fabric.material_selection_snapshot)
        self.assertEqual(row['output_material_selection_snapshot']['processing_stage'], 'SEWING')
        self.submit(120)
        receipt = InternalSemiFinishedReceipt.objects.get()
        line = receipt.lines.get()
        frozen = deepcopy(line.input_snapshot)
        self.fabric_catalog.name = '后来改名'
        self.fabric_catalog.archived_at = timezone.now()
        self.fabric_catalog.save(update_fields=['name', 'archived_at'])
        self.confirm(receipt)
        line.refresh_from_db()
        self.assertEqual(line.input_snapshot, frozen)
        self.assertEqual((line.input_per_output, line.input_quantity), (None, None))
        self.assertEqual(line.stock_movement.balance.stock_kind, 'CATALOG_SEMI')
        for name in ('input_material_selection_snapshot', 'output_material_selection_snapshot'):
            self.assertEqual(line.stock_movement.snapshot[name], frozen[name])
        self.assertEqual(self.preview()['lines'][0]['input_supported'], None)
        self.assertFalse(PublicStockMovement.objects.filter(direction='OUT').exists())

    def test_pending_receipts_and_direct_dispatch_share_actual_set_quota(self):
        self.direct(300)
        self.submit(201, expected=400)
        self.submit(200)
        self.submit(1, expected=400)
        receipt = InternalSemiFinishedReceipt.objects.get()
        self.confirm(receipt)
        row = next(row for row in self.preview()['lines'] if row['bom_line_id'] == str(self.parts[0].pk))
        self.assertEqual((row['received'], row['directly_committed'], row['can_receive']), ('200', '300', '0'))

    def test_catalog_internal_and_external_sewing_share_balance_and_remaining_limit(self):
        identity = build_semi_finished_identity(bom_line=self.parts[0], completed_craft=self.external_sewing, unit=self.set_unit)
        stock = credit_public_stock(identity=identity, zone=self.semi_zone, quantity=450,
            source_type='OUTSOURCING_RETURN', source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee,
            production_task=self.task, product_line=self.product_line, bom_line=self.parts[0]).balance
        self.submit(51, expected=400)
        self.submit(50)
        self.confirm(InternalSemiFinishedReceipt.objects.get())
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal(500))
        self.assertEqual(InternalSemiFinishedReceiptLine.objects.get().stock_movement.balance_id, stock.pk)

    def test_tampered_pending_input_is_rejected_without_stock(self):
        self.submit(10)
        receipt = InternalSemiFinishedReceipt.objects.get()
        line = receipt.lines.get()
        line.input_snapshot['input_material_selection_snapshot']['attributes']['color'] = '红色'
        line.save(update_fields=['input_snapshot'])
        self.confirm(receipt, expected=409)
        self.assertFalse(PublicStockMovement.objects.exists())
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, 'PENDING')

    def test_requirement_source_drift_is_rejected_instead_of_using_legacy_raw_pointer(self):
        saved = deepcopy(self.catalog_requirement.material_selection_snapshot)
        saved['attributes']['color'] = '红色'
        self.catalog_requirement.material_selection_snapshot = saved
        self.catalog_requirement.save(update_fields=['material_selection_snapshot'])
        response = self.client.get(self.url + 'preview/', {
            'schedule_product_id': str(self.schedule_product.pk), 'plan_category': 'SEWING'})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('面料需求与保存材料', str(response.data))
        self.assertFalse(InternalSemiFinishedReceipt.objects.exists())

    def test_same_physical_material_metadata_change_preserves_old_receipts_and_new_movement_snapshot(self):
        first = self.submit(100).data['data']
        first_receipt = InternalSemiFinishedReceipt.objects.get(pk=first['receipt_id'])
        self.confirm(first_receipt)
        second = self.submit(50).data['data']
        pending = InternalSemiFinishedReceipt.objects.get(pk=second['receipt_id'])
        original = deepcopy(pending.lines.get().input_snapshot)
        for bom_line in (self.fabric, *self.parts):
            selected = deepcopy(bom_line.material_selection_snapshot)
            selected.update(name=selected['name'] + '（改名）', catalog_version='updated-display-version',
                display_name=selected['display_name'] + '（新版显示）')
            bom_line.material_selection_snapshot = selected
            bom_line.save(update_fields=['material_selection_snapshot'])
        sync_catalog_requirements(MaterialIssue(production_task=self.task, product_line=self.product_line,
            stock_mode='PUBLIC_V2'), [self.catalog_requirement.pk])
        row = next(row for row in self.preview()['lines'] if row['bom_line_id'] == str(self.parts[0].pk))
        self.assertEqual((row['received'], row['can_receive']), ('150', '350'))
        self.confirm(pending)
        old_line = pending.lines.get()
        self.assertEqual(old_line.input_snapshot, original)
        self.assertEqual(old_line.stock_movement.snapshot['public_identity']['identity_snapshot'], old_line.attribute_snapshot)
        self.assertEqual(old_line.stock_movement.snapshot['input_material_selection_snapshot'], original['input_material_selection_snapshot'])
        third = self.submit(25).data['data']
        current = InternalSemiFinishedReceipt.objects.get(pk=third['receipt_id'])
        self.confirm(current)
        current_line = current.lines.get()
        self.assertEqual(current_line.stock_movement.balance_id, old_line.stock_movement.balance_id)
        self.assertEqual(current_line.stock_movement.balance.quantity, 175)
        self.assertNotEqual(current_line.attribute_snapshot, old_line.attribute_snapshot)
        self.assertEqual(current_line.stock_movement.snapshot['public_identity']['identity_snapshot'], current_line.attribute_snapshot)
        detail = self.client.get(self.url + str(current_line.stock_movement_id) + '/')
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data['data']['attributes'], current_line.attribute_snapshot)
