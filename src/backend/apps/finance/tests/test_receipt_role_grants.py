import json
from io import StringIO
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.organizations.models import (
    Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment,
    OrganizationUnit, RoleProfile,
)


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True)
class ReceiptRoleGrantTests(TestCase):
    def setUp(self):
        self.roles = {}
        for code in ("FINANCE", "CASHIER", "FACTORY_MANAGER", "GENERAL_MANAGER", "U04_GRANT_MANAGER"):
            self.roles[code] = RoleProfile.objects.create(
                role_code=code, display_name=code, auth_group=Group.objects.create(name=code),
            )
        self.actor = self.employee("MANAGER", manager=True)
        self.member = self.employee("MEMBER")
        EmployeeRoleAssignment.objects.create(
            employee=self.member, role_profile=self.roles["FINANCE"], effective_from=timezone.now(),
        )
        department = OrganizationUnit.objects.create(unit_code="U04_GRANT_DEPT", unit_name="隔离授权部门")
        EmployeeOrganizationAssignment.objects.create(
            employee=self.member, organization_unit=department, effective_from=timezone.now(), is_primary=True,
        )
        self.old_permission = Permission.objects.get(content_type__app_label="reference_data", codename="view_currency")
        RoleActionGrant.objects.create(role=self.roles["FINANCE"], permission=self.old_permission, scope="MODULE")
        self.roles["FINANCE"].auth_group.permissions.add(self.old_permission)
        self.member.user.groups.add(Group.objects.create(name="U04_GRANT_UNRELATED_NATIVE_GROUP"))
        self.member.user.user_permissions.add(self.old_permission)

    def employee(self, suffix, *, manager=False, **changes):
        user = get_user_model().objects.create_user(f"u04_grant_{suffix.lower()}")
        employee = Employee.objects.create(user=user, employee_code=f"U04_GRANT_{suffix}", display_name="隔离授权测试", **changes)
        if manager:
            role = self.roles["U04_GRANT_MANAGER"]
            permission = Permission.objects.get(content_type__app_label="access_control", codename="manage_access")
            RoleActionGrant.objects.get_or_create(role=role, permission=permission, scope="MODULE")
            role.auth_group.permissions.add(permission)
            EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
        return employee

    def employee_relations(self):
        user = get_user_model()
        return {
            model._meta.label: list(model.objects.order_by("pk").values())
            for model in (Employee, EmployeeRoleAssignment, EmployeeOrganizationAssignment,
                          user.groups.through, user.user_permissions.through)
        }

    def grants(self):
        return list(RoleActionGrant.objects.order_by("pk").values())

    def run_command(self, command="grant_finance_receipt_roles", **options):
        output = StringIO()
        call_command(command, database_name=connection.settings_dict["NAME"], stdout=output, **options)
        return output.getvalue()

    def assert_idempotent_grant(self, command, codenames, expected_count):
        relations = self.employee_relations()
        before_grants = self.grants()
        before_audits = AuditLog.objects.count()
        preview = json.loads(self.run_command(command))
        self.assertEqual(preview["mode"], "READ_ONLY")
        self.assertEqual(sum(len(item["add"]) for item in preview["plan"]), expected_count)
        self.assertEqual(self.grants(), before_grants)
        self.assertEqual(AuditLog.objects.count(), before_audits)
        output = self.run_command(command, apply=True, actor_employee_id=self.actor.pk)
        self.assertIn(f"APPLIED_AND_READ_BACK: {expected_count} MODULE grants", output)
        actual = set(RoleActionGrant.objects.filter(
            permission__content_type__app_label="finance",
        ).values_list("role__role_code", "permission__codename", "scope"))
        expected = {(role, code, "MODULE") for role in ("FINANCE", "CASHIER", "FACTORY_MANAGER", "GENERAL_MANAGER")
                    for code in codenames}
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), expected_count)
        self.assertEqual(AuditLog.objects.count() - before_audits, expected_count)
        applied = self.grants()
        group_permissions = list(Group.permissions.through.objects.order_by("pk").values())
        after_audits = AuditLog.objects.count()
        repeated = self.run_command(command, apply=True, actor_employee_id=self.actor.pk)
        self.assertIn(f"APPLIED_AND_READ_BACK: {expected_count} MODULE grants", repeated)
        self.assertEqual(self.grants(), applied)
        self.assertEqual(list(Group.permissions.through.objects.order_by("pk").values()), group_permissions)
        self.assertEqual(AuditLog.objects.count(), after_audits)
        self.assertEqual(self.employee_relations(), relations)
        for original in before_grants:
            self.assertIn(original, applied)
        self.assertTrue(self.roles["FINANCE"].auth_group.permissions.filter(pk=self.old_permission.pk).exists())
        preview = json.loads(self.run_command(command))
        self.assertEqual(sum(len(item["add"]) for item in preview["plan"]), 0)
        self.assertEqual(sum(len(item["unchanged"]) for item in preview["plan"]), expected_count)

    def test_account_command_remains_16(self):
        self.assert_idempotent_grant("grant_finance_account_roles", (
            "view_financeaccount", "add_financeaccount", "change_financeaccount", "delete_financeaccount",
        ), 16)

    def test_subject_command_remains_16(self):
        self.assert_idempotent_grant("grant_finance_subject_roles", (
            "view_accountingsubject", "add_accountingsubject", "change_accountingsubject", "delete_accountingsubject",
        ), 16)

    def test_statement_command_remains_16(self):
        self.assert_idempotent_grant("grant_finance_statement_roles", (
            "view_receivablestatement", "add_receivablestatement", "change_receivablestatement", "void_receivablestatement",
        ), 16)

    def test_receipt_command_dry_run_and_idempotent_apply(self):
        self.assert_idempotent_grant("grant_finance_receipt_roles", (
            "view_receipt", "add_receipt", "void_receipt",
        ), 12)

    def test_delete_command_only_adds_eight_and_is_idempotent(self):
        self.assert_idempotent_grant("grant_finance_delete_roles", (
            "delete_receivablestatement", "delete_receipt",
        ), 8)

    def test_rejects_unqualified_actors_without_grants_or_audit(self):
        disabled = self.employee("DISABLED", manager=True)
        disabled.user.is_active = False
        disabled.user.save(update_fields=["is_active"])
        left = self.employee("LEFT", manager=True, status="LEFT")
        archived = self.employee("ARCHIVED", manager=True, archived_at=timezone.now())
        unbound = Employee.objects.create(employee_code="U04_GRANT_UNBOUND", display_name="隔离无账号")
        before_grants, before_audits, relations = self.grants(), AuditLog.objects.count(), self.employee_relations()
        for actor in (None, uuid4(), unbound.pk, self.member.pk, disabled.pk, left.pk, archived.pk):
            with self.subTest(actor=actor), self.assertRaises(CommandError):
                self.run_command(apply=True, actor_employee_id=actor)
            self.assertEqual(self.grants(), before_grants)
            self.assertEqual(AuditLog.objects.count(), before_audits)
            self.assertEqual(self.employee_relations(), relations)

    def test_rejects_scope_conflict_without_expansion(self):
        permission = Permission.objects.get(content_type__app_label="finance", codename="view_receipt")
        RoleActionGrant.objects.create(role=self.roles["FINANCE"], permission=permission, scope="OWN")
        before_grants, before_audits = self.grants(), AuditLog.objects.count()
        for apply in (False, True):
            with self.subTest(apply=apply), self.assertRaisesMessage(CommandError, "现有权限范围冲突"):
                self.run_command(apply=apply, actor_employee_id=self.actor.pk)
            self.assertEqual(self.grants(), before_grants)
            self.assertEqual(AuditLog.objects.count(), before_audits)

    def test_rejects_wrong_database_name(self):
        before_grants = self.grants()
        with self.assertRaisesMessage(CommandError, "目标数据库名不匹配"):
            call_command("grant_finance_receipt_roles", database_name="not_the_registered_test_database",
                         apply=True, actor_employee_id=self.actor.pk, stdout=StringIO())
        self.assertEqual(self.grants(), before_grants)

    def test_rejects_archived_role_and_disabled_management(self):
        before_grants = self.grants()
        self.roles["CASHIER"].archived_at = timezone.now()
        self.roles["CASHIER"].save(update_fields=["archived_at"])
        with self.assertRaisesMessage(CommandError, "目标角色已归档"):
            self.run_command(apply=True, actor_employee_id=self.actor.pk)
        self.roles["CASHIER"].archived_at = None
        self.roles["CASHIER"].save(update_fields=["archived_at"])
        with override_settings(ACCESS_MANAGEMENT_ENABLED=False), self.assertRaisesMessage(CommandError, "权限管理尚未启用"):
            self.run_command(apply=True, actor_employee_id=self.actor.pk)
        self.assertEqual(self.grants(), before_grants)
