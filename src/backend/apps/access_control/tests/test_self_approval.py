from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.access_control.module_policy import prohibit_self_approval
from apps.organizations.models import Employee


@override_settings(MODULE_ACCESS_ENABLED=True)
class SelfApprovalTests(SimpleTestCase):
    def actor(self, **user_fields):
        return Employee(user=get_user_model()(**user_fields), status='ACTIVE')

    def test_active_superuser_can_review_own_submission(self):
        actor = self.actor(is_superuser=True, is_active=True)
        prohibit_self_approval(actor, actor.pk)

    def test_staff_or_admin_username_does_not_grant_exemption(self):
        for fields in ({}, {'is_staff': True}, {'username': 'admin'}):
            with self.subTest(fields=fields):
                actor = self.actor(**fields)
                with self.assertRaisesMessage(PermissionDenied, '提交人不能审批'):
                    prohibit_self_approval(actor, actor.pk)

    def test_inactive_superuser_or_employee_is_not_exempt(self):
        for field in ('user', 'status', 'archived_at'):
            with self.subTest(field=field):
                actor = self.actor(is_superuser=True, is_active=True)
                if field == 'user':
                    actor.user.is_active = False
                elif field == 'status':
                    actor.status = 'INACTIVE'
                else:
                    actor.archived_at = timezone.now()
                with self.assertRaises(PermissionDenied):
                    prohibit_self_approval(actor, actor.pk)

    def test_other_submitter_remains_reviewable(self):
        prohibit_self_approval(self.actor(), self.actor().pk)

    def test_missing_submitter_still_requires_verifiable_source(self):
        actor = self.actor(is_superuser=True, is_active=True)
        with self.assertRaisesMessage(PermissionDenied, '缺少可核实的提交人'):
            prohibit_self_approval(actor, None)
