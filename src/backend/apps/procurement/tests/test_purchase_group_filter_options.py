"""U2总单筛选选项：只读权限、完整父集合和原数据范围。"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.models import RoleActionGrant
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile

from ..models import PurchaseGroup
from .group_test_fixtures import ensure_group_test_reference_data
from . import test_purchase_order_api as order_tests


@override_settings(MODULE_ACCESS_ENABLED=False, ACCESS_MANAGEMENT_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class PurchaseGroupFilterOptionsTests(APITestCase):
    make_task = order_tests.PurchaseOrderApiTests.make_task
    url = "/api/v1/purchase-groups/filter-options/"

    def setUp(self):
        ensure_group_test_reference_data()
        order_tests.PurchaseOrderApiTests.setUp(self)
        self.user.user_permissions.set(Permission.objects.filter(
            content_type__app_label="procurement", codename="view_purchaseorder",
        ))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))

    def make_group(self, task, number, **changes):
        values = {"production_task": task, "group_number": number,
            "production_task_number_snapshot": f"SAVED-{number}", "sales_order_number_snapshot": f"ORDER-{number}",
            "customer_name_snapshot": "筛选测试", "source_revision": "", "compatibility_issues": ["SOURCE_ID_MISSING"]}
        values.update(changes)
        return PurchaseGroup.objects.create(**values)

    def test_all_visible_empty_unknown_groups_are_deduplicated_without_bom_or_batch(self):
        task = self.make_task("OPTIONS")
        self.make_group(task, "OPTION-OLD")
        latest = self.make_group(task, "OPTION-LATEST")
        other = self.make_task("OPTIONS-OTHER")
        other_group = self.make_group(other, "OPTION-OTHER")
        task.task_number = "CURRENT-TASK-NUMBER"
        task.save(update_fields=["task_number"])
        response = self.client.get(self.url, {"page": 2, "page_size": 1, "production_task_id": str(task.pk)})
        self.assertEqual(response.status_code, 200, response.data)
        rows = {row["id"]: row for row in response.data["data"]["production_tasks"]}
        self.assertEqual(set(rows), {str(task.pk), str(other.pk)})
        self.assertEqual(rows[str(task.pk)], {"id": str(task.pk),
            "task_number": latest.production_task_number_snapshot, "order_number": latest.sales_order_number_snapshot})
        self.assertEqual(rows[str(other.pk)]["task_number"], other_group.production_task_number_snapshot)
        self.assertFalse(task.purchase_orders.exists())
        self.assertFalse(task.boms.exists())
        self.assertEqual(self.client.get("/api/v1/purchase-orders/filter-options/").data["data"]["production_tasks"], [])
        self.assertEqual(self.client.get("/api/v1/purchase-orders/options/").status_code, 403)

    def test_archived_groups_and_archived_tasks_are_excluded(self):
        self.make_group(self.make_task("ARCHIVED-GROUP"), "ARCHIVED-GROUP", archived_at=timezone.now())
        task = self.make_task("ARCHIVED-TASK")
        self.make_group(task, "ARCHIVED-TASK")
        task.archived_at = timezone.now()
        task.save(update_fields=["archived_at"])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"], {"production_tasks": []})

    def test_data_range_matches_parent_list_and_unauthorized_roles_are_denied(self):
        self.make_group(self.make_task("PRIVATE"), "PRIVATE")
        outsider = get_user_model().objects.create_user(username="option-outsider")
        Employee.objects.create(user=outsider, employee_code="OPTION-OUT", display_name="范围外")
        outsider.user_permissions.set(Permission.objects.filter(content_type__app_label="procurement", codename="view_purchaseorder"))
        client = APIClient()
        client.force_authenticate(outsider)
        self.assertEqual(client.get(self.url).data["data"]["production_tasks"], [])
        self.assertEqual(client.get("/api/v1/purchase-groups/").data["data"], [])
        for app, code in [("procurement", "view_supplier"), ("inventory", "receive_material")]:
            outsider.user_permissions.set(Permission.objects.filter(content_type__app_label=app, codename=code))
            client.force_authenticate(get_user_model().objects.get(pk=outsider.pk))
            self.assertEqual(client.get(self.url).status_code, 403)
        client.force_authenticate(user=None)
        self.assertIn(client.get(self.url).status_code, [401, 403])

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True)
    def test_module_view_role_can_read_without_create_permission(self):
        self.make_group(self.make_task("MODULE-VIEW"), "MODULE-VIEW")
        self.user.user_permissions.clear()
        role = RoleProfile.objects.create(role_code="OPTION-VIEW", display_name="总单只读",
            auth_group=Group.objects.create(name="option-view"))
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=role, effective_from=timezone.now())
        view = Permission.objects.get(content_type__app_label="procurement", codename="view_purchaseorder")
        RoleActionGrant.objects.create(role=role, permission=view, scope="MODULE")
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["data"]["production_tasks"]), 1)
        self.assertEqual(self.client.post("/api/v1/purchase-groups/", {}, format="json").status_code, 403)
