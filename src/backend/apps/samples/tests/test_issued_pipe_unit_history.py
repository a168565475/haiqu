"""只核已领管材历史单位依据；不重跑采购、收货或领料确认用例。"""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
from apps.inventory.models import PublicStockMovement, Warehouse, WarehouseZone
from apps.inventory.public_stock_services import credit_public_stock
from apps.reference_data.models import ProductionUnit
from apps.samples.catalog_stock import debit_catalog_plan
from apps.samples.models import SampleMaterialIssue, SampleMaterialIssueLine, SampleMaterialRequest
from . import test_catalog_materials as fixtures


class IssuedPipeUnitHistoryTests(APITestCase):
    setUp = fixtures.SampleCatalogMaterialsTests.setUp
    create_customer = fixtures.SampleCatalogMaterialsTests.create_customer
    create_inquiry_with_item = fixtures.SampleCatalogMaterialsTests.create_inquiry_with_item
    create_quotation_version_with_line = fixtures.SampleCatalogMaterialsTests.create_quotation_version_with_line
    payload = fixtures.SampleCatalogMaterialsTests.payload
    submit = fixtures.SampleCatalogMaterialsTests.submit
    review = fixtures.SampleCatalogMaterialsTests.review
    prepare = fixtures.SampleCatalogMaterialsTests.prepare
    put = fixtures.SampleCatalogMaterialsTests.put
    setup_catalog = fixtures.SampleCatalogMaterialsTests.setup_catalog
    line = fixtures.SampleCatalogMaterialsTests.line
    save_lines = fixtures.SampleCatalogMaterialsTests.save_lines

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_issued_pipe_keeps_meter_basis_after_unit_rename_without_relabelling_unproven_history(self):
        self.setup_catalog()
        self.catalog.category_key = self.catalog.template_key = 'TUBE'
        self.catalog.save()
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name='根', defaults={'unit_code': 'U4R3ROOT'})
        meter, _ = ProductionUnit.objects.get_or_create(unit_name='米', defaults={'unit_code': 'U4R3METER'})
        row = self.line(category='tube', quantity='12')
        row['material_selection']['attributes'] = {'material': '铁', 'shape': '圆管', 'section_size': '25', 'thickness': '1.2', 'length': '仅属性原文'}
        response = self.save_lines([row], submit=True)
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data['data']['draft']['lines'][0]
        record = SampleMaterialRequest.objects.get(sample_request_id=self.root.split('/')[-2])
        frozen_draft = deepcopy(record.draft)
        sample = record.sample_request
        sample.status = 'METALWORK_PENDING'  # 已领历史读取前置，不冒充重新走领料确认。
        sample.save(update_fields=['status', 'updated_at'])
        issue = SampleMaterialIssue.objects.create(material_request=record, status='ISSUED',
            initiated_by=self.employee, confirmed_by=self.employee, initiated_at=timezone.now(), confirmed_at=timezone.now())
        line = SampleMaterialIssueLine.objects.create(issue=issue, line_key=row['key'], unit=meter,
            material_catalog=self.catalog, material_selection_snapshot=row['material_selection_snapshot'],
            category='tube', name_snapshot=row['name'], specification_snapshot=row['specification'], material_snapshot=row['material'],
            requested_quantity=12, warehouse_quantity=9, arrived_quantity=3, available_quantity=12, issued_quantity=12, shortage_quantity=0)
        warehouse = Warehouse.objects.create(warehouse_number='U4-R3-HISTORY', warehouse_name='已领历史单位隔离', warehouse_type='MATERIAL')
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='实际原长区')
        allocations = []
        for length, roots in (('3.00', 2), ('6.00', 1)):
            identity = build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
                material_selection_snapshot=row['material_selection_snapshot'], raw_bar_length_m=length)
            incoming = credit_public_stock(identity=identity, zone=zone, quantity=roots,
                source_type='TEST_U4_ISSUED_UNIT_HISTORY', source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee)
            allocations.append({'balance': incoming.balance, 'quantity': Decimal(roots)})
        debit_catalog_plan({'allocations': allocations}, issue=issue, line=line, actor_employee=self.employee)
        ledger_count = PublicStockMovement.objects.count()
        before = self.client.get(self.root + 'material-issue/')
        self.assertEqual(before.status_code, 200, before.data)
        meter.unit_name = 'R3公共米单位后来改名'
        meter.save(update_fields=['unit_name', 'updated_at'])
        reopened = self.client.get(self.root + 'material-issue/')
        self.assertEqual(reopened.status_code, 200, reopened.data)
        history = reopened.data['data']['lines'][0]
        self.assertEqual(history['unitLabel'], '米')
        self.assertEqual(Decimal(history['issuedQuantity']), 12)
        self.assertEqual(history['barCount'], 3)
        self.assertEqual(sorted((Decimal(batch['rawBarLengthM']), batch['barCount'], Decimal(batch['meterQuantity'])) for batch in history['pipeBatches']),
            [(Decimal(3), 2, Decimal(6)), (Decimal(6), 1, Decimal(6))])
        self.assertEqual(history['pipeBatches'], before.data['data']['lines'][0]['pipeBatches'])
        self.assertEqual(PublicStockMovement.objects.count(), ledger_count)

        # 顶层提交历史才是依据；即使修订稿保留TOTAL_METERS，也不能补造旧根/公斤口径。
        for old_unit in ('根', '公斤'):
            with self.subTest(unproven_unit=old_unit):
                legacy_unit, _ = ProductionUnit.objects.get_or_create(unit_name=old_unit, defaults={'unit_code': 'U4R3KG'})
                legacy_selection = deepcopy(row['material_selection_snapshot'])
                legacy_selection.update(unit_id=str(legacy_unit.pk), unit_name=old_unit)
                line.unit = legacy_unit
                line.material_selection_snapshot = legacy_selection
                line.save(update_fields=['unit', 'material_selection_snapshot', 'updated_at'])
                draft = deepcopy(frozen_draft)
                draft['currentDraft'] = deepcopy(frozen_draft)
                draft['lines'][0].pop('pipeInputMode')
                draft['lines'][0].pop('pipeCalculation')
                draft['lines'][0]['unitLabel'] = old_unit
                draft['lines'][0]['material_selection_snapshot'] = legacy_selection
                record.draft = draft
                record.save(update_fields=['draft', 'updated_at'])
                unknown = self.client.get(self.root + 'material-issue/')
                self.assertEqual(unknown.status_code, 200, unknown.data)
                self.assertEqual(unknown.data['data']['lines'][0]['unitLabel'], '待核实')
                self.assertFalse(unknown.data['data']['lines'][0]['pipeBatches'])
        line.unit = meter
        line.material_selection_snapshot = row['material_selection_snapshot']
        line.save(update_fields=['unit', 'material_selection_snapshot', 'updated_at'])
        record.draft = frozen_draft
        record.save(update_fields=['draft', 'updated_at'])
        missing = PublicStockMovement.objects.filter(direction='OUT').first()
        saved_snapshot = deepcopy(missing.snapshot)
        PublicStockMovement.objects.filter(pk=missing.pk).update(snapshot={})
        unknown = self.client.get(self.root + 'material-issue/')
        self.assertEqual(unknown.status_code, 200, unknown.data)
        self.assertEqual(unknown.data['data']['lines'][0]['unitLabel'], '待核实')
        PublicStockMovement.objects.filter(pk=missing.pk).update(snapshot=saved_snapshot)
        self.assertEqual(PublicStockMovement.objects.count(), ledger_count)
        self.assertEqual(self.client.get(self.root + 'material-issue/').data['data']['lines'][0]['pipeBatches'], history['pipeBatches'])
