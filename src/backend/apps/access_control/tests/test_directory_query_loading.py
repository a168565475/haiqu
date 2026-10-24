from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import (
    Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile,
)
from apps.workshop_config.models import Workshop
from apps.access_control.api.serializers import AccessEmployeeSerializer, RoleSerializer, TeamSerializer
from apps.access_control.api.views import AccessEmployeeViewSet, RoleViewSet, SalesTeamViewSet
from apps.access_control.models import RoleActionGrant, RoleGrantResource, SalesTeam, SalesTeamMembership
from apps.access_control.selectors import (
    employees_with_directory_context, roles_with_directory_context, teams_with_directory_context,
)


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class DirectoryQueryLoadingTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        cls.admin = get_user_model().objects.create_superuser("admin")
        cls.manager = Employee.objects.create(user=cls.admin, employee_code="DIRECTORY_ADMIN", display_name="管理员")
        cls.workshop = Workshop.objects.get(name="金工车间")
        permission = Permission.objects.get(content_type__app_label="workshop_reporting", codename="view_workreport")
        cls.employee_ids = []
        cls.role_ids = []
        cls.team_ids = []
        for index in range(25):
            user = get_user_model().objects.create_user(f"directory_employee_{index}")
            employee = Employee.objects.create(user=user, employee_code=f"000_DIRECTORY_{index:02}", display_name=f"员工{index}")
            department = OrganizationUnit.objects.create(unit_code=f"DIRECTORY_{index:02}", unit_name=f"部门{index}")
            role = RoleProfile.objects.create(
                auth_group=Group.objects.create(name=f"DIRECTORY_ROLE_{index}"),
                role_code=f"000_DIRECTORY_{index:02}", display_name=f"角色{index}",
            )
            EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=cls.now - timedelta(days=1))
            EmployeeOrganizationAssignment.objects.create(employee=employee, organization_unit=department, effective_from=cls.now - timedelta(days=1))
            grant = RoleActionGrant.objects.create(role=role, permission=permission, scope="WORKSHOP")
            RoleGrantResource.objects.create(grant=grant, workshop=cls.workshop)
            team = SalesTeam.objects.create(code=f"000_DIRECTORY_{index:02}", name=f"业务组{index}", manager=cls.manager)
            SalesTeamMembership.objects.create(team=team, employee=employee, created_by_employee=cls.manager)
            cls.employee_ids.append(employee.pk)
            cls.role_ids.append(role.pk)
            cls.team_ids.append(team.pk)

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def assert_list_queries_do_not_grow(self, path):
        counts = []
        for page_size in (1, 25):
            self.client.force_authenticate(get_user_model().objects.get(pk=self.admin.pk))
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(f"/api/v1/access/{path}/", {"page_size": page_size})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(len(response.data["data"]), page_size)
            counts.append(len(queries))
        self.assertEqual(counts[1], counts[0], f"{path}: 1条和25条的查询数分别为{counts}")

    def test_employee_list_queries_do_not_grow_with_page_size(self):
        self.assert_list_queries_do_not_grow("employees")

    def test_role_list_queries_do_not_grow_with_page_size(self):
        self.assert_list_queries_do_not_grow("roles")

    def test_team_list_queries_do_not_grow_with_page_size(self):
        self.assert_list_queries_do_not_grow("sales-teams")

    def test_employee_prefetch_preserves_time_status_and_account_fields(self):
        employee = Employee.objects.get(pk=self.employee_ids[0])
        for index, (start, end, archived) in enumerate([
            (self.now, None, False),
            (self.now + timedelta(seconds=1), None, False),
            (self.now - timedelta(days=1), self.now, False),
            (self.now - timedelta(days=1), self.now + timedelta(seconds=1), False),
            (self.now - timedelta(days=1), None, True),
        ]):
            role = RoleProfile.objects.create(
                auth_group=Group.objects.create(name=f"DIRECTORY_BOUNDARY_{index}"),
                role_code=f"DIRECTORY_BOUNDARY_{index}", display_name=f"边界角色{index}",
                archived_at=self.now if archived else None,
            )
            EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=start, effective_to=end)
            department = OrganizationUnit.objects.create(
                unit_code=f"DIRECTORY_BOUNDARY_{index}", unit_name=f"边界部门{index}",
                archived_at=self.now if archived else None,
            )
            EmployeeOrganizationAssignment.objects.create(employee=employee, organization_unit=department, effective_from=start, effective_to=end)
        inactive = OrganizationUnit.objects.create(unit_code="DIRECTORY_INACTIVE", unit_name="停用部门", status="INACTIVE")
        EmployeeOrganizationAssignment.objects.create(employee=employee, organization_unit=inactive, effective_from=self.now - timedelta(days=1))
        SalesTeam.objects.filter(pk=self.team_ids[0]).update(is_active=False)
        no_account = Employee.objects.create(employee_code="DIRECTORY_NO_ACCOUNT", display_name="无账号")
        ids = [employee.pk, no_account.pk, self.manager.pk]
        base = Employee.objects.filter(pk__in=ids).select_related("user", "wecom_binding").order_by("employee_code")
        with patch("django.utils.timezone.now", return_value=self.now):
            expected = AccessEmployeeSerializer(base.all(), many=True).data
            actual = AccessEmployeeSerializer(employees_with_directory_context(base.all()), many=True).data
        # 原查询没有关系排序契约；合成数据比较成员及部门 ID-名称配对。
        # 真实页面的部门显示顺序另由只读接口完整响应对照覆盖。
        for rows in (expected, actual):
            for row in rows:
                self.assertEqual(len(row["role_ids"]), len(set(row["role_ids"])))
                row["role_ids"] = sorted(row["role_ids"])
                names = row["department"].split("、") if row["department"] else []
                self.assertEqual(len(names), len(row["department_ids"]))
                departments = sorted(zip(row["department_ids"], names))
                row["department_ids"] = [pk for pk, _ in departments]
                row["department"] = "、".join(name for _, name in departments)
        self.assertEqual(actual, expected)
        row = next(row for row in actual if row["id"] == str(employee.pk))
        self.assertEqual(len(row["role_ids"]), 3)
        self.assertEqual(len(row["department_ids"]), 3)
        self.assertEqual(row["team_id"], str(self.team_ids[0]))
        self.assertIsNone(next(row for row in actual if row["id"] == str(no_account.pk))["login_count"])
        self.assertTrue(next(row for row in actual if row["id"] == str(self.manager.pk))["account_protected"])

    def test_role_prefetch_preserves_counts_grants_resources_and_etag(self):
        role = RoleProfile.objects.get(pk=self.role_ids[0])
        for index, (start, end) in enumerate([
            (self.now, None),
            (self.now + timedelta(seconds=1), None),
            (self.now - timedelta(days=1), self.now),
            (self.now - timedelta(days=1), self.now + timedelta(seconds=1)),
        ]):
            employee = Employee.objects.create(
                employee_code=f"DIRECTORY_COUNT_{index}", display_name="人数边界",
                status="LEFT", archived_at=self.now,
            )
            EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=start, effective_to=end)
        base = RoleProfile.objects.filter(pk__in=self.role_ids).select_related("auth_group").order_by("role_code")
        with patch("django.utils.timezone.now", return_value=self.now):
            expected = RoleSerializer(base.all(), many=True).data
            actual = RoleSerializer(roles_with_directory_context(base.all()), many=True).data
        self.assertEqual(actual, expected)
        self.assertEqual(actual[0]["assigned_employee_count"], 3)
        self.assertEqual(actual[0]["grants"][0]["resource_ids"], [str(self.workshop.pk)])

    def test_team_prefetch_preserves_members_and_etag(self):
        employee = Employee.objects.create(employee_code="DIRECTORY_EXTRA_MEMBER", display_name="额外成员")
        SalesTeamMembership.objects.create(team_id=self.team_ids[0], employee=employee, created_by_employee=self.manager)
        base = SalesTeam.objects.filter(pk__in=self.team_ids).select_related("manager").order_by("code")
        self.assertEqual(
            TeamSerializer(teams_with_directory_context(base.all()), many=True).data,
            TeamSerializer(base.all(), many=True).data,
        )

    @override_settings(ACCESS_RESOURCE_SCOPES_ENABLED=False)
    def test_disabled_resource_scopes_never_query_resource_table(self):
        with CaptureQueriesContext(connection) as queries:
            rows = RoleSerializer(roles_with_directory_context(RoleProfile.objects.filter(pk__in=self.role_ids)), many=True).data
        self.assertTrue(rows)
        self.assertTrue(all(row["grants"][0]["resource_ids"] == [] for row in rows))
        self.assertFalse(any("role_grant_resource" in query["sql"] for query in queries))

    def test_single_object_queries_do_not_use_list_annotations_or_prefetch(self):
        for view_class, pk, serializer, marker in [
            (AccessEmployeeViewSet, self.employee_ids[0], AccessEmployeeSerializer, "_directory_team_id"),
            (RoleViewSet, self.role_ids[0], RoleSerializer, "_directory_employee_count"),
            (SalesTeamViewSet, self.team_ids[0], TeamSerializer, "_directory_memberships"),
        ]:
            with self.subTest(view=view_class.__name__):
                view = view_class()
                view.action = "retrieve"
                obj = view.get_queryset().get(pk=pk)
                self.assertFalse(hasattr(obj, marker))
                self.assertFalse(obj._prefetched_objects_cache if hasattr(obj, "_prefetched_objects_cache") else {})
                self.assertTrue(serializer(obj).data["etag"])
