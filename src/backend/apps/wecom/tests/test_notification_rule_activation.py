"""首次配置的整批保护和落库检查；隔离PostgreSQL，不代表真实员工验收。"""
from io import StringIO
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.organizations.models import Employee, RoleProfile
from apps.wecom.management.commands.configure_production_notification_rules import DISABLED_REASONS, notification_plan
from apps.wecom.models import NotificationRule, NotificationEvent, NotificationRecipient, NotificationDelivery
from apps.wecom.notification_catalog import all_events


class NotificationRuleActivationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(username='admin', email='')
        Employee.objects.create(user=cls.user, employee_code='ACTIVATION_ADMIN', display_name='隔离配置管理员')
        codes = {code for event in all_events() for code in event['default_role_codes']}
        for code in codes:
            RoleProfile.objects.create(role_code=code, display_name=code, auth_group=Group.objects.create(name=code))

    def apply(self, **updates):
        options = dict(apply=True, database_name=connection.settings_dict['NAME'], actor_username='admin',
            expected_digest=notification_plan()['digest'], stdout=StringIO())
        options.update(updates)
        call_command('configure_production_notification_rules', **options)
        return json.loads(options['stdout'].getvalue())

    def test_default_preview_policy_and_no_writes(self):
        # notification_plan与命令只读分支相同；TestCase事务已查询，不能再次SET TRANSACTION。
        plan = notification_plan()
        self.assertEqual(len(plan['rules']), len(all_events()))
        self.assertEqual({row['event_code'] for row in plan['rules'] if not row['after']['enabled']}, set(DISABLED_REASONS))
        self.assertFalse(plan['will_send'])
        self.assertFalse(NotificationRule.objects.exists())

    def test_pending_receipt_events_are_enabled_and_confirmation_can_target_submitter(self):
        plan = notification_plan()
        rows = {row['event_code']: row for row in plan['rules']}
        self.assertTrue(rows['SEMI_FINISHED_RECEIPT_SUBMITTED']['after']['enabled'])
        self.assertTrue(rows['ASSEMBLY_FINISHED_RECEIPT_SUBMITTED']['after']['enabled'])

        from apps.wecom.notification_catalog import get_event
        for code in ('INTERNAL_SEMI_RECEIPT_CONFIRMED', 'ASSEMBLY_FINISHED_RECEIPT_CONFIRMED'):
            event = get_event(code)
            self.assertIn('SUBMITTER', event['supported_scopes'])
            self.assertIn('confirmed_by', event['allowed_variables'])
            self.assertIn('confirmed_at', event['allowed_variables'])

    def test_existing_pending_rule_keeps_manual_disabled_state(self):
        event = next(event for event in all_events() if event['event_code'] == 'SEMI_FINISHED_RECEIPT_SUBMITTED')
        from apps.wecom.notification_selectors import default_rule_payload
        payload = default_rule_payload(event)
        NotificationRule.objects.create(event_code=event['event_code'], allowed_variables=event['allowed_variables'],
            updated_by_employee=self.user.employee_profile, name=payload['name'],
            title_template=payload['title_template'], body_template=payload['body_template'],
            recipient_role_codes=payload['recipient_role_codes'], recipient_scope=payload['recipient_scope'],
            enabled=False)
        row = next(row for row in notification_plan()['rules'] if row['event_code'] == event['event_code'])
        self.assertEqual(row['change'], 'PRESERVE')
        self.assertFalse(row['after']['enabled'])

    def test_apply_audits_all_rules_without_messages_and_repeat_preserves_versions(self):
        result = self.apply()
        self.assertEqual(result['created_count'], len(all_events()))
        self.assertEqual(NotificationRule.objects.filter(enabled=True).count(), len(all_events()) - len(DISABLED_REASONS))
        self.assertEqual(AuditLog.objects.filter(object_type='WECOM_NOTIFICATION', action='RULE_UPDATE').count(), len(all_events()))
        for model in [NotificationEvent, NotificationRecipient, NotificationDelivery]:
            self.assertFalse(model.objects.exists())
        self.assertEqual(self.apply()['created_count'], 0)
        self.assertEqual(set(NotificationRule.objects.values_list('version', flat=True)), {1})
        self.assertEqual(AuditLog.objects.filter(object_type='WECOM_NOTIFICATION', action='RULE_UPDATE').count(), len(all_events()))

    def test_database_digest_and_manager_guards_prevent_all_writes(self):
        for updates in [{'database_name': 'wrong'}, {'expected_digest': 'stale'}, {'actor_username': 'missing'}]:
            with self.subTest(updates=updates), self.assertRaises(CommandError):
                self.apply(**updates)
            self.assertFalse(NotificationRule.objects.exists())

    def test_missing_role_stops_before_any_write(self):
        RoleProfile.objects.filter(role_code='TECHNICAL').update(archived_at=timezone.now())
        with self.assertRaises(CommandError):
            self.apply()
        self.assertFalse(NotificationRule.objects.exists())

    def test_existing_custom_rule_is_preserved(self):
        self.apply()
        rule = NotificationRule.objects.get(event_code='PRODUCTION_TASK_CONFIRMED')
        rule.title_template = '任务确认知悉'
        rule.enabled = False
        rule.save()
        self.assertEqual(self.apply()['created_count'], 0)
        rule.refresh_from_db()
        self.assertEqual(rule.title_template, '任务确认知悉')
        self.assertFalse(rule.enabled)

    def test_conflicting_enabled_deferred_rule_stops_before_new_rules(self):
        row = next(row for row in notification_plan()['rules'] if row['event_code'] == 'SAMPLE_INVENTORY_RECEIVED')
        NotificationRule.objects.create(event_code=row['event_code'], allowed_variables=row['allowed_variables'],
            updated_by_employee=self.user.employee_profile,
            **{**row['after'], 'enabled': True})
        with self.assertRaises(CommandError):
            self.apply()
        self.assertEqual(NotificationRule.objects.count(), 1)
