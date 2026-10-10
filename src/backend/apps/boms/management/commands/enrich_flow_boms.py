import json
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.boms.api.serializers import BomUpdateInputSerializer
from apps.boms.models import Bom, BomStatus
from apps.boms.services import update_bom_lines, verify_bom
from apps.boms.simulation_data import (
    build_bom_simulation_sections,
    load_bom_simulation_catalog,
    summarize_bom_simulation_sections,
)
from apps.core.api.concurrency import etag_for_instance
from apps.core.database_backup import validate_database_backup
from apps.inventory.models import MaterialInbound
from apps.procurement.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchaseRequest,
    PurchaseReturn,
    Supplier,
    SupplierPurchaseSheet,
)
from apps.procurement.services import create_purchase_order, evaluate_purchase_source
from apps.reference_data.models import Currency


CONFIRM_TOKEN = "ENRICH-FLOW-BOMS-20260917"
PRODUCT_NUMBER_PREFIX = "FLOW260917-P"


class _EtagRequest:
    def __init__(self, instance):
        self.headers = {"If-Match": etag_for_instance(instance)}
        self.META = {}
        self.request_id = None


class Command(BaseCommand):
    help = "补全 FLOW-20260917 的 60 份 BOM，并安全重建 50 张草稿采购订单。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm-token", default="")
        parser.add_argument("--backup-path", default="")
        parser.add_argument("--backup-attestation-path", default="")
        parser.add_argument("--report", default="")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("仅允许在 DEBUG 开发环境执行 BOM 模拟数据补全。")
        boms = list(
            Bom.objects.filter(
                product_number_snapshot__startswith=PRODUCT_NUMBER_PREFIX,
                archived_at__isnull=True,
            )
            .select_related("production_task", "product_line", "created_by_employee")
            .prefetch_related("sections__lines")
            .order_by("created_at", "id")
        )
        purchase_orders = list(
            PurchaseOrder.objects.filter(
                lines__bom_id__in=[bom.pk for bom in boms],
                archived_at__isnull=True,
            )
            .select_related("production_task")
            .prefetch_related("lines")
            .distinct()
            .order_by("created_at", "id")
        )
        preflight = self._preflight(boms, purchase_orders)
        current_report = self._report(preflight)
        preflight["already_enriched"] = bool(
            current_report["checks"]["all_passed"]
            and preflight["purchase_order_line_count"] > preflight["purchase_order_count"]
        )
        if not options["apply"] or options["confirm_token"] != CONFIRM_TOKEN:
            self.stdout.write(json.dumps({"mode": "DRY_RUN", "preflight": preflight}, ensure_ascii=False, indent=2))
            self.stdout.write(self.style.WARNING(
                f"执行写入需传入 --apply --confirm-token {CONFIRM_TOKEN}"
            ))
            return
        if preflight["already_enriched"]:
            current_report["mode"] = "NO_OP"
            current_report["reason"] = "目标 BOM 与采购订单已经满足全部数量和引用校验，未重复写入。"
            self._write_report_if_requested(current_report, options["report"])
            self.stdout.write(json.dumps(current_report, ensure_ascii=False, indent=2))
            self.stdout.write(self.style.SUCCESS("目标数据已经补全，本次未重复写入。"))
            return
        try:
            validate_database_backup(
                options["backup_path"],
                options["backup_attestation_path"],
            )
        except ValueError as exc:
            raise CommandError(f"数据库备份验证失败：{exc} 禁止删除并重建采购订单。") from exc

        catalog = load_bom_simulation_catalog()
        actor = boms[0].created_by_employee
        if actor is None:
            raise CommandError("模拟 BOM 缺少创建员工，不能写入审计日志。")
        suppliers = list(
            Supplier.objects.filter(archived_at__isnull=True, is_disabled=False).order_by(
                "supplier_number", "id"
            )
        )
        if not suppliers:
            raise CommandError("没有可用供应商，无法重建采购订单。")
        cny = Currency.objects.filter(
            code="CNY",
            status="ACTIVE",
            archived_at__isnull=True,
        ).first()
        if cny is None:
            raise CommandError("缺少 CNY 币种资料。")

        with transaction.atomic():
            locked_boms = list(
                Bom.objects.select_for_update(of=("self",))
                .filter(pk__in=[bom.pk for bom in boms])
                .select_related("production_task", "product_line", "created_by_employee")
                .prefetch_related("sections__lines")
                .order_by("created_at", "id")
            )
            locked_purchase_orders = list(
                PurchaseOrder.objects.select_for_update(of=("self",))
                .filter(pk__in=[order.pk for order in purchase_orders])
                .select_related("production_task")
                .prefetch_related("lines")
                .order_by("created_at", "id")
            )
            if {item.pk for item in locked_boms} != {item.pk for item in boms} or {
                item.pk for item in locked_purchase_orders
            } != {item.pk for item in purchase_orders}:
                raise CommandError("目标 BOM 或采购订单在预检后发生变化，事务已回滚。")
            self._preflight(locked_boms, locked_purchase_orders)
            purchase_sources = []
            for order in locked_purchase_orders:
                order_lines = list(order.lines.all())
                bom_ids = {line.bom_id for line in order_lines if line.bom_id}
                if len(bom_ids) != 1:
                    raise CommandError(f"采购订单 {order.order_number} 没有唯一 BOM 来源。")
                purchase_sources.append(
                    {
                        "production_task_id": order.production_task_id,
                        "bom_id": bom_ids.pop(),
                        "delivery_date": min(
                            (line.delivery_date for line in order_lines if line.delivery_date),
                            default=timezone.localdate() + timedelta(days=20),
                        ),
                    }
                )

            PurchaseOrder.objects.filter(pk__in=[order.pk for order in locked_purchase_orders]).delete()
            boms = locked_boms
            for index, bom in enumerate(boms, start=1):
                serializer = BomUpdateInputSerializer(
                    data={
                        "sections": build_bom_simulation_sections(
                            bom=bom,
                            index=index,
                            catalog=catalog,
                        )
                    },
                    context={"bom": bom},
                )
                serializer.is_valid(raise_exception=True)
                updated = update_bom_lines(
                    bom=bom,
                    sections=serializer.validated_data["sections"],
                    actor_employee=actor,
                    request=_EtagRequest(bom),
                )
                verify_bom(
                    bom=updated,
                    quantity_confirmation_reason="模拟数据补全；订单数量与生产任务数量一致。",
                    actor_employee=actor,
                    request=_EtagRequest(updated),
                )

            refreshed_boms = {
                bom.pk: bom
                for bom in Bom.objects.filter(pk__in=[item.pk for item in boms]).select_related("production_task")
            }
            allowed_task_ids = [item["production_task_id"] for item in purchase_sources]
            for index, item in enumerate(purchase_sources, start=1):
                task = refreshed_boms[item["bom_id"]].production_task
                bom = refreshed_boms[item["bom_id"]]
                source = evaluate_purchase_source(task, bom_id=bom.pk)
                if not source["can_create"]:
                    raise CommandError(f"第 {index} 张采购订单被门禁阻止：{source['blockers']}")
                lines = []
                for source_line in source["lines"]:
                    required_quantity = source_line.get("required_quantity")
                    if required_quantity is None or Decimal(required_quantity) <= 0:
                        raise CommandError(f"第 {index} 张采购订单存在无效采购数量：{source_line}")
                    supplier = self._supplier_for_line(suppliers, source_line)
                    lines.append(
                        {
                            "bom_line_id": source_line["bom_line_id"],
                            "supplier_id": supplier.pk,
                            "delivery_date": item["delivery_date"],
                            "actual_purchase_quantity": Decimal(required_quantity),
                            "unit_price": Decimal("8.5000") + Decimal(index % 9),
                        }
                    )
                create_purchase_order(
                    validated_data={
                        "production_task_id": task.pk,
                        "bom_id": bom.pk,
                        "source_revision": source["source_revision"],
                        "currency_id": cny.pk,
                        "is_mailed": False,
                        "lines": lines,
                    },
                    allowed_task_ids=allowed_task_ids,
                    actor_employee=actor,
                    request=None,
                )
            report = self._report(preflight)
            if not report["checks"]["all_passed"]:
                raise CommandError(f"写入后校验未通过：{report['checks']}")
        self._write_report_if_requested(report, options["report"])
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        self.stdout.write(self.style.SUCCESS("60 份 BOM 已补全，50 张草稿采购订单已按新 BOM 重建。"))

    @staticmethod
    def _supplier_for_line(suppliers, source_line):
        suggested = source_line.get("suggested_supplier_category")
        if suggested:
            for supplier in suppliers:
                if suggested in supplier.supplier_categories:
                    return supplier
        return suppliers[0]

    @staticmethod
    def _write_report_if_requested(report, report_path):
        report_path = report_path.strip()
        if not report_path:
            return
        path = Path(report_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(path)

    @staticmethod
    def _preflight(boms, purchase_orders):
        problems = []
        if len(boms) != 60:
            problems.append(f"目标 BOM 应为 60 份，实际为 {len(boms)} 份。")
        if len(purchase_orders) != 50:
            problems.append(f"目标采购订单应为 50 张，实际为 {len(purchase_orders)} 张。")
        non_draft = [order.order_number for order in purchase_orders if order.status != PurchaseOrderStatus.DRAFT]
        if non_draft:
            problems.append(f"以下采购订单不是草稿：{', '.join(non_draft[:5])}")
        if PurchaseReturn.objects.filter(purchase_order_id__in=[item.pk for item in purchase_orders]).exists():
            problems.append("目标采购订单已有退货记录。")
        if PurchaseRequest.objects.exists() or SupplierPurchaseSheet.objects.exists() or MaterialInbound.objects.exists():
            problems.append("采购申请、采购单或材料入库已产生后续数据，不能重建采购订单。")
        if problems:
            raise CommandError("；".join(problems))
        return {
            "bom_count": len(boms),
            "verified_bom_count": sum(item.status == BomStatus.VERIFIED for item in boms),
            "purchase_order_count": len(purchase_orders),
            "purchase_order_statuses": sorted({item.status for item in purchase_orders}),
            "purchase_order_line_count": sum(item.lines.count() for item in purchase_orders),
        }

    @staticmethod
    def _report(preflight):
        boms = Bom.objects.filter(
            product_number_snapshot__startswith=PRODUCT_NUMBER_PREFIX,
            archived_at__isnull=True,
        )
        section_summary = summarize_bom_simulation_sections(
            list(boms.prefetch_related("sections__lines")),
            expected_bom_count=60,
        )
        counts_by_title = section_summary["counts_by_title"]
        ranges = section_summary["ranges"]
        purchase_orders = PurchaseOrder.objects.filter(
            lines__bom__in=boms,
            archived_at__isnull=True,
        ).select_related("production_task").prefetch_related("lines").distinct()
        purchase_order_list = list(purchase_orders)
        purchase_lines = PurchaseOrderLine.objects.filter(purchase_order__in=purchase_orders)
        invalid_purchase_lines = purchase_lines.filter(
            Q(bom_line__isnull=True)
            | ~Q(bom_line__section__bom_id=F("bom_id"))
            | ~Q(bom__production_task_id=F("purchase_order__production_task_id"))
        ).exists()
        checks = {
            "bom_count_60": boms.count() == 60,
            "all_boms_verified": boms.filter(status=BomStatus.VERIFIED).count() == 60,
            "all_seven_sections_present": section_summary["all_valid"],
            "all_bom_lines_have_units": not boms.filter(sections__lines__unit="").exists(),
            "purchase_order_count_50": purchase_orders.count() == 50,
            "all_purchase_orders_draft": not purchase_orders.exclude(status=PurchaseOrderStatus.DRAFT).exists(),
            "all_purchase_lines_link_current_bom_line": not invalid_purchase_lines,
            "all_purchase_source_lines_complete": Command._purchase_sources_complete(
                purchase_order_list
            ),
        }
        checks["all_passed"] = all(checks.values())
        return {
            "generated_at": timezone.now().isoformat(),
            "preflight": preflight,
            "bom_count": boms.count(),
            "bom_line_count": sum(sum(values) for values in counts_by_title.values()),
            "section_ranges": ranges,
            "purchase_order_count": purchase_orders.count(),
            "purchase_order_line_count": sum(order.lines.count() for order in purchase_orders),
            "checks": checks,
        }

    @staticmethod
    def _purchase_sources_complete(purchase_orders):
        for order in purchase_orders:
            order_lines = list(order.lines.all())
            bom_ids = {line.bom_id for line in order_lines if line.bom_id}
            if len(bom_ids) != 1 or any(line.bom_line_id is None for line in order_lines):
                return False
            source = evaluate_purchase_source(
                order.production_task,
                bom_id=bom_ids.pop(),
            )
            blocker_codes = Counter(
                blocker.get("code") for blocker in source.get("blockers", [])
            )
            if (
                blocker_codes != Counter({"PURCHASE_ORDER_EXISTS": 1})
                or str(source.get("existing_purchase_order_id")) != str(order.pk)
                or source.get("source_revision") != order.source_revision
            ):
                return False
            expected_lines = {
                str(line["bom_line_id"]): Decimal(line["required_quantity"])
                for line in source.get("preview_lines", [])
            }
            actual_lines = {str(line.bom_line_id): line for line in order_lines}
            if len(actual_lines) != len(order_lines) or set(actual_lines) != set(expected_lines):
                return False
            if any(
                line.source_bom_line_id_snapshot != line.bom_line_id
                or line.required_quantity != expected_lines[line_id]
                or line.actual_purchase_quantity != expected_lines[line_id]
                for line_id, line in actual_lines.items()
            ):
                return False
        return True
