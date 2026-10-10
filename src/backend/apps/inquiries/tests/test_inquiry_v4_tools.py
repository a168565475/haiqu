from django.contrib.auth.models import Permission
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APITestCase

from apps.inquiries.models import Inquiry, InquiryItem
from apps.inquiries.models import InquirySlaLink
from apps.workflow.models import SlaPolicy, SlaTracking
from apps.preferences.api.serializers import SavedViewSerializer
from apps.inquiries.selectors import inquiry_display_stage
from types import SimpleNamespace
from .test_inquiry_api import InquiryApiTests


class InquiryV4ToolsTests(APITestCase):
    setUp = InquiryApiTests.setUp
    create_customer = InquiryApiTests.create_customer
    inquiry_payload = InquiryApiTests.inquiry_payload
    create_inquiry = InquiryApiTests.create_inquiry

    def test_amount_filter_uses_product_totals_and_exact_currency(self):
        inquiry_id = self.create_inquiry().data['data']['id']
        InquiryItem.objects.filter(inquiry_id=inquiry_id).update(quantity='3', target_unit_price='0.25', target_currency_code='USD')
        path = '/api/v1/inquiries/'
        for amount, currency, count in [('0.75', 'USD', 1), ('0.75000001', 'USD', 0), ('0', 'CNY', 0)]:
            response = self.client.get(path, {'amount_min': amount, 'amount_currency': currency})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['meta']['total'], count)
        InquiryItem.objects.filter(inquiry_id=inquiry_id).update(target_unit_price=None)
        self.assertEqual(self.client.get(path, {'amount_min': '0', 'amount_currency': 'USD'}).data['meta']['total'], 0)

    def test_missing_or_invalid_amount_currency_is_rejected(self):
        for query in [{'amount_min': '10'}, {'amount_currency': 'USD'}, {'amount_min': '-1', 'amount_currency': 'USD'}, {'amount_min': 'NaN', 'amount_currency': 'USD'}, {'amount_min': '10', 'amount_currency': 'US1'}]:
            self.assertEqual(self.client.get('/api/v1/inquiries/', query).status_code, 400, query)

    def test_missing_price_on_other_line_does_not_pretend_complete_amount(self):
        inquiry_id = self.create_inquiry().data['data']['id']
        InquiryItem.objects.filter(inquiry_id=inquiry_id).update(quantity='2', target_unit_price='5000', target_currency_code='USD')
        InquiryItem.objects.create(inquiry_id=inquiry_id, line_number=2, product_description='待补价', quantity='1', unit_code='PCS')
        response = self.client.get('/api/v1/inquiries/', {'amount_min': '10000', 'amount_currency': 'USD'})
        self.assertEqual(response.data['meta']['total'], 0)

    def test_delete_preview_is_read_only_and_requires_delete_permission(self):
        inquiry_id = self.create_inquiry().data['data']['id']
        before = Inquiry.objects.get(pk=inquiry_id).updated_at
        response = self.client.get(f'/api/v1/inquiries/{inquiry_id}/deletion-preview/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('ETag', response)
        self.assertEqual(response.data['data']['quotation_count'], 0)
        self.assertEqual(response.data['data']['inquiry_file_link_count'], 0)
        self.assertEqual(Inquiry.objects.get(pk=inquiry_id).updated_at, before)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='inquiries', codename='delete_inquiry'))
        self.user = type(self.user).objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(f'/api/v1/inquiries/{inquiry_id}/deletion-preview/').status_code, 403)

    def test_saved_view_accepts_inquiry_tool_fields_only_for_inquiries(self):
        payload = {'module_code': 'INQUIRY', 'view_name': '金额筛选', 'filter_definition': {'amount_min': '10000', 'amount_currency': 'USD', 'density': 'compact'}, 'column_definition': ['owner', 'country'], 'sort_definition': []}
        serializer = SavedViewSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        payload['module_code'] = 'CUSTOMER'
        self.assertFalse(SavedViewSerializer(data=payload).is_valid())

    def test_risk_includes_expired_running_record_before_background_update(self):
        inquiry_id = self.create_inquiry().data['data']['id']
        now = timezone.now()
        policy = SlaPolicy.objects.create(policy_code='INQ_V4_TEST', display_name='询盘测试', target_type='INQUIRY')
        tracking = SlaTracking.objects.create(sla_policy=policy, status='RUNNING', started_at=now-timedelta(hours=2), next_deadline_at=now-timedelta(minutes=1))
        InquirySlaLink.objects.create(inquiry_id=inquiry_id, sla_tracking=tracking, is_current=True)
        response = self.client.get('/api/v1/inquiries/', {'sla_state': 'RISK'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['meta']['total'], 1)
        self.assertEqual(response.data['data'][0]['sla_summary']['state'], 'BREACHED')

    def test_list_labels_follow_the_same_flow_as_detail_without_new_statuses(self):
        for status, owner, expected in [('NEW', None, '新询盘'), ('NEW', self.employee.pk, '已分配'), ('ANALYZING', self.employee.pk, '已首响'), ('READY_FOR_QUOTE', self.employee.pk, '需求确认')]:
            self.assertEqual(inquiry_display_stage(SimpleNamespace(status=status, owner_employee_id=owner))[1], expected)
