from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.access_control.models import MaterialSectionGrant
from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.inventory.models import MaterialInbound, MaterialInboundLine
from apps.organizations.models import Employee
from apps.procurement.models import PurchaseOrderLine
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory

from . import test_inbound_loading as loading_fixture
from . import test_purchase_saved_material_receipts as saved_material_fixture


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class PurchaseReceivingSectionTests(ScopedActorMixin, APITestCase):
    make_order = loading_fixture.InboundLoadingTests.make_order
    get = loading_fixture.InboundLoadingTests.get

    def setUp(self):
        loading_fixture.InboundLoadingTests.setUp(self)
        self.line.category_snapshot = '型材'
        self.line.save(update_fields=['category_snapshot'])
        self.hardware = PurchaseOrderLine.objects.create(
            purchase_order=self.order, line_number=2, quantity_parse_status='READY',
            section_type_snapshot='ACCESSORY', section_title_snapshot='五金件',
            actual_purchase_quantity=10, supplier_name_snapshot='五金专用供应商',
        )
        self.packaging = self.order.lines.create(
            line_number=3, quantity_parse_status='READY', section_title_snapshot='包材', actual_purchase_quantity=5,
        )
        self.order.lines.create(
            line_number=4, quantity_parse_status='READY', section_title_snapshot='面料', actual_purchase_quantity=3,
        )
        self.scoped_actor()
        grant = self.grant('inventory.receive_material', 'MATERIAL')
        self.selection = MaterialSectionGrant.objects.create(grant=grant, sections=['TUBE'])

    def test_manager_can_replace_and_copy_material_sections(self):
        admin = get_user_model().objects.create_superuser('admin')
        Employee.objects.create(user=admin, employee_code='RECEIVING-ADMIN', display_name='收货权限管理员')
        self.client.force_authenticate(admin)
        root = f'/api/v1/access/roles/{self.selection.grant.role_id}/'
        role = self.client.get(root)
        self.assertEqual(role.status_code, 200, role.data)
        options = self.client.get('/api/v1/access/catalog/scope-options/')
        self.assertIn({'id': 'TUBE', 'name': '管材', 'active': True}, options.data['material_sections'])
        grants = [{'permission': 'inventory.receive_material', 'scope': 'MATERIAL',
                   'resource_ids': ['HARDWARE', 'TUBE']}]
        saved = self.client.put(root + 'grants/', {'grants': grants}, format='json', HTTP_IF_MATCH=role['ETag'])
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data['grants'], grants)
        copied = self.client.post(root + 'copy/', {'role_code': 'RECEIVING_COPY', 'display_name': '仓管复制'},
                                  format='json', HTTP_IF_MATCH=saved['ETag'])
        self.assertEqual(copied.status_code, 201, copied.data)
        self.assertEqual(copied.data['grants'], grants)

    def test_list_and_eligible_lines_show_only_assigned_sections(self):
        options = self.get('options', {'scope': 'receiving', 'include_catalog_semi': 'true'}).json()['data']
        self.assertIn(str(self.zone.pk), [zone['id'] for zone in options['zones']])
        self.assertEqual(self.client.get(self.root + 'options/').status_code, 403)
        rows = self.get('procurement-inbound-orders').data['data']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['receiving_sections'], [{'id': 'A', 'name': '管材'}])
        self.assertEqual(rows[0]['line_count'], 1)
        self.assertFalse(self.get('procurement-inbound-orders', {'q': '五金专用供应商'}).data['data'])
        params = {'purchase_order_id': str(self.order.pk)}
        lines = self.get('eligible-lines', params).json()['data']
        self.assertEqual([line['id'] for line in lines], [str(self.line.pk)])
        denied = self.client.get(self.root + 'eligible-lines/', {**params, 'material_section': 'B'})
        self.assertEqual(denied.status_code, 403)

    def test_receiving_status_and_quality_count_follow_assigned_sections(self):
        def summary(expected):
            row = self.get('procurement-inbound-orders').data['data'][0]
            fields = ('receiving_status', 'remaining_line_count', 'pending_quality_count')
            self.assertEqual(tuple(row[field] for field in fields), expected)

        def receive(number, lines):
            inbound = MaterialInbound.objects.create(
                inbound_number=number, purchase_order=self.order, received_by_employee=self.employee,
            )
            for line, quantity in lines:
                MaterialInboundLine.objects.create(
                    inbound=inbound, purchase_order_line=line, raw_material_information=self.raw_material,
                    zone=self.zone, received_quantity=quantity, accepted_quantity=quantity,
                    purchased_quantity_snapshot=line.actual_purchase_quantity,
                    section_title_snapshot=line.section_title_snapshot, category_snapshot=line.category_snapshot,
                )
            return inbound

        receive('SECTION-HARDWARE', [(self.hardware, 10), (self.packaging, 2)])
        summary(('PENDING_RECEIPT', 1, 0))

        first = receive('SECTION-TUBE-1', [(self.line, 4)])
        summary(('PARTIAL_RECEIVED', 1, 1))
        second = receive('SECTION-TUBE-2', [(self.line, 6)])
        summary(('RECEIPT_COMPLETE', 0, 2))
        MaterialInbound.objects.filter(pk__in=[first.pk, second.pk]).update(status='CONFIRMED')
        summary(('COMPLETED', 0, 0))

        self.selection.sections = ['TUBE', 'HARDWARE', 'PACKAGING']
        self.selection.save(update_fields=['sections'])
        summary(('PARTIAL_RECEIVED', 1, 1))

    def test_detail_keeps_original_batch_and_filters_mixed_history(self):
        inbound = MaterialInbound.objects.create(
            inbound_number='RECEIVING-SECTION-OLD', purchase_order=self.order, received_by_employee=self.employee,
        )
        for line, section in [(self.line, '型材'), (self.hardware, '五金件')]:
            MaterialInboundLine.objects.create(
                inbound=inbound, purchase_order_line=line, raw_material_information=self.raw_material, zone=self.zone,
                section_title_snapshot=section, received_quantity=2, accepted_quantity=2, purchased_quantity_snapshot=10,
                supplier_name_snapshot=f'{section}供应商',
            )
        response = self.client.get(f'/api/v1/purchase-orders/{self.order.pk}/details/')
        self.assertEqual(response.status_code, 200, response.data)
        detail = response.json()['data']
        self.assertEqual([row['id'] for row in detail['lines']], [str(self.line.pk)])
        self.assertEqual(detail['inbounds'][0]['inbound_number'], inbound.inbound_number)
        self.assertEqual(detail['inbounds'][0]['material_section'], '')
        self.assertEqual([row['purchase_order_line_id'] for row in detail['inbounds'][0]['lines']], [str(self.line.pk)])
        self.assertEqual(self.get('procurement-inbound-orders').data['data'][0]['received_quantity'], '2.0000')
        records = self.get('purchase-receipt-records', {'section': 'UNASSIGNED'}).data
        self.assertEqual([item['id'] for item in records['sections']], ['A', 'UNASSIGNED'])
        self.assertEqual(records['data'][0]['line_count'], 1)
        self.assertFalse(records['data'][0]['can_quality_confirm'])
        self.assertEqual(records['data'][0]['supplier_names'], ['型材供应商'])
        self.assertEqual(self.get('purchase-receipt-records', {'q': '五金件供应商'}).data['data'], [])
        unfiltered = self.get('purchase-receipt-records', {'q': self.order.production_task_number_snapshot}).data
        self.assertEqual(len(unfiltered['data']), 1)
        self.assertEqual(unfiltered['data'][0]['production_task_number'], self.order.production_task_number_snapshot)
        self.assertEqual(unfiltered['data'][0]['material_section_display'], '未登记')
        root = self.root + 'purchase-receipt-records/'
        detail = self.client.get(root + f'{inbound.pk}/')
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual([str(row['purchase_order_line_id']) for row in detail.data['data']['lines']], [str(self.line.pk)])
        self.assertEqual(self.get('purchase-receipt-records', {'section': 'B'}).data['data'], [])

    def test_multiple_assigned_sections_and_atomic_rejection(self):
        def item(line):
            return {'purchase_order_line_id': str(line.pk), 'zone_id': str(self.zone.pk),
                    'received_quantity': '1', 'expected_remaining_quantity': '10'}

        for path in ('receivings', 'receipts', 'batch-receipts'):
            response = self.client.post(self.root + path + '/', {'items': [item(self.hardware)]}, format='json')
            self.assertEqual(response.status_code, 403, response.data)
        self.selection.sections = ['TUBE', 'HARDWARE', 'PACKAGING', 'FABRIC']
        self.selection.save(update_fields=['sections'])
        rows = self.get('procurement-inbound-orders').data['data']
        self.assertEqual(rows[0]['receiving_sections'], [
            {'id': 'A', 'name': '管材'}, {'id': 'B', 'name': '五金件、塑料件'}, {'id': 'C', 'name': '面料、辅料'},
            {'id': 'D', 'name': '包材'},
        ])
        eligible = self.get('eligible-lines', {'purchase_order_id': self.order.pk, 'material_section': 'B'}).json()
        self.assertEqual(eligible['material_section_display'], '五金件、塑料件')
        lines = eligible['data']
        self.assertEqual({line['id'] for line in lines}, {str(self.hardware.pk)})
        eligible = self.get('eligible-lines', {'purchase_order_id': self.order.pk, 'material_section': 'D'}).json()
        self.assertEqual(eligible['material_section_display'], '包材')
        self.assertEqual([line['id'] for line in eligible['data']], [str(self.packaging.pk)])
        response = self.client.post(self.root + 'receivings/', {
            'material_section': 'A', 'items': [item(self.line), item(self.hardware)],
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(MaterialInbound.objects.exists())

    def test_quality_keeps_complete_historical_b_record(self):
        self.grant('inventory.quality_confirm_material')
        inbound = MaterialInbound.objects.create(
            inbound_number='RECEIVING-OLD-B', purchase_order=self.order, received_by_employee=self.employee,
            material_section='B',
        )
        for line in (self.hardware, self.packaging):
            MaterialInboundLine.objects.create(
                inbound=inbound, purchase_order_line=line, raw_material_information=self.raw_material,
                zone=self.zone, section_title_snapshot=line.section_title_snapshot,
                received_quantity=2, accepted_quantity=2, purchased_quantity_snapshot=line.actual_purchase_quantity,
            )
        root = self.root + 'purchase-receipt-records/'
        row = self.client.get(root, {'section': 'B'}).data['data'][0]
        self.assertEqual(row['material_section_display'], '五金件、塑料件、包材（历史）')
        self.assertTrue(row['can_quality_confirm'])
        self.assertEqual(row['line_count'], 2)
        detail = self.client.get(self.root + f'quality-batches/{inbound.pk}/')
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data['data']['material_section'], 'B')
        self.assertEqual(len(detail.data['data']['lines']), 2)
        self.assertFalse(self.client.get(root, {'section': 'D'}).data['data'])


@override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class AuthorizedSectionReceiptTests(ScopedActorMixin, APITestCase):
    payload = saved_material_fixture.PurchaseSavedMaterialReceiptsTests.payload

    def test_ordinary_receiver_can_submit_a_partial_receipt_for_an_assigned_section(self):
        saved_material_fixture.PurchaseSavedMaterialReceiptsTests.setUp(self)
        self.scoped_actor()
        grant = self.grant('inventory.receive_material', 'MATERIAL')
        MaterialSectionGrant.objects.create(grant=grant, sections=['HARDWARE', 'PACKAGING'])
        category, _ = ProductCategory.objects.get_or_create(category_name='包材', defaults={'item_type': 'MATERIAL'})
        material = RawMaterialInformation.objects.create(
            material_number='SECTION-BOX', item_type='MATERIAL', category=category, unit=self.raw_material.unit,
            material_name='验收纸箱', specification='验收规格',
        )
        packaging = self.purchase_line.purchase_order.lines.create(
            line_number=2, quantity_parse_status='READY', section_type_snapshot='ACCESSORY',
            section_title_snapshot='包材', category_snapshot='包材', part_name_snapshot=material.material_name,
            raw_material_snapshot=material.material_number, source_unit_text=self.purchase_line.source_unit_text,
            actual_purchase_quantity=5, calculation_snapshot={
                'schema_version': 1, 'source': 'PRODUCTION_PURCHASE', 'raw_material_id': str(material.pk),
                'unit_id': str(material.unit_id),
            },
        )
        body = {**self.payload(), 'material_section': 'B'}
        body['items'].append({**body['items'][0], 'purchase_order_line_id': str(packaging.pk),
                              'received_quantity': '1', 'expected_remaining_quantity': '5'})
        mixed = self.client.post('/api/v1/material-inventory/receivings/', body, format='json')
        self.assertEqual(mixed.status_code, 400, mixed.data)
        self.assertFalse(MaterialInbound.objects.exists())
        body = {**body, 'material_section': 'D', 'items': [body['items'][1]]}
        response = self.client.post('/api/v1/material-inventory/receivings/', body, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        record = MaterialInbound.objects.get(pk=response.data['data']['id'])
        self.assertEqual(record.purchase_order_id, self.purchase_line.purchase_order_id)
        self.assertEqual(record.received_by_employee, self.scope_employee)
        self.assertEqual(record.status, 'PENDING_QUALITY')
        self.assertEqual(record.material_section, 'D')
        self.assertEqual(set(record.lines.values_list('purchase_order_line_id', flat=True)), {packaging.pk})
        detail = self.client.get(f'/api/v1/purchase-orders/{record.purchase_order_id}/details/', {'receiving': '1'})
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data['data']['inbounds'][0]['material_section_display'], '包材')
