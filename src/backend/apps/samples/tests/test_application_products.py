import uuid

from django.contrib.auth.models import Permission
from django.middleware.csrf import _get_new_csrf_string
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.files.models import BusinessFile
from ..models import SampleInventoryLine, SampleInventoryReceipt, SampleRequest, SampleRequestStatus, SampleWorkflowStage
from . import test_application_api as application_tests
from . import test_application_identity as identity_tests


class SampleApplicationProductsTests(APITestCase):
    setUp = application_tests.SampleApplicationApiTests.setUp
    create_customer = application_tests.SampleApplicationApiTests.create_customer
    payload = application_tests.SampleApplicationApiTests.payload
    submit = application_tests.SampleApplicationApiTests.submit
    review = application_tests.SampleApplicationApiTests.review
    product = identity_tests.SampleApplicationIdentityTests.product

    def prepared(self, **updates):
        selected = self.product(str(uuid.uuid4())[:8])
        created = self.submit(self.payload(order_date=None, sample_due_date=None, **updates))
        approved = self.review(created)
        self.assertEqual(approved.status_code, 200, approved.data)
        product = approved.data['data']['products'][0]
        data = {'purpose': '完善后的要求', 'products': [{
            'id': product['id'], 'product_id': str(selected.pk), 'category_id': str(self.product_category.pk),
            'product_name': selected.product_name, 'specification': selected.specification,
            'length_cm': '51.25', 'armrest_width_cm': None, 'seat_width_cm': None,
            'back_height_cm': None, 'seat_height_cm': None,
            'details': [{'id': product['details'][0]['id'], 'product_color_id': str(self.product_color.pk),
                         'color_code': self.product_color.color_code, 'sample_quantity': 5, 'tolerance': 'NONE', 'notes': '注意靠背'}],
        }]}
        return approved, selected, data

    def save(self, approved, data, etag=None, client=None):
        return (client or self.client).patch(
            f"/api/v1/sample-requests/{approved.data['data']['id']}/application-products/",
            data, format='json', HTTP_IF_MATCH=etag or approved['ETag'],
        )

    def test_complete_nullable_dates_real_product_color_and_material_handoff(self):
        approved, selected, data = self.prepared()
        response = self.save(approved, data)
        self.assertEqual(response.status_code, 200, response.data)
        sample = response.data['data']
        product = sample['products'][0]
        self.assertEqual(sample['status'], 'MATERIALS_PENDING')
        self.assertFalse(sample['edit_capabilities']['can_complete'])
        self.assertTrue(sample['application_actions']['can_edit_materials'])
        self.assertTrue(sample['application_actions']['can_edit_products'])
        self.assertIsNone(sample['order_date'])
        self.assertIsNone(sample['sample_due_date'])
        self.assertEqual(sample['request_number'], approved.data['data']['request_number'])
        self.assertEqual(product['product_id'], str(selected.pk))
        self.assertEqual(product['product_number_snapshot'], selected.product_number)
        self.assertEqual(product['total_sample_quantity'], 5)
        self.assertEqual(product['length_cm'], '51.25')
        self.assertEqual(product['details'][0]['color_name'], self.product_color.color_name)
        self.assertIsNone(product['task_sheet_file_id'])
        self.assertNotEqual(response['ETag'], approved['ETag'])
        self.assertTrue(AuditLog.objects.filter(object_id=sample['id'], action='REQUIREMENTS_COMPLETED').exists())
        self.assertEqual(self.save(approved, data).status_code, 412)
        updated = self.save(response, data)
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data['data']['status'], 'MATERIALS_PENDING')
        self.assertTrue(AuditLog.objects.filter(object_id=sample['id'], action='PRODUCT_REQUIREMENTS_UPDATED').exists())
        # 产品保存后的版本可以直接用于现有无需用料接口；旧版本仍拒绝。
        url = f"/api/v1/sample-requests/{sample['id']}/no-materials/"
        self.assertEqual(self.client.post(url, {}, format='json', HTTP_IF_MATCH=approved['ETag']).status_code, 412)
        self.assertEqual(self.client.post(url, {}, format='json', HTTP_IF_MATCH=updated['ETag']).status_code, 200)

    def test_products_remain_editable_at_every_stage_without_restarting_workflow(self):
        approved, _, data = self.prepared()
        completed = self.save(approved, data)
        self.assertEqual(completed.status_code, 200, completed.data)
        sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
        workflow = list(sample.workflow_records.values_list('id', flat=True))
        for status in SampleRequestStatus.values:
            with self.subTest(status=status):
                sample.status = status
                sample.save(update_fields=['status', 'updated_at'])
                current = self.client.get(f'/api/v1/sample-requests/{sample.pk}/')
                self.assertTrue(current.data['data']['application_actions']['can_edit_products'])
                data['purpose'] = f'阶段 {status} 的修订'
                saved = self.save(current, data)
                self.assertEqual(saved.status_code, 200, saved.data)
                self.assertEqual(saved.data['data']['status'], status)
                self.assertEqual(saved.data['data']['purpose'], data['purpose'])
                self.assertEqual(list(sample.workflow_records.values_list('id', flat=True)), workflow)
                self.assertEqual(self.save(current, data).status_code, 412)

    def test_legacy_materials_pending_first_completion_is_recorded_once(self):
        approved, _, data = self.prepared()
        sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
        sample.status = SampleRequestStatus.MATERIALS_PENDING
        sample.save(update_fields=['status', 'updated_at'])
        current = self.client.get(f'/api/v1/sample-requests/{sample.pk}/')
        self.assertTrue(current.data['data']['edit_capabilities']['can_complete'])
        first = self.save(current, data)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertFalse(first.data['data']['edit_capabilities']['can_complete'])
        second = self.save(first, data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(sample.workflow_records.filter(stage=SampleWorkflowStage.REQUIREMENTS_COMPLETED).count(), 1)
        self.assertEqual(AuditLog.objects.filter(object_id=sample.pk, action='REQUIREMENTS_COMPLETED').count(), 1)

    def test_product_quantity_cannot_fall_below_cumulative_inventory(self):
        approved, _, data = self.prepared()
        completed = self.save(approved, data)
        self.assertEqual(completed.status_code, 200, completed.data)
        sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
        sample.status = SampleRequestStatus.FINISHED
        sample.save(update_fields=['status', 'updated_at'])
        detail = sample.items.get()
        for number in range(2):
            receipt = SampleInventoryReceipt.objects.create(
                receipt_number=f'QA-EDIT-INVENTORY-{number}', submitted_by_employee=self.employee,
                submitted_at=timezone.now(),
            )
            SampleInventoryLine.objects.create(receipt=receipt, sample_item=detail,
                product_name_snapshot=detail.product_description_snapshot, sampling_quantity=5,
                received_quantity=2, location='测试样品库')
        current = self.client.get(f'/api/v1/sample-requests/{sample.pk}/')
        data['products'][0]['details'][0]['sample_quantity'] = 3
        denied = self.save(current, data)
        self.assertEqual(denied.status_code, 400, denied.data)
        self.assertIn('累计已入库数量', str(denied.data))
        detail.refresh_from_db()
        self.assertEqual(detail.sample_quantity, 5)
        data['products'][0]['details'][0]['sample_quantity'] = 4
        accepted = self.save(current, data)
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertEqual(accepted.data['data']['status'], 'FINISHED')
        self.assertEqual(accepted.data['data']['products'][0]['details'][0]['sample_quantity'], 4)

    def test_invalid_input_rolls_back_without_advancing_stage(self):
        approved, _, data = self.prepared()
        for key, invalid in [('product_id', str(uuid.uuid4())), ('category_id', None), ('length_cm', '-1'), ('product_name', '')]:
            with self.subTest(key=key):
                original = data['products'][0][key]
                data['products'][0][key] = invalid
                self.assertEqual(self.save(approved, data).status_code, 400)
                data['products'][0][key] = original
        data['products'][0]['details'][0]['sample_quantity'] = 0
        self.assertEqual(self.save(approved, data).status_code, 400)
        data['products'][0]['details'][0]['sample_quantity'] = 2147483648
        self.assertEqual(self.save(approved, data).status_code, 400)
        sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
        self.assertEqual(sample.status, 'PENDING_COMPLETION')
        self.assertIsNone(sample.products.get().category_id)

    def test_validation_after_product_update_rolls_back_entire_transaction(self):
        approved, _, data = self.prepared()
        sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
        product = sample.products.get()
        detail = product.details.get()
        detail.cutting_reported_quantity = 3
        detail.save(update_fields=['cutting_reported_quantity'])
        data['products'][0]['details'][0]['sample_quantity'] = 2
        self.assertEqual(self.save(approved, data).status_code, 400)
        product.refresh_from_db(); sample.refresh_from_db()
        self.assertIsNone(product.category_id)
        self.assertEqual(sample.status, 'PENDING_COMPLETION')

    def test_custom_name_and_manual_specification_clear_formal_identity(self):
        for mode in ('null', 'omitted', 'stale_id'):
            with self.subTest(mode=mode):
                approved, selected, data = self.prepared()
                product = SampleRequest.objects.get(pk=approved.data['data']['id']).products.get()
                product.product = selected
                product.product_number_snapshot = selected.product_number
                product.product_code_snapshot = selected.product_code
                product.item_number_snapshot = selected.product_item.item_number
                product.material_snapshot = '旧材质'
                product.product_image = BusinessFile.objects.create(original_name='旧图.png', storage_key=f'fixtures/{uuid.uuid4()}.png', content_type='image/png', size_bytes=1, scan_status='CLEAN')
                product.save()
                values = data['products'][0]
                values.update(product_name='自定义新品', specification='手工规格 71×48')
                if mode == 'null':
                    values['product_id'] = None
                elif mode == 'omitted':
                    values.pop('product_id')
                response = self.save(approved, data)
                self.assertEqual(response.status_code, 200, response.data)
                product.refresh_from_db()
                self.assertIsNone(product.product_id)
                self.assertIsNone(product.product_image_id)
                for field in ('product_number_snapshot', 'product_code_snapshot', 'item_number_snapshot', 'material_snapshot'):
                    self.assertEqual(getattr(product, field), '', field)
                self.assertEqual(product.product_name, '自定义新品')
                self.assertEqual(product.specification, '手工规格 71×48')
                self.assertEqual(product.details.get().specification_snapshot, '手工规格 71×48')

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_sample_only_identity_can_read_candidates_options_and_save(self):
        approved, selected, data = self.prepared()
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label='samples', codename__in=['view_samplerequest', 'complete_sample_requirements']))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        url = f"/api/v1/sample-requests/{approved.data['data']['id']}/application-product-options/"
        self.assertEqual(self.client.get('/api/v1/products/').status_code, 403)
        self.assertEqual(self.client.get('/api/v1/sample-requests/form-options/').status_code, 200)
        candidates = self.client.get(url, {'q': selected.product_name})
        self.assertEqual(candidates.status_code, 200, candidates.data)
        self.assertEqual(candidates.data['data'], [{'id': str(selected.pk), 'product_name': selected.product_name, 'specification': selected.specification, 'category_id': str(selected.category_id)}])
        self.assertEqual(self.client.get(url, {'q': 'a' * 201}).status_code, 400)
        self.assertEqual(self.save(approved, data).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 200)

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_candidates_and_save_reject_missing_permission_and_foreign_sample(self):
        approved, _, data = self.prepared()
        url = f"/api/v1/sample-requests/{approved.data['data']['id']}/application-product-options/"
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label='samples', codename='view_samplerequest'))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        self.assertFalse(self.client.get(f"/api/v1/sample-requests/{approved.data['data']['id']}/").data['data']['application_actions']['can_edit_products'])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.save(approved, data).status_code, 403)
        self.other_user.user_permissions.set(Permission.objects.filter(content_type__app_label='samples', codename__in=['view_samplerequest', 'complete_sample_requirements']))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.other_user.pk))
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.save(approved, data).status_code, 404)

    def test_foreign_or_duplicate_product_and_detail_ids_are_rejected(self):
        approved, _, data = self.prepared()
        product = data['products'][0]
        original = product['id']
        product['id'] = str(uuid.uuid4())
        self.assertEqual(self.save(approved, data).status_code, 400)
        product['id'] = original
        product['details'][0]['id'] = str(uuid.uuid4())
        self.assertEqual(self.save(approved, data).status_code, 400)
        data['products'].append(dict(product))
        self.assertEqual(self.save(approved, data).status_code, 400)

    def test_permission_and_missing_version(self):
        approved, _, data = self.prepared()
        url = f"/api/v1/sample-requests/{approved.data['data']['id']}/application-products/"
        self.assertEqual(self.client.patch(url, data, format='json').status_code, 428)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='samples', codename='complete_sample_requirements'))
        # 重新读取用户，防止前次请求留下权限缓存。
        self.user.refresh_from_db()
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.save(approved, data).status_code, 403)

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_ordinary_identity_module_permission(self):
        approved, _, data = self.prepared()
        self.assertEqual(self.save(approved, data).status_code, 200)

    def test_session_csrf_and_edit_before_director_approval(self):
        approved, _, data = self.prepared()
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(self.save(approved, data, client=client).status_code, 403)
        csrf = _get_new_csrf_string()
        client.cookies['csrftoken'] = csrf
        client.credentials(HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(self.save(approved, data, client=client).status_code, 200)
        created = self.submit()
        product = created.data['data']['products'][0]
        data['products'][0]['id'] = product['id']
        data['products'][0]['details'][0]['id'] = product['details'][0]['id']
        saved = self.save(created, data, client=client)
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data['data']['status'], 'DIRECTOR_REVIEW')
        self.assertFalse(SampleRequest.objects.get(pk=created.data['data']['id']).workflow_records.filter(
            stage=SampleWorkflowStage.REQUIREMENTS_COMPLETED,
        ).exists())
