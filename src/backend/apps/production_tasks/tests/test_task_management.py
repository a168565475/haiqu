from decimal import Decimal
import json
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.boms.models import Bom, BomCreationMethod
from apps.files.models import BusinessFile

from ..models import ProductionRunBatch, ProductionTask, ProductionTaskProductImage, ProductionTaskStatus
from . import test_production_task_api as fixtures
from . import test_order_corrections as correction_fixtures


class ProductionTaskPatchContractTests(SimpleTestCase):
    def test_patch_accepts_creation_business_fields_without_identity(self):
        from ..api.serializers import ProductionTaskPatchSerializer
        fields = ProductionTaskPatchSerializer().fields
        for name in ('includes_tax', 'tax_rate', 'planner_id', 'order_date', 'salesperson_id',
                     'preproduction_sample_required', 'production_priority', 'production_batch_number'):
            self.assertIn(name, fields)
        self.assertNotIn('task_number', fields)

    def test_work_reports_convert_operation_counts_to_product_quantity(self):
        from ..services import _reported_quantity_lower_bound
        rows = [dict(work_item_id='cut', order_quantity_snapshot=10, required_quantity_snapshot=40, quantity=24),
                dict(work_item_id='cut', order_quantity_snapshot=10, required_quantity_snapshot=40, quantity=8),
                dict(work_item_id='pack', order_quantity_snapshot=10, required_quantity_snapshot=10, quantity=7)]
        self.assertEqual(_reported_quantity_lower_bound(rows), Decimal('8'))
        rows += [dict(work_item_id='old', order_quantity_snapshot=10, required_quantity_snapshot=None, quantity=1)] * 2
        self.assertEqual(_reported_quantity_lower_bound(rows), Decimal('10'))


class ProductionTaskManagementTests(APITestCase):
    setUp = fixtures.ProductionTaskApiTests.setUp
    payload = fixtures.ProductionTaskApiTests.payload
    create_task = fixtures.ProductionTaskApiTests.create_task

    def task(self):
        created = self.create_task()
        task = ProductionTask.objects.get(pk=created.data['data']['id'])
        return task, f'/api/v1/production-tasks/{task.pk}/'

    def delete(self, task, url, **headers):
        headers.setdefault('HTTP_IF_MATCH', self.client.get(url)['ETag'])
        return self.client.delete(url, **headers)

    def test_delete_requires_cancelled_and_etag_then_preserves_audit(self):
        task, url = self.task()
        self.assertEqual(self.delete(task, url).status_code, 409)
        task.status = ProductionTaskStatus.CANCELLED
        task.save()
        self.assertEqual(self.client.delete(url).status_code, 428)
        self.assertEqual(self.delete(task, url, HTTP_IF_MATCH='"old"').status_code, 412)
        line_id = task.products.get().pk
        image = BusinessFile.objects.create(original_name='shared.png', storage_key='unit/shared.png',
                                            content_type='image/png', size_bytes=1, scan_status='CLEAN')
        line = task.products.get()
        line.image_file = image
        line.save()
        response = self.delete(task, url)
        self.assertEqual(response.status_code, 204, getattr(response, 'data', None))
        self.assertFalse(ProductionTask.objects.filter(pk=task.pk).exists())
        audit = AuditLog.objects.get(object_id=task.pk, action='DELETED')
        self.assertEqual(audit.before_data['products'][0]['id'], str(line_id))
        self.assertEqual(audit.before_data['deleted_records']['products'][0]['image_file_id'], str(image.pk))
        self.assertTrue(BusinessFile.objects.filter(pk=image.pk).exists())
        self.assertTrue(AuditLog.objects.filter(object_id=task.pk, action='CREATED').exists())

    def test_delete_permission_and_downstream_protection(self):
        task, url = self.task()
        task.status = ProductionTaskStatus.CANCELLED
        task.save()
        self.user.user_permissions.remove(Permission.objects.get(codename='delete_productiontask'))
        for name in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            self.user.__dict__.pop(name, None)
        self.assertEqual(self.delete(task, url).status_code, 403)
        self.user.user_permissions.add(Permission.objects.get(codename='delete_productiontask'))
        for name in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            self.user.__dict__.pop(name, None)
        Bom.objects.create(bom_number='DELETE-PROTECT', production_task=task,
                           product_line=task.products.get(), creation_method=BomCreationMethod.BLANK,
                           order_quantity=10, created_by_employee=self.employee)
        self.assertEqual(self.delete(task, url).status_code, 409)
        self.assertTrue(ProductionTask.objects.filter(pk=task.pk).exists())
        self.assertFalse(AuditLog.objects.filter(object_id=task.pk, action='DELETED').exists())

    def test_delete_unstarted_run_but_protect_actual_run(self):
        task, url = self.task()
        task.status = ProductionTaskStatus.CANCELLED
        task.save()
        run = ProductionRunBatch.objects.create(production_task=task, batch_number='B1', planned_quantity=10,
                                               actual_quantity=1, good_quantity=1)
        self.assertEqual(self.delete(task, url).status_code, 409)
        run.actual_quantity = run.good_quantity = 0
        run.save()
        self.assertEqual(self.delete(task, url).status_code, 204)

    def test_delete_rejects_session_without_csrf(self):
        task, url = self.task()
        task.status = ProductionTaskStatus.CANCELLED
        task.save()
        self.user.set_password('session-test-password')
        self.user.save()
        client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(client.login(username=self.user.username, password='session-test-password'))
        response = client.delete(url, HTTP_IF_MATCH=self.client.get(url)['ETag'])
        self.assertEqual(response.status_code, 403, response.data)
        self.assertTrue(ProductionTask.objects.filter(pk=task.pk).exists())

    def test_audit_failure_rolls_back_deletion_and_header_edit(self):
        task, url = self.task()
        with patch('apps.production_tasks.services.write_audit_log', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                self.client.patch(url, {'production_priority': 'HIGH'}, format='json',
                                  HTTP_IF_MATCH=self.client.get(url)['ETag'])
        task.refresh_from_db()
        self.assertEqual(task.production_priority, 'NORMAL')
        task.status = ProductionTaskStatus.CANCELLED
        task.save()
        with patch('apps.production_tasks.services.write_audit_log', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                self.delete(task, url)
        self.assertTrue(task.products.exists())
        self.assertTrue(ProductionTask.objects.filter(pk=task.pk).exists())

    def test_actual_quantity_lower_bound_rolls_back_all_changes(self):
        task, url = self.task()
        task.actual_quantity = 9
        task.save()
        item = self.payload()['products'][0]
        item.update(client_key=str(task.products.get().pk), quantity=8)
        response = self.client.patch(url, {'production_priority': 'HIGH', 'products': [item]}, format='json',
                                    HTTP_IF_MATCH=self.client.get(url)['ETag'])
        self.assertEqual(response.status_code, 409, response.data)
        task.refresh_from_db()
        self.assertEqual(task.production_priority, 'NORMAL')
        self.assertEqual(task.products.get().quantity, 10)

    def test_new_header_fields_edit_during_production_and_tax_merge(self):
        task, url = self.task()
        for state in (ProductionTaskStatus.IN_PRODUCTION, ProductionTaskStatus.PAUSED):
            task.status = state
            task.save()
            response = self.client.patch(url, {'tax_rate': 5, 'preproduction_sample_required': False,
                'production_priority': 'HIGH', 'production_batch_number': 'B-EDIT',
                'planner_id': str(self.follower.pk), 'order_tolerance_percent': '7.00', 'is_repeat_order': True},
                format='json', HTTP_IF_MATCH=self.client.get(url)['ETag'])
            self.assertEqual(response.status_code, 200, response.data)
            task.refresh_from_db()
            self.assertEqual(task.status, state)
            self.assertEqual(task.tax_rate, 5)
            self.assertEqual(task.order_source, 'REPEAT')
        before = task.updated_at
        response = self.client.patch(url, {'includes_tax': False}, format='json',
                                    HTTP_IF_MATCH=self.client.get(url)['ETag'])
        self.assertEqual(response.status_code, 400, response.data)
        task.refresh_from_db()
        self.assertEqual(task.updated_at, before)
        response = self.client.patch(url, {'includes_tax': False, 'tax_rate': None}, format='json',
                                    HTTP_IF_MATCH=self.client.get(url)['ETag'])
        self.assertEqual(response.status_code, 200, response.data)

    def test_manual_product_edits_price_and_audits_material_and_specification(self):
        task, url = self.task()
        item = self.payload()['products'][0]
        item.update(client_key=str(task.products.get().pk), product_id=None, customer_product_name='手动产品',
                    customer_specification='新规格', material='钢', unit_price='19.25', quantity=12)
        response = self.client.patch(url, {'products': [item]}, format='json',
                                    HTTP_IF_MATCH=self.client.get(url)['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(task.products.get().unit_price, Decimal('19.25'))
        audit = AuditLog.objects.get(object_id=task.pk, action='UPDATED')
        self.assertEqual(audit.after_data['products'][0]['material'], '钢')
        self.assertEqual(audit.after_data['products'][0]['customer_specification'], '新规格')
        self.assertEqual(audit.after_data['products'][0]['unit_price'], '19.2500')

    def test_multi_batch_total_change_is_explicit_and_atomic(self):
        task, url = self.task()
        from ..models import ProductionDeliveryBatch
        batch = task.delivery_batches.first()
        if batch:
            batch.quantity = 6
            batch.save()
        else:
            ProductionDeliveryBatch.objects.create(production_task=task, line_number=1, quantity=6,
                                                    delivery_date=task.delivery_date)
        ProductionDeliveryBatch.objects.create(production_task=task, line_number=2, quantity=4,
                                                delivery_date=task.delivery_date)
        item = self.payload()['products'][0]
        item.update(client_key=str(task.products.get().pk), quantity=12)
        response = self.client.patch(url, {'products': [item]}, format='json',
                                    HTTP_IF_MATCH=self.client.get(url)['ETag'])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(task.products.get().quantity, 10)
        self.assertEqual(list(task.delivery_batches.values_list('quantity', flat=True)), [6, 4])

    def test_missing_product_fields_and_manual_empty_details_are_rejected(self):
        task, url = self.task()
        for products in ([{'client_key': str(task.products.get().pk)}],
                         [{**self.payload()['products'][0], 'client_key': str(task.products.get().pk), 'details': []}]):
            response = self.client.patch(url, {'products': products}, format='json',
                                        HTTP_IF_MATCH=self.client.get(url)['ETag'])
            self.assertEqual(response.status_code, 400, response.data)

    def test_replacing_primary_image_puts_new_upload_first_and_keeps_other_images(self):
        task, url = self.task()
        line = task.products.get()
        images = [BusinessFile.objects.create(original_name=f'{name}.png', storage_key=f'unit/{name}.png',
                                              content_type='image/png', size_bytes=1, scan_status='CLEAN')
                  for name in ('A', 'B', 'C')]
        line.image_file = images[0]
        line.save()
        for index, image in enumerate(images[:2], start=1):
            ProductionTaskProductImage.objects.create(product_line=line, line_number=index, image_file=image)
        item = self.payload()['products'][0]
        item.update(client_key=str(line.pk), retained_image_ids=[str(images[1].pk)], replace_primary_image=True)
        with patch('apps.production_tasks.services.save_scanned_image', return_value=images[2]):
            response = self.client.patch(url, {'payload': json.dumps({'products': [item]}),
                f'product_image_{line.pk}': SimpleUploadedFile('C.png', b'new', content_type='image/png')},
                format='multipart', HTTP_IF_MATCH=self.client.get(url)['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        read = self.client.get(url).data['data']['products'][0]
        self.assertEqual(read['image_name'], 'C.png')
        self.assertEqual([image['name'] for image in read['images']], ['C.png', 'B.png'])
        self.assertEqual(BusinessFile.objects.filter(pk__in=[image.pk for image in images]).count(), 3)


class ProductionTaskSalesManagementTests(APITestCase):
    setUp = correction_fixtures.SalesProductionCorrectionTests.setUp
    direct_payload = correction_fixtures.SalesProductionCorrectionTests.direct_payload
    create_direct = correction_fixtures.SalesProductionCorrectionTests.create_direct
    make_source_task = correction_fixtures.SalesProductionCorrectionTests.make_source_task

    def product_payload(self, line):
        return {'client_key': str(line.pk), 'product_id': str(line.product_id) if line.product_id else None,
                'product_color_id': str(line.product_color_id) if line.product_color_id else None,
                'color_code': line.color_code_snapshot, 'customer_color': line.customer_color_snapshot,
                'customer_product_name': line.customer_product_name_snapshot,
                'customer_specification': line.customer_specification_snapshot, 'material': line.material_snapshot,
                'quantity': int(line.quantity), 'unit_id': str(line.unit_id), 'currency_id': str(line.currency_id),
                'unit_price': str(line.unit_price), 'exchange_rate': str(line.exchange_rate),
                'details': []}

    def test_source_quantity_edit_has_nominal_limit_and_preserves_price_snapshot(self):
        task, created = self.make_source_task()
        url = f'/api/v1/production-tasks/{task.pk}/'
        line = task.products.get()
        limit = int(line.sales_order_delivery_batch_line.quantity)
        read = self.client.get(url)
        self.assertEqual(read.data['data']['products'][0]['max_production_quantity'], limit)
        item = self.product_payload(line)
        item['quantity'] = limit + 1
        response = self.client.patch(url, {'products': [item]}, format='json', HTTP_IF_MATCH=read['ETag'])
        self.assertEqual(response.status_code, 400, response.data)
        item['quantity'] = 5
        response = self.client.patch(url, {'products': [item]}, format='json', HTTP_IF_MATCH=read['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        refreshed = task.products.get()
        self.assertEqual(refreshed.quantity, 5)
        self.assertEqual(refreshed.exchange_rate_snapshot, line.exchange_rate_snapshot)
        self.assertEqual(refreshed.unit_price, line.unit_price)
        self.assertEqual(task.delivery_batches.get().quantity, 5)
        submitted = self.client.post(url + 'submit/', {}, format='json', HTTP_IF_MATCH=response['ETag'])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        item['material'] = '不得改的材质'
        response = self.client.patch(url, {'products': [item]}, format='json', HTTP_IF_MATCH=submitted['ETag'])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(task.products.get().material_snapshot, line.material_snapshot)

    def test_source_identity_and_salesperson_are_immutable(self):
        task, created = self.make_source_task()
        url = f'/api/v1/production-tasks/{task.pk}/'
        for data in ({'task_number': 'HT123'}, {'salesperson_id': str(self.employee.pk)},
                     {'order_date': task.order_date.isoformat()}, {'sales_order_id': str(task.sales_order_id)},
                     {'preproduction_sample_required': True}):
            response = self.client.patch(url, data, format='json', HTTP_IF_MATCH=created['ETag'])
            self.assertEqual(response.status_code, 400, response.data)

    def test_same_source_rows_are_checked_as_one_nominal_allocation(self):
        task, created = self.make_source_task()
        url = f'/api/v1/production-tasks/{task.pk}/'
        line = task.products.get()
        line.quantity = 5
        line.save()
        second = task.products.get()
        second.pk = None
        second.line_number = 2
        second.save()
        items = [self.product_payload(row) for row in task.products.all()]
        for row in items:
            row['quantity'] = 6
        response = self.client.patch(url, {'products': items}, format='json',
                                    HTTP_IF_MATCH=self.client.get(url)['ETag'])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(list(task.products.values_list('quantity', flat=True)), [5, 5])

    def test_other_task_allocation_reduces_limit_and_cancellation_releases_it(self):
        task, created = self.make_source_task()
        url = f'/api/v1/production-tasks/{task.pk}/'
        line = task.products.get()
        item = self.product_payload(line)
        item['quantity'] = 5
        patched = self.client.patch(url, {'products': [item]}, format='json', HTTP_IF_MATCH=created['ETag'])
        self.assertEqual(patched.status_code, 200, patched.data)
        other = self.client.post('/api/v1/production-tasks/create-from-sales-order/', {
            'task_number': 'HT26201', 'delivery_batch_line_id': str(line.sales_order_delivery_batch_line_id),
            'quantity': 4, 'follower_ids': [str(self.employee.pk)], 'delivery_date': task.delivery_date.isoformat(),
            'includes_tax': False, 'tax_rate': None, 'order_tolerance_percent': '100.00',
            'is_repeat_order': False, 'delivery_method': 'SINGLE',
        }, format='json')
        self.assertEqual(other.status_code, 201, other.data)
        self.assertEqual(self.client.get(url).data['data']['products'][0]['max_production_quantity'], 6)
        item['quantity'] = 7
        rejected = self.client.patch(url, {'products': [item]}, format='json', HTTP_IF_MATCH=patched['ETag'])
        self.assertEqual(rejected.status_code, 400, rejected.data)
        other_url = f"/api/v1/production-tasks/{other.data['data']['id']}/"
        cancelled = self.client.post(other_url + 'cancel/', {'reason': '释放占用'}, format='json', HTTP_IF_MATCH=other['ETag'])
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(self.client.get(url).data['data']['products'][0]['max_production_quantity'], 10)

    def test_legacy_sales_row_keeps_source_lock_when_line_link_is_missing(self):
        task, created = self.make_source_task()
        url = f'/api/v1/production-tasks/{task.pk}/'
        line = task.products.get()
        line.sales_order_delivery_batch_line = None
        line.save()
        read = self.client.get(url)
        self.assertEqual(read.data['data']['products'][0]['max_production_quantity'], 10)
        item = self.product_payload(line)
        item['unit_price'] = '99'
        rejected = self.client.patch(url, {'products': [item]}, format='json', HTTP_IF_MATCH=read['ETag'])
        self.assertEqual(rejected.status_code, 400, rejected.data)
