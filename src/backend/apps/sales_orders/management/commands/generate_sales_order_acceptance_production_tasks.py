import json
import uuid
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeStatus
from apps.production_tasks.api.serializers import ProductionTaskCreateFromSalesOrderSerializer
from apps.production_tasks.models import ProductionTask, ProductionTaskStatus
from apps.production_tasks.services import (
    create_production_order_from_sales_order,
    submit_production_task,
)
from apps.sales_orders.models import DeliveryBatchStatus, SalesOrder, SalesOrderStatus


MARKER_PREFIX = "QA-SO-260914-"
CONFIRM_TOKEN = "CREATE-PRODUCTION-QA-SO-260914"
EXPECTED_ORDER_COUNT = 20
EXPECTED_NEW_TASK_COUNT = 5


def _etag_request(instance):
    return SimpleNamespace(headers={"If-Match": etag_for_instance(instance)}, META={})


class Command(BaseCommand):
    help = "为销售订单验收数据中满足门禁的订单建立生产任务单并提交 PMC。默认仅预检。"

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="执行真实数据库写入。")
        parser.add_argument("--confirm", help=f"写入时必须传入 {CONFIRM_TOKEN}。")
        parser.add_argument("--report", help="将本次生成与验收结果写入 JSON 文件。")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("仅允许在 DEBUG 开发环境执行验收数据命令。")

        orders = list(
            SalesOrder.objects.filter(customer_po_number__startswith=MARKER_PREFIX)
            .select_related("salesperson", "merchandiser")
            .prefetch_related("production_tasks", "delivery_batches__lines__sales_order_line")
            .order_by("customer_po_number")
        )
        if len(orders) != EXPECTED_ORDER_COUNT:
            raise CommandError(
                f"验收数据应为 {EXPECTED_ORDER_COUNT} 条，当前为 {len(orders)} 条；命令不会继续。"
            )

        candidates = self._eligible_orders(orders)
        if not options["commit"]:
            self.stdout.write(self.style.SUCCESS(
                f"预检通过：当前有 {len(candidates)} 条已确认且未生成任务单的销售订单可处理。"
            ))
            for order in candidates:
                self.stdout.write(f"- {order.customer_po_number} / {order.order_number}")
            self.stdout.write(
                f"如需写入，请追加 --commit --confirm {CONFIRM_TOKEN}。"
            )
            return

        if options.get("confirm") != CONFIRM_TOKEN:
            raise CommandError(f"请明确追加 --confirm {CONFIRM_TOKEN} 后再写入。")

        if not candidates:
            report = self._build_report(created_task_ids=[])
            self._write_report(options.get("report"), report)
            self.stdout.write(self.style.WARNING("没有新的可生成订单；未重复创建生产任务单。"))
            return
        if len(candidates) != EXPECTED_NEW_TASK_COUNT:
            raise CommandError(
                f"预期首次处理 {EXPECTED_NEW_TASK_COUNT} 条，当前可处理 {len(candidates)} 条；"
                "可能存在部分写入或状态变化，请人工核对。"
            )

        actor = self._actor()
        created_task_ids = []
        with transaction.atomic():
            for order in candidates:
                batch = order.delivery_batches.get(status=DeliveryBatchStatus.ACTIVE)
                batch_line = batch.lines.get()
                quantity = int(batch_line.quantity)
                if batch_line.quantity != quantity or quantity < 1:
                    raise CommandError(
                        f"{order.customer_po_number} 的交付数量不是正整数，不能生成生产任务单。"
                    )

                request_key = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{MARKER_PREFIX}{order.pk}:{batch_line.pk}:production-submit",
                )
                planned_start_date = min(timezone.localdate(), batch.planned_delivery_date)
                payload = {
                    "request_key": str(request_key),
                    "delivery_batch_line_id": str(batch_line.pk),
                    "quantity": quantity,
                    "planned_start_date": planned_start_date.isoformat(),
                    "planned_end_date": batch.planned_delivery_date.isoformat(),
                    "production_priority": "NORMAL",
                    "production_batch_number": f"SOQA-{order.customer_po_number[-3:]}",
                    "planner_id": str((order.merchandiser or order.salesperson).pk),
                }
                serializer = ProductionTaskCreateFromSalesOrderSerializer(data=payload)
                serializer.is_valid(raise_exception=True)
                task = create_production_order_from_sales_order(
                    validated_data=dict(serializer.validated_data),
                    actor_employee=actor,
                    request=None,
                )
                task = submit_production_task(
                    task=task,
                    actor_employee=actor,
                    request=_etag_request(task),
                )
                created_task_ids.append(task.pk)

            report = self._build_report(created_task_ids=created_task_ids)
            if not report["checks"]["all_passed"]:
                raise CommandError("生成后的完整性验收未通过，本次事务已回滚。")

        self._write_report(options.get("report"), report)
        self.stdout.write(self.style.SUCCESS(
            f"已建立并提交 PMC：{len(created_task_ids)} 张生产任务单；"
            "对应销售订单已进入履约中。"
        ))

    def _eligible_orders(self, orders):
        candidates = []
        for order in orders:
            if order.status != SalesOrderStatus.CONFIRMED:
                continue
            if order.production_tasks.exists():
                continue
            active_batches = [
                batch for batch in order.delivery_batches.all()
                if batch.status == DeliveryBatchStatus.ACTIVE
            ]
            if len(active_batches) != 1 or active_batches[0].lines.count() != 1:
                raise CommandError(
                    f"{order.customer_po_number} 的有效交付批次结构不是1批1行，请人工核对。"
                )
            candidates.append(order)
        return candidates

    def _actor(self):
        employees = list(
            Employee.objects.filter(
                status=EmployeeStatus.ACTIVE,
                archived_at__isnull=True,
            )
            .select_related("user")
            .order_by("employee_code", "id")
        )
        if not employees:
            raise CommandError("没有可用于写入审计记录的有效员工。")
        return next(
            (employee for employee in employees if employee.user_id and employee.user.is_superuser),
            employees[0],
        )

    def _build_report(self, created_task_ids):
        orders = list(
            SalesOrder.objects.filter(customer_po_number__startswith=MARKER_PREFIX)
            .prefetch_related("production_tasks__products", "delivery_batches__lines")
            .order_by("customer_po_number")
        )
        status_counts = Counter(order.status for order in orders)
        linked_tasks = list(
            ProductionTask.objects.filter(sales_order__in=orders)
            .exclude(status=ProductionTaskStatus.CANCELLED)
            .select_related("sales_order")
            .prefetch_related("products")
            .order_by("sales_order__customer_po_number", "task_number")
        )
        expected_request_keys = {
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{MARKER_PREFIX}{order.pk}:{batch_line.pk}:production-submit",
            )
            for order in orders
            for batch in order.delivery_batches.all()
            for batch_line in batch.lines.all()
        }
        generated_tasks = [
            task for task in linked_tasks
            if task.source_request_key in expected_request_keys
        ]
        rows = []
        for task in linked_tasks:
            source_batch_lines = {
                product.sales_order_delivery_batch_line_id for product in task.products.all()
            }
            rows.append({
                "task_id": str(task.pk),
                "task_number": task.task_number,
                "task_status": task.status,
                "sales_order_id": str(task.sales_order_id),
                "sales_order_number": task.sales_order.order_number,
                "customer_po_number": task.sales_order.customer_po_number,
                "quantity": str(sum((product.quantity for product in task.products.all()), 0)),
                "source_batch_line_ids": sorted(str(item) for item in source_batch_lines if item),
            })

        checks = {
            "order_count_20": len(orders) == EXPECTED_ORDER_COUNT,
            "status_distribution_after_generation": dict(status_counts) == {
                SalesOrderStatus.DRAFT: 5,
                SalesOrderStatus.FULFILLING: 10,
                SalesOrderStatus.COMPLETED: 5,
            },
            "non_cancelled_production_task_count_10": len(linked_tasks) == 10,
            "generated_tasks_submitted_to_pmc": (
                len(generated_tasks) == EXPECTED_NEW_TASK_COUNT
                and all(task.status == ProductionTaskStatus.PENDING_VALIDATION for task in generated_tasks)
            ),
            "all_tasks_link_sales_order_batch_and_product": all(
                task.sales_order_id
                and task.sales_order_delivery_batch_id
                and task.products.exists()
                and all(product.sales_order_delivery_batch_line_id for product in task.products.all())
                for task in linked_tasks
            ),
            "no_confirmed_order_left_eligible": not any(
                order.status == SalesOrderStatus.CONFIRMED and not order.production_tasks.exists()
                for order in orders
            ),
        }
        checks["all_passed"] = all(checks.values())
        return {
            "dataset": MARKER_PREFIX,
            "generated_at": timezone.now().isoformat(),
            "created_task_ids": [str(item) for item in created_task_ids],
            "order_status_counts": dict(sorted(status_counts.items())),
            "linked_task_count": len(linked_tasks),
            "linked_task_status_counts": dict(sorted(Counter(task.status for task in linked_tasks).items())),
            "checks": checks,
            "tasks": rows,
        }

    def _write_report(self, report_path, report):
        if not report_path:
            return
        path = Path(report_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"验收报告：{path}")
