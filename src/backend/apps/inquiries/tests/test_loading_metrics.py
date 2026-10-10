from django.utils import timezone
from rest_framework.test import APITestCase

from ..models import Inquiry
from . import test_inquiry_api


class InquiryLoadingMetricsTests(APITestCase):
    setUp = test_inquiry_api.InquiryApiTests.setUp
    create_customer = test_inquiry_api.InquiryApiTests.create_customer

    def test_counts_match_lists_and_preserve_scope(self):
        for index, owner in enumerate([self.employee, self.other_employee, None]):
            Inquiry.objects.create(customer_account=self.customer, inquiry_number=f"LOAD-{index}",
                owner_employee=owner, subject="统计", received_at=timezone.now())
        Inquiry.objects.create(customer_account=self.other_customer, inquiry_number="LOAD-HIDDEN",
            owner_employee=self.other_employee, subject="不可见", received_at=timezone.now())
        Inquiry.objects.create(customer_account=self.customer, inquiry_number="LOAD-ARCHIVED",
            subject="已归档", received_at=timezone.now(), archived_at=timezone.now())
        response = self.client.get('/api/v1/inquiries/metrics/')
        self.assertEqual(response.status_code, 200, response.data)
        counts = response.data['data']['list_counts']
        for key, params in [('all', {}), ('mine', {'owner_employee_id': self.employee.pk}),
                            ('unassigned', {'assignment_status': 'UNASSIGNED'})]:
            listing = self.client.get('/api/v1/inquiries/', {**params, 'page_size': 1})
            self.assertEqual(listing.status_code, 200, listing.data)
            self.assertEqual(counts[key], listing.data['meta']['total'])
        self.assertEqual(counts, {'all': 3, 'mine': 1, 'unassigned': 1})
        self.user.user_permissions.clear()
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get('/api/v1/inquiries/metrics/').status_code, 403)
