from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.crm.models import CustomerTimelineEvent
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit
from apps.reference_data.models import ReferenceDictionary

from ..models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerContact,
    CustomerDataAccessGrant,
    CustomerTransactionEntity,
)


class CustomerApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="customer_api_user",
            password="StrongTestPassword123!",
        )
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="CUSTOMER_API_USER",
            display_name="客户接口测试员工",
        )
        self.other_user = user_model.objects.create_user(username="customer_api_other")
        self.other_employee = Employee.objects.create(
            user=self.other_user,
            employee_code="CUSTOMER_API_OTHER",
            display_name="其他测试员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="customers").exclude(
                codename="view_all_customer"
            )
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def create_customer(self, code, name, owner=None):
        customer = CustomerAccount.objects.create(
            account_code=code,
            account_name=name,
            primary_country_code="CN",
        )
        CustomerAssignment.objects.create(
            customer_account=customer,
            employee=owner or self.employee,
            assignment_role="PRIMARY_OWNER",
            effective_from=timezone.now(),
        )
        return customer

    def test_create_customer_generates_number_owner_audit_and_timeline(self):
        response = self.client.post(
            "/api/v1/customers/",
            {
                "account_name": "新建客户",
                "primary_country_code": "CN",
                "primary_owner_employee_id": str(self.employee.pk),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        customer = CustomerAccount.objects.get(pk=response.data["data"]["id"])
        self.assertRegex(customer.account_code, r"^CUS-\d{6,}$")
        self.assertTrue(
            customer.assignments.filter(
                employee=self.employee,
                assignment_role="PRIMARY_OWNER",
                effective_to__isnull=True,
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="CUSTOMER_ACCOUNT",
                object_id=customer.pk,
                action="CREATED",
            ).exists()
        )
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                customer_account=customer,
                event_type="CUSTOMER_CREATED",
            ).exists()
        )
        self.assertIn("ETag", response)

    def test_customer_list_only_contains_assigned_customers(self):
        visible = self.create_customer("VISIBLE_CUSTOMER", "可见客户")
        hidden = self.create_customer(
            "HIDDEN_CUSTOMER",
            "不可见客户",
            owner=self.other_employee,
        )

        response = self.client.get("/api/v1/customers/")

        self.assertEqual(response.status_code, 200, response.data)
        returned_ids = {item["id"] for item in response.data["data"]}
        self.assertIn(str(visible.pk), returned_ids)
        self.assertNotIn(str(hidden.pk), returned_ids)

    def test_customer_list_supports_q_organization_and_archived_filters(self):
        organization = OrganizationUnit.objects.create(
            unit_code="CUSTOMER_API_TEAM",
            unit_name="客户接口测试组",
        )
        EmployeeOrganizationAssignment.objects.create(
            employee=self.employee,
            organization_unit=organization,
            is_primary=True,
            effective_from=timezone.now(),
        )
        active = self.create_customer("FILTER_ACTIVE", "阿尔法客户")
        archived = self.create_customer("FILTER_ARCHIVED", "贝塔客户")
        archived.archived_at = timezone.now()
        archived.archived_by_employee = self.employee
        archived.archive_reason = "筛选测试"
        archived.save()

        searched = self.client.get("/api/v1/customers/", {"q": "阿尔法"})
        by_organization = self.client.get(
            "/api/v1/customers/",
            {"organization_id": str(organization.pk)},
        )
        archived_only = self.client.get("/api/v1/customers/", {"archived": "true"})

        self.assertEqual(
            [item["id"] for item in searched.data["data"]],
            [str(active.pk)],
        )
        self.assertEqual(
            [item["id"] for item in by_organization.data["data"]],
            [str(active.pk)],
        )
        self.assertEqual(
            [item["id"] for item in archived_only.data["data"]],
            [str(archived.pk)],
        )

    def test_customer_update_requires_current_etag(self):
        customer = self.create_customer("ETAG_API_CUSTOMER", "修改前")
        detail_url = f"/api/v1/customers/{customer.pk}/"
        etag = self.client.get(detail_url).headers["ETag"]

        missing = self.client.patch(detail_url, {"account_name": "缺少条件"}, format="json")
        stale = self.client.patch(
            detail_url,
            {"account_name": "过期条件"},
            format="json",
            HTTP_IF_MATCH='"stale"',
        )
        success = self.client.patch(
            detail_url,
            {"account_name": "修改后"},
            format="json",
            HTTP_IF_MATCH=etag,
        )
        empty = self.client.patch(
            detail_url,
            {},
            format="json",
            HTTP_IF_MATCH=success.headers["ETag"],
        )

        self.assertEqual(missing.status_code, 428)
        self.assertEqual(stale.status_code, 412)
        self.assertEqual(success.status_code, 200, success.data)
        self.assertEqual(empty.status_code, 400, empty.data)
        customer.refresh_from_db()
        self.assertEqual(customer.account_name, "修改后")
        self.assertNotEqual(success.headers["ETag"], etag)

    def test_customer_archive_and_restore(self):
        customer = self.create_customer("ARCHIVE_CUSTOMER", "归档客户")
        url = f"/api/v1/customers/{customer.pk}/"
        etag = self.client.get(url).headers["ETag"]

        archived = self.client.post(
            f"{url}archive/",
            {"reason": "测试归档"},
            format="json",
            HTTP_IF_MATCH=etag,
        )
        restored = self.client.post(
            f"{url}restore/",
            {},
            format="json",
            HTTP_IF_MATCH=archived.headers["ETag"],
        )

        self.assertEqual(archived.status_code, 200, archived.data)
        self.assertEqual(restored.status_code, 200, restored.data)
        customer.refresh_from_db()
        self.assertIsNone(customer.archived_at)
        self.assertEqual(customer.archive_reason, "")

    def test_archived_customer_rejects_new_nested_records(self):
        customer = self.create_customer("LOCKED_CUSTOMER", "已归档客户")
        customer.archived_at = timezone.now()
        customer.archived_by_employee = self.employee
        customer.archive_reason = "停止维护"
        customer.save()

        response = self.client.post(
            f"/api/v1/customers/{customer.pk}/contacts/",
            {"display_name": "不应创建"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_contact_rejects_transaction_entity_from_another_customer(self):
        customer = self.create_customer("CONTACT_CUSTOMER_A", "客户甲")
        other_customer = self.create_customer("CONTACT_CUSTOMER_B", "客户乙")
        foreign_entity = CustomerTransactionEntity.objects.create(
            customer_account=other_customer,
            entity_code="FOREIGN_ENTITY",
            legal_name="其他客户主体",
        )

        response = self.client.post(
            f"/api/v1/customers/{customer.pk}/contacts/",
            {
                "display_name": "跨客户联系人",
                "transaction_entity": str(foreign_entity.pk),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("transaction_entity", response.data["error"]["field_errors"])

    def test_contact_method_is_normalized_and_audited(self):
        customer = self.create_customer("METHOD_CUSTOMER", "联系方式客户")
        contact = CustomerContact.objects.create(
            customer_account=customer,
            display_name="采购联系人",
        )

        response = self.client.post(
            f"/api/v1/contacts/{contact.pk}/methods/",
            {
                "method_type": "PHONE",
                "raw_value": "+86 138-0013-8000",
                "is_primary": True,
                "is_preferred": True,
                "verification_status": "UNVERIFIED",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["normalized_value"], "+8613800138000")
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="CUSTOMER_CONTACT_METHOD",
                object_id=response.data["data"]["id"],
                action="CREATED",
            ).exists()
        )

    def test_effective_role_end_requires_etag_and_writes_audit(self):
        customer = self.create_customer("ROLE_CUSTOMER", "角色客户")
        entity = CustomerTransactionEntity.objects.create(
            customer_account=customer,
            entity_code="ROLE_ENTITY",
            legal_name="角色主体",
        )
        created = self.client.post(
            f"/api/v1/customer-entities/{entity.pk}/roles/",
            {"role_type": "CONTRACTING"},
            format="json",
        )
        role_id = created.data["data"]["id"]
        role_url = f"/api/v1/customer-entity-roles/{role_id}/"
        etag = self.client.get(role_url).headers["ETag"]

        missing = self.client.post(f"{role_url}end/", {}, format="json")
        ended = self.client.post(
            f"{role_url}end/",
            {},
            format="json",
            HTTP_IF_MATCH=etag,
        )

        self.assertEqual(missing.status_code, 428)
        self.assertEqual(ended.status_code, 200, ended.data)
        self.assertIsNotNone(ended.data["data"]["effective_to"])
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="CUSTOMER_TRANSACTION_ENTITY_ROLE",
                object_id=role_id,
                action="ENDED",
            ).exists()
        )

    def test_customer_360_summary_counts_core_records(self):
        customer = self.create_customer("SUMMARY_CUSTOMER", "汇总客户")
        CustomerTransactionEntity.objects.create(
            customer_account=customer,
            entity_code="SUMMARY_ENTITY",
            legal_name="汇总主体",
        )
        CustomerContact.objects.create(customer_account=customer, display_name="汇总联系人")

        response = self.client.get(f"/api/v1/customers/{customer.pk}/summary/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["counts"]["entities"], 1)
        self.assertEqual(response.data["data"]["counts"]["contacts"], 1)

    def test_collaborator_can_be_added_and_ended(self):
        customer = self.create_customer("COLLABORATOR_CUSTOMER", "协作客户")

        created = self.client.post(
            f"/api/v1/customers/{customer.pk}/collaborators/",
            {
                "employee_id": str(self.other_employee.pk),
                "reason": "共同跟进",
            },
            format="json",
        )
        ended = self.client.post(
            f"/api/v1/customers/{customer.pk}/collaborators/{self.other_employee.pk}/end/",
            {"reason": "协作结束"},
            format="json",
        )

        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(ended.status_code, 200, ended.data)
        self.assertIsNotNone(ended.data["data"]["effective_to"])

    def test_attention_change_closes_previous_effective_record(self):
        customer = self.create_customer("ATTENTION_CUSTOMER", "关注客户")
        key_account = ReferenceDictionary.objects.get(
            category_code="CUSTOMER_ATTENTION",
            item_code="KEY_ACCOUNT",
        )
        routine = ReferenceDictionary.objects.get(
            category_code="CUSTOMER_ATTENTION",
            item_code="ROUTINE",
        )

        first = self.client.post(
            f"/api/v1/customers/{customer.pk}/set-attention/",
            {"attention_level_item_id": str(key_account.pk), "reason": "重点机会"},
            format="json",
        )
        second = self.client.post(
            f"/api/v1/customers/{customer.pk}/set-attention/",
            {"attention_level_item_id": str(routine.pk), "reason": "转常规维护"},
            format="json",
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        reviews = customer.attention_reviews.order_by("effective_from")
        self.assertEqual(reviews.count(), 2)
        self.assertIsNotNone(reviews.first().effective_to)
        self.assertIsNone(reviews.last().effective_to)

    def test_duplicate_effective_role_returns_validation_error(self):
        customer = self.create_customer("DUP_ROLE_CUSTOMER", "重复角色客户")
        entity = CustomerTransactionEntity.objects.create(
            customer_account=customer,
            entity_code="DUP_ROLE_ENTITY",
            legal_name="重复角色主体",
        )
        url = f"/api/v1/customer-entities/{entity.pk}/roles/"

        first = self.client.post(url, {"role_type": "CONTRACTING"}, format="json")
        duplicate = self.client.post(url, {"role_type": "CONTRACTING"}, format="json")

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(duplicate.status_code, 409, duplicate.data)
        self.assertEqual(duplicate.data["error"]["code"], "CONFLICT")

    def test_specific_contact_grant_allows_only_granted_customer(self):
        granted_customer = self.create_customer(
            "GRANTED_CUSTOMER",
            "授权客户",
            owner=self.other_employee,
        )
        denied_customer = self.create_customer(
            "DENIED_CUSTOMER",
            "未授权客户",
            owner=self.other_employee,
        )
        granted_contact = CustomerContact.objects.create(
            customer_account=granted_customer,
            display_name="授权联系人",
        )
        denied_contact = CustomerContact.objects.create(
            customer_account=denied_customer,
            display_name="未授权联系人",
        )
        permission = Permission.objects.get(
            content_type__app_label="customers",
            codename="view_customercontact",
        )
        CustomerDataAccessGrant.objects.create(
            employee=self.employee,
            customer_account=granted_customer,
            permission=permission,
            effective_from=timezone.now(),
            reason="测试精细数据授权",
        )

        granted = self.client.get(f"/api/v1/contacts/{granted_contact.pk}/")
        denied = self.client.get(f"/api/v1/contacts/{denied_contact.pk}/")

        self.assertEqual(granted.status_code, 200, granted.data)
        self.assertEqual(denied.status_code, 404)

    def test_action_permission_is_enforced_before_object_access(self):
        customer = self.create_customer("NO_CHANGE_CUSTOMER", "无修改权限客户")
        change_permission = Permission.objects.get(
            content_type__app_label="customers",
            codename="change_customeraccount",
        )
        self.user.user_permissions.remove(change_permission)
        if hasattr(self.user, "_perm_cache"):
            del self.user._perm_cache

        response = self.client.patch(
            f"/api/v1/customers/{customer.pk}/",
            {"account_name": "不应修改"},
            format="json",
            HTTP_IF_MATCH='"irrelevant"',
        )

        self.assertEqual(response.status_code, 403)
        customer.refresh_from_db()
        self.assertEqual(customer.account_name, "无修改权限客户")
