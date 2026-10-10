from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth.models import Permission
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.inquiries.models import Inquiry
from apps.inquiries.services import _start_sla
from apps.workflow.models import SlaPolicy
from . import test_inquiry_api as fixture
from .test_inquiry_worktime import CALENDAR, local


class HandlingSettingsTests(APITestCase):
    create_customer = fixture.InquiryApiTests.create_customer
    inquiry_payload = fixture.InquiryApiTests.inquiry_payload
    create_inquiry = fixture.InquiryApiTests.create_inquiry
    url = '/api/v1/inquiry-handling-time/settings/'

    def setUp(self):
        with patch('django.utils.timezone.now', return_value=local('2026-09-01T08:30')):
            fixture.InquiryApiTests.setUp(self)

    def current(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        return deepcopy(response.data['data']), response.headers['ETag']

    def test_save_audits_and_freezes_running_clocks_but_new_stage_uses_new_rules(self):
        inquiry = Inquiry.objects.get(pk=self.create_inquiry().data['data']['id'])
        first = _start_sla(inquiry, local('2026-09-14T09:00'), 'FIRST_RESPONSE').sla_tracking
        deadline = first.next_deadline_at
        data, etag = self.current()
        self.assertEqual(len(data['stage_minutes']), 8)
        data['stage_minutes']['FIRST_RESPONSE'] = 300
        data['stage_minutes']['REQUIREMENT_CONFIRMATION'] = 240
        data['work_calendar']['periods'] = [[540, 720], [840, 1080]]
        saved = self.client.put(self.url, data, format='json', HTTP_IF_MATCH=etag)
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertNotEqual(saved.headers['ETag'], etag)
        self.assertEqual(saved.data['data'], data)
        first.refresh_from_db()
        self.assertEqual(first.next_deadline_at, deadline)
        self.assertEqual(first.tracking_data['work_calendar'], CALENDAR)
        self.assertEqual(first.tracking_data['target_minutes'], 240)
        next_stage = _start_sla(inquiry, local('2026-09-14T09:00'), 'REQUIREMENT_CONFIRMATION').sla_tracking
        self.assertEqual(next_stage.next_deadline_at, local('2026-09-14T15:00'))
        self.assertEqual(next_stage.tracking_data['work_calendar'], data['work_calendar'])
        audit = AuditLog.objects.get(action='INQUIRY_HANDLING_SETTINGS_UPDATED')
        self.assertEqual(audit.before_data['stage_minutes']['FIRST_RESPONSE'], 240)
        self.assertEqual(audit.after_data, data)
        stale = self.client.put(self.url, data, format='json', HTTP_IF_MATCH=etag)
        self.assertEqual(stale.status_code, 412)

    def test_invalid_stage_or_calendar_is_rejected_without_write(self):
        data, etag = self.current()
        invalid = []
        missing = deepcopy(data)
        del missing['stage_minutes']['QUOTE_CREATION']
        invalid.append(missing)
        for value in [0, -1, 1.5, True, 527041]:
            candidate = deepcopy(data)
            candidate['stage_minutes']['QUOTE_CREATION'] = value
            invalid.append(candidate)
        candidate = deepcopy(data)
        candidate['stage_minutes']['ASSIGNMENT'] = 241
        invalid.append(candidate)
        for periods in [[[540, 720], [700, 1080]], [[540, 540], [840, 1080]], [[540, 720]], [[False, 720], [840, 1080]]]:
            candidate = deepcopy(data)
            candidate['work_calendar']['periods'] = periods
            invalid.append(candidate)
        candidate = deepcopy(data)
        candidate['work_calendar']['rest_saturday'] = '2026-09-06'
        invalid.append(candidate)
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                response = self.client.put(self.url, candidate, format='json', HTTP_IF_MATCH=etag)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.current(), (data, etag))
        self.assertFalse(AuditLog.objects.filter(action='INQUIRY_HANDLING_SETTINGS_UPDATED').exists())

    def test_requires_etag_and_separate_view_manage_permissions(self):
        data, etag = self.current()
        self.assertEqual(self.client.put(self.url, data, format='json').status_code, 428)
        self.other_user.user_permissions.add(Permission.objects.get(content_type__app_label='workflow', codename='view_slapolicy'))
        self.client.force_authenticate(user=self.other_user)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.put(self.url, data, format='json', HTTP_IF_MATCH=etag).status_code, 403)

    def test_disabled_policy_is_not_silently_recreated(self):
        SlaPolicy.objects.filter(target_type='INQUIRY').update(is_enabled=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)
