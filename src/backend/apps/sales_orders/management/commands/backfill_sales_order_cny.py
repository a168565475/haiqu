import json
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.audit import write_audit_log
from apps.organizations.models import Employee, EmployeeStatus
from apps.sales_orders.models import SalesOrder, SalesOrderLine
from apps.sales_orders.pricing import cny_line_amounts, current_cny_rate, validate_cny_total
from apps.sales_orders.services import sales_order_snapshot


class Command(BaseCommand):
    help = "将尚无人民币快照的历史销售订单按当前配置补算一次；默认预览，不改历史版本和生产任务。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--employee-code", help="具有销售订单修改权限的在职员工")
        parser.add_argument("--order-number", action="append", default=[], help="可重复指定；省略时检查全部未归档销售订单")

    @transaction.atomic
    def handle(self, *args, **options):
        actor = None
        if options["apply"]:
            actor = Employee.objects.select_related("user").filter(
                employee_code=options.get("employee_code"), status=EmployeeStatus.ACTIVE, archived_at__isnull=True,
            ).first()
            if not actor or not actor.user or not actor.user.is_active or not actor.user.has_perm("sales_orders.change_salesorder"):
                raise CommandError("补算必须指定具有销售订单修改权限的在职员工 --employee-code。")

        queryset = SalesOrder.objects.filter(archived_at__isnull=True).order_by("pk")
        numbers = set(options["order_number"])
        if numbers:
            queryset = queryset.filter(order_number__in=numbers)
        if options["apply"]:
            queryset = queryset.select_for_update()
        orders = list(queryset)
        missing = numbers - {order.order_number for order in orders}
        if missing:
            raise CommandError(f"销售订单不存在或已归档：{', '.join(sorted(missing))}")

        # 整批先锁定、核对和计算，再写入；任一汇率或金额错误使本批完全不落库。
        prepared = []
        skipped = 0
        for order in orders:
            lines_query = SalesOrderLine.objects.filter(sales_order=order).order_by("pk")
            if options["apply"]:
                lines_query = lines_query.select_for_update()
            lines = list(lines_query)
            if order.exchange_rate_snapshot and order.total_amount_cny is not None and all(
                line.unit_price_cny is not None and line.line_total_cny is not None for line in lines
            ):
                skipped += 1
                continue
            if order.exchange_rate_snapshot or order.total_amount_cny is not None or any(
                line.unit_price_cny is not None or line.line_total_cny is not None for line in lines
            ):
                raise CommandError(f"{order.order_number} 已存在不完整人民币快照，请先核对，不能自动覆盖。")
            try:
                record, snapshot = current_cny_rate(order.currency_code, lock=options["apply"])
                total = Decimal("0")
                for line in lines:
                    line.unit_price_cny, line.line_total_cny = cny_line_amounts(line.unit_price, line.quantity, snapshot["rate"])
                    total += line.line_total_cny
                validate_cny_total(total)
            except ValidationError as exc:
                raise CommandError(f"{order.order_number} 无法补算：{exc.detail}") from exc
            snapshot.update(
                capture_reason="LEGACY_BACKFILL", captured_at=timezone.now().isoformat(),
                previous_exchange_rate=format(order.exchange_rate, ".8f"),
            )
            prepared.append((order, lines, record, snapshot, total))

        results = []
        for order, lines, record, snapshot, total in prepared:
            if options["apply"]:
                before = sales_order_snapshot(order)
                order.exchange_rate_record = record
                order.exchange_rate = Decimal(snapshot["rate"])
                order.exchange_rate_snapshot = snapshot
                order.total_amount_cny = total
                order.save(update_fields=["exchange_rate_record", "exchange_rate", "exchange_rate_snapshot", "total_amount_cny", "updated_at"])
                SalesOrderLine.objects.bulk_update(lines, ["unit_price_cny", "line_total_cny"])
                write_audit_log(
                    object_type="SALES_ORDER", object_id=order.pk, context_type="CUSTOMER_ACCOUNT",
                    context_id=order.customer_account_id, action="CNY_BACKFILLED", actor_employee=actor,
                    before_data=before, after_data=sales_order_snapshot(order),
                )
            results.append({"order_number": order.order_number, "exchange_rate": snapshot["rate"], "total_amount_cny": str(total)})
        self.stdout.write(json.dumps({"applied": options["apply"], "changed": len(prepared), "skipped": skipped, "orders": results}, ensure_ascii=False))
