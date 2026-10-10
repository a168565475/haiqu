from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.crm.models import CustomerCommunication
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit
from apps.reference_data.models import ReferenceDictionary
from apps.workflow.models import BusinessTask

from apps.customers.models import (
    CustomerAccount,
    CustomerActivityReview,
    CustomerAssignment,
    CustomerBusinessSnapshot,
    CustomerContact,
    CustomerContactMethod,
    CustomerContactRole,
    CustomerDuplicateCandidate,
    CustomerDuplicateCase,
    CustomerEntityAddress,
    CustomerGradeReview,
    CustomerSourceAttribution,
    CustomerTag,
    CustomerTagAssignment,
    CustomerTaskLink,
    CustomerTransactionEntity,
    CustomerTypeAssignment,
)


DEMO_CUSTOMERS = (
    ("CUS-DEMO-0001", "Aurora Outdoor GmbH", "DE", "A", "EXHIBITION", "ACTIVE", "128400.00", -2, 0),
    ("CUS-DEMO-0002", "Northwind Trading Ltd.", "US", "A", "WEBSITE", "FOLLOW_UP", "96800.00", -24, 1),
    ("CUS-DEMO-0003", "Atlas Leisure SAS", "FR", "B", "REFERRAL", "HIGH_RISK", "42600.00", -72, 0),
    ("CUS-DEMO-0004", "Blue Harbor Imports", "CA", "B", "PLATFORM", "DORMANT", "31200.00", -120, 4),
    ("CUS-DEMO-0005", "EverTrail Retail", "AU", "A", "EXHIBITION", "ACTIVE", "156000.00", -7, 2),
    ("CUS-DEMO-0006", "Cedar Peak Co.", "NL", "C", "WEBSITE", "FOLLOW_UP", "18900.00", -30, 1),
    ("CUS-DEMO-0007", "Solstice Home BV", "ES", "B", "REFERRAL", "HIGH_RISK", "27500.00", -144, 6),
    ("CUS-DEMO-0008", "Horizon Camp Supply", "GB", "A", "EXHIBITION", "ACTIVE", "84300.00", -5, 3),
)


class Command(BaseCommand):
    help = "创建或更新 CUS-01 客户列表演示数据（明确标记为 DEMO，可重复执行）。"

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        admin_user = get_user_model().objects.filter(username="admin").first()
        if admin_user is None:
            self.stderr.write(self.style.ERROR("未找到 admin 用户，无法绑定演示员工。"))
            return

        root_org = OrganizationUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        if root_org is None:
            self.stderr.write(self.style.ERROR("未找到有效组织，无法创建演示员工。"))
            return

        employees = []
        employee_definitions = (
            ("DEMO_SALES_A", "业务员 A", admin_user),
            ("DEMO_SALES_B", "业务员 B", None),
            ("DEMO_SALES_C", "业务员 C", None),
        )
        for code, name, user in employee_definitions:
            employee, _ = Employee.objects.update_or_create(
                employee_code=code,
                defaults={
                    "user": user,
                    "display_name": name,
                    "email": f"{code.lower()}@demo.invalid",
                    "status": "ACTIVE",
                    "archived_at": None,
                    "archive_reason": "",
                },
            )
            EmployeeOrganizationAssignment.objects.get_or_create(
                employee=employee,
                organization_unit=root_org,
                effective_to__isnull=True,
                defaults={
                    "position_title": "演示销售",
                    "is_primary": True,
                    "effective_from": now,
                },
            )
            employees.append(employee)

        dictionaries = {
            (item.category_code, item.item_code): item
            for item in ReferenceDictionary.objects.filter(
                category_code__in=["CUSTOMER_GRADE", "CUSTOMER_SOURCE", "CUSTOMER_TYPE"],
                status="ACTIVE",
                archived_at__isnull=True,
            )
        }
        importer_type = dictionaries[("CUSTOMER_TYPE", "IMPORTER")]
        demo_tag = CustomerTag.objects.get(tag_code="OUTDOOR_PRODUCTS")

        for index, definition in enumerate(DEMO_CUSTOMERS):
            code, name, country, grade, source, activity, value, contact_hours, follow_days = definition
            owner = employees[index % len(employees)]
            customer, _ = CustomerAccount.objects.update_or_create(
                account_code=code,
                defaults={
                    "account_name": name,
                    "english_name": name,
                    "short_name": name.split()[0],
                    "lifecycle_stage": "CUSTOMER" if activity == "ACTIVE" else "OPPORTUNITY",
                    "primary_country_code": country,
                    "primary_website_url": f"https://{code.lower()}.example.invalid",
                    "source_system": "DEMO",
                    "external_id": code,
                    "notes": "CUS-01 客户列表长期保留演示数据，不代表真实业务事实。",
                    "archived_at": None,
                    "archive_reason": "",
                },
            )
            CustomerAssignment.objects.get_or_create(
                customer_account=customer,
                assignment_role="PRIMARY_OWNER",
                effective_to__isnull=True,
                defaults={"employee": owner, "effective_from": now, "reason": "CUS-01 演示数据"},
            )
            CustomerGradeReview.objects.get_or_create(
                customer_account=customer,
                effective_to__isnull=True,
                defaults={
                    "grade_item": dictionaries[("CUSTOMER_GRADE", grade)],
                    "reviewed_by_employee": employees[0],
                    "reason": "CUS-01 演示等级",
                    "effective_from": now,
                },
            )
            CustomerSourceAttribution.objects.get_or_create(
                customer_account=customer,
                effective_to__isnull=True,
                defaults={
                    "source_item": dictionaries[("CUSTOMER_SOURCE", source)],
                    "recorded_by_employee": employees[0],
                    "notes": "CUS-01 演示来源",
                    "effective_from": now,
                },
            )
            CustomerTypeAssignment.objects.get_or_create(
                customer_account=customer,
                type_item=importer_type,
                effective_to__isnull=True,
                defaults={
                    "assigned_by_employee": employees[0],
                    "reason": "CUS-01 演示类型",
                    "effective_from": now,
                },
            )
            CustomerTagAssignment.objects.get_or_create(
                customer_account=customer,
                customer_tag=demo_tag,
                effective_to__isnull=True,
                defaults={
                    "assigned_by_employee": employees[0],
                    "reason": "CUS-01 演示标签",
                    "effective_from": now,
                },
            )
            CustomerActivityReview.objects.get_or_create(
                customer_account=customer,
                effective_to__isnull=True,
                defaults={
                    "activity_status": activity,
                    "source_type": "MANUAL",
                    "reviewed_by_employee": employees[0],
                    "reason": "CUS-01 演示活跃状态",
                    "effective_from": now,
                },
            )
            CustomerBusinessSnapshot.objects.update_or_create(
                customer_account=customer,
                source_reference="CUS-01-DEMO",
                defaults={
                    "source_type": "MANUAL",
                    "as_of_at": now,
                    "currency_code": "USD",
                    "customer_total_value": Decimal(value),
                    "last_12m_order_amount": Decimal(value) * Decimal("0.42"),
                    "last_12m_order_count": 8 + index,
                    "quote_conversion_rate": Decimal("42.00") if grade == "A" else Decimal("28.00"),
                    "credit_limit": Decimal("100000.00"),
                    "credit_used": Decimal("38000.00") + Decimal(index * 1000),
                    "open_complaint_count": 1 if activity == "HIGH_RISK" else 0,
                    "notes": "人工演示数据，不能作为订单或财务事实。",
                    "entered_by_employee": employees[0],
                    "is_current": True,
                },
            )
            CustomerCommunication.objects.update_or_create(
                source_system="DEMO",
                external_id=f"{code}-CONTACT",
                defaults={
                    "customer_account": customer,
                    "created_by_employee": owner,
                    "communication_type": "EMAIL",
                    "direction": "OUTBOUND",
                    "subject": "CUS-01 演示跟进",
                    "content": "用于客户列表最近联系时间展示。",
                    "occurred_at": now + timedelta(hours=contact_hours),
                },
            )
            task, _ = BusinessTask.objects.update_or_create(
                automation_key=f"CUS01_DEMO_{code}",
                defaults={
                    "assignee_employee": owner,
                    "created_by_employee": employees[0],
                    "title": f"跟进 {name}",
                    "description": "CUS-01 演示任务",
                    "status": "PENDING",
                    "priority": "NORMAL",
                    "due_at": now + timedelta(days=follow_days, hours=2),
                },
            )
            CustomerTaskLink.objects.get_or_create(customer_account=customer, business_task=task)

            entity, _ = CustomerTransactionEntity.objects.update_or_create(
                entity_code=f"{code}-LEGAL",
                defaults={
                    "customer_account": customer,
                    "entity_type": "COMPANY",
                    "legal_name": name,
                    "english_legal_name": name,
                    "registration_country_code": country,
                    "registration_number": f"REG-{index + 1:04d}",
                    "tax_country_code": country,
                    "tax_identifier": f"TAX-{code}",
                    "notes": "CUS-03 演示交易主体",
                    "archived_at": None,
                    "archive_reason": "",
                },
            )
            CustomerEntityAddress.objects.update_or_create(
                transaction_entity=entity,
                address_code="OFFICE",
                defaults={
                    "label": "办公地址",
                    "country_code": country,
                    "state_province": "Demo State",
                    "city": "Demo City",
                    "postal_code": f"10{index:03d}",
                    "address_line1": f"Business Street {index + 1}",
                    "address_line2": "",
                    "recipient_name": f"Contact {index + 1}",
                    "recipient_phone": f"+49 1000 {index + 1:04d}",
                    "is_verified": False,
                    "archived_at": None,
                    "archive_reason": "",
                },
            )
            for contact_index, (display_name, position, role_type) in enumerate((
                (f"{name.split()[0]} Buyer", "采购经理", "BUYER"),
                (f"{name.split()[0]} Director", "采购总监", "DECISION_MAKER"),
            )):
                contact, _ = CustomerContact.objects.update_or_create(
                    customer_account=customer,
                    display_name=display_name,
                    defaults={
                        "transaction_entity": entity,
                        "position_title": position,
                        "is_key_contact": contact_index == 1,
                        "status": "ACTIVE",
                        "notes": "CUS-05 客户联系人演示数据",
                        "archived_at": None,
                        "archive_reason": "",
                    },
                )
                email = f"contact{contact_index + 1}.{index + 1}@{code.lower()}.example.invalid"
                CustomerContactMethod.objects.update_or_create(
                    customer_contact=contact,
                    method_type="EMAIL",
                    raw_value=email,
                    defaults={
                        "normalized_value": email.lower(),
                        "normalization_version": 1,
                        "normalized_at": now,
                        "is_primary": True,
                        "is_preferred": True,
                        "verification_status": "UNVERIFIED",
                        "archived_at": None,
                        "archive_reason": "",
                    },
                )
                CustomerContactRole.objects.get_or_create(
                    customer_contact=contact,
                    role_type=role_type,
                    effective_to__isnull=True,
                    defaults={"effective_from": now, "notes": "CUS-05 演示角色"},
                )

        survivor = CustomerAccount.objects.get(account_code="CUS-DEMO-0001")
        duplicate, duplicate_created = CustomerAccount.objects.get_or_create(
            account_code="CUS-DEMO-DUP-0001",
            defaults={
                "account_name": "Aurora Outdoor Europe",
                "english_name": "Aurora Outdoor Europe",
                "short_name": "Aurora Europe",
                "lifecycle_stage": "OPPORTUNITY",
                "primary_country_code": "AT",
                "primary_website_url": survivor.primary_website_url,
                "source_system": "DEMO",
                "external_id": "CUS-DEMO-DUP-0001",
                "notes": "CUS-08 重复客户治理演示数据。",
            },
        )
        if duplicate_created:
            CustomerAssignment.objects.create(
                customer_account=duplicate,
                employee=employees[1],
                assignment_role="PRIMARY_OWNER",
                effective_from=now,
                reason="CUS-08 演示数据",
            )
            CustomerSourceAttribution.objects.create(
                customer_account=duplicate,
                source_item=dictionaries[("CUSTOMER_SOURCE", "WEBSITE")],
                recorded_by_employee=employees[0],
                notes="CUS-08 演示来源",
                effective_from=now,
            )
            CustomerActivityReview.objects.create(
                customer_account=duplicate,
                activity_status="FOLLOW_UP",
                source_type="MANUAL",
                reviewed_by_employee=employees[0],
                reason="CUS-08 演示活跃状态",
                effective_from=now,
            )
        duplicate_case = CustomerDuplicateCase.objects.filter(
            matching_strategy_version="CUS-08-DEMO-V1",
        ).first()
        if duplicate_case is None:
            duplicate_case = CustomerDuplicateCase.objects.create(
                reviewer_employee=employees[0],
                matching_strategy_version="CUS-08-DEMO-V1",
                notes="网站和名称高相似度的演示重复组。",
            )
            CustomerDuplicateCandidate.objects.bulk_create([
                CustomerDuplicateCandidate(
                    duplicate_case=duplicate_case,
                    customer_account=survivor,
                    confidence_score=Decimal("0.9800"),
                    matched_fields={"name": "similar", "website": "same"},
                ),
                CustomerDuplicateCandidate(
                    duplicate_case=duplicate_case,
                    customer_account=duplicate,
                    confidence_score=Decimal("0.9800"),
                    matched_fields={"name": "similar", "website": "same"},
                ),
            ])

        self.stdout.write(
            self.style.SUCCESS(
                f"客户 CRM 演示数据已就绪：{len(DEMO_CUSTOMERS)} 个主客户、联系人、地址和重复治理案例。"
            )
        )
