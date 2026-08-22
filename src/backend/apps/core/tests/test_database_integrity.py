import uuid

from django.db import DatabaseError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.customers.models import CustomerAccount, CustomerContact, CustomerTransactionEntity
from apps.inquiries.models import Inquiry
from apps.organizations.models import Employee, OrganizationUnit


class DatabaseIntegrityTests(TestCase):
    def assert_database_rejects(self, callback):
        # PostgreSQL 约束错误会中止当前保存点，单独包一层事务才能继续当前测试。
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                callback()

    def test_audit_log_is_append_only_at_database_level(self):
        audit_log = AuditLog.objects.create(
            object_type="TEST_OBJECT",
            object_id=uuid.uuid4(),
            action="CREATED",
            occurred_at=timezone.now(),
        )

        self.assert_database_rejects(
            lambda: AuditLog.objects.filter(pk=audit_log.pk).update(action="UPDATED")
        )

    def test_organization_hierarchy_rejects_indirect_cycle(self):
        root = OrganizationUnit.objects.create(unit_code="TEST_ROOT", unit_name="测试根组织")
        child = OrganizationUnit.objects.create(
            unit_code="TEST_CHILD",
            unit_name="测试子组织",
            parent=root,
        )

        self.assert_database_rejects(
            lambda: OrganizationUnit.objects.filter(pk=root.pk).update(parent=child)
        )

    def test_contact_entity_must_belong_to_same_customer(self):
        first_customer = CustomerAccount.objects.create(
            account_code="TEST_ACCOUNT_A",
            account_name="测试客户 A",
        )
        second_customer = CustomerAccount.objects.create(
            account_code="TEST_ACCOUNT_B",
            account_name="测试客户 B",
        )
        first_entity = CustomerTransactionEntity.objects.create(
            customer_account=first_customer,
            entity_code="TEST_ENTITY_A",
            legal_name="测试主体 A",
        )

        self.assert_database_rejects(
            lambda: CustomerContact.objects.create(
                customer_account=second_customer,
                transaction_entity=first_entity,
                display_name="错误归属联系人",
            )
        )

    def test_submitted_inquiry_requires_at_least_one_item(self):
        employee = Employee.objects.create(
            employee_code="TEST_OWNER",
            display_name="测试负责人",
        )
        customer = CustomerAccount.objects.create(
            account_code="TEST_INQUIRY_ACCOUNT",
            account_name="测试询价客户",
        )
        inquiry = Inquiry.objects.create(
            customer_account=customer,
            owner_employee=employee,
            inquiry_number="TEST-INQ-NO-ITEM",
            subject="无明细询价",
            received_at=timezone.now(),
        )

        self.assert_database_rejects(
            lambda: Inquiry.objects.filter(pk=inquiry.pk).update(status="SUBMITTED")
        )
