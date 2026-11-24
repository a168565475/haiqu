"""通知状态测试；隔离库允许用候选查询替身，不替代真实业务验收。"""
import importlib.util
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings
from unittest.mock import patch
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.utils import timezone
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.access_control.models import RoleActionGrant
from apps.production_tasks.models import ProductionTask
from apps.reference_data.models import Currency
from apps.wecom.models import NotificationDelivery, NotificationRecipient, NotificationRule
from apps.procurement.tracking_models import PurchaseTrackingContent, PurchaseTrackingDigest, PurchaseTrackingIssue


class TrackingFixture:
    def setUp(self):
        super().setUp()
        self.now = timezone.now().replace(hour=0, minute=30, second=0, microsecond=0)  # 北京08:30
        self.member = Employee.objects.create(user=get_user_model().objects.create_user(username='tracking'),
            employee_code='TRACKING', display_name='跟踪测试')
        self.role = RoleProfile.objects.create(auth_group=Group.objects.create(name='tracking-role'),
            role_code='PURCHASING', display_name='采购测试')
        EmployeeRoleAssignment.objects.create(employee=self.member, role_profile=self.role,
            effective_from=self.now - timedelta(days=1))
        RoleActionGrant.objects.create(role=self.role, scope='MODULE', permission=Permission.objects.get(
            content_type__app_label='procurement', codename='view_purchaseorder'))
        self.task = self.make_task('A')
        for code in ('PURCHASE_TRACKING_RISK', 'PURCHASE_TRACKING_DIGEST'):
            NotificationRule.objects.create(event_code=code, name=code, title_template='采购跟踪',
                body_template='{{reason_summary}}', allowed_variables=['reason_summary'],
                recipient_role_codes=['PURCHASING', 'PMC', 'MERCHANDISER'], recipient_scope='ROLE_POLICY',
                enabled=True, updated_by_employee=self.member)
        self.rows = [self.candidate(self.task)]
        self.collect = patch('apps.procurement.tracking_runner.collect_candidates', side_effect=self.candidates)
        self.collect.start()
        self.addCleanup(self.collect.stop)

    @override_settings(PURCHASE_TRACKING_ENABLED=False)
    def make_task(self, suffix):
        return ProductionTask.objects.create(task_number='TRACK-'+suffix, contract_number='CTR-'+suffix,
            order_source='NEW', order_number='ORD-'+suffix, order_date=self.now.date(),
            delivery_date=self.now.date()+timedelta(days=10), salesperson=self.member,
            currency=Currency.objects.get_or_create(code='CNY', defaults={'numeric_code':'156','chinese_name':'人民币'})[0],
            includes_tax=True, order_tolerance_percent='3', is_repeat_order=False,
            preproduction_sample_required=False, delivery_method='SPLIT', status='READY',
            created_by_employee=self.member)

    def candidate(self, task, rank=20, quantity='10'):
        return {'source_key': 'arrival:'+str(task.pk), 'kind': 'arrival', 'code': 'NEAR_DUE',
            'rank': rank, 'production_task_id': str(task.pk), 'row_key': str(task.pk),
            'snapshot': {'task_number': task.task_number, 'material_name':'测试材料',
                'unreceived_quantity':quantity, 'risks':[{'code':'NEAR_DUE','label':'临近交期'}]}}

    def candidates(self, *, task_ids=None, now=None):
        return [dict(row) for row in self.rows if task_ids is None or row['production_task_id'] in {str(i) for i in task_ids}]

    def run_tracking(self, **kwargs):
        from apps.procurement.tracking_runner import recompute_tracking
        return recompute_tracking(now=kwargs.pop('now', self.now), **kwargs)


@override_settings(PURCHASE_TRACKING_ENABLED=True, PURCHASE_TRACKING_WECOM_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True,
    MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class TrackingPersistenceTests(TrackingFixture, TestCase):
    def test_scan_replay_is_idempotent_and_same_rank_revises_only_unsent_channel(self):
        self.run_tracking()
        delivery = NotificationDelivery.objects.get(channel='WECOM')
        in_app = NotificationDelivery.objects.get(channel='IN_APP')
        self.rows[0]['snapshot']['unreceived_quantity'] = '5'
        self.run_tracking()
        self.run_tracking()
        self.assertEqual(NotificationRecipient.objects.count(), 1)
        self.assertEqual(PurchaseTrackingContent.objects.filter(delivery=in_app).count(), 1)
        self.assertEqual(PurchaseTrackingContent.objects.filter(delivery=delivery).count(), 2)
        self.assertIn('未到 5', delivery.tracking_contents.first().body)

    def test_resolve_recur_and_rank_upgrade_create_distinct_opportunities(self):
        self.run_tracking()
        saved = self.rows
        self.rows=[]
        self.run_tracking()
        self.assertFalse(PurchaseTrackingIssue.objects.get().active)
        self.rows=saved
        self.run_tracking()
        self.rows[0]['rank']=30
        self.run_tracking()
        issue=PurchaseTrackingIssue.objects.get()
        self.assertEqual(issue.cycle, 2)
        self.assertEqual(NotificationRecipient.objects.count(), 3)
        self.assertEqual(NotificationDelivery.objects.filter(channel='WECOM',status='PENDING').count(),1)

    def test_downgrade_invalidates_old_unsent_body_and_reupgrade_notifies_again(self):
        self.rows[0]['rank']=30
        self.run_tracking()
        old=NotificationDelivery.objects.get(channel='WECOM')
        self.rows[0]['rank']=20
        self.run_tracking()
        old.refresh_from_db()
        self.assertEqual(old.status,'SKIPPED')
        self.assertEqual(NotificationRecipient.objects.count(),1)
        self.rows[0]['rank']=30
        self.run_tracking()
        self.assertEqual(NotificationRecipient.objects.count(),2)
        self.assertEqual(NotificationDelivery.objects.filter(channel='WECOM',status='PENDING').count(),1)

    def test_partial_scan_before_nine_does_not_resolve_unscanned_tasks(self):
        other=self.make_task('B')
        self.rows.append(self.candidate(other))
        self.run_tracking()
        self.rows=[self.rows[1]]
        self.run_tracking(task_ids=[self.task.pk])
        self.assertTrue(PurchaseTrackingIssue.objects.get(production_task=other).active)
        self.assertFalse(PurchaseTrackingIssue.objects.get(production_task=self.task).active)

    def test_partial_callback_at_nine_produces_full_digest_and_no_duplicate_instant(self):
        other=self.make_task('B')
        self.rows.append(self.candidate(other))
        at_nine=self.now.replace(hour=1,minute=0)
        self.run_tracking(task_ids=[self.task.pk],now=at_nine)
        self.run_tracking(now=at_nine)
        digest=PurchaseTrackingDigest.objects.get()
        self.assertEqual(digest.item_count,2)
        self.assertEqual(NotificationRecipient.objects.count(),1)
        self.assertEqual(NotificationDelivery.objects.count(),2)
        self.assertEqual(PurchaseTrackingIssue.objects.filter(active=True).count(),2)

    def test_empty_digest_is_evaluated_once_and_later_risk_is_immediate(self):
        saved=self.rows
        self.rows=[]
        at_nine=self.now.replace(hour=1,minute=0)
        self.run_tracking(now=at_nine)
        self.assertEqual(PurchaseTrackingDigest.objects.get().item_count,0)
        self.rows=saved
        self.run_tracking(now=at_nine+timedelta(minutes=1))
        self.assertEqual(NotificationRecipient.objects.get().event.event_code,'PURCHASE_TRACKING_RISK')

    def test_digest_supersedes_only_unattempted_wecom_instant(self):
        self.run_tracking()
        old=NotificationDelivery.objects.get(channel='WECOM')
        self.run_tracking(now=self.now.replace(hour=1,minute=0))
        old.refresh_from_db()
        self.assertEqual(old.status,'SKIPPED')
        self.assertEqual(NotificationDelivery.objects.filter(channel='WECOM',status='PENDING').count(),1)
        self.assertEqual(NotificationDelivery.objects.filter(channel='IN_APP',status='ACCEPTED').count(),2)

    def test_disabled_feature_and_preview_never_write(self):
        with override_settings(PURCHASE_TRACKING_ENABLED=False):
            self.assertFalse(self.run_tracking()['enabled'])
            self.assertEqual(self.run_tracking(dry_run=True)['candidate_count'],1)
        self.assertFalse(PurchaseTrackingIssue.objects.exists())
        self.assertFalse(NotificationDelivery.objects.exists())

    def test_disabled_rules_keep_issue_and_enable_later_gets_immediate(self):
        NotificationRule.objects.update(enabled=False)
        self.run_tracking()
        self.assertEqual(PurchaseTrackingIssue.objects.count(),1)
        self.assertFalse(NotificationDelivery.objects.exists())
        NotificationRule.objects.update(enabled=True)
        self.run_tracking()
        self.assertEqual(NotificationDelivery.objects.count(),2)

    def test_inbox_prunes_each_task_after_permission_changes(self):
        from apps.wecom.notification_selectors import recipient_payload
        other=self.make_task('B')
        self.rows.append(self.candidate(other))
        self.run_tracking(now=self.now.replace(hour=1,minute=0))
        recipient=NotificationRecipient.objects.get()
        with patch('apps.procurement.tracking_permissions.employee_can_view_task',
                   side_effect=lambda employee, task_id: str(task_id)==str(self.task.pk)):
            payload=recipient_payload(recipient,self.member.user)
        self.assertIn(self.task.task_number,payload['body'])
        self.assertNotIn(other.task_number,payload['body'])

    def test_attempted_uncertain_content_is_not_revised_or_requeued(self):
        self.run_tracking()
        delivery=NotificationDelivery.objects.get(channel='WECOM')
        delivery.status='UNCERTAIN'
        delivery.attempt_count=1
        delivery.save()
        self.rows[0]['snapshot']['unreceived_quantity']='4'
        self.run_tracking()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status,'UNCERTAIN')
        self.assertEqual(delivery.tracking_contents.count(),1)

    def test_current_follower_union_new_member_receives_and_removed_member_is_suppressed(self):
        self.run_tracking()
        follower=Employee.objects.create(user=get_user_model().objects.create_user(username='tracking-follower'),
            employee_code='TRACK_FOLLOWER',display_name='跟单测试')
        role=RoleProfile.objects.create(auth_group=Group.objects.create(name='tracking-follow-role'),
            role_code='MERCHANDISER',display_name='跟单测试')
        EmployeeRoleAssignment.objects.create(employee=follower,role_profile=role,effective_from=self.now-timedelta(days=1))
        RoleActionGrant.objects.create(role=role,scope='FOLLOWED',permission=Permission.objects.get(
            content_type__app_label='procurement',codename='view_purchaseorder'))
        self.task.followers.add(follower)
        self.run_tracking()
        self.assertEqual(NotificationRecipient.objects.filter(employee=follower).count(),1)
        self.assertEqual(NotificationRecipient.objects.filter(employee=self.member).count(),1)
        self.task.followers.remove(follower)
        self.run_tracking()
        self.assertEqual(NotificationDelivery.objects.get(recipient__employee=follower,channel='WECOM').status,'SKIPPED')
        skipped=NotificationDelivery.objects.get(recipient__employee=follower,channel='WECOM')
        self.assertEqual(skipped.error_code,'TRACKING_RECIPIENT_INELIGIBLE')
        self.task.followers.add(follower)
        self.rows[0]['snapshot']['unreceived_quantity']='3'
        self.run_tracking()
        skipped.refresh_from_db()
        self.assertEqual(skipped.status,'PENDING')
        self.assertEqual(skipped.tracking_contents.count(),2)
        self.assertEqual(NotificationRecipient.objects.filter(employee=follower).count(),1)

    def test_semantic_clock_only_change_does_not_create_a_new_content_revision(self):
        self.rows[0]['snapshot']['evaluated_at']='2026-11-05T00:00:00Z'
        self.run_tracking()
        self.rows[0]['snapshot']['evaluated_at']='2026-11-05T00:01:00Z'
        self.run_tracking()
        self.assertEqual(PurchaseTrackingIssue.objects.get().revision,1)
        self.assertEqual(PurchaseTrackingContent.objects.count(),2)

    def test_material_count_does_not_multiply_same_task_permission_checks(self):
        from copy import deepcopy
        from apps.procurement.tracking_permissions import employee_can_view_task
        from apps.wecom.notification_selectors import unread_count
        for index in range(1,8):
            row=deepcopy(self.rows[0])
            row['source_key']+=f':{index}'
            row['row_key']+=f':{index}'
            self.rows.append(row)
        with patch('apps.procurement.tracking_permissions.employee_can_view_task', wraps=employee_can_view_task) as access:
            self.run_tracking()
        self.assertEqual(access.call_count,1)
        with patch('apps.procurement.tracking_permissions.employee_can_view_task', wraps=employee_can_view_task) as access:
            self.assertEqual(unread_count(self.member.pk),8)
        self.assertEqual(access.call_count,1)


class TrackingTransitionTests(SimpleTestCase):
    def transition(self, previous, candidate):
        module_name = "apps.procurement.tracking_notifications"
        self.assertIsNotNone(importlib.util.find_spec(module_name), "采购风险生命周期尚未实现")
        from apps.procurement.tracking_notifications import issue_transition
        return issue_transition(previous, candidate)

    def previous(self, **changes):
        return SimpleNamespace(**{"active": True, "rank": 20, "cycle": 1,
            "transition": 1, "revision": 1, "fingerprint": "old", **changes})

    def test_same_level_partial_purchase_revises_without_second_immediate(self):
        value = self.transition(self.previous(), {"rank": 20, "fingerprint": "new"})
        self.assertEqual(value, {"cycle": 1, "transition": 1, "revision": 2, "notify": False})

    def test_downgrade_then_upgrade_has_a_new_immediate_opportunity(self):
        value = self.transition(self.previous(rank=30), {"rank": 20, "fingerprint": "new"})
        self.assertEqual(value["transition"], 2)
        self.assertFalse(value["notify"])
        value = self.transition(self.previous(rank=20, transition=2), {"rank": 30, "fingerprint": "new"})
        self.assertEqual(value["transition"], 3)
        self.assertTrue(value["notify"])

    def test_recurrence_with_identical_content_is_a_new_cycle(self):
        value = self.transition(self.previous(active=False), {"rank": 20, "fingerprint": "old"})
        self.assertEqual(value["cycle"], 2)
        self.assertTrue(value["notify"])

    def test_first_discovery_is_not_lost(self):
        self.assertEqual(self.transition(None, {"rank": 20, "fingerprint": "new"}),
                         {"cycle": 1, "transition": 1, "revision": 1, "notify": True})
