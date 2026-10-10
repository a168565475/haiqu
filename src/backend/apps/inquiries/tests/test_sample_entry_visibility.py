from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.inquiries.api.serializers import InquiryListSerializer
from apps.inquiries.models import InquiryStatus


class SampleEntryVisibilityTests(SimpleTestCase):
    def setUp(self):
        self.serializer = InquiryListSerializer(context={
            'request': SimpleNamespace(user=SimpleNamespace(has_perm=lambda permission: False)),
        })

    def test_only_accepted_quotation_stage_exposes_sample_entry(self):
        for status in InquiryStatus.values:
            with self.subTest(status=status):
                inquiry = SimpleNamespace(status=status, archived_at=None, list_items=[object()])
                self.assertEqual(self.serializer.get_allowed_actions(inquiry)['create_sample'], status == 'QUOTE_ACCEPTED')

    def test_accepted_stage_without_products_still_hides_entry(self):
        inquiry = SimpleNamespace(status='QUOTE_ACCEPTED', archived_at=None, list_items=[])
        self.assertFalse(self.serializer.get_allowed_actions(inquiry)['create_sample'])

    def test_no_request_cannot_expose_entry(self):
        self.assertFalse(InquiryListSerializer().get_allowed_actions(SimpleNamespace())['create_sample'])
