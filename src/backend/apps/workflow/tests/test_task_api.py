from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.crm.models import CustomerTimelineEvent
from apps.customers.models import CustomerAccount, CustomerAssignment, CustomerTaskLink
from apps.organizations.models import Employee

from ..models import BusinessTask, TaskReminder


class TaskApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="task_api_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="TASK_API_USER",
            display_name="任务接口测试员工",
        )
        self.other_user = user_model.objects.create_user(username="task_api_other")
        self.other_employee = Employee.objects.create(
            user=self.other_user,
            employee_code="TASK_API_OTHER",
            display_name="其他任务测试员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="workflow")
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.customer = self.create_customer("TASK_CUSTOMER", "任务客户", self.employee)
        self.other_customer = self.create_customer(
            "OTHER_TASK_CUSTOMER",
            "其他任务客户",
            self.other_employee,
        )

    def create_customer(self, code, name, owner):
        customer = CustomerAccount.objects.create(
            account_code=code,
            account_name=name,
            primary_country_code="CN",
        )
        CustomerAssignment.objects.create(
            customer_account=customer,
            employee=owner,
            assignment_role="PRIMARY_OWNER",
            effective_from=timezone.now(),
        )
        return customer

    def test_create_customer_task_writes_link_audit_and_timeline(self):
        response = self.client.post(
            "/api/v1/tasks/",
            {
                "assignee_employee_id": str(self.employee.pk),
                "title": "跟进客户需求",
                "description": "电话确认规格",
                "priority": "HIGH",
                "source_type": "CUSTOMER",
                "source_id": str(self.customer.pk),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        task = BusinessTask.objects.get(pk=response.data["data"]["id"])
        self.assertTrue(
            CustomerTaskLink.objects.filter(
                customer_account=self.customer,
                business_task=task,
                is_primary_source=True,
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="BUSINESS_TASK",
                object_id=task.pk,
                action="CREATED",
            ).exists()
        )
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                customer_account=self.customer,
                source_id=task.pk,
                event_type="TASK_CREATED",
            ).exists()
        )
        self.assertEqual(response.data["data"]["source"]["type"], "CUSTOMER")

    def test_task_source_outside_customer_scope_returns_not_found(self):
        response = self.client.post(
            "/api/v1/tasks/",
            {
                "assignee_employee_id": str(self.employee.pk),
                "title": "越权任务",
                "source_type": "CUSTOMER",
                "source_id": str(self.other_customer.pk),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(BusinessTask.objects.filter(title="越权任务").exists())

    def test_task_list_contains_only_assigned_or_created_tasks(self):
        assigned = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.other_employee,
            title="分配给我",
        )
        created = BusinessTask.objects.create(
            assignee_employee=self.other_employee,
            created_by_employee=self.employee,
            title="我创建的",
        )
        hidden = BusinessTask.objects.create(
            assignee_employee=self.other_employee,
            created_by_employee=self.other_employee,
            title="无关任务",
        )

        response = self.client.get("/api/v1/tasks/")

        returned_ids = {item["id"] for item in response.data["data"]}
        self.assertIn(str(assigned.pk), returned_ids)
        self.assertIn(str(created.pk), returned_ids)
        self.assertNotIn(str(hidden.pk), returned_ids)

    def test_permanently_delete_task_removes_source_link(self):
        task = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.employee,
            title="待永久删除任务",
        )
        CustomerTaskLink.objects.create(
            customer_account=self.customer,
            business_task=task,
            is_primary_source=True,
        )
        url = f"/api/v1/tasks/{task.pk}/"
        etag = self.client.get(url).headers["ETag"]

        response = self.client.delete(url, HTTP_IF_MATCH=etag)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(BusinessTask.objects.filter(pk=task.pk).exists())
        self.assertFalse(CustomerTaskLink.objects.filter(business_task=task).exists())
        self.assertTrue(CustomerAccount.objects.filter(pk=self.customer.pk).exists())

    def test_explicit_task_scopes_keep_my_and_created_tasks_separate(self):
        assigned = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.other_employee,
            title="负责人是我",
        )
        created = BusinessTask.objects.create(
            assignee_employee=self.other_employee,
            created_by_employee=self.employee,
            title="创建人是我",
        )

        mine = self.client.get("/api/v1/tasks/?scope=ME")
        mine_ids = {item["id"] for item in mine.data["data"]}
        self.assertIn(str(assigned.pk), mine_ids)
        self.assertNotIn(str(created.pk), mine_ids)

        created_by_me = self.client.get("/api/v1/tasks/?scope=CREATED_BY_ME")
        created_ids = {item["id"] for item in created_by_me.data["data"]}
        self.assertIn(str(created.pk), created_ids)
        self.assertNotIn(str(assigned.pk), created_ids)

    def test_task_state_machine_and_etag(self):
        task = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.employee,
            title="状态任务",
        )
        url = f"/api/v1/tasks/{task.pk}/"
        etag = self.client.get(url).headers["ETag"]

        missing = self.client.post(f"{url}start/", {}, format="json")
        started = self.client.post(
            f"{url}start/",
            {"note": "开始处理"},
            format="json",
            HTTP_IF_MATCH=etag,
        )
        completed = self.client.post(
            f"{url}complete/",
            {"note": "处理完成"},
            format="json",
            HTTP_IF_MATCH=started.headers["ETag"],
        )
        invalid = self.client.post(
            f"{url}start/",
            {},
            format="json",
            HTTP_IF_MATCH=completed.headers["ETag"],
        )

        self.assertEqual(missing.status_code, 428)
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(completed.data["data"]["status"], "COMPLETED")
        self.assertIsNotNone(completed.data["data"]["completed_at"])
        self.assertEqual(invalid.status_code, 409)

    def test_complete_closes_scheduled_reminders(self):
        task = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.employee,
            title="提醒关闭任务",
        )
        reminder = TaskReminder.objects.create(business_task=task, remind_at=timezone.now())
        url = f"/api/v1/tasks/{task.pk}/"
        etag = self.client.get(url).headers["ETag"]

        response = self.client.post(
            f"{url}complete/",
            {"note": "已处理"},
            format="json",
            HTTP_IF_MATCH=etag,
        )

        self.assertEqual(response.status_code, 200, response.data)
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, "CLOSED")
        self.assertIsNotNone(reminder.closed_at)

    def test_reassign_changes_assignee_and_terminal_task_cannot_be_edited(self):
        task = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.employee,
            title="待转派任务",
        )
        url = f"/api/v1/tasks/{task.pk}/"
        etag = self.client.get(url).headers["ETag"]
        reassigned = self.client.post(
            f"{url}reassign/",
            {
                "assignee_employee_id": str(self.other_employee.pk),
                "reason": "改由其他员工处理",
            },
            format="json",
            HTTP_IF_MATCH=etag,
        )
        cancelled = self.client.post(
            f"{url}cancel/",
            {},
            format="json",
            HTTP_IF_MATCH=reassigned.headers["ETag"],
        )
        edit_terminal = self.client.patch(
            url,
            {"title": "不应修改"},
            format="json",
            HTTP_IF_MATCH=cancelled.headers["ETag"],
        )

        self.assertEqual(reassigned.status_code, 200, reassigned.data)
        self.assertEqual(
            reassigned.data["data"]["assignee"]["id"],
            str(self.other_employee.pk),
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(edit_terminal.status_code, 409)
