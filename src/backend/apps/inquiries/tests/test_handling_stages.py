import json
from io import StringIO
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import RequestFactory
from rest_framework.test import APITestCase

from apps.core.api.concurrency import etag_for_instance
from apps.inquiries.models import Inquiry
from apps.inquiries.services import _start_sla, assign_inquiry, mark_inquiry_quote_accepted
from apps.inquiries.handling_time import handle_time_event, sample_submitted, stages_for_enrollment
from apps.quotations.models import QuotationLine
from apps.quotations.services import create_quotation_draft, dispatch_version, create_version
from apps.samples.models import SampleRequest, SampleItem
from apps.samples.services import transition_sample_request
from . import test_inquiry_api as api_fixture
from .test_inquiry_worktime import local


class HandlingStageTests(APITestCase):
    create_customer = api_fixture.InquiryApiTests.create_customer
    inquiry_payload = api_fixture.InquiryApiTests.inquiry_payload
    create_inquiry = api_fixture.InquiryApiTests.create_inquiry

    def setUp(self):
        with patch('django.utils.timezone.now', return_value=local('2026-09-01T08:30')):
            api_fixture.InquiryApiTests.setUp(self)

    def request_for(self, instance):
        request = RequestFactory().post('/', HTTP_IF_MATCH=etag_for_instance(instance))
        request.user = self.user
        return request

    def active(self, inquiry, stage):
        return inquiry.sla_links.get(stage_code=stage, is_current=True).sla_tracking

    def ready_inquiry(self):
        created = self.create_inquiry()
        inquiry = Inquiry.objects.get(pk=created.data['data']['id'])
        inquiry.status='READY_FOR_QUOTE'
        inquiry.save(update_fields=['status'])
        _start_sla(inquiry, local('2026-09-14T09:30'), 'QUOTE_CREATION')
        return inquiry

    def quote(self, inquiry):
        with patch('django.utils.timezone.now', return_value=local('2026-09-14T10:00')):
            return create_quotation_draft(quotation_data={'customer_account':self.customer,'transaction_entity':self.entity,'owner_employee':self.employee,'source_inquiry':inquiry,'subject':'阶段时限测试'}, version_data={'currency_code':'USD'}, actor_employee=self.employee, request=None)

    def send(self, version, instant):
        version.refresh_from_db()
        if version.status == 'DRAFT':
            QuotationLine.objects.create(quotation_version=version,line_number=1,product_description_snapshot='测试报价产品',quantity=1,unit_code='PCS',unit_price=10,line_total=10)
            version.status='ISSUED'
            version.locked_at=local(instant)
            version.transaction_entity_snapshot={'legal_name':'阶段测试主体'}
            version.address_snapshot={'address':'阶段测试地址'}
            version.contact_snapshot={'name':'阶段测试联系人'}
            version.save(update_fields=['status','locked_at','transaction_entity_snapshot','address_snapshot','contact_snapshot','updated_at'])
        with patch('django.utils.timezone.now', return_value=local(instant)):
            return dispatch_version(version=version, validated_data={'channel':'EMAIL','recipient_snapshot':{'email':'test@example.test'}},actor_employee=self.employee,request=self.request_for(version),require_formal_document=False)

    def test_assignment_is_parallel_and_transfer_does_not_reset_first_response(self):
        created=self.create_inquiry()
        inquiry=Inquiry.objects.get(pk=created.data['data']['id'])
        inquiry.owner_employee=None
        inquiry.save(update_fields=['owner_employee','updated_at'])
        with patch('django.utils.timezone.now',return_value=local('2026-09-14T08:30')):
            response=self.client.post(f'/api/v1/inquiries/{inquiry.pk}/submit/',{},format='json',HTTP_IF_MATCH=etag_for_instance(inquiry))
        self.assertEqual(response.status_code,200,response.data)
        first=self.active(inquiry,'FIRST_RESPONSE')
        deadline=first.next_deadline_at
        self.assertEqual(self.active(inquiry,'ASSIGNMENT').next_deadline_at,local('2026-09-14T09:00'))
        inquiry.refresh_from_db()
        with patch('django.utils.timezone.now',return_value=local('2026-09-14T09:05')):
            assign_inquiry(inquiry=inquiry,owner_employee=self.employee,reason='接手',actor_employee=self.employee,request=self.request_for(inquiry))
        first.refresh_from_db()
        self.assertEqual(first.next_deadline_at,deadline)
        self.assertEqual(inquiry.sla_links.get(stage_code='ASSIGNMENT').sla_tracking.status,'BREACHED')

    def test_confirmed_requirements_immediately_starts_quote_creation_deadline(self):
        inquiry=Inquiry.objects.get(pk=self.create_inquiry().data['data']['id'])
        base=f'/api/v1/inquiries/{inquiry.pk}/'
        with patch('django.utils.timezone.now',return_value=local('2026-09-14T08:30')):
            submitted=self.client.post(base+'submit/',{},format='json',HTTP_IF_MATCH=etag_for_instance(inquiry))
        self.assertEqual(submitted.status_code,200,submitted.data)
        with patch('django.utils.timezone.now',return_value=local('2026-09-14T09:00')):
            responded=self.client.post(base+'respond/',{'communication_type':'EMAIL','content':'已回复并核对产品需求','occurred_at':local('2026-09-14T09:00').isoformat()},format='json',HTTP_IF_MATCH=submitted.headers['ETag'])
        self.assertEqual(responded.status_code,200,responded.data)
        self.assertEqual(self.active(inquiry,'REQUIREMENT_CONFIRMATION').next_deadline_at,local('2026-09-14T11:00'))
        with patch('django.utils.timezone.now',return_value=local('2026-09-14T09:30')):
            confirmed=self.client.post(base+'confirm-requirements/',{},format='json',HTTP_IF_MATCH=responded.headers['ETag'])
        self.assertEqual(confirmed.status_code,200,confirmed.data)
        self.assertEqual(self.active(inquiry,'QUOTE_CREATION').next_deadline_at,local('2026-09-14T10:30'))
        self.assertFalse(inquiry.sla_links.filter(stage_code='REQUIREMENT_CONFIRMATION',is_current=True).exists())

    def test_quote_creation_delivery_and_repeated_send_preserve_round(self):
        inquiry=self.ready_inquiry()
        quote,version=self.quote(inquiry)
        self.assertFalse(inquiry.sla_links.filter(stage_code='QUOTE_CREATION',is_current=True).exists())
        delivery=self.active(inquiry,'QUOTE_DELIVERY')
        self.assertEqual(delivery.next_deadline_at,local('2026-09-14T15:30'))
        self.send(version,'2026-09-14T16:00')
        delivery.refresh_from_db()
        self.assertEqual(delivery.status,'BREACHED')
        follow=self.active(inquiry,'CUSTOMER_FOLLOW_UP')
        self.assertEqual(follow.next_deadline_at,local('2026-09-15T16:00'))
        self.send(version,'2026-09-14T16:10')
        self.assertEqual(self.active(inquiry,'CUSTOMER_FOLLOW_UP').pk,follow.pk)
        quote.refresh_from_db()
        with patch('django.utils.timezone.now',return_value=local('2026-09-15T16:05')):
            create_version(quotation=quote,validated_data={'currency_code':'USD'},actor_employee=self.employee,request=self.request_for(quote))
        follow.refresh_from_db()
        self.assertEqual(follow.status,'CANCELLED')
        self.assertIsNotNone(follow.breached_at)
        second=self.active(inquiry,'QUOTE_DELIVERY')
        self.assertEqual(second.tracking_data['round_number'],2)
        quote.refresh_from_db()
        create_version(quotation=quote,validated_data={'currency_code':'USD'},actor_employee=self.employee,request=self.request_for(quote))
        self.assertEqual(self.active(inquiry,'QUOTE_DELIVERY').pk,second.pk)

    def test_follow_up_rolls_only_its_stage_and_accepted_sample_handoff(self):
        inquiry=self.ready_inquiry()
        inquiry.status='QUOTED';inquiry.save(update_fields=['status'])
        handle_time_event(inquiry.pk,'QUOTE_SENT',key='sent-round-1',now=local('2026-09-14T10:00'))
        first=self.active(inquiry,'CUSTOMER_FOLLOW_UP')
        handle_time_event(inquiry.pk,'FOLLOW_UP',key='communication-1',now=local('2026-09-14T11:00'))
        second=self.active(inquiry,'CUSTOMER_FOLLOW_UP')
        self.assertNotEqual(first.pk,second.pk)
        handle_time_event(inquiry.pk,'FOLLOW_UP',key='communication-1',now=local('2026-09-14T11:30'))
        self.assertEqual(self.active(inquiry,'CUSTOMER_FOLLOW_UP').pk,second.pk)
        with patch('django.utils.timezone.now',return_value=local('2026-09-14T14:00')):
            mark_inquiry_quote_accepted(inquiry=inquiry,actor_employee=self.employee,request=None)
        self.assertEqual(self.active(inquiry,'POST_ACCEPTANCE').next_deadline_at,local('2026-09-14T16:00'))
        sample=SampleRequest.objects.create(request_number='HANDLING-SAMPLE',customer_account=self.customer,owner_employee=self.employee,requested_at=local('2026-09-14T14:30'),source_inquiry=inquiry,status='DIRECTOR_REVIEW')
        sample_submitted(sample)
        self.assertFalse(inquiry.sla_links.filter(stage_code='POST_ACCEPTANCE',is_current=True).exists())
        sample_follow=self.active(inquiry,'SAMPLE_FOLLOW_UP')
        sample_submitted(sample)
        self.assertEqual(self.active(inquiry,'SAMPLE_FOLLOW_UP').pk,sample_follow.pk)
        handle_time_event(inquiry.pk,'ORDER_CREATED')
        self.assertFalse(inquiry.sla_links.filter(is_current=True).exists())

    def test_enrollment_is_dry_by_default_and_does_not_change_existing_deadlines(self):
        inquiry=self.ready_inquiry()
        prior=self.active(inquiry,'QUOTE_CREATION').next_deadline_at
        other=Inquiry.objects.get(pk=self.create_inquiry().data['data']['id'])
        other.status='READY_FOR_QUOTE';other.save(update_fields=['status'])
        call_command('enroll_inquiry_handling_time',stdout=StringIO())
        self.assertFalse(other.sla_links.exists())
        with TemporaryDirectory() as directory:
            output=Path(directory)/'before.json'
            with patch('django.utils.timezone.now',return_value=local('2026-09-14T11:00')):
                call_command('enroll_inquiry_handling_time',apply=True,output=str(output),stdout=StringIO())
            self.assertEqual(self.active(inquiry,'QUOTE_CREATION').next_deadline_at,prior)
            enrolled=self.active(other,'QUOTE_CREATION')
            self.assertEqual(enrolled.next_deadline_at,local('2026-09-14T12:00'))
            self.assertIn('启用时接入',enrolled.tracking_data['entry_reason'])
            self.assertFalse(json.loads(output.read_text())['applied'])

    def test_multiple_versions_sent_then_resend_cannot_finish_new_delivery(self):
        inquiry=self.ready_inquiry()
        quote,first=self.quote(inquiry)
        quote.refresh_from_db()
        with patch('django.utils.timezone.now',return_value=local('2026-09-14T10:10')):
            second,_=create_version(quotation=quote,validated_data={'currency_code':'USD'},actor_employee=self.employee,request=self.request_for(quote))
        self.send(first,'2026-09-14T11:00')
        follow=self.active(inquiry,'CUSTOMER_FOLLOW_UP')
        self.send(second,'2026-09-14T11:10')
        self.assertEqual(self.active(inquiry,'CUSTOMER_FOLLOW_UP').pk,follow.pk)
        quote.refresh_from_db()
        with patch('django.utils.timezone.now',return_value=local('2026-09-14T11:20')):
            create_version(quotation=quote,validated_data={'currency_code':'USD'},actor_employee=self.employee,request=self.request_for(quote))
        delivery=self.active(inquiry,'QUOTE_DELIVERY')
        self.send(second,'2026-09-14T11:30')
        self.assertEqual(self.active(inquiry,'QUOTE_DELIVERY').pk,delivery.pk)
        self.assertFalse(inquiry.sla_links.filter(stage_code='CUSTOMER_FOLLOW_UP',is_current=True).exists())

        inquiry.refresh_from_db()
        for action in ['sync-quotation','mark-quoted']:
            synced=self.client.post(f'/api/v1/inquiries/{inquiry.pk}/{action}/',{},format='json',HTTP_IF_MATCH=etag_for_instance(inquiry))
            self.assertEqual(synced.status_code,200,synced.data)
            inquiry.refresh_from_db()
            current=self.active(inquiry,'QUOTE_DELIVERY')
            self.assertEqual(current.pk,delivery.pk)
            self.assertEqual(current.next_deadline_at,delivery.next_deadline_at)
        with TemporaryDirectory() as directory:
            call_command('enroll_inquiry_handling_time',apply=True,output=str(Path(directory)/'repeat.json'),stdout=StringIO())
        self.assertEqual(self.active(inquiry,'QUOTE_DELIVERY').pk,delivery.pk)
        self.assertFalse(inquiry.sla_links.filter(stage_code='CUSTOMER_FOLLOW_UP',is_current=True).exists())

        inquiry.sla_links.all().delete()
        self.assertEqual(stages_for_enrollment(inquiry), ['QUOTE_DELIVERY'])

    def test_sample_submitted_before_acceptance_and_legacy_submission(self):
        inquiry=self.ready_inquiry()
        sample=SampleRequest.objects.create(request_number='EARLY-SAMPLE',customer_account=self.customer,owner_employee=self.employee,requested_at=local('2026-09-14T10:00'),source_inquiry=inquiry,status='DIRECTOR_REVIEW')
        sample_submitted(sample)
        mark_inquiry_quote_accepted(inquiry=inquiry,actor_employee=self.employee,request=None)
        self.active(inquiry,'SAMPLE_FOLLOW_UP')
        self.assertFalse(inquiry.sla_links.filter(stage_code='POST_ACCEPTANCE',is_current=True).exists())
        other=self.ready_inquiry()
        mark_inquiry_quote_accepted(inquiry=other,actor_employee=self.employee,request=None)
        draft=SampleRequest.objects.create(request_number='LEGACY-SAMPLE',customer_account=self.customer,owner_employee=self.employee,requested_at=local('2026-09-14T10:00'),source_inquiry=other)
        SampleItem.objects.create(sample_request=draft,line_number=1,product_description_snapshot='测试样品',requested_quantity=1,unit_code='PCS')
        transition_sample_request(sample_request=draft,action='SUBMITTED',note='测试提交',actor_employee=self.employee,request=self.request_for(draft))
        self.active(other,'SAMPLE_FOLLOW_UP')
        self.assertFalse(other.sla_links.filter(stage_code='POST_ACCEPTANCE',is_current=True).exists())
