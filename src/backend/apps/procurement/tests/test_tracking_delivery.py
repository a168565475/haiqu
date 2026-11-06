"""真实PostgreSQL互斥/冻结正文测试；仅企微网络使用替身。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from io import StringIO
import json

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import close_old_connections, connections, transaction, DatabaseError
from django.core.management import call_command
from django.test import TransactionTestCase, override_settings, TestCase, SimpleTestCase

from apps.procurement.tests import test_tracking_notifications as fixtures
from apps.procurement.tracking_models import PurchaseTrackingContent, PurchaseTrackingDigest, PurchaseTrackingIssue
from apps.procurement.tracking_notifications import render_content, content_target
from apps.wecom.client import WeComSendUncertain
from apps.wecom.credentials import encrypt_secret
from apps.wecom.message_cards import build_text_notice_card
from apps.wecom.models import NotificationDelivery, NotificationEvent, NotificationRecipient, WeComBinding, WeComConfig
from apps.wecom.notification_services import process_delivery, register_business_event
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory
from apps.core.api.exceptions import Conflict
from apps.wecom.models import NotificationPreviewAttempt, NotificationRule
from apps.wecom import notification_preview_services as preview_services
from apps.wecom.notification_selectors import rule_etag
from apps.wecom.selectors import config_etag


SETTINGS = dict(PURCHASE_TRACKING_ENABLED=True, PURCHASE_TRACKING_WECOM_ENABLED=True,
    ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
    ACCESS_RESOURCE_SCOPES_ENABLED=True, WECOM_FERNET_KEYS=[Fernet.generate_key().decode()])


class TrackingCardTests(SimpleTestCase):
    def test_coverage_summary_targets_coverage_tab(self):
        target=content_target([{'kind':'coverage','snapshot':{}}, {'kind':'coverage','snapshot':{}}],
            object_id='00000000-0000-0000-0000-000000000001')
        self.assertEqual(target['query'],{'tab':'coverage'})
    def test_unicode_and_symbols_are_preserved_in_bounded_gateway_parts(self):
        material='中文 & < > 零件'*400
        _, body, parts=render_content([{'kind':'arrival','code':'OVERDUE','snapshot':{'material_name':material}}])
        self.assertGreater(len(parts),1)
        recovered=''.join(part.split('\n',1)[1] for part in parts)
        self.assertEqual(recovered,body)
        self.assertIn(material,recovered)
        for part in parts:
            build_text_notice_card('采购跟踪提醒',part,
                'https://erp.cnhitree.com/?notification=00000000-0000-0000-0000-000000000001',preview=False)


@override_settings(**SETTINGS)
class TrackingSchemaTests(fixtures.TrackingFixture, TestCase):
    def test_system_event_cannot_be_forged_through_generic_business_registration(self):
        with self.assertRaises(ValidationError):
            register_business_event(event_code='PURCHASE_TRACKING_RISK',idempotency_key='forged',
                object_type='ProductionTask',object_id=self.task.pk)

    def test_content_is_append_only_in_database(self):
        self.run_tracking()
        content=PurchaseTrackingContent.objects.first()
        with self.assertRaises(DatabaseError), transaction.atomic():
            PurchaseTrackingContent.objects.filter(pk=content.pk).update(body='改写历史')

    def test_preview_reports_risks_and_potential_qualified_channels_without_persistence(self):
        result=self.run_tracking(dry_run=True)
        self.assertEqual(result['risk_counts'],{'NEAR_DUE':1})
        self.assertEqual(result['task_count'],1)
        self.assertEqual(result['recipients'][0]['role_codes'],['PURCHASING'])
        self.assertEqual(result['recipients'][0]['channels'],{'IN_APP':True,'WECOM':False})
        self.assertFalse(PurchaseTrackingIssue.objects.exists())
        self.assertFalse(NotificationDelivery.objects.exists())

    def test_command_defaults_to_read_only_preview(self):
        output=StringIO()
        call_command('process_purchase_tracking',stdout=output)
        self.assertTrue(json.loads(output.getvalue())['dry_run'])
        self.assertFalse(PurchaseTrackingIssue.objects.exists())

    def test_disabled_tracking_does_not_occupy_general_worker_batch(self):
        self.run_tracking()
        output=StringIO()
        with override_settings(PURCHASE_TRACKING_ENABLED=False):
            call_command('process_notification_deliveries',stdout=output)
        self.assertIn('"candidate_count": 0',output.getvalue())
        self.assertEqual(NotificationDelivery.objects.get(channel='WECOM').status,'PENDING')

    def test_send_record_reports_channel_revision_not_original_event_body(self):
        from apps.wecom.send_record_selectors import send_record_payload
        self.run_tracking()
        self.rows[0]['snapshot']['unreceived_quantity']='2'
        self.run_tracking()
        delivery=NotificationDelivery.objects.get(channel='WECOM')
        self.assertIn('未到 2',send_record_payload(delivery,'BUSINESS')['body'])
        self.assertIn('未到 10',delivery.recipient.event.rendered_body)


class TrackingDeliveryFixture(fixtures.TrackingFixture):
    def configure(self):
        config=WeComConfig.objects.create(enabled=True,secret_ciphertext=encrypt_secret('tracking-test-secret'))
        WeComBinding.objects.create(employee=self.member,corp_id=config.corp_id,user_id='Tracking.Test',
            member_name='测试',source='MANUAL',created_by_employee=self.member)


@override_settings(**SETTINGS)
class TrackingConcurrentDeliveryTests(TrackingDeliveryFixture, TransactionTestCase):

    def test_nine_oclock_partial_hook_and_full_scan_claim_one_digest_and_two_channels(self):
        barrier=Barrier(2)
        now=self.now.replace(hour=1,minute=0)
        def worker(partial):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.run_tracking(now=now,task_ids=[self.task.pk] if partial else None)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures=[executor.submit(worker,partial) for partial in (True,False)]
            [future.result(timeout=40) for future in futures]
        self.assertEqual(PurchaseTrackingDigest.objects.count(),1)
        self.assertEqual(NotificationRecipient.objects.count(),1)
        self.assertEqual(NotificationDelivery.objects.count(),2)

    def test_duplicate_delivery_claims_send_once_and_uncertain_is_not_auto_replayed(self):
        self.configure()
        self.run_tracking()
        delivery=NotificationDelivery.objects.get(channel='WECOM')
        barrier=Barrier(2)
        def worker():
            close_old_connections()
            try:
                current=NotificationDelivery.objects.get(pk=delivery.pk)
                barrier.wait(timeout=10)
                return process_delivery(current)
            finally:
                connections.close_all()
        with patch('apps.wecom.client.WeComClient.send_text_notice',side_effect=WeComSendUncertain()) as sender:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures=[executor.submit(worker) for _ in range(2)]
                [future.result(timeout=40) for future in futures]
            delivery.refresh_from_db()
            process_delivery(delivery)
        self.assertEqual(sender.call_count,1)
        self.assertEqual(delivery.status,'UNCERTAIN')

    def test_segments_keep_accepted_prefix_and_explicit_retry_keeps_frozen_body(self):
        self.configure()
        self.rows[0]['snapshot']['material_name']='材料 & < >'*600
        self.run_tracking()
        delivery=NotificationDelivery.objects.get(channel='WECOM')
        content=delivery.tracking_contents.first()
        def fail_second(*args,**kwargs):
            if kwargs['body']==content.parts[0]:
                return {'msgid':'accepted-first'}
            raise WeComSendUncertain()
        with patch('apps.wecom.client.WeComClient.send_text_notice',side_effect=fail_second) as sender:
            process_delivery(delivery)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status,'UNCERTAIN')
        self.assertEqual(len(delivery.tracking_part_results),1)
        with patch('apps.wecom.client.WeComClient.send_text_notice',return_value={'msgid':'rest'}) as sender:
            process_delivery(delivery,allow_uncertain=True)
        self.assertEqual([call.kwargs['body'] for call in sender.call_args_list],content.parts[1:])
        delivery.refresh_from_db()
        self.assertEqual(delivery.status,'ACCEPTED')
        self.assertEqual(delivery.tracking_contents.count(),1)

    def test_unattempted_configuration_failure_can_use_latest_content_on_explicit_retry(self):
        self.run_tracking()
        delivery=NotificationDelivery.objects.get(channel='WECOM')
        with patch('apps.wecom.client.WeComClient.send_text_notice') as sender:
            failed=process_delivery(delivery)
        sender.assert_not_called()
        self.assertEqual(failed.status,'FAILED')
        self.assertEqual(failed.attempt_count,0)
        self.rows[0]['snapshot']['unreceived_quantity']='6'
        self.run_tracking()
        self.configure()
        with patch('apps.wecom.client.WeComClient.send_text_notice',return_value={'msgid':'first-send'}) as sender:
            accepted=process_delivery(failed,allow_failed=True)
        self.assertEqual(accepted.status,'ACCEPTED')
        self.assertIn('未到 6',sender.call_args.kwargs['body'])
        self.assertEqual(accepted.tracking_contents.count(),2)
        self.assertEqual(NotificationDelivery.objects.filter(channel='IN_APP').count(),1)

    def test_role_revoked_after_queue_prevents_actual_external_send(self):
        self.configure()
        self.run_tracking()
        delivery=NotificationDelivery.objects.get(channel='WECOM')
        self.role.archived_at=self.now
        self.role.save()
        with patch('apps.wecom.client.WeComClient.send_text_notice') as sender:
            value=process_delivery(delivery)
        sender.assert_not_called()
        self.assertEqual(value.status,'SKIPPED')


    def test_revocation_between_segments_stops_remaining_parts_and_keeps_accepted_receipt(self):
        self.configure()
        self.rows[0]['snapshot']['material_name']='长材料名称'*500
        self.run_tracking()
        delivery=NotificationDelivery.objects.get(channel='WECOM')
        def revoke_after_accept(*args,**kwargs):
            self.member.user.is_active=False
            self.member.user.save(update_fields=['is_active'])
            return {'msgid':'first-before-revocation'}
        with patch('apps.wecom.client.WeComClient.send_text_notice',side_effect=revoke_after_accept) as sender:
            value=process_delivery(delivery)
        self.assertEqual(sender.call_count,1)
        self.assertEqual(value.status,'SKIPPED')
        self.assertEqual(value.error_code,'TRACKING_CHANGED_DURING_SEND')
        self.assertEqual(len(value.tracking_part_results),1)

    def test_delayed_previous_day_digest_is_not_replayed_after_restart(self):
        self.configure()
        self.run_tracking(now=self.now.replace(hour=1,minute=0)-timedelta(days=1))
        delivery=NotificationDelivery.objects.get(channel='WECOM')
        with patch('apps.wecom.client.WeComClient.send_text_notice') as sender:
            value=process_delivery(delivery)
        sender.assert_not_called()
        self.assertEqual(value.status,'SKIPPED')


@override_settings(**{**SETTINGS, 'PURCHASE_TRACKING_WECOM_ENABLED': False})
class TrackingInAppOnlyTests(TrackingDeliveryFixture, TransactionTestCase):
    def make_preview(self, code):
        self.member.user.is_superuser = True
        self.member.user.save(update_fields=['is_superuser'])
        request = APIRequestFactory().post('/api/v1/notifications/rules/' + code + '/preview-send/')
        request.user = self.member.user
        preview = preview_services.signed_preview(request, code, {},
            rule_etag(NotificationRule.objects.filter(event_code=code).first()),
            {'title': '采购测试预览', 'body': '只通过模拟网关验证'})
        return request, preview, {'preview_token': preview['preview_token'], 'draft': {},
            'binding_id': str(WeComBinding.objects.get().pk), 'config_etag': config_etag(WeComConfig.objects.get())}

    def test_tracking_template_preview_cannot_bypass_disabled_channel(self):
        self.configure()
        for code in ('PURCHASE_TRACKING_RISK', 'PURCHASE_TRACKING_DIGEST'):
            request, preview, data = self.make_preview(code)
            with patch('apps.wecom.client.WeComClient.send_text_notice', return_value={'msgid':'mocked'}) as sender:
                with self.assertRaises(Conflict):
                    preview_services.send_preview(request, code, data)
            sender.assert_not_called()
            self.assertIn('采购企微', preview['send_blocked_reason'])
        self.assertFalse(NotificationPreviewAttempt.objects.exists())

    def test_other_business_template_preview_is_unaffected(self):
        self.configure()
        code = 'PRODUCTION_TASK_CONFIRMED'
        request, preview, data = self.make_preview(code)
        self.assertEqual(preview['send_blocked_reason'], '')
        with patch('apps.wecom.client.WeComClient.send_text_notice', return_value={'msgid':'other-preview'}) as sender:
            result = preview_services.send_preview(request, code, data)
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(result.status, 'ACCEPTED')

    def test_ready_configuration_still_creates_only_in_app_acceptance_for_instant_and_digest(self):
        self.configure()
        with patch('apps.wecom.client.WeComClient.send_text_notice', return_value={'msgid':'mocked'}) as sender:
            self.run_tracking()
            self.run_tracking(now=self.now.replace(hour=1,minute=0))
            for delivery in NotificationDelivery.objects.filter(channel='WECOM'):
                process_delivery(delivery,allow_failed=True,allow_uncertain=True)
        sender.assert_not_called()
        self.assertEqual(NotificationDelivery.objects.filter(channel='IN_APP',status='ACCEPTED').count(),2)
        deliveries=list(NotificationDelivery.objects.filter(channel='WECOM'))
        self.assertEqual(len(deliveries),2)
        self.assertTrue(all(row.status=='SKIPPED' and row.error_code=='TRACKING_WECOM_DISABLED'
            and row.attempt_count==0 and not row.tracking_part_results for row in deliveries))

    def test_existing_pending_is_cancelled_and_is_not_revived_after_enabling(self):
        self.configure()
        with override_settings(PURCHASE_TRACKING_WECOM_ENABLED=True):
            self.run_tracking()
        delivery=NotificationDelivery.objects.get(channel='WECOM')
        self.run_tracking()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status,'SKIPPED')
        self.assertEqual(delivery.error_code,'TRACKING_WECOM_DISABLED')
        self.rows[0]['snapshot']['unreceived_quantity']='4'
        with override_settings(PURCHASE_TRACKING_WECOM_ENABLED=True), patch('apps.wecom.client.WeComClient.send_text_notice') as sender:
            self.run_tracking()
            process_delivery(delivery,allow_failed=True,allow_uncertain=True)
        sender.assert_not_called()
        self.assertEqual(NotificationDelivery.objects.get(channel='WECOM').pk,delivery.pk)
        self.assertEqual(NotificationDelivery.objects.get(channel='WECOM').status,'SKIPPED')
        self.assertEqual(delivery.tracking_contents.count(),1)

    def test_direct_pending_delivery_is_blocked_without_relying_on_worker_filter(self):
        self.configure()
        with override_settings(PURCHASE_TRACKING_WECOM_ENABLED=True):
            self.run_tracking()
        delivery=NotificationDelivery.objects.get(channel='WECOM')
        with patch('apps.wecom.client.WeComClient.send_text_notice', return_value={'msgid':'mocked'}) as sender:
            result=process_delivery(delivery)
        sender.assert_not_called()
        self.assertEqual(result.status,'SKIPPED')
        self.assertEqual(result.error_code,'TRACKING_WECOM_DISABLED')

    def test_manual_failed_and_uncertain_retries_are_blocked_and_preserve_attempts(self):
        self.configure()
        with override_settings(PURCHASE_TRACKING_WECOM_ENABLED=True):
            self.run_tracking()
        delivery=NotificationDelivery.objects.get(channel='WECOM')
        with patch('apps.wecom.client.WeComClient.send_text_notice', return_value={'msgid':'mocked'}) as sender:
            for status in ('FAILED','UNCERTAIN'):
                delivery.status=status
                delivery.attempt_count=1
                delivery.error_code='PREVIOUS_RESULT'
                delivery.save(update_fields=['status','attempt_count','error_code'])
                result=process_delivery(delivery,allow_failed=True,allow_uncertain=True)
                self.assertEqual(result.status,status)
                self.assertEqual(result.attempt_count,1)
                self.assertEqual(result.error_code,'PREVIOUS_RESULT')
        sender.assert_not_called()

    def test_worker_excludes_tracking_only_and_keeps_other_business_events(self):
        self.configure()
        with override_settings(PURCHASE_TRACKING_WECOM_ENABLED=True):
            self.run_tracking()
        tracking=NotificationDelivery.objects.get(channel='WECOM')
        event=NotificationEvent.objects.create(event_code='SAMPLE_COMPLETED',idempotency_key='legacy-tracking-test',
            object_type='SAMPLE',object_id=str(self.task.pk),object_version='1',context={},rule_version=1,
            template_name='旧业务测试',rendered_title='旧业务',rendered_body='只测队列选择，不发送')
        recipient=NotificationRecipient.objects.create(event=event,employee=self.member,
            employee_name='测试',scope='ROLE_POLICY')
        other=NotificationDelivery.objects.create(recipient=recipient,channel='WECOM',idempotency_key='legacy-delivery')
        output=StringIO()
        call_command('process_notification_deliveries',stdout=output)
        self.assertIn(str(other.pk),output.getvalue())
        self.assertNotIn(str(tracking.pk),output.getvalue())

    def test_preview_exposes_wecom_disabled_even_with_ready_configuration(self):
        self.configure()
        preview=self.run_tracking(dry_run=True)
        self.assertFalse(preview['wecom_enabled'])
        self.assertEqual(preview['recipients'][0]['channels'],{'IN_APP':True,'WECOM':False})

    def test_switch_off_between_segments_stops_remaining_gateway_calls(self):
        self.configure()
        self.rows[0]['snapshot']['material_name']='材料很长'*700
        with override_settings(PURCHASE_TRACKING_WECOM_ENABLED=True):
            self.run_tracking()
            delivery=NotificationDelivery.objects.get(channel='WECOM')
            def disable_after_first(*args,**kwargs):
                settings.PURCHASE_TRACKING_WECOM_ENABLED=False
                return {'msgid':'first-part'}
            with patch('apps.wecom.client.WeComClient.send_text_notice',side_effect=disable_after_first) as sender:
                result=process_delivery(delivery)
        self.assertEqual(sender.call_count,1)
        self.assertEqual(result.status,'SKIPPED')
        self.assertEqual(result.error_code,'TRACKING_WECOM_DISABLED')
        self.assertEqual(len(result.tracking_part_results),1)

