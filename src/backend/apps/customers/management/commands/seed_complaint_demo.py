from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.reference_data.models import ReferenceDictionary

from apps.customers.complaint_services import create_complaint
from apps.customers.models import CustomerAssignment, CustomerComplaint


class Command(BaseCommand):
    help = "为开发环境创建一条可重复使用的行业客诉样本。"

    @transaction.atomic
    def handle(self, *args, **options):
        existing = CustomerComplaint.objects.filter(
            source_order_reference="SO-DEMO-2026-001",
            title="折叠椅到货后发现表面划伤",
        ).first()
        if existing is not None:
            self.stdout.write(self.style.SUCCESS(f"客诉样本已存在：{existing.complaint_code}"))
            return

        assignment = CustomerAssignment.objects.filter(
            assignment_role="PRIMARY_OWNER",
            effective_to__isnull=True,
            customer_account__archived_at__isnull=True,
            employee__status="ACTIVE",
            employee__archived_at__isnull=True,
        ).select_related("customer_account", "employee").order_by("customer_account__account_code").first()
        if assignment is None:
            raise CommandError("未找到带有效负责人的客户，请先创建客户基础数据。")

        complaint_type = ReferenceDictionary.objects.get(
            category_code="COMPLAINT_TYPE",
            item_code="QUALITY",
            status="ACTIVE",
            archived_at__isnull=True,
        )
        severity = ReferenceDictionary.objects.get(
            category_code="COMPLAINT_SEVERITY",
            item_code="SERIOUS",
            status="ACTIVE",
            archived_at__isnull=True,
        )
        complaint = create_complaint(
            validated_data={
                "customer_account": assignment.customer_account,
                "complaint_type_item": complaint_type,
                "severity_item": severity,
                "title": "折叠椅到货后发现表面划伤",
                "source_order_reference": "SO-DEMO-2026-001",
                "source_order_snapshot": {
                    "order_date": "2026-08-20",
                    "product_name": "户外折叠椅",
                    "product_sku": "CHAIR-ALU-001",
                },
                "issue_description": "客户验货时发现部分椅架表面划伤，要求核查包装及运输环节并给出补救方案。",
                "owner_employee": assignment.employee,
            },
            actor_employee=assignment.employee,
            request=None,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"已创建客诉样本：{complaint.complaint_code} / {assignment.customer_account.account_name}"
            )
        )
