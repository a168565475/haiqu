from copy import deepcopy
from uuid import uuid4
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.material_catalog.models import MaterialCatalog, MaterialAttributeValue
from apps.products.models import RawMaterialInformation
from apps.samples.models import SampleMaterialRequest
from django.test import override_settings
from .test_material_api import SampleMaterialApiTests as Fixtures


class SampleCatalogMaterialsTests(APITestCase):
    setUp = Fixtures.setUp
    create_customer = Fixtures.create_customer
    create_inquiry_with_item = Fixtures.create_inquiry_with_item
    create_quotation_version_with_line = Fixtures.create_quotation_version_with_line
    payload = Fixtures.payload
    submit = Fixtures.submit
    review = Fixtures.review
    prepare = Fixtures.prepare
    put = Fixtures.put

    def setup_catalog(self):
        self.prepare()
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="material_catalog"))
        for key in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            self.user.__dict__.pop(key, None)
        self.catalog = MaterialCatalog.objects.create(category_key="HARDWARE", template_key="HARDWARE", name="U4独立五金")
        self.state = self.client.get(self.root + "materials/")

    def line(self, **changes):
        return {"key": str(uuid4()), "category": "hardware", "name": "", "specification": "", "material": "", "color": "",
            "quantity": "12", "unitId": "", "notes": "", "material_catalog_id": str(self.catalog.pk),
            "material_selection": {"catalog_version": self.catalog.updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
                "attributes": {"specification": "M8", "color": "黑色"}, "unit_id": str(self.unit.pk)}, **changes}

    def save_lines(self, lines, *, submit=False, etag=None):
        return self.put("materials", {"lines": lines, "notes": ""}, submit, etag or self.state["ETag"])

    def test_save_without_bom_freezes_selection_and_does_not_create_legacy(self):
        self.setup_catalog()
        other = MaterialCatalog.objects.create(category_key="HARDWARE", template_key="HARDWARE", name="U4另一品名")
        count = RawMaterialInformation.objects.count()
        saved = self.save_lines([self.line()], submit=True)
        self.assertEqual(saved.status_code, 200, saved.data)
        row = saved.data["data"]["draft"]["lines"][0]
        self.assertEqual(row["material_selection_snapshot"]["attributes"]["specification"], "M8")
        self.assertEqual(row["unitId"], str(self.unit.pk))
        self.assertFalse(other.attribute_values.exists())
        self.assertEqual(RawMaterialInformation.objects.count(), count)
        self.assertEqual(self.client.get(self.root + "materials/").data["data"]["draft"]["lines"][0], row)

    @override_settings(MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False)
    def test_fill_permission_can_save_existing_public_material_without_catalog_access(self):
        from types import SimpleNamespace
        from rest_framework.exceptions import PermissionDenied
        from apps.boms.catalog_selection import apply_catalog_selection
        from apps.reference_data.models import MaterialAttributePublicValue

        self.setup_catalog()
        self.user.user_permissions.remove(*Permission.objects.filter(content_type__app_label='material_catalog'))
        for key in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            self.user.__dict__.pop(key, None)
        self.assertTrue(self.user.has_perm('samples.edit_sample_materials'))
        self.assertFalse(self.user.has_perm('material_catalog.view_materialcatalog'))
        self.assertFalse(self.user.has_perm('material_catalog.change_materialcatalog'))
        MaterialAttributePublicValue.objects.create(category_key='HARDWARE', template_key='HARDWARE',
            scope='BASE', field_key='specification', value='M8')
        public_count, legacy_count = MaterialAttributePublicValue.objects.count(), RawMaterialInformation.objects.count()
        selected = self.line()
        selected['material_selection']['attributes'] = {'specification': 'M8'}
        self.assertEqual(self.client.get('/api/v1/sample-material-sources/', {'category': 'HARDWARE'}).status_code, 200)
        saved = self.save_lines([selected])
        self.assertEqual(saved.status_code, 200, saved.data)
        row = saved.data['data']['draft']['lines'][0]
        self.assertEqual(row['material_catalog_id'], str(self.catalog.pk))
        self.assertEqual(row['material_selection_snapshot']['attributes'], {'specification': 'M8'})
        self.assertEqual((MaterialAttributePublicValue.objects.count(), RawMaterialInformation.objects.count()),
                         (public_count, legacy_count))

        self.assertEqual(self.client.get('/api/v1/material-catalog/').status_code, 403)
        denied = self.client.patch(f'/api/v1/material-catalog/{self.catalog.pk}/', {'spray_enabled': True}, format='json')
        self.assertEqual(denied.status_code, 403, denied.data)
        self.catalog.refresh_from_db()
        self.assertFalse(self.catalog.spray_enabled)
        missing = self.line()
        missing['material_selection']['attributes'] = {'specification': '填料不能新增公共规格'}
        denied = self.save_lines([missing], etag=saved['ETag'])
        self.assertEqual(denied.status_code, 403, denied.data)
        self.assertEqual(MaterialAttributePublicValue.objects.count(), public_count)
        self.assertEqual(self.client.get(self.root + 'materials/').data['data']['draft'], saved.data['data']['draft'])

        projection = SimpleNamespace(section=SimpleNamespace(title='五金件', section_type='OTHER'), raw_values={})
        with self.assertRaises(PermissionDenied):
            apply_catalog_selection(projection, selected, old=None, request=SimpleNamespace(user=self.user),
                                    persist=False, versions={})

    @override_settings(MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False)
    def test_catalog_access_without_fill_permission_cannot_save_sample_materials(self):
        self.setup_catalog()
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='samples', codename='edit_sample_materials'))
        for key in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            self.user.__dict__.pop(key, None)
        self.assertTrue(self.user.has_perm('material_catalog.view_materialcatalog'))
        self.assertFalse(self.user.has_perm('samples.edit_sample_materials'))
        denied = self.save_lines([self.line()])
        self.assertEqual(denied.status_code, 403, denied.data)
        self.assertFalse(SampleMaterialRequest.objects.filter(sample_request_id=self.root.split('/')[-2]).exists())
        self.assertFalse(self.catalog.attribute_values.exists())

    def test_later_invalid_line_rolls_back_options_and_draft(self):
        self.setup_catalog()
        response = self.save_lines([self.line(), self.line(material_catalog_id=str(uuid4()))])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(MaterialAttributeValue.objects.filter(catalog=self.catalog).exists())
        self.assertFalse(SampleMaterialRequest.objects.filter(sample_request_id=self.root.split("/")[-2]).exists())

    def test_ordinary_edit_preserves_frozen_content_after_catalog_change(self):
        self.setup_catalog()
        saved = self.save_lines([self.line()], submit=True)
        self.assertEqual(saved.status_code, 200, saved.data)
        row = saved.data["data"]["draft"]["lines"][0]
        frozen = deepcopy(row["material_selection_snapshot"])
        self.catalog.name = "后来目录名"
        self.catalog.save()
        self.catalog.attribute_values.all().update(value="后来属性")
        row["notes"] = "仅改备注"
        response = self.save_lines([row], etag=saved["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["draft"]["lines"][0]["material_selection_snapshot"], frozen)
        self.assertEqual(SampleMaterialRequest.objects.get().draft["lines"][0]["notes"], "")

    def test_stale_catalog_and_wrong_category_are_rejected(self):
        self.setup_catalog()
        line = self.line()
        self.catalog.save()
        response = self.save_lines([line])
        self.assertEqual(response.status_code, 412, response.data)
        self.assertFalse(self.catalog.attribute_values.exists())
        self.catalog.refresh_from_db()
        response = self.save_lines([self.line(category="plastic")])
        self.assertEqual(response.status_code, 400, response.data)

    def test_existing_saved_category_mismatch_rejects_and_rolls_back_other_line_supplement(self):
        from apps.reference_data.models import ProductionUnit
        self.setup_catalog()
        saved = self.save_lines([self.line()])
        self.assertEqual(saved.status_code, 200, saved.data)
        original = deepcopy(saved.data['data']['draft'])
        mismatched = {**original['lines'][0], 'category': 'tube'}
        self.catalog.refresh_from_db()
        extra = self.line()
        extra['material_selection']['attributes']['color'] = 'R1整单回滚颜色'
        extra['material_selection'].pop('unit_id')
        extra['material_selection']['unit_name'] = 'R1整单回滚单位'
        response = self.save_lines([extra, mismatched], etag=saved['ETag'])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(self.catalog.attribute_values.filter(value='R1整单回滚颜色').exists())
        self.assertFalse(ProductionUnit.objects.filter(unit_name='R1整单回滚单位').exists())
        self.assertEqual(self.client.get(self.root + 'materials/').data['data']['draft'], original)

    def test_pipe_demand_uses_total_meters_while_material_snapshot_keeps_roots(self):
        self.setup_catalog()
        self.catalog.category_key = self.catalog.template_key = "TUBE"
        self.catalog.save()
        from apps.reference_data.models import ProductionUnit
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name='根', defaults={'unit_code': 'U4ROOT'})
        line = self.line(category="tube")
        line["material_selection"]["attributes"] = {"material": "铁", "shape": "方管", "section_size": "25", "thickness": "1.2"}
        response = self.save_lines([line], submit=True)
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["data"]["draft"]["lines"][0]
        self.assertEqual(row['unitLabel'], '米')
        self.assertNotIn('length', row['material_selection_snapshot']['attributes'])
        self.assertEqual(row['material_selection_snapshot']['unit_name'], '根')
        self.assertEqual(row["quantity"], "12")
        self.assertEqual(row['pipeInputMode'], 'TOTAL_METERS')

    def test_cannot_submit_new_legacy_line_or_mix_sources(self):
        self.setup_catalog()
        response = self.save_lines([self.line(rawMaterialId=str(uuid4()))], submit=True)
        self.assertEqual(response.status_code, 400, response.data)
        row = self.line()
        row.pop("material_catalog_id")
        row.pop("material_selection")
        row.update(name="手填", specification="M8", unitId=str(self.unit.pk))
        response = self.save_lines([row], submit=True)
        self.assertEqual(response.status_code, 400, response.data)

    def stock(self, row, quantity, suffix='A'):
        from apps.inventory.models import Warehouse, WarehouseZone
        from apps.inventory.public_stock_services import credit_public_stock
        from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
        warehouse, _ = Warehouse.objects.get_or_create(warehouse_number='U4-WH', defaults={'warehouse_name': 'U4隔离材料仓', 'warehouse_type': 'MATERIAL'})
        zone, _ = WarehouseZone.objects.get_or_create(warehouse=warehouse, zone_name=suffix)
        identity = build_catalog_stock_identity(material_catalog_id=row['material_catalog_id'], material_selection_snapshot=row['material_selection_snapshot'])
        return credit_public_stock(identity=identity, zone=zone, quantity=Decimal(quantity), source_type='MATERIAL_INBOUND',
            source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee).balance

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_saved_catalog_inventory_issue_and_retry_only_debit_selected_zone(self):
        self.setup_catalog()
        response = self.save_lines([self.line()], submit=True)
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data['data']['draft']['lines'][0]
        balance = self.stock(row, '12')
        other = self.stock(row, '30', suffix='B')
        current = self.client.get(self.root + 'warehouse-review/')
        candidates = self.client.get(self.root + 'warehouse-inventory/')
        self.assertEqual(candidates.status_code, 200, candidates.data)
        candidate = next(item for item in candidates.data['data']['lines'][0]['candidates'] if item['balanceId'] == str(balance.pk))
        warehouse = self.put('warehouse-review', {'lines': [{'key': row['key'], 'supplyQuantity': '12',
            'inventoryAllocations': [{**candidate, 'quantity': '12'}]}], 'notes': ''}, True, current['ETag'])
        self.assertEqual(warehouse.status_code, 200, warehouse.data)
        state = self.client.get(self.root + 'material-issue/')
        self.assertEqual(state.status_code, 200, state.data)
        started = self.client.post(self.root + 'material-issue/initiate/', {'client_request_id': str(uuid4())}, format='json', HTTP_IF_MATCH=state['ETag'])
        self.assertEqual(started.status_code, 200, started.data)
        request_id = str(uuid4())
        confirmed = self.client.post(self.root + 'material-issue/confirm/', {'request_id': request_id}, format='json', HTTP_IF_MATCH=started['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        retry = self.client.post(self.root + 'material-issue/confirm/', {'request_id': request_id}, format='json', HTTP_IF_MATCH=started['ETag'])
        self.assertEqual(retry.status_code, 200, retry.data)
        balance.refresh_from_db(); other.refresh_from_db()
        self.assertEqual(balance.quantity, 0)
        self.assertEqual(other.quantity, 30)

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_catalog_inventory_does_not_match_other_attributes_or_units(self):
        self.setup_catalog()
        response = self.save_lines([self.line()], submit=True)
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data['data']['draft']['lines'][0]
        balance = self.stock(row, '12')
        from apps.samples.warehouse_stock import stock_rows
        other = deepcopy(row)
        other['material_selection_snapshot']['attributes']['specification'] = 'M10'
        self.assertEqual(stock_rows(other)[1], [])
        self.assertEqual([entry[0].pk for entry in stock_rows(row)[1]], [balance.pk])

    def test_six_existing_categories_save_their_own_attributes(self):
        self.setup_catalog()
        entries = [
            ('tube', 'TUBE', 'TUBE', {'material': '铁', 'shape': '圆管', 'section_size': '25', 'thickness': '1.2', 'length': '3'}),
            ('hardware', 'HARDWARE', 'HARDWARE', {'specification': 'M8'}),
            ('plastic', 'PLASTIC', 'PLASTIC', {'model': 'P25'}),
            ('accessory', 'AUXILIARY', 'AUXILIARY_GENERAL', {'specification': 'A10'}),
            ('fabric', 'FABRIC', 'FABRIC', {'material': '涤纶', 'fabric_spec': '600D', 'width': '150', 'color': '黑色'}),
            ('packaging', 'PACKAGING', 'PACKAGING_GENERAL', {'specification': '40x30'}),
        ]
        lines = []
        for category, key, template, attrs in entries:
            self.catalog = MaterialCatalog.objects.create(category_key=key, template_key=template, name='U4-' + category)
            row = self.line(category=category)
            row['material_selection']['attributes'] = attrs
            if category == 'tube':
                from apps.reference_data.models import ProductionUnit
                root_unit, _ = ProductionUnit.objects.get_or_create(unit_name='根', defaults={'unit_code': 'U4ROOT'})
                row['material_selection']['unit_id'] = str(root_unit.pk)
            lines.append(row)
        response = self.save_lines(lines, submit=True)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row['material_selection_snapshot']['category_key'] for row in response.data['data']['draft']['lines']],
            [entry[1] for entry in entries])

    def test_new_unit_is_private_and_missing_etag_cannot_write(self):
        self.setup_catalog()
        row = self.line()
        row['material_selection'].pop('unit_id')
        row['material_selection']['unit_name'] = 'U4专用单位'
        denied = self.client.put(self.root + 'materials/', {'draft': {'lines': [row], 'notes': ''}, 'submit': False}, format='json')
        self.assertEqual(denied.status_code, 428, denied.data)
        self.assertFalse(self.catalog.allowed_units.exists())
        saved = self.save_lines([row])
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data['data']['draft']['lines'][0]['unitLabel'], 'U4专用单位')
        self.assertEqual(self.catalog.allowed_units.count(), 1)

    def test_view_without_change_cannot_add_missing_options(self):
        self.setup_catalog()
        self.user.user_permissions.remove(*Permission.objects.filter(content_type__app_label='material_catalog', codename='change_materialcatalog'))
        for key in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            self.user.__dict__.pop(key, None)
        response = self.save_lines([self.line()])
        self.assertEqual(response.status_code, 403, response.data)
        self.assertFalse(self.catalog.attribute_values.exists())

    def purchasing_access(self):
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=['inventory', 'procurement']))
        for key in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            self.user.__dict__.pop(key, None)

    def create_shortage_order(self, line, **purchase_values):
        from apps.procurement.models import PurchaseOrder
        from apps.samples.models import SampleMaterialProcurementRequest
        self.purchasing_access()
        response = self.save_lines([line], submit=True)
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data['data']['draft']['lines'][0]
        current = self.client.get(self.root + 'warehouse-review/')
        checked = self.put('warehouse-review', {'lines': [{'key': row['key'], 'supplyQuantity': '0', 'inventoryAllocations': []}], 'notes': ''}, True, current['ETag'])
        self.assertEqual(checked.status_code, 200, checked.data)
        procurement = SampleMaterialProcurementRequest.objects.get(material_request__sample_request_id=self.root.split('/')[-2])
        source = self.client.get('/api/v1/purchase-orders/source/', {'sample_procurement_request_id': str(procurement.pk)})
        self.assertEqual(source.status_code, 200, source.data)
        result = self.client.post('/api/v1/purchase-orders/', {'source_type': 'SAMPLE', 'sample_procurement_request_id': str(procurement.pk),
            'source_revision': source.data['data']['source_revision'], 'is_mailed': False,
            'lines': [{'sample_line_key': row['key'], 'actual_purchase_quantity': row['quantity'], 'unit_price': '2', **purchase_values}]}, format='json')
        self.assertEqual(result.status_code, 201, result.data)
        order = PurchaseOrder.objects.get(pk=result.data['data']['id'])
        # 本组验证U4来源与收货接线；采购表签发/进入采购中仍由U3专门链路验证。
        order.status = 'PURCHASING'
        order.save(update_fields=['status', 'updated_at'])
        return order, row

    def receive_and_issue(self, order, row):
        from apps.core.api.concurrency import etag_for_instance
        from apps.inventory.models import Warehouse, WarehouseZone, MaterialInbound, PublicStockBalance
        warehouse = Warehouse.objects.create(warehouse_number='U4-RECEIVE', warehouse_name='样品到货仓', warehouse_type='MATERIAL')
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='样品到货区')
        payload = {'purchase_order_id': str(order.pk), 'client_request_id': str(uuid4()),
            'items': [{'purchase_order_line_id': str(line.pk), 'zone_id': str(zone.pk)} for line in order.lines.all()]}
        result = self.client.post('/api/v1/material-inventory/sample-receivings/', payload, format='json', HTTP_IF_MATCH=etag_for_instance(order))
        self.assertEqual(result.status_code, 201, result.data)
        inbound = MaterialInbound.objects.get(pk=result.data['data']['id'])
        self.assertEqual(inbound.status, 'CONFIRMED')
        self.assertIsNone(inbound.quality_confirmed_at)
        replay = self.client.post('/api/v1/material-inventory/sample-receivings/', payload, format='json', HTTP_IF_MATCH=etag_for_instance(order))
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(MaterialInbound.objects.filter(purchase_order=order).count(), 1)
        changed = self.client.post('/api/v1/material-inventory/sample-receivings/', {**payload, 'remark': '不同请求内容'},
            format='json', HTTP_IF_MATCH=etag_for_instance(order))
        self.assertEqual(changed.status_code, 409, changed.data)
        issue = self.client.get(self.root + 'material-issue/')
        self.assertEqual(issue.status_code, 200, issue.data)
        started = self.client.post(self.root + 'material-issue/initiate/', {'client_request_id': str(uuid4())}, format='json', HTTP_IF_MATCH=issue['ETag'])
        self.assertEqual(started.status_code, 200, started.data)
        confirmed = self.client.post(self.root + 'material-issue/confirm/', {'request_id': str(uuid4())}, format='json', HTTP_IF_MATCH=started['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(PublicStockBalance.objects.get(material_catalog_id=self.catalog.pk).quantity, 0)
        return inbound

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_catalog_shortage_purchase_receiving_and_issue_preserve_snapshot(self):
        self.setup_catalog()
        order, row = self.create_shortage_order(self.line())
        frozen = deepcopy(order.lines.get().material_selection_snapshot)
        self.catalog.name = '采购后目录改名'
        self.catalog.save()
        self.catalog.attribute_values.update(value='采购后目录属性')
        inbound = self.receive_and_issue(order, row)
        self.assertEqual(inbound.lines.get().material_selection_snapshot, frozen)

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_pipe_mixed_actual_lengths_receipt_issue_and_replay(self):
        from apps.core.api.concurrency import etag_for_instance
        from apps.inventory.models import Warehouse, WarehouseZone, MaterialInbound, PublicStockBalance, PublicStockMovement
        from apps.procurement.models import PurchaseOrder
        from apps.reference_data.models import ProductionUnit
        from apps.samples.models import SampleMaterialProcurementRequest
        self.setup_catalog()
        self.purchasing_access()
        self.catalog.category_key = self.catalog.template_key = 'TUBE'
        self.catalog.save()
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name='根', defaults={'unit_code': 'U4ROOT'})
        ProductionUnit.objects.get_or_create(unit_name='米', defaults={'unit_code': 'U4METER'})
        line = self.line(category='tube', quantity='12')
        line['material_selection']['attributes'] = {'material': '铁', 'shape': '圆管', 'section_size': '25', 'thickness': '1.2', 'length': '属性不能猜实际长度'}
        saved = self.save_lines([line], submit=True)
        self.assertEqual(saved.status_code, 200, saved.data)
        row = saved.data['data']['draft']['lines'][0]
        self.assertEqual(row['unitLabel'], '米')
        self.assertEqual(row['material_selection_snapshot']['unit_name'], '根')
        warehouse = Warehouse.objects.create(warehouse_number='U4-MIXED', warehouse_name='两种实际长度', warehouse_type='MATERIAL')
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='同区分长')
        for count, length in ((4, '3.00'), (2, '6.00')):
            self.catalog.refresh_from_db()
            response = self.client.post('/api/v1/material-inventory/manual-receipts/', {
                'client_request_id': str(uuid4()), 'inbound_date': timezone.localdate().isoformat(),
                'remark': 'U4 R2实际长度隔离检查',
                'items': [{'material_catalog_id': str(self.catalog.pk), 'material_selection': {
                    'catalog_version': self.catalog.updated_at.isoformat(), 'scope': 'BASE', 'processing_state': 'RAW',
                    'attributes': row['material_selection_snapshot']['attributes'], 'unit_id': str(self.unit.pk)},
                    'zone_id': str(zone.pk), 'received_bar_count': count, 'raw_bar_length_m': length}]}, format='json')
            self.assertEqual(response.status_code, 201, response.data)
        candidates = self.client.get(self.root + 'warehouse-inventory/').data['data']['lines'][0]['candidates']
        self.assertEqual(len(candidates), 2)
        current = self.client.get(self.root + 'warehouse-review/')
        reviewed = self.put('warehouse-review', {'lines': [{'key': row['key'], 'supplyQuantity': '9',
            'inventoryAllocations': [{**candidate, 'quantity': '1'} for candidate in candidates]}], 'notes': ''}, True, current['ETag'])
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        procurement = SampleMaterialProcurementRequest.objects.get(material_request__sample_request_id=self.root.split('/')[-2])
        source = self.client.get('/api/v1/purchase-orders/source/', {'sample_procurement_request_id': str(procurement.pk)})
        purchased = self.client.post('/api/v1/purchase-orders/', {'source_type': 'SAMPLE', 'sample_procurement_request_id': str(procurement.pk),
            'source_revision': source.data['data']['source_revision'], 'is_mailed': False,
            'lines': [{'sample_line_key': row['key'], 'actual_purchase_quantity': '3', 'actual_bar_count': 1,
                'raw_bar_length_m': '3.00', 'unit_price': '2'}]}, format='json')
        self.assertEqual(purchased.status_code, 201, purchased.data)
        order = PurchaseOrder.objects.get(pk=purchased.data['data']['id'])
        order.status = 'PURCHASING'  # 仅本测试前置；不声称采购签发流程验收。
        order.save(update_fields=['status', 'updated_at'])
        purchase = order.lines.get()
        self.assertEqual(purchase.source_unit_text, '米')
        self.assertEqual(purchase.actual_purchase_quantity, 3)
        receipt_payload = {'purchase_order_id': str(order.pk), 'client_request_id': str(uuid4()),
            'items': [{'purchase_order_line_id': str(purchase.pk), 'zone_id': str(zone.pk)}]}
        received = self.client.post('/api/v1/material-inventory/sample-receivings/', receipt_payload, format='json', HTTP_IF_MATCH=etag_for_instance(order))
        self.assertEqual(received.status_code, 201, received.data)
        receipt = MaterialInbound.objects.get(pk=received.data['data']['id']).lines.get()
        self.assertEqual((receipt.accepted_bar_count, receipt.accepted_quantity, receipt.raw_bar_length_m), (1, 3, 3))
        state = self.client.get(self.root + 'material-issue/')
        started = self.client.post(self.root + 'material-issue/initiate/', {'client_request_id': str(uuid4())}, format='json', HTTP_IF_MATCH=state['ETag'])
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(started.data['data']['lines'][0]['barCount'], 3)
        # 到货流水丢失不能挪用同池余料；恢复准确来源后才允许确认。
        movement = PublicStockMovement.objects.get(source_type='MATERIAL_INBOUND', source_line_id=receipt.pk)
        PublicStockMovement.objects.filter(pk=movement.pk).update(source_line_id=uuid4())
        blocked = self.client.get(self.root + 'material-issue/')
        self.assertTrue(blocked.data['data']['blockers'])
        self.assertFalse(PublicStockMovement.objects.filter(direction='OUT').exists())
        PublicStockMovement.objects.filter(pk=movement.pk).update(source_line_id=receipt.pk)
        state = self.client.get(self.root + 'material-issue/')
        confirmation = {'request_id': str(uuid4())}
        confirmed = self.client.post(self.root + 'material-issue/confirm/', confirmation, format='json', HTTP_IF_MATCH=state['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        issued = confirmed.data['data']['lines'][0]
        self.assertEqual(issued['unitLabel'], '米')
        self.assertEqual(Decimal(issued['issuedQuantity']), 12)
        self.assertEqual(issued['barCount'], 3)
        self.assertEqual(sorted((Decimal(batch['rawBarLengthM']), batch['barCount'], Decimal(batch['meterQuantity'])) for batch in issued['pipeBatches']), [(Decimal(3), 2, Decimal(6)), (Decimal(6), 1, Decimal(6))])
        self.assertEqual(sorted((balance.raw_bar_length_m, balance.quantity, balance.meter_quantity) for balance in PublicStockBalance.objects.filter(material_catalog_id=self.catalog.pk)), [(Decimal(3), Decimal(3), Decimal(9)), (Decimal(6), Decimal(1), Decimal(6))])
        replay = self.client.post(self.root + 'material-issue/confirm/', confirmation, format='json', HTTP_IF_MATCH=state['ETag'])
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(PublicStockMovement.objects.filter(direction='OUT').count(), 2)
        self.assertEqual(self.client.get(self.root + 'material-issue/').data['data']['lines'][0]['pipeBatches'], issued['pipeBatches'])

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_catalog_pipe_root_quantity_and_meter_price_remain_separate(self):
        self.setup_catalog()
        self.catalog.category_key = self.catalog.template_key = 'TUBE'
        self.catalog.save()
        from apps.reference_data.models import ProductionUnit
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name='根', defaults={'unit_code': 'U4ROOT'})
        ProductionUnit.objects.get_or_create(unit_name='米', defaults={'unit_code': 'U4METER'})
        row = self.line(category='tube', quantity='3')
        row['material_selection']['attributes'] = {'material': '铁', 'shape': '圆管', 'section_size': '25', 'thickness': '1.2', 'length': '3'}
        order, saved = self.create_shortage_order(row, actual_bar_count=4, raw_bar_length_m='3.00', actual_purchase_quantity='12')
        purchase = order.lines.get()
        self.assertEqual(purchase.actual_purchase_quantity, 12)
        self.assertEqual(purchase.actual_purchase_meters, 12)
        self.assertEqual(purchase.amount, 24)
        inbound = self.receive_and_issue(order, saved)
        self.assertEqual(inbound.lines.get().accepted_quantity, 12)

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_manual_receipt_stock_and_sample_arrival_share_identity_without_issuing_other_stock(self):
        from apps.procurement.models import PurchaseOrder
        from apps.samples.models import SampleMaterialProcurementRequest
        from apps.inventory.models import Warehouse, WarehouseZone, PublicStockBalance
        self.setup_catalog()
        self.purchasing_access()
        saved = self.save_lines([self.line()], submit=True)
        self.assertEqual(saved.status_code, 200, saved.data)
        row = saved.data['data']['draft']['lines'][0]
        warehouse = Warehouse.objects.create(warehouse_number='U4-MANUAL', warehouse_name='手工入库仓', warehouse_type='MATERIAL')
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='同身份区')
        self.catalog.refresh_from_db()
        receipt = self.client.post('/api/v1/material-inventory/manual-receipts/', {
            'client_request_id': str(uuid4()), 'inbound_date': timezone.localdate().isoformat(), 'remark': 'U4隔离手工入库',
            'items': [{'material_catalog_id': str(self.catalog.pk), 'material_selection': {
                'catalog_version': self.catalog.updated_at.isoformat(), 'scope': 'BASE', 'processing_state': 'RAW',
                'attributes': row['material_selection_snapshot']['attributes'], 'unit_id': row['unitId']},
                'zone_id': str(zone.pk), 'received_quantity': '12'}]}, format='json')
        self.assertEqual(receipt.status_code, 201, receipt.data)
        lookup = self.client.get(self.root + 'warehouse-inventory/')
        self.assertEqual(lookup.status_code, 200, lookup.data)
        candidate = lookup.data['data']['lines'][0]['candidates'][0]
        current = self.client.get(self.root + 'warehouse-review/')
        checked = self.put('warehouse-review', {'lines': [{'key': row['key'], 'supplyQuantity': '4',
            'inventoryAllocations': [{**candidate, 'quantity': '4'}]}], 'notes': ''}, True, current['ETag'])
        self.assertEqual(checked.status_code, 200, checked.data)
        procurement = SampleMaterialProcurementRequest.objects.get(material_request__sample_request_id=self.root.split('/')[-2])
        source = self.client.get('/api/v1/purchase-orders/source/', {'sample_procurement_request_id': str(procurement.pk)})
        self.assertEqual(source.status_code, 200, source.data)
        result = self.client.post('/api/v1/purchase-orders/', {'source_type': 'SAMPLE', 'sample_procurement_request_id': str(procurement.pk),
            'source_revision': source.data['data']['source_revision'], 'is_mailed': False,
            'lines': [{'sample_line_key': row['key'], 'actual_purchase_quantity': '10', 'unit_price': '2'}]}, format='json')
        self.assertEqual(result.status_code, 201, result.data)
        order = PurchaseOrder.objects.get(pk=result.data['data']['id'])
        order.status = 'PURCHASING'
        order.save(update_fields=['status', 'updated_at'])
        # 同库区收10，安排4+实际到货10全领；原手工库存剩8，不能把同品库存全部领走。
        from apps.core.api.concurrency import etag_for_instance
        arrived = self.client.post('/api/v1/material-inventory/sample-receivings/', {'purchase_order_id': str(order.pk),
            'client_request_id': str(uuid4()), 'items': [{'purchase_order_line_id': str(order.lines.get().pk), 'zone_id': str(zone.pk)}]},
            format='json', HTTP_IF_MATCH=etag_for_instance(order))
        self.assertEqual(arrived.status_code, 201, arrived.data)
        issue = self.client.get(self.root + 'material-issue/')
        started = self.client.post(self.root + 'material-issue/initiate/', {'client_request_id': str(uuid4())}, format='json', HTTP_IF_MATCH=issue['ETag'])
        self.assertEqual(started.status_code, 200, started.data)
        confirmed = self.client.post(self.root + 'material-issue/confirm/', {'request_id': str(uuid4())}, format='json', HTTP_IF_MATCH=started['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        balance = PublicStockBalance.objects.get(material_catalog_id=self.catalog.pk)
        self.assertEqual(balance.quantity, 8)

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_wrong_receiving_zone_rolls_back_catalog_inbound_and_arrival(self):
        from apps.core.api.concurrency import etag_for_instance
        from apps.inventory.models import Warehouse, WarehouseZone, MaterialInbound, PublicStockMovement
        from apps.samples.models import SampleMaterialArrival
        self.setup_catalog()
        order, row = self.create_shortage_order(self.line())
        warehouse = Warehouse.objects.create(warehouse_number='U4-BAD', warehouse_name='不匹配半成品仓', warehouse_type='SEMI_FINISHED')
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='不匹配区')
        response = self.client.post('/api/v1/material-inventory/sample-receivings/', {'purchase_order_id': str(order.pk),
            'client_request_id': str(uuid4()), 'items': [{'purchase_order_line_id': str(order.lines.get().pk), 'zone_id': str(zone.pk)}]},
            format='json', HTTP_IF_MATCH=etag_for_instance(order))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(MaterialInbound.objects.filter(purchase_order=order).exists())
        self.assertFalse(PublicStockMovement.objects.exists())
        self.assertFalse(SampleMaterialArrival.objects.exists())

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_non_root_pipe_selection_rejects_without_partial_options(self):
        from apps.reference_data.models import ProductionUnit
        self.setup_catalog()
        self.catalog.category_key = self.catalog.template_key = 'TUBE'
        self.catalog.save()
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name='公斤', defaults={'unit_code': 'U4KG'})
        row = self.line(category='tube', quantity='1.25')
        row['material_selection']['attributes'] = {'material': '铁', 'shape': '圆管', 'section_size': '25', 'thickness': '1.2', 'length': '3'}
        result = self.save_lines([row])
        self.assertEqual(result.status_code, 400, result.data)
        self.assertFalse(self.catalog.attribute_values.exists())
        self.assertFalse(self.catalog.allowed_units.exists())

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_common_unit_rename_does_not_change_candidate_or_issued_saved_label(self):
        self.setup_catalog()
        saved = self.save_lines([self.line()], submit=True)
        self.assertEqual(saved.status_code, 200, saved.data)
        row = saved.data['data']['draft']['lines'][0]
        frozen_unit = row['unitLabel']
        self.stock(row, '12')
        self.unit.unit_name = 'R1单位后来改名'
        self.unit.save()
        lookup = self.client.get(self.root + 'warehouse-inventory/')
        self.assertEqual(lookup.status_code, 200, lookup.data)
        candidate = lookup.data['data']['lines'][0]['candidates'][0]
        self.assertEqual(candidate['unitLabel'], frozen_unit)
        current = self.client.get(self.root + 'warehouse-review/')
        reviewed = self.put('warehouse-review', {'lines': [{'key': row['key'], 'supplyQuantity': '12',
            'inventoryAllocations': [{**candidate, 'quantity': '12'}]}], 'notes': ''}, True, current['ETag'])
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        state = self.client.get(self.root + 'material-issue/')
        started = self.client.post(self.root + 'material-issue/initiate/', {'client_request_id': str(uuid4())}, format='json', HTTP_IF_MATCH=state['ETag'])
        self.assertEqual(started.status_code, 200, started.data)
        confirmed = self.client.post(self.root + 'material-issue/confirm/', {'request_id': str(uuid4())}, format='json', HTTP_IF_MATCH=started['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data['data']['lines'][0]['unitLabel'], frozen_unit)
        self.unit.unit_name = 'R1已领后再次改名'
        self.unit.save()
        reopened = self.client.get(self.root + 'material-issue/')
        self.assertEqual(reopened.status_code, 200, reopened.data)
        self.assertEqual(reopened.data['data']['lines'][0]['unitLabel'], frozen_unit)
