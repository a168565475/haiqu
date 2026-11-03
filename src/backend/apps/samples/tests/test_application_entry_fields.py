from rest_framework.test import APITestCase

from apps.crm.models import CustomerTimelineEvent
from apps.organizations.models import EmployeeRoleAssignment
from apps.product_catalog.models import ProductCatalog
from apps.product_catalog.tests.test_product_entry_drafts import typed_product_draft
from ..models import SampleRequest
from . import test_application_api as fixtures
from . import test_application_products as product_fixtures
from . import test_application_basics as basic_fixtures


class SampleApplicationEntryFieldsTests(APITestCase):
    setUp = fixtures.SampleApplicationApiTests.setUp
    create_customer = fixtures.SampleApplicationApiTests.create_customer
    payload = fixtures.SampleApplicationApiTests.payload
    submit = fixtures.SampleApplicationApiTests.submit
    review = fixtures.SampleApplicationApiTests.review
    product = product_fixtures.SampleApplicationProductsTests.product
    prepared = product_fixtures.SampleApplicationProductsTests.prepared
    save = product_fixtures.SampleApplicationProductsTests.save
    basic = basic_fixtures.SampleApplicationBasicEditTests.basic

    def remove_sales_role(self):
        EmployeeRoleAssignment.objects.filter(employee=self.employee, role_profile__role_code='SALESPERSON').delete()

    def test_create_number_and_selected_color_without_creating_product_master(self):
        before = ProductCatalog.objects.count()
        created = self.submit(self.payload(manual_request_number='123', product_catalog_id=None,
                                          product_selection={'draft': typed_product_draft()}))
        self.assertEqual(created.status_code, 201, created.data)
        sample = SampleRequest.objects.get(pk=created.data['data']['id'])
        self.assertEqual(sample.request_number, 'HTS123')
        self.assertEqual(sample.manual_request_number, '123')
        self.assertIsNone(sample.products.get().product_catalog_id)
        self.assertEqual(ProductCatalog.objects.count(), before)
        detail = sample.items.get()
        self.assertEqual((detail.product_color_id, detail.color_card_snapshot, detail.color_code_snapshot, detail.color_name_snapshot),
                         (self.product_color.pk, self.product_color.color_card, self.product_color.color_code, self.product_color.color_name))
        duplicate = self.submit(self.payload(manual_request_number='123'))
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        for number in ('', 'HTS123', 'HTS-123', '含空 格'):
            response = self.submit(self.payload(manual_request_number=number))
            self.assertEqual(response.status_code, 400, response.data)

    def test_non_salesperson_creates_without_customer_and_still_has_workflow(self):
        self.remove_sales_role()
        before = CustomerTimelineEvent.objects.count()
        payload = self.payload(product_catalog_id=None, product_selection={'draft': typed_product_draft()})
        payload.pop('customer_account_id')
        payload.pop('customer_contact_id')
        created = self.submit(payload)
        self.assertEqual(created.status_code, 201, created.data)
        sample = SampleRequest.objects.get(pk=created.data['data']['id'])
        self.assertIsNone(sample.customer_account_id)
        self.assertIsNone(sample.customer_contact_id)
        self.assertEqual(CustomerTimelineEvent.objects.count(), before)
        approved = self.review(created)
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data['data']['customer_name'], '')
        self.assertTrue(approved.data['data']['application_actions']['can_edit_products'])
        product = approved.data['data']['products'][0]
        edited = self.save(approved, {'purpose': '修改内部样品', 'basic': self.basic(manual_request_number='EMPTY123'),
            'products': [{'id': product['id'], 'product_catalog_id': None,
                'product_selection': {'draft': typed_product_draft(name='内部新样品')},
                'product_name': '内部新样品', 'specification': product['specification'],
                'details': [{'id': product['details'][0]['id'], 'product_color_id': str(self.product_color.pk),
                             'sample_quantity': 4, 'tolerance': 'NONE'}]}]})
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(edited.data['data']['request_number'], 'HTSEMPTY123')
        self.assertIsNone(edited.data['data']['customer_account'])
        self.assertEqual(edited.data['data']['products'][0]['product_name'], '内部新样品')

    def test_hidden_customer_is_preserved_and_number_can_change_with_etag(self):
        approved, _, payload = self.prepared()
        self.remove_sales_role()
        self.second_product_color.color_card = '另一色卡'
        self.second_product_color.save(update_fields=['color_card'])
        payload['products'][0]['details'][0]['product_color_id'] = str(self.second_product_color.pk)
        payload['basic'] = self.basic(manual_request_number='EDIT123', customer_account_id=str(self.other_customer.pk), customer_contact_id=None)
        saved = self.save(approved, payload)
        self.assertEqual(saved.status_code, 200, saved.data)
        sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
        self.assertEqual(sample.customer_account_id, self.customer.pk)
        self.assertEqual(sample.customer_contact_id, self.contact.pk)
        self.assertEqual(sample.request_number, 'HTSEDIT123')
        detail = sample.items.get()
        self.assertEqual((detail.product_color_id, detail.color_card_snapshot, detail.color_code_snapshot, detail.color_name_snapshot),
                         (self.second_product_color.pk, '另一色卡', self.second_product_color.color_code, self.product_color.color_name))
        self.assertEqual(self.save(approved, payload).status_code, 412)

    def test_existing_number_is_not_rewritten_and_role_flag_uses_effective_role(self):
        approved, _, payload = self.prepared()
        sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
        sample.manual_request_number = 'OLD123'
        sample.request_number = 'HTS-OLD123'
        sample.save(update_fields=['manual_request_number', 'request_number', 'updated_at'])
        current = self.client.get(f'/api/v1/sample-requests/{sample.pk}/')
        payload['basic'] = self.basic(manual_request_number='OLD123')
        saved = self.save(current, payload)
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data['data']['request_number'], 'HTS-OLD123')
        self.assertTrue(self.client.get('/api/v1/sample-requests/form-options/').data['data']['is_salesperson'])
        self.remove_sales_role()
        self.assertFalse(self.client.get('/api/v1/sample-requests/form-options/').data['data']['is_salesperson'])
