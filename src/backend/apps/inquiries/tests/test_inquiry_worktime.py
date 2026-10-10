from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.inquiries.models import Inquiry, InquirySlaLink
from apps.inquiries.services import _start_sla, _finish_sla
from apps.inquiries.worktime import add_work_minutes, working_seconds
from apps.workflow.models import SlaPolicy
from . import test_inquiry_api as api_fixture


CALENDAR = {"mode": "ALTERNATING_WEEKS_V1", "timezone": "Asia/Shanghai", "rest_saturday": "2026-09-05", "periods": [[510, 720], [810, 1050]]}


def local(value):
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("Asia/Shanghai"))


class WorkCalendarTests(SimpleTestCase):
    def test_confirmed_examples_and_work_boundaries(self):
        examples = [
            ("2026-09-10T08:30", 240, "2026-09-10T14:00"),
            ("2026-09-10T14:00", 120, "2026-09-10T16:00"),
            ("2026-09-11T16:30", 240, "2026-09-12T11:30"),
            ("2026-09-18T16:30", 240, "2026-09-21T11:30"),
            ("2026-09-10T12:00", 120, "2026-09-10T15:30"),
            ("2026-09-10T17:30", 240, "2026-09-11T14:00"),
            ("2026-09-06T10:00", 120, "2026-09-07T10:30"),
            ("2026-08-29T08:30", 240, "2026-08-29T14:00"),
            ("2026-09-10T08:30:30", 240, "2026-09-10T14:00:30"),
            ("2026-12-31T16:30", 120, "2027-01-01T09:30"),
        ]
        for start, minutes, expected in examples:
            with self.subTest(start=start):
                deadline = add_work_minutes(local(start), minutes, CALENDAR)
                self.assertEqual(deadline, local(expected))
                self.assertEqual(working_seconds(local(start), deadline, CALENDAR), minutes * 60)

    def test_clock_excludes_lunch_and_weekend_in_both_directions(self):
        for start, end in [("2026-09-10T12:00", "2026-09-10T13:30"), ("2026-09-18T17:30", "2026-09-21T08:30")]:
            self.assertEqual(working_seconds(local(start), local(end), CALENDAR), 0)
        self.assertEqual(working_seconds(local("2026-09-10T14:00"), local("2026-09-10T08:30"), CALENDAR), -14400)

    def test_bad_calendar_or_target_cannot_loop_indefinitely(self):
        for minutes in [-1, True, 600000, 1.5]:
            with self.assertRaises(ValueError):
                add_work_minutes(local("2026-09-10T08:30"), minutes, CALENDAR)
        with self.assertRaises(ValueError):
            add_work_minutes(local("2026-09-10T08:30"), 240, {**CALENDAR, "rest_saturday": "2026-09-06"})


class InquiryWorktimeApiTests(APITestCase):
    def setUp(self):
        # 测试时钟回到早晨前，客户归属必须已经生效，否则正确的数据权限会返回404。
        with patch('django.utils.timezone.now', return_value=local('2026-09-01T08:30')):
            api_fixture.InquiryApiTests.setUp(self)
    create_customer = api_fixture.InquiryApiTests.create_customer
    inquiry_payload = api_fixture.InquiryApiTests.inquiry_payload
    create_inquiry = api_fixture.InquiryApiTests.create_inquiry

    def test_real_submit_response_confirmation_and_frozen_calendar(self):
        created = self.create_inquiry()
        base = f"/api/v1/inquiries/{created.data['data']['id']}/"
        self.assertEqual(created.data['data']['sla'], [])
        self.assertEqual(created.data['data']['handling_time_rule']['response_minutes'], 240)
        with patch('django.utils.timezone.now', return_value=local("2026-09-10T08:30")):
            submitted = self.client.post(base + 'submit/', {}, format='json', HTTP_IF_MATCH=created.headers['ETag'])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        record = InquirySlaLink.objects.get(inquiry_id=created.data['data']['id'], is_current=True).sla_tracking
        self.assertEqual(record.next_deadline_at, local("2026-09-10T14:00"))
        with patch('django.utils.timezone.now', return_value=local("2026-09-10T14:00")):
            responded = self.client.post(base + 'respond/', {'communication_type': 'EMAIL', 'content': '已回复并确认收到客户需求。', 'occurred_at': local("2026-09-10T14:00").isoformat()}, format='json', HTTP_IF_MATCH=submitted.headers['ETag'])
        self.assertEqual(responded.status_code, 200, responded.data)
        record.refresh_from_db()
        self.assertEqual(record.status, 'MET')
        current = InquirySlaLink.objects.get(inquiry_id=created.data['data']['id'], is_current=True).sla_tracking
        self.assertEqual(current.next_deadline_at, local("2026-09-10T16:00"))
        self.assertEqual(responded.data['data']['sla'][-1]['work_calendar'], CALENDAR)
        policy = current.sla_policy
        policy.config_data = {'work_calendar': {**CALENDAR, 'rest_saturday': '2026-09-12'}}
        policy.save(update_fields=['config_data'])
        current.refresh_from_db()
        self.assertEqual(current.tracking_data['work_calendar'], CALENDAR)
        with patch('django.utils.timezone.now', return_value=local("2026-09-10T16:01")):
            confirmed = self.client.post(base + 'confirm-requirements/', {}, format='json', HTTP_IF_MATCH=responded.headers['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        current.refresh_from_db()
        self.assertEqual(current.status, 'BREACHED')
        self.assertIsNotNone(current.completed_at)
        self.assertFalse(InquirySlaLink.objects.filter(inquiry_id=created.data['data']['id'], is_current=True).exists())

    def test_worktime_warning_filters_metrics_and_no_history_backfill(self):
        inquiry = Inquiry.objects.get(pk=self.create_inquiry().data['data']['id'])
        link = _start_sla(inquiry, local('2026-09-10T08:30'), 'FIRST_RESPONSE')
        for instant in ['2026-09-10T12:00', '2026-09-10T13:00']:
            with patch('django.utils.timezone.now', return_value=local(instant)):
                response = self.client.get('/api/v1/inquiries/', {'sla_state': 'DUE_SOON'})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['meta']['total'], 1)
                self.assertEqual(response.data['data'][0]['sla_summary']['remaining_seconds'], 1800)
                self.assertEqual(self.client.get('/api/v1/inquiries/metrics/').data['data']['due_soon'], 1)
        with patch('django.utils.timezone.now', return_value=local('2026-09-10T14:01')):
            self.assertEqual(self.client.get('/api/v1/inquiries/', {'sla_state': 'BREACHED'}).data['meta']['total'], 1)
        link.sla_tracking.status = 'BREACHED'
        link.sla_tracking.save(update_fields=['status'])
        _finish_sla(inquiry, 'MET', local('2026-09-10T14:05'), 'FIRST_RESPONSE')
        link.refresh_from_db()
        self.assertFalse(link.is_current)
        self.assertEqual(self.client.get('/api/v1/inquiries/', {'sla_state': 'NONE'}).data['meta']['total'], 1)

    def test_legacy_policy_retains_continuous_clock(self):
        SlaPolicy.objects.filter(target_type='INQUIRY').update(is_enabled=False)
        SlaPolicy.objects.create(policy_code='LEGACY', display_name='原规则', target_type='INQUIRY', response_minutes=240, is_enabled=True)
        inquiry = Inquiry.objects.get(pk=self.create_inquiry().data['data']['id'])
        record = _start_sla(inquiry, local('2026-09-10T11:30'), 'FIRST_RESPONSE').sla_tracking
        self.assertEqual(record.next_deadline_at, local('2026-09-10T15:30'))
        self.assertNotIn('work_calendar', record.tracking_data)
