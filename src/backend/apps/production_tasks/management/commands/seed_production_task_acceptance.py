from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee, EmployeeStatus
from apps.products.models import ProductInformation, ProductStatus
from apps.production_tasks.models import (
    DeliveryMethod,
    OrderSource,
    ProductionDeliveryBatch,
    ProductionPriority,
    ProductionRunBatch,
    ProductionRunBatchStatus,
    ProductionTask,
    ProductionTaskDetail,
    ProductionTaskProduct,
    ProductionTaskStatus,
)
from apps.production_tasks.numbering import PRODUCTION_TASK_NUMBER_PATTERN, next_production_task_number
from apps.reference_data.models import Currency, ProductColor, ReferenceStatus
from apps.sales_orders.models import (
    DeliveryBatchStatus,
    SalesOrder,
    SalesOrderDeliveryBatch,
    SalesOrderDeliveryBatchLine,
    SalesOrderLine,
    SalesOrderSource,
    SalesOrderStatus,
)


STATUS_SEQUENCE = [
    ProductionTaskStatus.DRAFT,
    ProductionTaskStatus.PENDING_VALIDATION,
    ProductionTaskStatus.READY,
    ProductionTaskStatus.IN_PRODUCTION,
    ProductionTaskStatus.PAUSED,
    ProductionTaskStatus.COMPLETED,
    ProductionTaskStatus.CANCELLED,
    ProductionTaskStatus.DRAFT,
    ProductionTaskStatus.PENDING_VALIDATION,
    ProductionTaskStatus.READY,
    ProductionTaskStatus.IN_PRODUCTION,
    ProductionTaskStatus.COMPLETED,
    ProductionTaskStatus.CANCELLED,
    ProductionTaskStatus.DRAFT,
    ProductionTaskStatus.PENDING_VALIDATION,
    ProductionTaskStatus.READY,
    ProductionTaskStatus.IN_PRODUCTION,
    ProductionTaskStatus.PAUSED,
    ProductionTaskStatus.COMPLETED,
    ProductionTaskStatus.CANCELLED,
]

PRIORITY_SEQUENCE = [
    ProductionPriority.NORMAL,
    ProductionPriority.HIGH,
    ProductionPriority.URGENT,
    ProductionPriority.LOW,
]


class Command(BaseCommand):
    help = "幂等准备 20 条生产任务单验收数据，任务编号使用统一 HT 年度流水。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            help="必须明确传入 QA-MO-260911，防止误向非验收数据库写入数据。",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("仅允许在 DEBUG 开发环境执行生产任务单验收数据命令。")
        if options.get("confirm") != "QA-MO-260911":
            raise CommandError("请明确追加 --confirm QA-MO-260911 后再执行。")

        customers = list(CustomerAccount.objects.filter(archived_at__isnull=True).order_by("account_code", "id")[:20])
        employees = list(Employee.objects.filter(status=EmployeeStatus.ACTIVE, archived_at__isnull=True).order_by("employee_code")[:12])
        products = list(ProductInformation.objects.filter(status=ProductStatus.ACTIVE, archived_at__isnull=True).select_related("unit", "product_item").order_by("product_number")[:20])
        colors = list(ProductColor.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True).order_by("color_card", "color_name", "color_code")[:20])
        currency = Currency.objects.filter(code="CNY", status=ReferenceStatus.ACTIVE, archived_at__isnull=True).first()

        missing = []
        if not customers:
            missing.append("客户")
        if len(employees) < 2:
            missing.append("至少 2 名有效员工")
        if not products:
            missing.append("产品")
        if not colors:
            missing.append("颜色")
        if currency is None:
            missing.append("有效 CNY 币种")
        if missing:
            raise CommandError(f"缺少验收数据依赖：{'、'.join(missing)}。")

        created_count = 0
        updated_count = 0
        base_date = date(2026, 9, 11)
        now = timezone.make_aware(datetime(2026, 9, 11, 9, 0, 0))

        for index, status in enumerate(STATUS_SEQUENCE, start=1):
            customer = customers[(index - 1) % len(customers)]
            salesperson = employees[(index - 1) % len(employees)]
            follower = employees[index % len(employees)]
            planner = employees[(index + 1) % len(employees)]
            order_date = base_date - timedelta(days=(index % 8) + 1)
            delivery_date = base_date + timedelta(days=7 + index)
            planned_start = base_date + timedelta(days=index % 5)
            planned_end = delivery_date - timedelta(days=index % 3)
            quantity = 80 + index * 35
            contract_number = f"QA-CON-260911-{index:03d}"
            line_count = 2 if index % 3 == 0 else 1
            line_quantities = [quantity]
            if line_count == 2:
                line_quantities = [quantity, 25 + index * 4]
            total_quantity = sum(line_quantities)

            source_order = None
            source_batch = None
            source_batch_lines = {}
            if index == 3:
                source_order, _ = SalesOrder.objects.update_or_create(
                    order_number=f"QA-SO-260911-{index:03d}",
                    defaults={
                        "version_number": 1,
                        "source_type": SalesOrderSource.DIRECT,
                        "customer_account": customer,
                        "salesperson": salesperson,
                        "merchandiser": follower,
                        "contract_number": f"QA-CON-260911-{index:03d}",
                        "order_date": order_date,
                        "direct_order_reason": "生产任务单 V3 页面验收专用销售订单。",
                        "currency_code": currency.code,
                        "exchange_rate": Decimal("1.000000"),
                        "order_tolerance_percent": Decimal("0"),
                        "includes_tax": False,
                        "preproduction_sample_required": True,
                        "status": SalesOrderStatus.FULFILLING,
                        "total_amount": Decimal("0"),
                        "confirmed_at": now - timedelta(days=4),
                        "confirmed_by_employee": planner,
                        "created_by_employee": salesperson,
                    },
                )
                source_batch, _ = SalesOrderDeliveryBatch.objects.update_or_create(
                    sales_order=source_order,
                    line_number=1,
                    defaults={
                        "batch_number": "QA-D01",
                        "planned_delivery_date": delivery_date,
                        "status": DeliveryBatchStatus.ACTIVE,
                        "cancelled_at": None,
                        "cancellation_reason": "",
                        "notes": "生产任务单 V3 来源锁定验收专用批次。",
                    },
                )
                desired_source_lines = []
                for line_number, line_quantity in enumerate(line_quantities, start=1):
                    product = products[(index + line_number - 2) % len(products)]
                    order_line, _ = SalesOrderLine.objects.update_or_create(
                        sales_order=source_order,
                        line_number=line_number,
                        defaults={
                            "product": product,
                            "product_number_snapshot": product.product_number,
                            "product_code_snapshot": product.product_code,
                            "product_name_snapshot": product.product_name,
                            "specification_snapshot": product.specification,
                            "unit_code_snapshot": product.unit.unit_code,
                            "quantity": Decimal(line_quantity),
                            "unit_price": Decimal("0"),
                            "line_total": Decimal("0"),
                            "quality_requirements": "QA 来源锁定验收：颜色和尺寸须与确认样一致。",
                            "packaging_requirements": "QA 来源锁定验收：按生产任务标签装箱。",
                        },
                    )
                    source_line, _ = SalesOrderDeliveryBatchLine.objects.update_or_create(
                        delivery_batch=source_batch,
                        sales_order_line=order_line,
                        defaults={"quantity": Decimal(line_quantity)},
                    )
                    source_batch_lines[line_number] = source_line
                    desired_source_lines.append(order_line.id)
                SalesOrderDeliveryBatchLine.objects.filter(delivery_batch=source_batch).exclude(
                    sales_order_line_id__in=desired_source_lines
                ).delete()
                SalesOrderLine.objects.filter(sales_order=source_order).exclude(id__in=desired_source_lines).delete()
                SalesOrderDeliveryBatch.objects.filter(sales_order=source_order).exclude(id=source_batch.id).delete()
            is_started = status in {
                ProductionTaskStatus.IN_PRODUCTION,
                ProductionTaskStatus.PAUSED,
                ProductionTaskStatus.COMPLETED,
            }
            is_finished = status == ProductionTaskStatus.COMPLETED
            status_reason = {
                ProductionTaskStatus.PAUSED: f"QA 验收暂停：等待第 {index} 批面料到厂。",
                ProductionTaskStatus.COMPLETED: f"QA 验收完工：第 {index} 批质量抽检通过。",
                ProductionTaskStatus.CANCELLED: f"QA 验收取消：客户调整第 {index} 批交付计划。",
            }.get(status, "")

            task_defaults = {
                "order_source": OrderSource.REPEAT if index % 4 == 0 else OrderSource.NEW,
                "order_number": f"QA-SO-260911-{index:03d}",
                "sales_order": source_order,
                "sales_order_delivery_batch": source_batch,
                "sales_order_line": None,
                "customer_account": customer,
                "order_date": order_date,
                "delivery_date": delivery_date,
                "salesperson": salesperson,
                "currency": currency,
                "includes_tax": index % 2 == 0,
                "order_tolerance_percent": Decimal(index % 4),
                "is_repeat_order": index % 4 == 0,
                "preproduction_sample_required": index % 3 == 0,
                "delivery_method": DeliveryMethod.SPLIT if index % 3 == 0 else DeliveryMethod.SINGLE,
                "special_requirements_html": f"<p>QA验收任务{index}：按确认样生产，重点检查尺寸、颜色和表面处理。</p>",
                "packaging_method_html": f"QA包装方案{index}：五层瓦楞纸箱，外箱粘贴任务编号。",
                "freight_amount": Decimal(index * 10),
                "other_fee_amount": Decimal(index * 3),
                "status": status,
                "status_reason": status_reason,
                "planned_start_date": planned_start if status != ProductionTaskStatus.DRAFT else None,
                "planned_end_date": planned_end if status != ProductionTaskStatus.DRAFT else None,
                "production_priority": PRIORITY_SEQUENCE[(index - 1) % len(PRIORITY_SEQUENCE)],
                "production_batch_number": f"QA-BATCH-{index:03d}",
                "planner": planner if status != ProductionTaskStatus.DRAFT else None,
                "accepted_by_employee": planner if status in {ProductionTaskStatus.READY, ProductionTaskStatus.IN_PRODUCTION, ProductionTaskStatus.PAUSED, ProductionTaskStatus.COMPLETED} else None,
                "started_at": now - timedelta(days=2) if is_started else None,
                "completed_at": now - timedelta(hours=index) if is_finished else None,
                "actual_quantity": Decimal(total_quantity) if is_finished else Decimal(0),
                "actual_good_quantity": Decimal(total_quantity - index % 5) if is_finished else Decimal(0),
                "excess_quantity": Decimal(index % 3) if is_finished else Decimal(0),
                "created_by_employee": salesperson,
                "submitted_at": now - timedelta(days=3) if status not in {ProductionTaskStatus.DRAFT, ProductionTaskStatus.CANCELLED} else None,
            }
            task = ProductionTask.objects.filter(contract_number=contract_number).first()
            created = task is None
            if task is not None and not PRODUCTION_TASK_NUMBER_PATTERN.fullmatch(task.task_number):
                raise CommandError(
                    f"{task.task_number} 仍是旧格式，请先执行 renumber_production_tasks 再更新验收数据。"
                )
            if task is None:
                task = ProductionTask(
                    task_number=next_production_task_number(order_date),
                    contract_number=contract_number,
                )
            for field_name, field_value in task_defaults.items():
                setattr(task, field_name, field_value)
            task.save()
            task.followers.set([follower])
            created_count += int(created)
            updated_count += int(not created)

            for line_number, line_quantity in enumerate(line_quantities, start=1):
                product = products[(index + line_number - 2) % len(products)]
                color = colors[(index * 2 + line_number - 3) % len(colors)]
                unit_price = Decimal("18.50") + Decimal(index * 2 + line_number) / Decimal("10")
                product_line, _ = ProductionTaskProduct.objects.update_or_create(
                    production_task=task,
                    line_number=line_number,
                    defaults={
                        "product": product,
                        "sales_order_delivery_batch_line": source_batch_lines.get(line_number),
                        "product_number_snapshot": product.product_number,
                        "product_code_snapshot": product.product_code,
                        "item_number_snapshot": product.product_item.item_number,
                        "product_name_snapshot": product.product_name,
                        "specification_snapshot": product.specification,
                        "product_color": color,
                        "color_card_snapshot": color.color_card,
                        "color_name_snapshot": color.color_name,
                        "color_code_snapshot": color.color_code,
                        "quantity": line_quantity,
                        "unit": product.unit,
                        "currency": currency,
                        "unit_price": unit_price,
                        "total_amount": unit_price * line_quantity,
                        "exchange_rate": Decimal("1.000"),
                        "special_requirements": f"第 {line_number} 行：颜色和尺寸须与 QA 确认样一致。",
                        "packaging_method": f"每箱 {2 + index % 5} 件，内附说明书和验收标签。",
                    },
                )
                ProductionTaskDetail.objects.update_or_create(
                    product_line=product_line,
                    line_number=1,
                    defaults={
                        "template_key": "QA_ACCEPTANCE",
                        "detail_type": "QUALITY",
                        "category_label": "验收要求",
                        "is_selected": True,
                        "description": f"任务 {index} 第 {line_number} 行的结构、外观和包装验收说明。",
                    },
                )
                ProductionTaskDetail.objects.filter(product_line=product_line).exclude(line_number=1).delete()

            ProductionTaskProduct.objects.filter(production_task=task).exclude(
                line_number__in=range(1, line_count + 1)
            ).delete()

            delivery_quantities = [total_quantity]
            if task.delivery_method == DeliveryMethod.SPLIT:
                first_quantity = total_quantity // 2
                delivery_quantities = [first_quantity, total_quantity - first_quantity]
            for delivery_line_number, delivery_quantity in enumerate(delivery_quantities, start=1):
                ProductionDeliveryBatch.objects.update_or_create(
                    production_task=task,
                    line_number=delivery_line_number,
                    defaults={
                        "quantity": delivery_quantity,
                        "delivery_date": delivery_date - timedelta(days=2 if delivery_line_number == 1 and len(delivery_quantities) == 2 else 0),
                        "note": f"QA 验收交付批次 {index}-{delivery_line_number}",
                    },
                )
            ProductionDeliveryBatch.objects.filter(production_task=task).exclude(
                line_number__in=range(1, len(delivery_quantities) + 1)
            ).delete()
            run_status = {
                ProductionTaskStatus.IN_PRODUCTION: ProductionRunBatchStatus.IN_PROGRESS,
                ProductionTaskStatus.PAUSED: ProductionRunBatchStatus.IN_PROGRESS,
                ProductionTaskStatus.COMPLETED: ProductionRunBatchStatus.COMPLETED,
                ProductionTaskStatus.CANCELLED: ProductionRunBatchStatus.CANCELLED,
            }.get(status, ProductionRunBatchStatus.PLANNED)
            ProductionRunBatch.objects.update_or_create(
                production_task=task,
                batch_number=f"QA-BATCH-{index:03d}",
                defaults={
                    "planned_quantity": total_quantity,
                    "actual_quantity": total_quantity if is_finished else (total_quantity // 2 if is_started else 0),
                    "good_quantity": total_quantity - index % 5 if is_finished else (total_quantity // 2 - index % 3 if is_started else 0),
                    "status": run_status,
                    "started_at": now - timedelta(days=2) if is_started else None,
                    "completed_at": now - timedelta(hours=index) if is_finished else None,
                    "note": status_reason or f"QA 验收生产批次 {index}",
                },
            )
            ProductionRunBatch.objects.filter(production_task=task).exclude(
                batch_number=f"QA-BATCH-{index:03d}"
            ).delete()

        status_counts = {
            status: ProductionTask.objects.filter(contract_number__startswith="QA-CON-260911-", status=status).count()
            for status in ProductionTaskStatus.values
        }
        self.stdout.write(self.style.SUCCESS(
            f"生产任务单验收数据已就绪：新建 {created_count} 条，更新 {updated_count} 条，共 20 条；状态分布 {status_counts}"
        ))
