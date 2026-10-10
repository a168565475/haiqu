from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.customers.models import CustomerAccount, CustomerTaskLink
from apps.organizations.models import Employee, EmployeeStatus
from apps.workflow.models import (
    BusinessTask,
    TaskChecklistItem,
    TaskCollaborator,
    TaskEvent,
    TaskOriginType,
    TaskPriority,
    TaskReminder,
    TaskReminderStatus,
    TaskStatus,
    TaskType,
    TaskWorkState,
)


TASK_ROWS = [
    ("跟进报价 V3 客户反馈", TaskStatus.IN_PROGRESS, TaskPriority.HIGH, TaskType.QUOTATION_FOLLOW_UP, -2, TaskWorkState.NORMAL),
    ("确认月亮椅新订单数量", TaskStatus.PENDING, TaskPriority.URGENT, TaskType.CUSTOMER_FOLLOW_UP, -1, TaskWorkState.NORMAL),
    ("回复秋季新品询盘", TaskStatus.PENDING, TaskPriority.HIGH, TaskType.INQUIRY_RESPONSE, 0, TaskWorkState.NORMAL),
    ("收集露营桌打样反馈", TaskStatus.IN_PROGRESS, TaskPriority.NORMAL, TaskType.SAMPLE_FEEDBACK, 0, TaskWorkState.WAITING_CUSTOMER),
    ("确认包装唛头修改内容", TaskStatus.PENDING, TaskPriority.NORMAL, TaskType.COMMUNICATION_FOLLOW_UP, 1, TaskWorkState.NORMAL),
    ("发送折叠椅更新报价", TaskStatus.IN_PROGRESS, TaskPriority.HIGH, TaskType.QUOTATION_FOLLOW_UP, 2, TaskWorkState.NORMAL),
    ("核对客户交期要求", TaskStatus.PENDING, TaskPriority.NORMAL, TaskType.CUSTOMER_FOLLOW_UP, 3, TaskWorkState.NORMAL),
    ("跟进样品签收结果", TaskStatus.IN_PROGRESS, TaskPriority.NORMAL, TaskType.SAMPLE_FEEDBACK, 4, TaskWorkState.WAITING_CUSTOMER),
    ("回复产品材质问题", TaskStatus.PENDING, TaskPriority.LOW, TaskType.INQUIRY_RESPONSE, 5, TaskWorkState.NORMAL),
    ("确认合同付款节点", TaskStatus.PENDING, TaskPriority.HIGH, TaskType.COMMUNICATION_FOLLOW_UP, 6, TaskWorkState.BLOCKED),
    ("整理客户年度采购计划", TaskStatus.IN_PROGRESS, TaskPriority.NORMAL, TaskType.CUSTOMER_FOLLOW_UP, 7, TaskWorkState.NORMAL),
    ("补充报价单运输条款", TaskStatus.PENDING, TaskPriority.NORMAL, TaskType.QUOTATION_FOLLOW_UP, 10, TaskWorkState.NORMAL),
    ("确认样品颜色选择", TaskStatus.PENDING, TaskPriority.LOW, TaskType.SAMPLE_FEEDBACK, 14, TaskWorkState.WAITING_CUSTOMER),
    ("回访历史客户合作意向", TaskStatus.PENDING, TaskPriority.NORMAL, TaskType.CUSTOMER_FOLLOW_UP, None, TaskWorkState.NORMAL),
    ("完成德国客户季度回访", TaskStatus.COMPLETED, TaskPriority.HIGH, TaskType.CUSTOMER_FOLLOW_UP, -6, TaskWorkState.NORMAL),
    ("完成南非客户报价复盘", TaskStatus.COMPLETED, TaskPriority.NORMAL, TaskType.QUOTATION_FOLLOW_UP, -4, TaskWorkState.NORMAL),
    ("完成新品询盘答复", TaskStatus.COMPLETED, TaskPriority.LOW, TaskType.INQUIRY_RESPONSE, -3, TaskWorkState.NORMAL),
    ("取消重复的客户回访", TaskStatus.CANCELLED, TaskPriority.NORMAL, TaskType.CUSTOMER_FOLLOW_UP, 8, TaskWorkState.NORMAL),
    ("取消已失效样品反馈", TaskStatus.CANCELLED, TaskPriority.LOW, TaskType.SAMPLE_FEEDBACK, None, TaskWorkState.NORMAL),
    ("暂停等待资料的沟通任务", TaskStatus.CANCELLED, TaskPriority.NORMAL, TaskType.COMMUNICATION_FOLLOW_UP, 12, TaskWorkState.NORMAL),
]


class Command(BaseCommand):
    help = "创建或更新任务中心原型验收用的 20 条本地演示任务。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="确认写入当前数据库；不带此参数时只显示说明。",
        )

    def handle(self, *args, **options):
        if not options["apply"]:
            raise CommandError("这是写入命令。确认当前为本地开发库后，请追加 --apply。")
        if not settings.DEBUG:
            raise CommandError("该命令只允许在 DEBUG=True 的本地开发环境执行。")

        employees = list(
            Employee.objects.filter(status=EmployeeStatus.ACTIVE, archived_at__isnull=True).order_by("employee_code")
        )
        customers = list(CustomerAccount.objects.filter(archived_at__isnull=True).order_by("account_code")[:20])
        if len(employees) < 3:
            raise CommandError("至少需要 3 名在职员工，当前数据不足。")
        if len(customers) < 20:
            raise CommandError("至少需要 20 个未归档客户，当前数据不足。")

        preferred_codes = ["DEMO_SALES_A", "DEMO_SALES_B", "DEMO_SALES_C"]
        employees_by_code = {employee.employee_code: employee for employee in employees}
        assignees = [employees_by_code.get(code) for code in preferred_codes]
        if any(employee is None for employee in assignees):
            assignees = employees[:3]

        now = timezone.localtime()
        today_at_17 = now.replace(hour=17, minute=30, second=0, microsecond=0)
        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for index, row in enumerate(TASK_ROWS, start=1):
                title, status, priority, task_type, due_days, work_state = row
                # 开发自动登录账号对应业务员 A；保留 2 条其他负责人数据后，
                # “我的任务”页会连同原有 2 条任务展示 20 条，便于一次验收完整表格。
                assignee_index = 0 if index <= 18 else 1 if index == 19 else 2
                assignee = assignees[assignee_index]
                customer = customers[index - 1]
                due_at = None if due_days is None else today_at_17 + timedelta(days=due_days)
                created_at = now - timedelta(days=26 - index, hours=index % 5)
                completed_at = now - timedelta(days=20 - index) if status == TaskStatus.COMPLETED else None
                cancelled_at = now - timedelta(days=20 - index) if status == TaskStatus.CANCELLED else None
                automation_key = f"TASK_V3_PROTOTYPE_{index:02d}"

                task, created = BusinessTask.objects.update_or_create(
                    automation_key=automation_key,
                    defaults={
                        "assignee_employee": assignee,
                        "created_by_employee": assignees[0],
                        "title": title,
                        "description": (
                            f"联系 {customer.account_name}，确认当前事项、记录客户反馈，并明确下一步负责人和完成时间。"
                        ),
                        "status": status,
                        "priority": priority,
                        "task_type": task_type,
                        "origin_type": TaskOriginType.BUSINESS_EVENT if index % 3 == 0 else TaskOriginType.MANUAL,
                        "origin_code": f"TASK-DEMO-{index:02d}",
                        "work_state": work_state,
                        "work_state_reason": "等待客户确认" if work_state == TaskWorkState.WAITING_CUSTOMER else "付款资料尚未齐全" if work_state == TaskWorkState.BLOCKED else "",
                        "next_check_at": None if status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED} else now + timedelta(hours=index * 4),
                        "due_at": due_at,
                        "completed_at": completed_at,
                        "completion_result": "已完成客户沟通并记录结论。" if completed_at else "",
                        "cancelled_at": cancelled_at,
                        "cancel_reason": "演示任务已失效或重复。" if cancelled_at else "",
                        "archived_at": None,
                    },
                )
                created_count += int(created)
                updated_count += int(not created)
                if created:
                    BusinessTask.objects.filter(pk=task.pk).update(created_at=created_at, updated_at=created_at)
                else:
                    # 重置演示数据也属于一次写入，必须让旧 ETag/批量版本失效。
                    BusinessTask.objects.filter(pk=task.pk).update(business_version=F("business_version") + 1)

                CustomerTaskLink.objects.filter(business_task=task).delete()
                CustomerTaskLink.objects.create(customer_account=customer, business_task=task, is_primary_source=True)

                TaskChecklistItem.objects.filter(business_task=task).delete()
                checklist_rows = [
                    "确认客户当前需求与关键变化",
                    "整理报价或沟通所需资料",
                    "向客户发送结果并记录反馈",
                    "明确下一步负责人和截止时间",
                ]
                completed_items = 1 if status == TaskStatus.IN_PROGRESS else len(checklist_rows) if status == TaskStatus.COMPLETED else 0
                for sort_order, content in enumerate(checklist_rows, start=1):
                    is_completed = sort_order <= completed_items
                    TaskChecklistItem.objects.create(
                        business_task=task,
                        content=content,
                        sort_order=sort_order,
                        is_completed=is_completed,
                        completed_at=created_at + timedelta(hours=sort_order) if is_completed else None,
                        completed_by_employee=assignee if is_completed else None,
                    )

                TaskReminder.objects.filter(business_task=task).delete()
                reminder_status = TaskReminderStatus.CLOSED if status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED} else TaskReminderStatus.SCHEDULED
                reminder_at = (due_at or now + timedelta(days=8)) - timedelta(hours=4)
                TaskReminder.objects.create(
                    business_task=task,
                    remind_at=reminder_at,
                    status=reminder_status,
                    closed_at=completed_at or cancelled_at,
                    close_reason="任务已结束" if reminder_status == TaskReminderStatus.CLOSED else "",
                )

                TaskCollaborator.objects.filter(business_task=task).delete()
                collaborator = assignees[(assignee_index + 1) % len(assignees)]
                TaskCollaborator.objects.create(
                    business_task=task,
                    employee=collaborator,
                    added_by_employee=assignees[0],
                )

                TaskEvent.objects.filter(business_task=task).delete()
                events = [
                    ("CREATED", "创建任务", created_at),
                    ("CUSTOMER_CONTACTED", "已联系客户，等待业务反馈。", created_at + timedelta(hours=5)),
                    ("CHECKLIST_UPDATED", "已更新任务检查清单。", created_at + timedelta(days=1)),
                    ("FOLLOW_UP", "已确认下一步处理计划。", created_at + timedelta(days=2)),
                ]
                for event_type, note, occurred_at in events:
                    TaskEvent.objects.create(
                        business_task=task,
                        event_type=event_type,
                        actor_employee=assignee,
                        note=note,
                        occurred_at=min(occurred_at, now),
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"任务原型数据已就绪：新增 {created_count} 条，更新 {updated_count} 条，共 20 条；未修改其他任务。"
            )
        )
