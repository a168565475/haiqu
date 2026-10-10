from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.organizations.models import Employee
from apps.workflow.models import BusinessTask

from ..models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerContact,
    CustomerContactEmploymentEvent,
    CustomerContactMethod,
    CustomerContactRole,
    CustomerContactTaskLink,
)


class ContactModuleApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="contact_module_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="CONTACT_MODULE_USER",
            display_name="联系人模块测试员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="customers").exclude(
                codename="view_all_customer"
            )
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.customer = CustomerAccount.objects.create(
            account_code="CONTACT-CUSTOMER-001",
            account_name="联系人测试客户",
            primary_country_code="CN",
        )
        CustomerAssignment.objects.create(
            customer_account=self.customer,
            employee=self.employee,
            assignment_role="PRIMARY_OWNER",
            effective_from=timezone.now(),
        )

    def create_contact(self, *, email="buyer@example.com", is_key_contact=False, **overrides):
        payload = {
            "display_name": "采购联系人",
            "position_title": "采购经理",
            "is_key_contact": is_key_contact,
            "methods": [{"method_type": "EMAIL", "raw_value": email, "is_primary": True}],
            "role_types": ["BUYER"],
        }
        payload.update(overrides)
        response = self.client.post(
            f"/api/v1/customers/{self.customer.pk}/contacts/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_composite_create_list_masks_and_detail_reveals_with_permission(self):
        created = self.create_contact(email="Buyer@Example.com")
        contact_id = created.data["data"]["id"]

        listing = self.client.get("/api/v1/contacts/")
        detail = self.client.get(f"/api/v1/contacts/{contact_id}/")

        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(listing.data["meta"]["total"], 1)
        self.assertNotEqual(listing.data["data"][0]["methods"][0]["display_value"], "Buyer@Example.com")
        self.assertEqual(detail.data["data"]["methods"][0]["display_value"], "Buyer@Example.com")
        self.assertEqual(CustomerContactMethod.objects.get().normalized_value, "buyer@example.com")
        self.assertEqual(detail.data["data"]["active_roles"][0]["role_type"], "BUYER")

    def test_customer_contact_search_does_not_filter_parent_customer(self):
        self.create_contact(email="search@example.com", display_name="CUS05-QA-搜索联系人")

        response = self.client.get(
            f"/api/v1/customers/{self.customer.pk}/contacts/",
            {"q": "CUS05-QA", "status": "ACTIVE", "ordering": "display_name"},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 1)
        self.assertEqual(response.data["data"][0]["display_name"], "CUS05-QA-搜索联系人")

    def test_summary_covers_customer_outside_filtered_page_and_excludes_archived(self):
        now = timezone.now()
        active = CustomerContact.objects.create(customer_account=self.customer, display_name="张经理", is_primary_contact=True)
        CustomerContact.objects.create(customer_account=self.customer, display_name="李经理", status="LEFT")
        CustomerContact.objects.create(customer_account=self.customer, display_name="停用", status="INACTIVE")
        CustomerContact.objects.create(customer_account=self.customer, display_name="归档", archived_at=now)
        CustomerContactRole.objects.create(customer_contact=active, role_type="DECISION_MAKER", effective_from=now - timedelta(days=1))
        CustomerContactRole.objects.create(customer_contact=active, role_type="BUYER", effective_from=now + timedelta(days=1))
        response = self.client.get(f"/api/v1/customers/{self.customer.pk}/contacts/", {
            "q": "李经理", "page_size": 1, "include_summary": "true",
        })
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 1)
        summary = response.data["summary"]
        self.assertEqual({k: summary[k] for k in ["total", "active", "decision_maker", "primary", "left", "stale"]},
                         {"total": 3, "active": 1, "decision_maker": 1, "primary": 1, "left": 1, "stale": 1})
        self.assertEqual(summary["priority_candidates"][0]["id"], str(active.pk))
        self.assertEqual(len(summary["priority_candidates"][0]["active_roles"]), 1)
        other = CustomerAccount.objects.create(account_code="HIDDEN", account_name="无权限客户")
        hidden = self.client.get(f"/api/v1/customers/{other.pk}/contacts/", {"include_summary": "true"})
        self.assertEqual(hidden.status_code, 404)

    def test_summary_uses_last_interaction_and_retains_priority_ties(self):
        from apps.crm.models import CommunicationContactParticipant, CustomerCommunication
        from ..contact_selectors import customer_contact_summary
        now = timezone.now()
        contacts = [CustomerContact.objects.create(customer_account=self.customer, display_name=name, is_key_contact=True)
                    for name in ["张", "王", "李"]]
        for index, contact in enumerate(contacts):
            event = CustomerCommunication.objects.create(customer_account=self.customer, communication_type="EMAIL",
                occurred_at=now - timedelta(days=1 if index < 2 else 31), subject="统计测试")
            CommunicationContactParticipant.objects.create(communication=event, customer_contact=contact)
        summary = customer_contact_summary(self.customer)
        self.assertEqual(summary["stale"], 1)
        self.assertEqual({row["id"] for row in summary["priority_candidates"]}, {str(row.pk) for row in contacts[:2]})

    def test_duplicate_requires_acknowledgement(self):
        self.create_contact()
        duplicate = self.client.post(
            f"/api/v1/customers/{self.customer.pk}/contacts/",
            {
                "display_name": "第二联系人",
                "methods": [{"method_type": "EMAIL", "raw_value": "BUYER@example.com"}],
            },
            format="json",
        )
        confirmed = self.client.post(
            f"/api/v1/customers/{self.customer.pk}/contacts/",
            {
                "display_name": "第二联系人",
                "methods": [{"method_type": "EMAIL", "raw_value": "BUYER@example.com"}],
                "duplicate_acknowledged": True,
            },
            format="json",
        )

        self.assertEqual(duplicate.status_code, 409, duplicate.data)
        self.assertEqual(confirmed.status_code, 201, confirmed.data)

    def test_key_contact_leave_creates_idempotent_replacement_task(self):
        created = self.create_contact(is_key_contact=True)
        contact_id = created.data["data"]["id"]
        response = self.client.post(
            f"/api/v1/contacts/{contact_id}/mark-left/",
            {"reason": "客户人员调整"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(CustomerContact.objects.get(pk=contact_id).status, "LEFT")
        task = BusinessTask.objects.get(automation_key=f"CONTACT_REPLACEMENT:{contact_id}")
        self.assertEqual(task.assignee_employee, self.employee)
        self.assertEqual(task.priority, "HIGH")
        self.assertIsNotNone(response.data["replacement_task_id"])

    def test_key_contact_leave_without_owner_rolls_back(self):
        created = self.create_contact(is_key_contact=True)
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="customers", codename="view_all_customer")
        )
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)
        self.customer.assignments.update(effective_to=timezone.now())
        response = self.client.post(
            f"/api/v1/contacts/{created.data['data']['id']}/mark-left/",
            {"reason": "客户人员调整"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(CustomerContact.objects.get().status, "ACTIVE")
        self.assertFalse(BusinessTask.objects.exists())

    def test_direct_patch_to_left_is_rejected(self):
        created = self.create_contact()
        response = self.client.patch(
            f"/api/v1/contacts/{created.data['data']['id']}/",
            {"status": "LEFT"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_last_active_method_cannot_be_archived(self):
        created = self.create_contact()
        method = CustomerContactMethod.objects.get()
        detail = self.client.get(f"/api/v1/contact-methods/{method.pk}/")
        response = self.client.post(
            f"/api/v1/contact-methods/{method.pk}/archive/",
            {"reason": "不再使用"},
            format="json",
            HTTP_IF_MATCH=detail.headers["ETag"],
        )
        self.assertEqual(response.status_code, 409, response.data)

    def test_cus05_profile_options_history_and_contact_task_link(self):
        created = self.create_contact(
            english_name="Alex Buyer",
            department_name="采购部",
            preferred_language_code="EN",
            timezone_code="Asia/Shanghai",
            is_primary_contact=True,
        )
        contact_id = created.data["data"]["id"]
        options = self.client.get("/api/v1/contacts/options/")
        published_languages = self.client.get(
            "/api/v1/reference-data/options/CONTACT_LANGUAGE/"
        )
        published_timezones = self.client.get(
            "/api/v1/reference-data/options/CONTACT_TIMEZONE/"
        )
        self.assertEqual(options.status_code, 200, options.data)
        self.assertIn("language_options", options.data["data"])
        self.assertSetEqual(
            {item["value"] for item in options.data["data"]["language_options"]},
            {item["code"] for item in published_languages.data["data"]},
        )
        self.assertSetEqual(
            {item["value"] for item in options.data["data"]["timezone_options"]},
            {
                item["extra"]["timezone_code"]
                for item in published_timezones.data["data"]
            },
        )
        self.assertEqual(created.data["data"]["english_name"], "Alex Buyer")
        self.assertTrue(created.data["data"]["is_primary_contact"])
        self.assertTrue(CustomerContactEmploymentEvent.objects.filter(customer_contact_id=contact_id).exists())

        patched = self.client.patch(
            f"/api/v1/contacts/{contact_id}/",
            {
                "position_title": "采购总监",
                "department_name": "战略采购部",
                "role_types": ["DECISION_MAKER", "BUYER"],
                "methods": [{"method_type": "PHONE", "raw_value": "+86 138 0000 0000", "is_primary": True}],
            },
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(patched.status_code, 200, patched.data)
        self.assertEqual(patched.data["data"]["department_name"], "战略采购部")
        self.assertEqual(len(patched.data["data"]["active_roles"]), 2)
        history = self.client.get(f"/api/v1/contacts/{contact_id}/employment-history/")
        self.assertEqual(history.status_code, 200, history.data)
        self.assertGreaterEqual(len(history.data["data"]), 2)

        task_response = self.client.post(
            "/api/v1/contacts/bulk-create-tasks/",
            {
                "contact_ids": [contact_id],
                "title": "联系采购总监",
                "due_at": (timezone.now() + timedelta(days=2)).isoformat(),
                "assignee_mode": "CUSTOMER_OWNER",
            },
            format="json",
        )
        self.assertEqual(task_response.status_code, 201, task_response.data)
        self.assertTrue(CustomerContactTaskLink.objects.filter(customer_contact_id=contact_id).exists())

    def test_primary_contact_leave_requires_replacement_and_records_real_effects(self):
        primary = self.create_contact(
            email="primary@example.com",
            display_name="主要联系人",
            is_primary_contact=True,
        )
        replacement = self.create_contact(
            email="replacement@example.com",
            display_name="接替联系人",
        )
        contact_id = primary.data["data"]["id"]
        rejected = self.client.post(
            f"/api/v1/contacts/{contact_id}/mark-left/",
            {"reason": "人员调整"},
            format="json",
            HTTP_IF_MATCH=primary.headers["ETag"],
        )
        self.assertEqual(rejected.status_code, 409, rejected.data)

        accepted = self.client.post(
            f"/api/v1/contacts/{contact_id}/mark-left/",
            {
                "effective_date": timezone.localdate().isoformat(),
                "replacement_contact_id": replacement.data["data"]["id"],
                "unfinished_task_policy": "TRANSFER_TO_OWNER",
                "preserve_history": True,
                "remove_from_marketing": True,
                "notify_stakeholders": True,
                "reason": "人员调整",
            },
            format="json",
            HTTP_IF_MATCH=primary.headers["ETag"],
        )
        self.assertEqual(accepted.status_code, 200, accepted.data)
        left = CustomerContact.objects.get(pk=contact_id)
        new_primary = CustomerContact.objects.get(pk=replacement.data["data"]["id"])
        self.assertEqual(left.status, "LEFT")
        self.assertTrue(left.marketing_opt_out)
        self.assertTrue(new_primary.is_primary_contact)
        self.assertTrue(BusinessTask.objects.filter(automation_key__startswith="CONTACT_LEFT_NOTICE:").exists())
        self.assertTrue(
            CustomerContactEmploymentEvent.objects.filter(
                customer_contact=left,
                event_type="LEFT",
            ).exists()
        )

    def test_profile_patch_requires_if_match(self):
        created = self.create_contact()
        response = self.client.patch(
            f"/api/v1/contacts/{created.data['data']['id']}/",
            {"department_name": "采购部"},
            format="json",
        )
        self.assertEqual(response.status_code, 428, response.data)
