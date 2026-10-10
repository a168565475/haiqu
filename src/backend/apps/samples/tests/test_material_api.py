import uuid
from copy import deepcopy
from unittest.mock import patch
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient, APITestCase
from apps.reference_data.models import ProductionUnit
from apps.audit.models import AuditLog
from ..models import SampleMaterialRequest, SampleMaterialProcurementRequest
from . import test_application_api as application_tests


class SampleMaterialApiTests(APITestCase):
    setUp = application_tests.SampleApplicationApiTests.setUp
    create_customer = application_tests.SampleApplicationApiTests.create_customer
    create_inquiry_with_item = application_tests.SampleApplicationApiTests.create_inquiry_with_item
    create_quotation_version_with_line = application_tests.SampleApplicationApiTests.create_quotation_version_with_line
    payload = application_tests.SampleApplicationApiTests.payload
    submit = application_tests.SampleApplicationApiTests.submit
    review = application_tests.SampleApplicationApiTests.review

    def prepare(self):
        approved = self.review(self.submit())
        self.assertEqual(approved.status_code, 200, approved.data)
        self.root = f"/api/v1/sample-requests/{approved.data['data']['id']}/"
        self.unit = ProductionUnit.objects.create(unit_code='QA_MATERIAL', unit_name='验收米')
        return approved

    def draft(self, quantities=('12', '6', '4')):
        # 通用交接用例保留小数单位和明确原料身份；管材由独立根米专项覆盖。
        from apps.reference_data.models import ProductCategory
        from apps.products.models import RawMaterialInformation
        category, _ = ProductCategory.objects.get_or_create(category_name='五金', defaults={'item_type': 'MATERIAL'})
        lines = []
        for i, quantity in enumerate(quantities):
            material, _ = RawMaterialInformation.objects.get_or_create(material_number=f'SAMPLE-GENERIC-{i}', defaults={
                'item_type': 'MATERIAL', 'category': category, 'material_name': f'五金{i}',
                'specification': '25×1.2', 'material': '6063', 'unit': self.unit,
            })
            lines.append({'key': str(uuid.uuid4()), 'category': 'hardware', 'rawMaterialId': str(material.pk),
                          'name': material.material_name, 'specification': material.specification, 'material': material.material,
                          'color': '黑色', 'quantity': quantity, 'unitId': str(self.unit.pk), 'notes': ''})
        return {'lines': lines, 'notes': '材料备注'}

    def put(self, endpoint, draft, submit, etag, client=None):
        return (client or self.client).put(self.root + endpoint + '/', {'draft': draft, 'submit': submit}, format='json', HTTP_IF_MATCH=etag)

    def to_warehouse(self):
        self.prepare()
        state = self.client.get(self.root + 'materials/')
        result = self.put('materials', self.draft(), True, state['ETag'])
        self.assertEqual(result.status_code, 200, result.data)
        return self.client.get(self.root + 'warehouse-review/')

    def supplies(self, response, values=('12', '2', '0')):
        return {'lines': [{'key': line['key'], 'supplyQuantity': value} for line, value in zip(response.data['data']['draft']['lines'], values)], 'notes': '请采购缺口材料'}

    def test_material_draft_reload_submit_and_freeze(self):
        self.prepare()
        state = self.client.get(self.root + 'materials/')
        self.assertTrue(state.data['data']['canEdit'])
        draft = self.draft()
        saved = self.put('materials', draft, False, state['ETag'])
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(self.client.get(self.root + 'materials/').data['data']['draft']['lines'][0]['color'], '黑色')
        submitted = self.put('materials', draft, True, saved['ETag'])
        self.assertEqual(submitted.data['data']['status'], 'WAREHOUSE_PENDING')
        self.assertFalse(submitted.data['data']['canEdit'])
        self.assertEqual(self.put('materials', draft, False, submitted['ETag']).status_code, 409)
        record = SampleMaterialRequest.objects.get()
        self.assertEqual(record.submitted_by_id, self.employee.pk)
        self.assertIsNotNone(record.submitted_at)

    def test_incomplete_draft_allowed_but_submit_rejected(self):
        self.prepare()
        state = self.client.get(self.root + 'materials/')
        draft = self.draft(('',))
        draft['lines'][0].update(name='', specification='', unitId='')
        saved = self.put('materials', draft, False, state['ETag'])
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(self.put('materials', draft, True, saved['ETag']).status_code, 400)

    def test_invalid_quantity_unit_and_duplicate_keys_are_rejected(self):
        self.prepare()
        state = self.client.get(self.root + 'materials/')
        for value in ['-1', '1e3', '0', '0.00001', '100000000000000']:
            self.assertEqual(self.put('materials', self.draft((value,)), True, state['ETag']).status_code, 400)
        draft = self.draft()
        draft['lines'][1]['key'] = draft['lines'][0]['key']
        self.assertEqual(self.put('materials', draft, False, state['ETag']).status_code, 400)
        draft = self.draft()
        draft['lines'][0]['unitId'] = 'bad-unit'
        self.assertEqual(self.put('materials', draft, True, state['ETag']).status_code, 400)
        self.unit.status = 'INACTIVE'
        self.unit.save()
        self.assertEqual(self.put('materials', self.draft(), True, state['ETag']).status_code, 400)
        self.assertFalse(SampleMaterialRequest.objects.exists())

    def test_shortage_snapshot_atomic_and_no_duplicate_submission(self):
        state = self.to_warehouse()
        draft = self.supplies(state)
        saved = self.put('warehouse-review', draft, False, state['ETag'])
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertFalse(SampleMaterialProcurementRequest.objects.exists())
        self.assertEqual(self.client.get(self.root + 'warehouse-review/').data['data']['draft']['lines'][1]['supplyQuantity'], '2')
        done = self.put('warehouse-review', draft, True, saved['ETag'])
        self.assertEqual(done.status_code, 200, done.data)
        self.assertEqual(done.data['data']['status'], 'PROCUREMENT_PENDING')
        self.assertEqual(done.data['data']['statusLabel'], '等待采购')
        self.assertFalse(done.data['data']['canEdit'])
        demand = SampleMaterialProcurementRequest.objects.get()
        self.assertEqual([line['shortageQuantity'] for line in demand.lines], ['4', '4'])
        self.assertTrue(all(line['color'] == '黑色' for line in demand.lines))
        self.assertEqual(self.put('warehouse-review', draft, True, saved['ETag']).status_code, 412)
        self.assertEqual(self.put('warehouse-review', draft, True, done['ETag']).status_code, 409)
        self.assertEqual(SampleMaterialProcurementRequest.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(action='WAREHOUSE_CONFIRMED').exists())

    def test_fully_supplied_does_not_create_procurement(self):
        state = self.to_warehouse()
        done = self.put('warehouse-review', self.supplies(state, ('12', '6', '4')), True, state['ETag'])
        self.assertEqual(done.status_code, 200, done.data)
        self.assertEqual(done.data['data']['status'], 'MATERIAL_ISSUE_PENDING')
        self.assertFalse(SampleMaterialProcurementRequest.objects.exists())

    def test_warehouse_cannot_change_demand_or_skip_lines(self):
        state = self.to_warehouse()
        for values in [('', '2', '0'), ('13', '2', '0'), ('-1', '2', '0'), ('0.00001', '2', '0')]:
            self.assertEqual(self.put('warehouse-review', self.supplies(state, values), True, state['ETag']).status_code, 400)
        self.assertEqual(self.put('warehouse-review', self.supplies(state, ('1',)), False, state['ETag']).status_code, 400)
        draft = self.supplies(state)
        draft['lines'][0]['quantity'] = '999'
        result = self.put('warehouse-review', draft, True, state['ETag'])
        self.assertEqual(result.data['data']['draft']['lines'][0]['quantity'], '12')

    def test_permissions_scope_and_etag(self):
        state = self.to_warehouse()
        self.other_user.user_permissions.set(Permission.objects.filter(content_type__app_label='samples', codename__in=['view_samplerequest', 'review_sample_materials']))
        client = APIClient()
        client.force_authenticate(user=self.other_user)
        self.assertEqual(client.get(self.root + 'warehouse-review/').status_code, 200)
        self.assertEqual(self.put('materials', self.draft(), False, state['ETag'], client).status_code, 403)
        self.assertEqual(self.put('warehouse-review', self.supplies(state), False, '', client).status_code, 428)
        self.assertEqual(self.put('warehouse-review', self.supplies(state), False, state['ETag'], client).status_code, 200)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='samples', codename='review_sample_materials'))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        current = self.client.get(self.root + 'warehouse-review/')
        self.assertFalse(current.data['data']['canEdit'])
        self.assertEqual(self.put('warehouse-review', self.supplies(state), True, current['ETag']).status_code, 403)

    def test_procurement_failure_rolls_back_status_supply_and_audit(self):
        state = self.to_warehouse()
        with patch('apps.samples.material_services.SampleMaterialProcurementRequest.objects.create', side_effect=RuntimeError('test rollback')):
            with self.assertRaises(RuntimeError):
                self.put('warehouse-review', self.supplies(state), True, state['ETag'])
        record = SampleMaterialRequest.objects.get()
        self.assertIsNone(record.reviewed_at)
        self.assertEqual(record.warehouse_draft, {})
        self.assertEqual(record.sample_request.status, 'WAREHOUSE_PENDING')
        self.assertFalse(AuditLog.objects.filter(action='WAREHOUSE_CONFIRMED').exists())

    def test_reload_does_not_expose_system_inventory_reference(self):
        state = self.to_warehouse()
        saved = self.put('warehouse-review', self.supplies(state, ('0.1', '2', '0')), False, state['ETag'])
        refreshed = self.client.get(self.root + 'warehouse-review/')
        self.assertEqual(saved['ETag'], refreshed['ETag'])
        self.assertEqual(refreshed.data['data']['draft']['lines'][0]['supplyQuantity'], '0.1')
        self.assertNotIn('inventoryMatch', refreshed.data['data']['draft']['lines'][0])
        self.assertNotIn('inventoryUpdatedAt', refreshed.data['data'])

    def test_material_editor_minimal_permissions_can_load_units_and_submit(self):
        self.prepare()
        self.other_user.user_permissions.set(Permission.objects.filter(content_type__app_label='samples', codename__in=['view_samplerequest', 'edit_sample_materials']))
        client = APIClient()
        client.force_authenticate(user=self.other_user)
        units = client.get('/api/v1/sample-requests/material-units/')
        self.assertEqual(units.status_code, 200)
        self.assertTrue(any(row['id'] == str(self.unit.pk) for row in units.data['data']))
        state = client.get(self.root + 'materials/')
        self.assertTrue(state.data['data']['canEdit'])
        self.assertEqual(self.put('materials', self.draft(), True, state['ETag'], client).status_code, 200)

    def test_procurement_role_can_find_real_queue_and_immutable_shortages(self):
        state = self.to_warehouse()
        done = self.put('warehouse-review', self.supplies(state), True, state['ETag'])
        self.assertEqual(done.status_code, 200)
        self.other_user.user_permissions.set(Permission.objects.filter(content_type__app_label='samples', codename__in=['view_samplerequest', 'view_sample_procurement']))
        client = APIClient()
        client.force_authenticate(user=self.other_user)
        queue = client.get('/api/v1/sample-requests/?status=PROCUREMENT_PENDING')
        self.assertEqual(queue.status_code, 200, queue.data)
        self.assertEqual(len(queue.data['data']), 1)
        self.assertEqual(queue.data['data'][0]['material_summary']['label'], '等待采购')
        self.assertEqual(queue.data['data'][0]['status_display'], '等待采购')
        result = client.get(self.root + 'warehouse-review/')
        self.assertEqual(len(result.data['data']['procurementRequest']['lines']), 2)
        self.assertFalse(result.data['data']['canEdit'])
        materials = client.get(self.root + 'materials/')
        self.assertEqual(materials.status_code, 200, materials.data)
        self.assertEqual(materials.data['data']['procurementRequest']['id'], result.data['data']['procurementRequest']['id'])

    def test_department_permission_does_not_expose_earlier_customer_stage(self):
        self.prepare()
        for permission in ['review_sample_materials', 'view_sample_procurement']:
            self.other_user.user_permissions.set(Permission.objects.filter(content_type__app_label='samples', codename__in=['view_samplerequest', permission]))
            client = APIClient()
            client.force_authenticate(user=type(self.other_user).objects.get(pk=self.other_user.pk))
            self.assertEqual(client.get(self.root + 'materials/').status_code, 404)
