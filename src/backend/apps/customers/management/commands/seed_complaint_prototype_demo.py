from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.organizations.models import Employee
from apps.reference_data.models import ReferenceDictionary

from apps.customers.complaint_services import create_complaint
from apps.customers.models import ComplaintStatus, CustomerAccount, CustomerComplaint, CustomerComplaintProgress


DEMO_ROWS = [
    ("折叠床支架焊点开裂", "QUALITY", "CRITICAL", ComplaintStatus.ACCEPTED),
    ("首批订单包装标签错误", "PACKAGING", "SERIOUS", ComplaintStatus.ACCEPTED),
    ("出货文件缺少原产地信息", "DOCUMENTATION", "IMPORTANT", ComplaintStatus.ACCEPTED),
    ("售后回复未在约定时间内完成", "SERVICE", "GENERAL", ComplaintStatus.ACCEPTED),
    ("桌板表面出现批量色差", "QUALITY", "CRITICAL", ComplaintStatus.RESPONSIBILITY_CONFIRMATION),
    ("交期延期影响客户促销计划", "DELIVERY", "SERIOUS", ComplaintStatus.RESPONSIBILITY_CONFIRMATION),
    ("外箱唛头与订单要求不一致", "PACKAGING", "IMPORTANT", ComplaintStatus.RESPONSIBILITY_CONFIRMATION),
    ("装箱单数量与实收数量不符", "DOCUMENTATION", "GENERAL", ComplaintStatus.RESPONSIBILITY_CONFIRMATION),
    ("椅架喷涂层运输后脱落", "QUALITY", "CRITICAL", ComplaintStatus.SOLUTION_PLANNING),
    ("补货排期未同步给客户", "DELIVERY", "SERIOUS", ComplaintStatus.SOLUTION_PLANNING),
    ("内盒彩印内容存在错别字", "PACKAGING", "IMPORTANT", ComplaintStatus.SOLUTION_PLANNING),
    ("客户多次询问未收到进展", "SERVICE", "GENERAL", ComplaintStatus.SOLUTION_PLANNING),
    ("桌脚尺寸超出确认公差", "QUALITY", "CRITICAL", ComplaintStatus.CUSTOMER_CONFIRMATION),
    ("分批出货时间需要重新确认", "DELIVERY", "SERIOUS", ComplaintStatus.CUSTOMER_CONFIRMATION),
    ("质检报告版本与订单不匹配", "DOCUMENTATION", "IMPORTANT", ComplaintStatus.CUSTOMER_CONFIRMATION),
    ("折叠机构异响问题已完成整改", "QUALITY", "GENERAL", ComplaintStatus.CLOSED),
    ("防潮包装方案已获客户确认", "PACKAGING", "CRITICAL", ComplaintStatus.CLOSED),
    ("延误订单补发已经签收", "DELIVERY", "SERIOUS", ComplaintStatus.CLOSED),
    ("客户重复提交后申请撤销", "OTHER", "IMPORTANT", ComplaintStatus.CANCELLED),
    ("订单信息有误后取消客诉", "OTHER", "GENERAL", ComplaintStatus.CANCELLED),
]

STATUS_PATHS = {
    ComplaintStatus.ACCEPTED: [ComplaintStatus.ACCEPTED],
    ComplaintStatus.RESPONSIBILITY_CONFIRMATION: [
        ComplaintStatus.ACCEPTED,
        ComplaintStatus.RESPONSIBILITY_CONFIRMATION,
    ],
    ComplaintStatus.SOLUTION_PLANNING: [
        ComplaintStatus.ACCEPTED,
        ComplaintStatus.RESPONSIBILITY_CONFIRMATION,
        ComplaintStatus.SOLUTION_PLANNING,
    ],
    ComplaintStatus.CUSTOMER_CONFIRMATION: [
        ComplaintStatus.ACCEPTED,
        ComplaintStatus.RESPONSIBILITY_CONFIRMATION,
        ComplaintStatus.SOLUTION_PLANNING,
        ComplaintStatus.CUSTOMER_CONFIRMATION,
    ],
    ComplaintStatus.CLOSED: [
        ComplaintStatus.ACCEPTED,
        ComplaintStatus.RESPONSIBILITY_CONFIRMATION,
        ComplaintStatus.SOLUTION_PLANNING,
        ComplaintStatus.CUSTOMER_CONFIRMATION,
        ComplaintStatus.CLOSED,
    ],
    ComplaintStatus.CANCELLED: [ComplaintStatus.ACCEPTED, ComplaintStatus.CANCELLED],
}


class Command(BaseCommand):
    help = "为本地开发环境准备 20 条客诉原型演示数据。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="确认写入本地开发数据库。")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("仅允许在 DEBUG=True 的开发环境执行。")
        if not options["apply"]:
            self.stdout.write("预检通过：将写入或更新 20 条客诉演示数据；确认后请加 --apply。")
            return

        customers = list(CustomerAccount.objects.filter(archived_at__isnull=True).order_by("account_code")[:20])
        if len(customers) < 20:
            raise CommandError(f"至少需要 20 个有效客户，当前只有 {len(customers)} 个。")

        preferred_codes = ["DEMO_SALES_A", "DEMO_SALES_B", "DEMO_SALES_C"]
        employees_by_code = {
            employee.employee_code: employee
            for employee in Employee.objects.filter(
                employee_code__in=preferred_codes,
                status="ACTIVE",
                archived_at__isnull=True,
            )
        }
        employees = [employees_by_code.get(code) for code in preferred_codes]
        if any(employee is None for employee in employees):
            employees = list(Employee.objects.filter(status="ACTIVE", archived_at__isnull=True).order_by("employee_code")[:3])
        if len(employees) < 3:
            raise CommandError("至少需要 3 名有效员工，才能生成不同负责人和协作人。")

        dictionaries = {
            (item.category_code, item.item_code): item
            for item in ReferenceDictionary.objects.filter(
                category_code__in=["COMPLAINT_TYPE", "COMPLAINT_SEVERITY"],
                status="ACTIVE",
                archived_at__isnull=True,
            )
        }
        required_keys = {
            *(('COMPLAINT_TYPE', row[1]) for row in DEMO_ROWS),
            *(('COMPLAINT_SEVERITY', row[2]) for row in DEMO_ROWS),
        }
        missing = sorted(required_keys - dictionaries.keys())
        if missing:
            raise CommandError(f"客诉字典缺失：{missing}")

        now = timezone.now()
        created_count = 0
        updated_count = 0
        for index, (title, type_code, severity_code, status) in enumerate(DEMO_ROWS, start=1):
            reference = f"SO-COMPLAINT-PROTOTYPE-{index:02d}"
            customer = customers[index - 1]
            owner = employees[(index - 1) % len(employees)]
            collaborator = employees[index % len(employees)]
            complaint_type = dictionaries[("COMPLAINT_TYPE", type_code)]
            severity = dictionaries[("COMPLAINT_SEVERITY", severity_code)]
            created_at = now - timedelta(days=21 - index, hours=index % 5)
            response_due_at = created_at + timedelta(hours=4 + (index % 4) * 4)
            target_completion_at = created_at + timedelta(days=2 + (index % 6))
            order_snapshot = {
                "order_date": (created_at - timedelta(days=12)).date().isoformat(),
                "product_name": ["户外折叠床", "庭院餐桌", "折叠椅", "遮阳棚"][index % 4],
                "product_sku": f"DEMO-SKU-{index:03d}",
                "demo_seed": "complaint-prototype-v1",
            }

            complaint = CustomerComplaint.objects.filter(source_order_reference=reference).first()
            if complaint is not None:
                seed_marker = (complaint.source_order_snapshot or {}).get("demo_seed")
                has_seed_progress = complaint.progress_entries.filter(progress_note__startswith="[原型演示]").exists()
                if seed_marker != "complaint-prototype-v1" and not has_seed_progress:
                    raise CommandError(f"订单引用 {reference} 已被非演示客诉占用，已停止且未写入任何数据。")
            is_new = complaint is None
            if is_new:
                complaint = create_complaint(
                    validated_data={
                        "customer_account": customer,
                        "complaint_type_item": complaint_type,
                        "severity_item": severity,
                        "title": title,
                        "source_order_reference": reference,
                        "source_order_snapshot": order_snapshot,
                        "issue_description": f"{customer.account_name}反馈：{title}。请核实事实、确认责任并在目标日期前反馈处理方案。",
                        "owner_employee": owner,
                    },
                    actor_employee=owner,
                    request=None,
                )
                created_count += 1
            else:
                updated_count += 1

            first_responded_at = None if status == ComplaintStatus.ACCEPTED else created_at + timedelta(hours=2 + index % 3)
            completed_at = created_at + timedelta(days=2 + index % 3) if status == ComplaintStatus.CLOSED else None
            cancelled_at = created_at + timedelta(days=1) if status == ComplaintStatus.CANCELLED else None
            CustomerComplaint.objects.filter(pk=complaint.pk).update(
                customer_account=customer,
                original_customer_account=customer,
                complaint_type_item=complaint_type,
                severity_item=severity,
                title=title,
                source_order_reference=reference,
                source_order_snapshot=order_snapshot,
                issue_description=f"{customer.account_name}反馈：{title}。请核实事实、确认责任并在目标日期前反馈处理方案。",
                status=status,
                owner_employee=owner,
                root_cause="正在核实生产、包装和交付记录。" if status != ComplaintStatus.ACCEPTED else "",
                responsibility="已安排责任部门复核。" if status in {ComplaintStatus.SOLUTION_PLANNING, ComplaintStatus.CUSTOMER_CONFIRMATION, ComplaintStatus.CLOSED} else "",
                solution="已形成整改及客户沟通方案。" if status in {ComplaintStatus.CUSTOMER_CONFIRMATION, ComplaintStatus.CLOSED} else "",
                customer_feedback="客户已确认处理结果。" if status == ComplaintStatus.CLOSED else "",
                first_response_due_at=response_due_at,
                target_completion_at=target_completion_at,
                first_responded_at=first_responded_at,
                completed_at=completed_at,
                cancelled_at=cancelled_at,
                created_by_employee=owner,
                last_updated_by_employee=owner,
                created_at=created_at,
                updated_at=completed_at or cancelled_at or min(now, created_at + timedelta(days=1 + index % 4)),
            )
            complaint.refresh_from_db()
            complaint.collaborator_employees.set([collaborator])
            if is_new:
                complaint.progress_entries.all().delete()

            path = STATUS_PATHS[status]
            previous_status = ComplaintStatus.ACCEPTED
            for step, to_status in enumerate(path):
                progress_values = {
                    "from_status": previous_status,
                    "to_status": to_status,
                    "progress_note": (
                        "[原型演示] 客诉已创建并受理。"
                        if step == 0
                        else f"[原型演示] 已推进至{ComplaintStatus(to_status).label}，处理事实和下一步已记录。"
                    ),
                    "root_cause": complaint.root_cause if step >= 1 else "",
                    "responsibility": complaint.responsibility if step >= 2 else "",
                    "solution": complaint.solution if step >= 3 else "",
                    "customer_feedback": complaint.customer_feedback if to_status == ComplaintStatus.CLOSED else "",
                    "created_by_employee": owner,
                }
                progress = complaint.progress_entries.filter(
                    progress_note__startswith="[原型演示]",
                    to_status=to_status,
                ).order_by("created_at").first()
                if progress is None:
                    progress = CustomerComplaintProgress.objects.create(complaint=complaint, **progress_values)
                else:
                    CustomerComplaintProgress.objects.filter(pk=progress.pk).update(**progress_values)
                CustomerComplaintProgress.objects.filter(pk=progress.pk).update(
                    created_at=created_at + timedelta(hours=step * 8),
                    updated_at=created_at + timedelta(hours=step * 8),
                )
                previous_status = to_status

        self.stdout.write(
            self.style.SUCCESS(
                f"客诉演示数据已就绪：新增 {created_count}，更新 {updated_count}，共 20 条；未修改其他客诉。"
            )
        )
