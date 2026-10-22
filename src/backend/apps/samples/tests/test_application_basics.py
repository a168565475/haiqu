import uuid

from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.customers.models import CustomerContact
from ..models import SampleRequest, SampleRequestStatus
from . import test_application_api as application_tests
from . import test_application_products as product_tests


class SampleApplicationBasicEditTests(APITestCase):
    setUp = product_tests.SampleApplicationProductsTests.setUp
    create_customer = product_tests.SampleApplicationProductsTests.create_customer
    payload = product_tests.SampleApplicationProductsTests.payload
    submit = product_tests.SampleApplicationProductsTests.submit
    review = product_tests.SampleApplicationProductsTests.review
    product = product_tests.SampleApplicationProductsTests.product
    prepared = product_tests.SampleApplicationProductsTests.prepared
    save = product_tests.SampleApplicationProductsTests.save
    create_inquiry_with_item = application_tests.SampleApplicationApiTests.create_inquiry_with_item

    def basic(self, **updates):
        return {
            **{key: value for key, value in self.payload().items() if key in {
                'customer_account_id', 'customer_contact_id', 'owner_employee_id',
                'source_type', 'source_id', 'sample_type', 'shipping_method',
                'delivery_batch', 'is_repeat_order', 'order_date', 'sample_due_date',
            }},
            **updates,
        }

    def test_basic_fields_edit_after_finished_preserves_rows_and_workflow(self):
        approved, _, data = self.prepared()
        completed = self.save(approved, data)
        self.assertEqual(completed.status_code, 200, completed.data)
        sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
        sample.status = SampleRequestStatus.FINISHED
        sample.save(update_fields=['status', 'updated_at'])
        rows = list(sample.products.values_list('id', flat=True)), list(sample.items.values_list('id', flat=True))
        workflow = list(sample.workflow_records.values_list('id', flat=True))
        current = self.client.get(f'/api/v1/sample-requests/{sample.pk}/')
        data['basic'] = self.basic(sample_type='TESTING', shipping_method='OTHER', delivery_batch='PARTIAL',
                                   is_repeat_order=True, order_date='2026-10-21', sample_due_date='2026-10-30',
                                   owner_employee_id=str(self.other_employee.pk), customer_contact_id=None)
        response = self.save(current, data)
        self.assertEqual(response.status_code, 200, response.data)
        sample.refresh_from_db()
        self.assertEqual(sample.status, SampleRequestStatus.FINISHED)
        self.assertEqual(sample.sample_type, 'TESTING')
        self.assertEqual(sample.shipping_method, 'OTHER')
        self.assertEqual(sample.delivery_batch, 'PARTIAL')
        self.assertTrue(sample.is_repeat_order)
        self.assertEqual(sample.owner_employee_id, self.other_employee.pk)
        self.assertIsNone(sample.customer_contact_id)
        self.assertEqual(str(sample.order_date), '2026-10-21')
        self.assertEqual(str(timezone.localtime(sample.requested_due_at).date()), '2026-10-30')
        self.assertEqual(rows, (list(sample.products.values_list('id', flat=True)), list(sample.items.values_list('id', flat=True))))
        self.assertEqual(list(sample.workflow_records.values_list('id', flat=True)), workflow)
        self.assertEqual(self.save(current, data).status_code, 412)

    def test_source_can_change_or_clear_without_recreating_product_rows(self):
        approved, _, data = self.prepared()
        inquiry, source_item = self.create_inquiry_with_item()
        data['basic'] = self.basic(source_type='inquiry', source_id=str(inquiry.pk), owner_employee_id=str(self.other_employee.pk))
        response = self.save(approved, data)
        self.assertEqual(response.status_code, 200, response.data)
        sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
        self.assertEqual(sample.source_inquiry_id, inquiry.pk)
        self.assertEqual(sample.transaction_entity_id, self.entity.pk)
        self.assertEqual(sample.owner_employee_id, self.other_employee.pk)
        product = sample.products.get()
        detail = sample.items.get()
        product.source_inquiry_item = source_item
        product.save(update_fields=['source_inquiry_item'])
        detail.source_inquiry_item = source_item
        detail.save(update_fields=['source_inquiry_item'])
        data['basic'] = self.basic()
        cleared = self.save(response, data)
        self.assertEqual(cleared.status_code, 200, cleared.data)
        sample.refresh_from_db(); product.refresh_from_db(); detail.refresh_from_db()
        self.assertIsNone(sample.source_inquiry_id)
        self.assertIsNone(sample.transaction_entity_id)
        self.assertIsNone(product.source_inquiry_item_id)
        self.assertIsNone(detail.source_inquiry_item_id)
        self.assertEqual(str(product.pk), data['products'][0]['id'])
        self.assertEqual(str(detail.pk), data['products'][0]['details'][0]['id'])

    def test_customer_can_change_to_accessible_customer_with_its_contact(self):
        approved, _, data = self.prepared()
        customer = self.create_customer('EDIT_CUSTOMER', '可改选客户', self.employee)
        contact = CustomerContact.objects.create(customer_account=customer, display_name='新客户联系人')
        data['basic'] = self.basic(customer_account_id=str(customer.pk), customer_contact_id=str(contact.pk))
        response = self.save(approved, data)
        self.assertEqual(response.status_code, 200, response.data)
        sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
        self.assertEqual(sample.customer_account_id, customer.pk)
        self.assertEqual(sample.customer_contact_id, contact.pk)

    def test_invalid_basic_data_rolls_back_product_edits(self):
        approved, _, data = self.prepared()
        self.other_employee.status = 'INACTIVE'
        self.other_employee.save(update_fields=['status'])
        inaccessible_source, _ = self.create_inquiry_with_item(number='INQ-FOREIGN', customer=self.other_customer, owner=self.other_employee)
        own_source, _ = self.create_inquiry_with_item(number='INQ-OWN')
        new_customer = self.create_customer('DIFFERENT_OWNER_CUSTOMER', '另一个可访问客户', self.employee)
        for changes in [
            {'customer_account_id': str(self.other_customer.pk)},
            {'customer_contact_id': str(uuid.uuid4())},
            {'owner_employee_id': str(self.other_employee.pk)},
            {'sample_due_date': '2026-09-01'},
            {'source_type': 'inquiry'},
            {'source_type': 'inquiry', 'source_id': str(inaccessible_source.pk)},
            {'customer_account_id': str(new_customer.pk)},
            {'customer_account_id': str(new_customer.pk), 'customer_contact_id': None, 'source_type': 'inquiry', 'source_id': str(own_source.pk)},
        ]:
            with self.subTest(changes=changes):
                data['basic'] = self.basic(**changes)
                response = self.save(approved, data)
                self.assertEqual(response.status_code, 400, response.data)
                sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
                self.assertIsNone(sample.products.get().category_id)
                self.assertEqual(sample.status, SampleRequestStatus.PENDING_COMPLETION)

    def test_changing_source_requires_source_permission(self):
        approved, _, data = self.prepared()
        inquiry, _ = self.create_inquiry_with_item()
        data['basic'] = self.basic(source_type='inquiry', source_id=str(inquiry.pk))
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='inquiries', codename='view_inquiry'))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        response = self.save(approved, data)
        self.assertEqual(response.status_code, 403, response.data)

    def test_edit_source_context_uses_edit_permission_and_keeps_creation_rules(self):
        approved, _, _ = self.prepared()
        inquiry, _ = self.create_inquiry_with_item()
        inquiry.status = 'DRAFT'
        inquiry.save(update_fields=['status'])
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='samples', codename='add_samplerequest'))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        query = {'sourceType': 'inquiry', 'sourceId': str(inquiry.pk)}
        response = self.client.get(f"/api/v1/sample-requests/{approved.data['data']['id']}/application-source-context/", query)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['customer']['id'], str(self.customer.pk))
        self.assertEqual(self.client.get('/api/v1/sample-requests/form-context/', query).status_code, 403)
