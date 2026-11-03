"""确认方案回归：真实隔离库的岗位、任务与收件关系，不调用企微网络。"""
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.audit.models import AuditLog
from apps.organizations.models import EmployeeRoleAssignment
from apps.wecom.models import NotificationEvent
from apps.wecom.notification_audit_events import register_audit_notification
from apps.wecom.notification_role_policy import ROLE_POLICIES, matching_roles
from apps.wecom.notification_selectors import recipient_payload
from apps.wecom.notification_services import _eligible_employees, register_business_event
from apps.wecom.notification_catalog import get_event
from .test_notifications import SETTINGS, create_rule, employee, grant_role
from .test_production_notifications import schedule_fixture


@override_settings(**SETTINGS, CONFIRMED_ROLE_POLICY_ENABLED=True)
class ConfirmedRoleNotificationTests(TestCase):
    def setUp(self):
        with override_settings(CONFIRMED_ROLE_POLICY_ENABLED=False):
            self.f = schedule_fixture()

    def task_event(self, roles, actor=None):
        create_rule('PRODUCTION_TASK_CONFIRMED', self.f.employee, roles, recipient_scope='ROLE_POLICY')
        return register_business_event(event_code='PRODUCTION_TASK_CONFIRMED', idempotency_key=str(uuid4()),
            object_type='production_tasks.ProductionTask', object_id=self.f.task.pk, object_version=1,
            actor_employee=actor or self.f.employee,
            context={'document_no': self.f.task.task_number, 'operator': (actor or self.f.employee).display_name,
                     'occurred_at': timezone.now().isoformat()})

    def add_grant(self, role, code, scope='MODULE'):
        app, codename = code.split('.')
        permission = Permission.objects.get(content_type__app_label=app, codename=codename)
        return RoleActionGrant.objects.create(role=role, permission=permission, scope=scope)

    def test_multi_role_recipient_deduplicates_and_silent_role_does_not_suppress(self):
        member = employee('POLICY_DUAL')
        grant_role(member, 'FINANCE', 'production_tasks.view_productiontask')
        grant_role(member, 'CASHIER', 'production_tasks.view_productiontask')
        grant_role(member, 'GENERAL_MANAGER', 'production_tasks.view_productiontask')
        member.user.is_superuser = True
        member.user.save(update_fields=['is_superuser'])
        event = self.task_event(['FINANCE', 'CASHIER', 'GENERAL_MANAGER'])
        recipient = event.recipients.get()
        self.assertEqual(recipient.employee_id, member.pk)
        self.assertEqual(recipient.role_codes, ['CASHIER', 'FINANCE'])
        self.assertEqual(recipient.deliveries.count(), 2)

    def test_recovery_admin_with_business_role_uses_same_policy_channels(self):
        member = employee('ADMIN')
        grant_role(member, 'TECHNICAL', 'production_tasks.view_productiontask')
        member.user.is_superuser = True
        member.user.save(update_fields=['is_superuser'])
        event = self.task_event(['TECHNICAL'])
        self.assertEqual(event.recipients.get().deliveries.get(channel='WECOM').status, 'PENDING')

    def test_actor_exclusion_is_per_role(self):
        member = employee('POLICY_SELF')
        grant_role(member, 'TECHNICAL', 'production_tasks.view_productiontask')
        grant_role(member, 'PMC', 'production_tasks.view_productiontask')
        event = self.task_event(['TECHNICAL', 'PMC'], member)
        self.assertEqual(event.recipients.get().role_codes, ['TECHNICAL'])

    def test_only_silent_superuser_does_not_receive(self):
        member = employee('POLICY_SILENT')
        grant_role(member, 'GENERAL_MANAGER', 'production_tasks.view_productiontask')
        member.user.is_superuser = True
        member.user.save(update_fields=['is_superuser'])
        self.assertFalse(self.task_event(['GENERAL_MANAGER']).recipients.exists())

    def test_superuser_followed_role_still_requires_current_assignment_and_grant(self):
        member = employee('POLICY_FOLLOW')
        role = grant_role(member, 'MERCHANDISER', 'production_tasks.view_productiontask', 'FOLLOWED')
        member.user.is_superuser = True
        member.user.save(update_fields=['is_superuser'])
        self.f.task.followers.add(member)
        event = self.task_event(['MERCHANDISER'])
        recipient = event.recipients.get()
        self.assertTrue(recipient_payload(recipient, member.user)['target_accessible'])
        self.f.task.followers.remove(member)
        payload = recipient_payload(recipient, member.user)
        self.assertFalse(payload['target_accessible'])
        self.assertNotIn(self.f.task.task_number, payload['body'])
        self.f.task.followers.add(member)
        RoleActionGrant.objects.filter(role=role).delete()
        self.assertFalse(recipient_payload(recipient, member.user)['target_accessible'])

    def test_delivery_eligibility_uses_current_membership(self):
        member = employee('POLICY_MEMBER')
        role = grant_role(member, 'TECHNICAL', 'production_tasks.view_productiontask')
        event = self.task_event(['TECHNICAL'])
        recipient = event.recipients.get()
        EmployeeRoleAssignment.objects.filter(employee=member, role_profile=role).update(effective_to=timezone.now())
        from types import SimpleNamespace
        rule = SimpleNamespace(recipient_scope=recipient.scope, recipient_role_codes=recipient.role_codes)
        self.assertEqual(_eligible_employees(get_event(event.event_code), rule, event.context,
            event.object_id, employee_id=member.pk), [])

    def test_factory_only_receives_administration_confirmation(self):
        manager = employee('POLICY_FACTORY')
        grant_role(manager, 'FACTORY_MANAGER', 'production_tasks.view_productiontask')
        event = self.task_event(['FACTORY_MANAGER'])
        self.assertFalse(event.recipients.exists())
        grant_role(self.f.employee, 'ADMINISTRATION', 'production_tasks.confirm_productiontask')
        from apps.wecom.models import NotificationRule
        NotificationRule.objects.filter(event_code='PRODUCTION_TASK_CONFIRMED').delete()
        event = self.task_event(['FACTORY_MANAGER'])
        self.assertEqual(event.recipients.get().employee_id, manager.pk)

    def test_closed_gate_has_no_new_policy_receivers(self):
        member = employee('POLICY_GATE')
        grant_role(member, 'TECHNICAL', 'production_tasks.view_productiontask')
        with override_settings(CONFIRMED_ROLE_POLICY_ENABLED=False):
            self.assertFalse(self.task_event(['TECHNICAL']).recipients.exists())

    def audit(self, action, before, after, object_type='PRODUCTION_TASK', object_id=None):
        return AuditLog.objects.create(object_type=object_type, object_id=object_id or self.f.task.pk,
            action=action, before_data=before, after_data=after, actor_employee=self.f.employee,
            actor_name_snapshot=self.f.employee.display_name, occurred_at=timezone.now())

    def test_new_follower_only_receives_assignment_and_old_reader_loses_access(self):
        new = employee('POLICY_NEW_FOLLOW')
        old = employee('POLICY_OLD_FOLLOW')
        role = grant_role(new, 'MERCHANDISER', 'production_tasks.view_productiontask', 'FOLLOWED')
        EmployeeRoleAssignment.objects.create(employee=old, role_profile=role, effective_from=timezone.now()-timedelta(minutes=1))
        self.f.task.followers.set([new])
        create_rule('PRODUCTION_TASK_UPDATED', self.f.employee, ['MERCHANDISER'], recipient_scope='ROLE_POLICY')
        log = self.audit('UPDATED', {'follower_ids': [str(old.pk)]}, {'follower_ids': [str(new.pk)]})
        event = register_audit_notification(log)
        self.assertEqual(list(event.recipients.values_list('employee_id', flat=True)), [new.pk])
        self.assertEqual(register_audit_notification(log).pk, event.pk)

    def test_deleted_finance_summary_has_no_target_and_revoked_grant_hides_it(self):
        member = employee('POLICY_FINANCE')
        role = grant_role(member, 'FINANCE', 'finance.view_receivablestatement')
        create_rule('FINANCE_STATEMENT_CHANGED', self.f.employee, ['FINANCE'], recipient_scope='ROLE_POLICY')
        log = self.audit('DELETE', {'number': 'DELETED-STATEMENT'}, {}, 'RECEIVABLE_STATEMENT', uuid4())
        event = register_audit_notification(log)
        recipient = event.recipients.get()
        payload = recipient_payload(recipient, member.user)
        self.assertIn('DELETED-STATEMENT', payload['body'])
        self.assertIsNone(payload['target'])
        RoleActionGrant.objects.filter(role=role).delete()
        self.assertNotIn('DELETED-STATEMENT', recipient_payload(recipient, member.user)['body'])

    def test_failure_audits_and_closed_gate_do_not_create_events(self):
        log = self.audit('DELETE_CLEANUP_FAILED', {}, {}, 'RECEIVABLE_STATEMENT', uuid4())
        self.assertIsNone(register_audit_notification(log))
        with override_settings(CONFIRMED_ROLE_POLICY_ENABLED=False):
            self.assertIsNone(register_audit_notification(self.audit('UPDATED', {}, {'delivery_date': '2026-11-02'})))

    def test_individual_bom_confirmation_keeps_real_product_and_version(self):
        member = employee('POLICY_BOM_TECH')
        grant_role(member, 'TECHNICAL', 'boms.view_bom')
        create_rule('BOM_CONFIRMED', self.f.employee, ['TECHNICAL'], recipient_scope='ROLE_POLICY')
        log = self.audit('VERIFY', {'status': 'PENDING_CONFIRMATION'}, {'status': 'VERIFIED'}, 'BOM', self.f.bom.pk)
        event = register_audit_notification(log)
        payload = recipient_payload(event.recipients.get(), member.user)
        self.assertIn(self.f.bom.product_name_snapshot, payload['body'])
        self.assertEqual(event.object_version, str(self.f.bom.version_number))
        self.assertEqual(payload['target']['params'], {'bomId': str(self.f.bom.pk)})

    def test_bom_ready_purchase_and_admin_receive_without_bom_read_grant(self):
        from apps.boms.notification_events import register_task_boms_confirmed
        purchase = employee('POLICY_BOM_PURCHASE')
        admin = employee('POLICY_BOM_ADMIN')
        grant_role(purchase, 'PURCHASING', 'procurement.add_purchaseorder')
        grant_role(admin, 'ADMINISTRATION', 'production_tasks.view_productiontask')
        create_rule('PRODUCTION_TASK_BOMS_CONFIRMED', self.f.employee, ['PURCHASING', 'ADMINISTRATION'], recipient_scope='ROLE_POLICY')
        event = register_task_boms_confirmed(task_id=self.f.task.pk, actor_employee=self.f.employee, confirmed_at=timezone.now())
        self.assertEqual(event.recipients.count(), 2)
        payload = recipient_payload(event.recipients.get(employee=purchase), purchase.user)
        self.assertEqual(payload['target']['route_name'], 'purchase-order-create')
        payload = recipient_payload(event.recipients.get(employee=admin), admin.user)
        self.assertEqual(payload['target']['route_name'], 'production-task-detail')

    def test_transaction_rollback_removes_notification(self):
        member = employee('POLICY_ROLLBACK')
        grant_role(member, 'TECHNICAL', 'production_tasks.view_productiontask')
        with self.assertRaises(RuntimeError), transaction.atomic():
            event = self.task_event(['TECHNICAL'])
            identifier = event.pk
            raise RuntimeError('rollback')
        self.assertFalse(NotificationEvent.objects.filter(pk=identifier).exists())

    def test_director_receipt_requires_original_submitter_and_selected_workshop(self):
        from apps.workshop_config.models import Workshop
        workshop = Workshop.objects.get(name='金工车间')
        member = employee('POLICY_DIRECTOR')
        role = grant_role(member, 'METAL_DIRECTOR', 'material_issues.view_materialissue', 'WORKSHOP')
        grant = RoleActionGrant.objects.get(role=role)
        RoleGrantResource.objects.create(grant=grant, workshop=workshop)
        facts = {'task_ids': {str(self.f.task.pk)}, 'actor_id': str(self.f.employee.pk), 'actor_roles': set(),
            'action': '', 'changed_fields': set(), 'new_follower_ids': set(), 'coating': False,
            'craft_ids': set(), 'workshop_ids': {str(workshop.pk)}, 'submitter_id': str(member.pk)}
        self.assertEqual(matching_roles('MATERIAL_ISSUE_ISSUED', member, ['METAL_DIRECTOR'], facts), ['METAL_DIRECTOR'])
        facts['submitter_id'] = str(self.f.employee.pk)
        self.assertEqual(matching_roles('MATERIAL_ISSUE_ISSUED', member, ['METAL_DIRECTOR'], facts), [])

    def test_sampling_requirements_explicitly_includes_actor(self):
        member = employee('POLICY_SAMPLER')
        grant_role(member, 'FABRIC_SAMPLING', 'samples.edit_sample_materials')
        facts = {'task_ids': set(), 'actor_id': str(member.pk), 'actor_roles': set(), 'action': '',
            'changed_fields': set(), 'new_follower_ids': set(), 'coating': False,
            'craft_ids': set(), 'workshop_ids': set(), 'submitter_id': str(member.pk)}
        self.assertEqual(matching_roles('SAMPLE_REQUIREMENTS_COMPLETED', member, ['FABRIC_SAMPLING'], facts), ['FABRIC_SAMPLING'])
        self.assertNotIn('MERCHANDISER', ROLE_POLICIES['WORK_REPORT_SAVED'])
