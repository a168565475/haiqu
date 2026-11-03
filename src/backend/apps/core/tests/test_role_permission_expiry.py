from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.utils import timezone

from apps.core.views import user_payload
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile


class RolePermissionExpiryTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.user = get_user_model().objects.create_user("role-expiry-user")
        self.employee = Employee.objects.create(
            user=self.user, employee_code="ROLE-EXPIRY", display_name="任职到期测试",
        )
        self.other_employee = Employee.objects.create(
            employee_code="ROLE-EXPIRY-OTHER", display_name="同角色员工",
        )

    def role(self, code, permission_code, *, archived=False):
        app_label, codename = permission_code.split(".")
        permission = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        role = RoleProfile.objects.create(
            role_code=code, display_name=code, auth_group=Group.objects.create(name=code),
            archived_at=self.now if archived else None,
        )
        role.auth_group.permissions.add(permission)
        return role

    def assert_expired_assignment_denied(self, other_effective_to):
        role = self.role("EXPIRY_OLD_ADMIN", "attendance.view_attendance")
        EmployeeRoleAssignment.objects.create(
            employee=self.employee, role_profile=role,
            effective_from=self.now - timedelta(days=2), effective_to=self.now - timedelta(days=1),
        )
        EmployeeRoleAssignment.objects.create(
            employee=self.other_employee, role_profile=role,
            effective_from=self.now - timedelta(days=1), effective_to=other_effective_to,
        )

        # 另一员工仍在同一岗位，不能让本人的已结束任职继续提供权限。
        self.assertNotIn("attendance.view_attendance", self.user.get_all_permissions())
        self.assertNotIn("attendance.view_attendance", user_payload(self.user)["permissions"])

    def test_expired_assignment_cannot_borrow_other_employee_open_assignment(self):
        self.assert_expired_assignment_denied(None)

    def test_expired_assignment_cannot_borrow_other_employee_timed_assignment(self):
        self.assert_expired_assignment_denied(self.now + timedelta(days=1))

    def test_current_roles_keep_union_and_ignore_future_or_archived_roles(self):
        for code, permission, starts_in_days, ends_in_days, archived in (
            ("EXPIRY_PURCHASE", "procurement.view_purchaseorder", -1, None, False),
            ("EXPIRY_BOM", "boms.view_bom", -1, 1, False),
            ("EXPIRY_FUTURE", "attendance.view_attendance", 1, None, False),
            ("EXPIRY_ARCHIVED", "production_tasks.add_productiontask", -1, None, True),
        ):
            role = self.role(code, permission, archived=archived)
            EmployeeRoleAssignment.objects.create(
                employee=self.employee, role_profile=role,
                effective_from=self.now + timedelta(days=starts_in_days),
                effective_to=self.now + timedelta(days=ends_in_days) if ends_in_days is not None else None,
            )
        native_group = Group.objects.create(name="expiry-native-group")
        native_group.permissions.add(Permission.objects.get(
            content_type__app_label="production_tasks", codename="view_productiontask",
        ))
        self.user.groups.add(native_group)
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="customers", codename="view_customeraccount",
        ))

        self.assertEqual(self.user.get_all_permissions(), {
            "procurement.view_purchaseorder", "boms.view_bom",
            "production_tasks.view_productiontask", "customers.view_customeraccount",
        })
