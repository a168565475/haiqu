import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.boms.api.serializers import BomUpdateInputSerializer
from apps.boms.models import Bom
from apps.boms.services import update_bom_lines, verify_bom
from apps.boms.simulation_data import (
    build_bom_simulation_sections,
    load_bom_simulation_catalog,
)
from apps.core.api.concurrency import etag_for_instance
from apps.core.database_backup import validate_database_backup
from apps.inventory.models import MaterialInbound
from apps.procurement.models import (
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseReturn,
    SupplierPurchaseSheet,
)
from apps.procurement.services import evaluate_purchase_source
from apps.products.material_identity import resolve_bom_line_raw_material


CONFIRM_TOKEN = "REPAIR-FLOW-BOM-MATERIAL-IDENTITIES-20260917"
PRODUCT_NUMBER_PREFIX = "FLOW260917-P"
PURCHASABLE_SECTION_TITLES = {
    "管材类",
    "五金件",
    "塑料件类",
    "辅料类",
    "面料类",
    "包材类",
}


class _EtagRequest:
    def __init__(self, instance):
        self.headers = {"If-Match": etag_for_instance(instance)}
        self.META = {}
        self.request_id = None


class Command(BaseCommand):
    help = "为 FLOW-20260917 模拟 BOM 冻结具体库存原料 ID；已进入后续流程的单据保持不动。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm-token", default="")
        parser.add_argument("--backup-path", default="")
        parser.add_argument("--backup-attestation-path", default="")
        parser.add_argument("--report", default="")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("仅允许在 DEBUG 开发环境修复流程模拟数据。")

        boms = list(
            Bom.objects.filter(
                product_number_snapshot__startswith=PRODUCT_NUMBER_PREFIX,
                archived_at__isnull=True,
            )
            .select_related("production_task", "created_by_employee")
            .prefetch_related("sections__lines")
            .order_by("created_at", "id")
        )
        if len(boms) != 60:
            raise CommandError(f"目标 BOM 应为 60 份，实际为 {len(boms)} 份。")

        orders = list(
            PurchaseOrder.objects.filter(
                lines__bom_id__in=[bom.pk for bom in boms],
                archived_at__isnull=True,
            )
            .distinct()
            .order_by("created_at", "id")
        )
        advanced_order_ids = self._advanced_order_ids(orders)
        advanced_bom_ids = set(
            PurchaseOrder.objects.filter(pk__in=advanced_order_ids)
            .values_list("lines__bom_id", flat=True)
        )
        safe_boms = [bom for bom in boms if bom.pk not in advanced_bom_ids]
        preflight = self._report(boms, orders, advanced_order_ids)

        if not options["apply"] or options["confirm_token"] != CONFIRM_TOKEN:
            self.stdout.write(
                json.dumps(
                    {
                        "mode": "DRY_RUN",
                        "preflight": preflight,
                        "safe_bom_count": len(safe_boms),
                        "advanced_bom_count": len(advanced_bom_ids),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f"执行安全范围写入需传入 --apply --confirm-token {CONFIRM_TOKEN}"
                )
            )
            return

        try:
            validate_database_backup(
                options["backup_path"],
                options["backup_attestation_path"],
            )
        except ValueError as exc:
            raise CommandError(f"数据库备份验证失败：{exc} 禁止写入修复。") from exc

        catalog = load_bom_simulation_catalog()
        target_bom_ids = [bom.pk for bom in safe_boms]
        target_order_ids = [
            order.pk
            for order in orders
            if order.pk not in advanced_order_ids
        ]
        with transaction.atomic():
            locked_boms = list(
                Bom.objects.select_for_update(of=("self",))
                .filter(pk__in=target_bom_ids)
                .select_related("production_task", "created_by_employee")
                .prefetch_related("sections__lines")
                .order_by("created_at", "id")
            )
            if {bom.pk for bom in locked_boms} != set(target_bom_ids):
                raise CommandError("目标 BOM 在预检后发生变化，事务已回滚。")

            locked_orders = list(
                PurchaseOrder.objects.select_for_update(of=("self",))
                .filter(pk__in=target_order_ids, archived_at__isnull=True)
                .order_by("created_at", "id")
            )
            if {order.pk for order in locked_orders} != set(target_order_ids):
                raise CommandError("目标采购订单在预检后发生变化，事务已回滚。")
            if any(order.status != PurchaseOrderStatus.DRAFT for order in locked_orders):
                raise CommandError("安全范围内出现非草稿采购订单，事务已回滚。")

            original_index_by_bom_id = {
                bom.pk: index for index, bom in enumerate(boms, start=1)
            }
            for bom in locked_boms:
                actor = bom.created_by_employee
                if actor is None:
                    raise CommandError(f"BOM {bom.bom_number} 缺少创建员工。")
                desired_sections = build_bom_simulation_sections(
                    bom=bom,
                    index=original_index_by_bom_id[bom.pk],
                    catalog=catalog,
                )
                self._attach_existing_ids(bom, desired_sections)
                serializer = BomUpdateInputSerializer(
                    data={"sections": desired_sections},
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
                    quantity_confirmation_reason="修复流程模拟数据的稳定库存原料 ID。",
                    actor_employee=actor,
                    request=_EtagRequest(updated),
                )

            for order in locked_orders:
                self._sync_draft_purchase_order(order)

            post_report = self._report(
                list(
                    Bom.objects.filter(
                        product_number_snapshot__startswith=PRODUCT_NUMBER_PREFIX,
                        archived_at__isnull=True,
                    )
                    .prefetch_related("sections__lines")
                    .order_by("created_at", "id")
                ),
                list(
                    PurchaseOrder.objects.filter(
                        lines__bom__product_number_snapshot__startswith=PRODUCT_NUMBER_PREFIX,
                        archived_at__isnull=True,
                    )
                    .distinct()
                    .order_by("created_at", "id")
                ),
                advanced_order_ids,
            )
            if post_report["safe_unresolved_line_count"] or post_report["safe_unit_mismatch_count"]:
                raise CommandError(f"写入后稳定原料校验未通过：{post_report}")

        result = {
            "mode": "APPLIED",
            "generated_at": timezone.now().isoformat(),
            "repaired_bom_count": len(target_bom_ids),
            "skipped_advanced_bom_count": len(advanced_bom_ids),
            "report": post_report,
        }
        self._write_report(result, options["report"])
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        self.stdout.write(self.style.SUCCESS("安全范围内的 BOM 稳定原料 ID 已修复。"))

    @staticmethod
    def _advanced_order_ids(orders):
        order_ids = [order.pk for order in orders]
        advanced = {
            order.pk for order in orders if order.status != PurchaseOrderStatus.DRAFT
        }
        advanced.update(
            SupplierPurchaseSheet.objects.filter(purchase_order_id__in=order_ids)
            .values_list("purchase_order_id", flat=True)
        )
        advanced.update(
            MaterialInbound.objects.filter(purchase_order_id__in=order_ids)
            .values_list("purchase_order_id", flat=True)
        )
        advanced.update(
            PurchaseReturn.objects.filter(purchase_order_id__in=order_ids)
            .values_list("purchase_order_id", flat=True)
        )
        return advanced

    @staticmethod
    def _attach_existing_ids(bom, desired_sections):
        existing_sections = {
            (section.title.strip(), section.section_type): section
            for section in bom.sections.all()
        }
        for desired_section in desired_sections:
            key = (
                desired_section["title"].strip(),
                desired_section["section_type"],
            )
            existing_section = existing_sections.get(key)
            if existing_section is None:
                raise CommandError(f"BOM {bom.bom_number} 缺少分区 {desired_section['title']}。")
            existing_lines = list(existing_section.lines.all().order_by("line_number", "id"))
            if len(existing_lines) != len(desired_section["lines"]):
                raise CommandError(
                    f"BOM {bom.bom_number} 的 {desired_section['title']} 明细数量已变化，禁止自动覆盖。"
                )
            desired_section["id"] = existing_section.pk
            for desired_line, existing_line in zip(
                desired_section["lines"],
                existing_lines,
                strict=True,
            ):
                desired_line["id"] = existing_line.pk

    @staticmethod
    def _sync_draft_purchase_order(order):
        order.refresh_from_db()
        source = evaluate_purchase_source(
            order.production_task,
            bom_id=order.lines.values_list("bom_id", flat=True).distinct().get(),
        )
        source_lines = source.get("preview_lines", [])
        source_by_bom_line_id = {line["bom_line_id"]: line for line in source_lines}
        order_lines = list(order.lines.select_for_update().order_by("line_number", "id"))
        if set(source_by_bom_line_id) != {str(line.bom_line_id) for line in order_lines}:
            raise CommandError(f"采购订单 {order.order_number} 的 BOM 明细集合不一致。")
        for line in order_lines:
            source_line = source_by_bom_line_id[str(line.bom_line_id)]
            required_quantity = source_line["required_quantity"]
            previous_required_quantity = line.required_quantity
            line.category_snapshot = source_line["category"]
            line.material_snapshot = source_line["material"]
            line.part_name_snapshot = source_line["part_name"]
            line.specification_snapshot = source_line["specification"]
            line.raw_material_snapshot = source_line["raw_material"]
            line.required_quantity = required_quantity
            line.source_quantity_field = source_line["source_quantity_field"]
            line.source_quantity_text = source_line["source_quantity_text"]
            line.source_unit_text = source_line["source_unit_text"]
            line.quantity_parse_status = source_line["quantity_parse_status"]
            if line.actual_purchase_quantity == previous_required_quantity:
                line.actual_purchase_quantity = required_quantity
            if line.actual_purchase_quantity is not None and line.unit_price is not None:
                line.amount = (line.actual_purchase_quantity * line.unit_price).quantize(
                    Decimal("0.0001")
                )
            line.save(
                update_fields=[
                    "category_snapshot",
                    "material_snapshot",
                    "part_name_snapshot",
                    "specification_snapshot",
                    "raw_material_snapshot",
                    "required_quantity",
                    "source_quantity_field",
                    "source_quantity_text",
                    "source_unit_text",
                    "quantity_parse_status",
                    "actual_purchase_quantity",
                    "amount",
                    "updated_at",
                ]
            )
        order.source_revision = source["source_revision"]
        amounts = [line.amount for line in order_lines if line.amount is not None]
        order.total_amount = sum(amounts, Decimal("0")) if len(amounts) == len(order_lines) else None
        order.save(update_fields=["source_revision", "total_amount", "updated_at"])

    @staticmethod
    def _identity_counts(boms, *, excluded_bom_ids):
        unresolved = 0
        mismatches = 0
        for bom in boms:
            if bom.pk in excluded_bom_ids:
                continue
            for section in bom.sections.all():
                if section.title.strip() not in PURCHASABLE_SECTION_TITLES:
                    continue
                for line in section.lines.all():
                    material, _ = resolve_bom_line_raw_material(line)
                    if material is None:
                        unresolved += 1
                        continue
                    source_unit = (line.unit or "").strip()
                    if source_unit not in {
                        material.unit.unit_name.strip(),
                        material.unit.unit_code.strip(),
                    }:
                        mismatches += 1
        return unresolved, mismatches

    @classmethod
    def _report(cls, boms, orders, advanced_order_ids):
        advanced_bom_ids = set(
            PurchaseOrder.objects.filter(pk__in=advanced_order_ids)
            .values_list("lines__bom_id", flat=True)
        )
        safe_unresolved, safe_mismatches = cls._identity_counts(
            boms,
            excluded_bom_ids=advanced_bom_ids,
        )
        advanced_unresolved, advanced_mismatches = cls._identity_counts(
            [bom for bom in boms if bom.pk in advanced_bom_ids],
            excluded_bom_ids=set(),
        )
        return {
            "bom_count": len(boms),
            "purchase_order_count": len(orders),
            "advanced_purchase_orders": [
                {
                    "id": str(order.pk),
                    "order_number": order.order_number,
                    "status": order.status,
                }
                for order in orders
                if order.pk in advanced_order_ids
            ],
            "safe_unresolved_line_count": safe_unresolved,
            "safe_unit_mismatch_count": safe_mismatches,
            "advanced_unresolved_line_count": advanced_unresolved,
            "advanced_unit_mismatch_count": advanced_mismatches,
        }

    @staticmethod
    def _write_report(report, report_path):
        report_path = report_path.strip()
        if not report_path:
            return
        path = Path(report_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(path)
