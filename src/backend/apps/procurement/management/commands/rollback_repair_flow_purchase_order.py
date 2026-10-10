import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.boms.api.serializers import BomUpdateInputSerializer
from apps.boms.management.commands.repair_flow_bom_material_identities import (
    Command as BomIdentityRepairCommand,
)
from apps.boms.models import Bom
from apps.boms.services import update_bom_lines, verify_bom
from apps.boms.simulation_data import (
    build_bom_simulation_sections,
    load_bom_simulation_catalog,
)
from apps.core.audit import write_audit_log
from apps.core.database_backup import validate_database_backup
from apps.inventory.models import (
    MaterialInbound,
    MaterialInboundLine,
    MaterialInboundStatus,
    MaterialStockMovement,
)
from apps.procurement.models import (
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseRequestAllocation,
    PurchaseReturn,
    SupplierPurchaseSheet,
    SupplierPurchaseSheetStatus,
)
from apps.products.material_identity import resolve_bom_line_raw_material


TARGET_PURCHASE_ORDER_ID = "7c957cbc-b8ba-4f94-94f2-a1f7d089b7de"
TARGET_PURCHASE_ORDER_NUMBER = "CGDD2026091750"
CONFIRM_TOKEN = "ROLLBACK-REPAIR-CGDD2026091750-20260917"
PRODUCT_NUMBER_PREFIX = "FLOW260917-P"
PURCHASABLE_SECTION_TITLES = {
    "管材类",
    "五金件",
    "塑料件类",
    "辅料类",
    "面料类",
    "包材类",
}


class Command(BaseCommand):
    help = "回退并修复指定流程模拟采购订单；仅限 CGDD2026091750。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm-token", default="")
        parser.add_argument("--backup-path", default="")
        parser.add_argument("--backup-attestation-path", default="")
        parser.add_argument("--report", default="")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("仅允许在 DEBUG 开发环境修复流程模拟数据。")

        preflight = self._preflight()
        if not options["apply"] or options["confirm_token"] != CONFIRM_TOKEN:
            self.stdout.write(
                json.dumps(
                    {"mode": "DRY_RUN", "preflight": preflight},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f"执行写入需传入 --apply --confirm-token {CONFIRM_TOKEN}"
                )
            )
            return

        try:
            backup_attestation = validate_database_backup(
                options["backup_path"],
                options["backup_attestation_path"],
            )
        except ValueError as exc:
            raise CommandError(f"数据库备份验证失败：{exc} 禁止执行回退。") from exc

        catalog = load_bom_simulation_catalog()
        with transaction.atomic():
            order = (
                PurchaseOrder.objects.select_for_update(of=("self",))
                .select_related("production_task", "created_by_employee")
                .get(pk=TARGET_PURCHASE_ORDER_ID, archived_at__isnull=True)
            )
            self._assert_order_identity(order)
            actor = order.created_by_employee
            if actor is None:
                raise CommandError("目标采购订单缺少创建员工，事务已回滚。")

            bom_ids = list(
                order.lines.order_by()
                .values_list("bom_id", flat=True)
                .distinct()
            )
            if len(bom_ids) != 1 or bom_ids[0] is None:
                raise CommandError("目标采购订单未唯一关联一份 BOM，事务已回滚。")
            bom = (
                Bom.objects.select_for_update(of=("self",))
                .select_related("production_task", "created_by_employee")
                .prefetch_related("sections__lines")
                .get(pk=bom_ids[0], archived_at__isnull=True)
            )

            inbound_ids = list(
                MaterialInbound.objects.filter(purchase_order=order)
                .order_by("id")
                .values_list("id", flat=True)
            )
            inbounds = list(
                MaterialInbound.objects.select_for_update(of=("self",))
                .filter(pk__in=inbound_ids)
                .order_by("id")
            )
            inbound_line_ids = list(
                MaterialInboundLine.objects.filter(inbound_id__in=inbound_ids)
                .order_by("id")
                .values_list("id", flat=True)
            )
            inbound_lines = list(
                MaterialInboundLine.objects.select_for_update(of=("self",))
                .filter(pk__in=inbound_line_ids)
                .order_by("id")
            )
            sheet_ids = list(
                SupplierPurchaseSheet.objects.filter(purchase_order=order)
                .order_by("id")
                .values_list("id", flat=True)
            )
            sheets = list(
                SupplierPurchaseSheet.objects.select_for_update(of=("self",))
                .filter(pk__in=sheet_ids)
                .order_by("id")
            )

            self._assert_locked_dependencies(
                order=order,
                inbounds=inbounds,
                inbound_lines=inbound_lines,
                sheets=sheets,
            )

            inbound_snapshots = [self._inbound_snapshot(item) for item in inbounds]
            for inbound, snapshot in zip(inbounds, inbound_snapshots, strict=True):
                write_audit_log(
                    object_type="MATERIAL_INBOUND",
                    object_id=inbound.pk,
                    context_type="PURCHASE_ORDER",
                    context_id=order.pk,
                    action="TEST_DATA_ROLLBACK",
                    actor_employee=actor,
                    before_data=snapshot,
                    after_data={"deleted": True, "reason": "稳定原料身份修复前回退待检入库"},
                )
            if inbound_line_ids:
                MaterialInboundLine.objects.filter(pk__in=inbound_line_ids).delete()
            if inbound_ids:
                MaterialInbound.objects.filter(pk__in=inbound_ids).delete()

            archived_at = timezone.now()
            sheet_snapshots = []
            for sheet in sheets:
                before = self._sheet_snapshot(sheet)
                sheet_snapshots.append(before)
                sheet.is_current = False
                sheet.archived_at = archived_at
                sheet.archived_by_employee = actor
                sheet.archive_reason = "稳定原料身份修复前回退已发布测试采购表"
                sheet.updated_by_employee = actor
                sheet.save(
                    update_fields=[
                        "is_current",
                        "archived_at",
                        "archived_by_employee",
                        "archive_reason",
                        "updated_by_employee",
                        "updated_at",
                    ]
                )
                write_audit_log(
                    object_type="SUPPLIER_PURCHASE_SHEET",
                    object_id=sheet.pk,
                    context_type="PURCHASE_ORDER",
                    context_id=order.pk,
                    action="ARCHIVED_FOR_TEST_DATA_REPAIR",
                    actor_employee=actor,
                    before_data=before,
                    after_data=self._sheet_snapshot(sheet),
                )

            bom_index = self._flow_bom_index(bom)
            desired_sections = build_bom_simulation_sections(
                bom=bom,
                index=bom_index,
                catalog=catalog,
            )
            BomIdentityRepairCommand._attach_existing_ids(bom, desired_sections)
            serializer = BomUpdateInputSerializer(
                data={"sections": desired_sections},
                context={"bom": bom},
            )
            serializer.is_valid(raise_exception=True)
            updated_bom = update_bom_lines(
                bom=bom,
                sections=serializer.validated_data["sections"],
                actor_employee=actor,
                request=_EtagRequest(bom),
            )
            verify_bom(
                bom=updated_bom,
                quantity_confirmation_reason="回退测试下游数据后修复稳定库存原料 ID。",
                actor_employee=actor,
                request=_EtagRequest(updated_bom),
            )

            order.status = PurchaseOrderStatus.DRAFT
            order.completed_at = None
            order.completed_by_employee = None
            order.completion_remark = ""
            order.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "completed_by_employee",
                    "completion_remark",
                    "updated_at",
                ]
            )
            BomIdentityRepairCommand._sync_draft_purchase_order(order)
            order.refresh_from_db()
            write_audit_log(
                object_type="PURCHASE_ORDER",
                object_id=order.pk,
                context_type="PRODUCTION_TASK",
                context_id=order.production_task_id,
                action="RESET_TO_DRAFT_FOR_TEST_DATA_REPAIR",
                actor_employee=actor,
                before_data={
                    "status": preflight["order_status"],
                    "active_supplier_sheet_count": preflight["active_supplier_sheet_count"],
                    "material_inbound_count": preflight["material_inbound_count"],
                },
                after_data={
                    "status": order.status,
                    "active_supplier_sheet_count": 0,
                    "material_inbound_count": 0,
                },
            )

            postflight = self._postflight(order, bom)
            if any(
                [
                    postflight["active_supplier_sheet_count"],
                    postflight["material_inbound_count"],
                    postflight["unresolved_identity_count"],
                    postflight["unit_mismatch_count"],
                ]
            ) or postflight["order_status"] != PurchaseOrderStatus.DRAFT:
                raise CommandError(f"回退后校验未通过，事务已回滚：{postflight}")

        result = {
            "mode": "APPLIED",
            "generated_at": timezone.now().isoformat(),
            "purchase_order_id": TARGET_PURCHASE_ORDER_ID,
            "purchase_order_number": TARGET_PURCHASE_ORDER_NUMBER,
            "backup_sha256": backup_attestation["backup_sha256"],
            "deleted_pending_inbound_count": len(inbound_snapshots),
            "deleted_pending_inbound_line_count": len(inbound_line_ids),
            "archived_published_sheet_count": len(sheet_snapshots),
            "preserved_pdf_count": sum(1 for item in sheet_snapshots if item["pdf_file_id"]),
            "postflight": postflight,
        }
        self._write_report(result, options["report"])
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        self.stdout.write(self.style.SUCCESS("目标测试采购订单已安全回退并修复。"))

    @staticmethod
    def _assert_order_identity(order):
        if str(order.pk) != TARGET_PURCHASE_ORDER_ID or order.order_number != TARGET_PURCHASE_ORDER_NUMBER:
            raise CommandError("目标采购订单身份不匹配，禁止执行。")
        if order.status != PurchaseOrderStatus.PURCHASING:
            raise CommandError(f"目标采购订单状态应为采购中，实际为 {order.status}。")

    @classmethod
    def _preflight(cls):
        try:
            order = PurchaseOrder.objects.get(
                pk=TARGET_PURCHASE_ORDER_ID,
                archived_at__isnull=True,
            )
        except PurchaseOrder.DoesNotExist as exc:
            raise CommandError("目标采购订单不存在。") from exc
        cls._assert_order_identity(order)
        inbounds = list(MaterialInbound.objects.filter(purchase_order=order).order_by("id"))
        inbound_line_ids = list(
            MaterialInboundLine.objects.filter(inbound__in=inbounds).values_list("id", flat=True)
        )
        sheets = list(SupplierPurchaseSheet.objects.filter(purchase_order=order).order_by("id"))
        cls._assert_locked_dependencies(
            order=order,
            inbounds=inbounds,
            inbound_lines=list(MaterialInboundLine.objects.filter(pk__in=inbound_line_ids)),
            sheets=sheets,
        )
        return {
            "purchase_order_id": str(order.pk),
            "purchase_order_number": order.order_number,
            "order_status": order.status,
            "active_supplier_sheet_count": sum(
                1 for item in sheets if item.archived_at is None and item.is_current
            ),
            "published_supplier_sheet_count": sum(
                1 for item in sheets if item.status == SupplierPurchaseSheetStatus.PUBLISHED
            ),
            "preserved_pdf_count": sum(1 for item in sheets if item.pdf_file_id),
            "material_inbound_count": len(inbounds),
            "material_inbound_line_count": len(inbound_line_ids),
            "stock_movement_count": 0,
            "purchase_return_count": 0,
            "purchase_request_allocation_count": 0,
        }

    @staticmethod
    def _assert_locked_dependencies(*, order, inbounds, inbound_lines, sheets):
        from apps.inventory.models import PublicStockMovement
        if len(inbounds) != 1 or inbounds[0].status != MaterialInboundStatus.PENDING_QUALITY:
            raise CommandError("目标采购订单必须且只能有 1 张待质检入库单。")
        inbound_ids = [item.pk for item in inbounds]
        inbound_line_ids = [item.pk for item in inbound_lines]
        if any(inbound.stock_mode != "LEGACY" for inbound in inbounds):
            raise CommandError("公共库存入库不适用旧采购回退工具，须先完成接续核验。")
        if (PublicStockMovement.objects.filter(source_type="MATERIAL_INBOUND", source_id__in=inbound_ids).exists()
                or PublicStockMovement.objects.filter(source_type="MATERIAL_INBOUND", source_line_id__in=inbound_line_ids).exists()):
            raise CommandError("待检入库已形成公共库存流水，禁止执行自动回退。")
        if not inbound_line_ids:
            raise CommandError("待质检入库单没有明细，禁止执行自动回退。")
        if PurchaseReturn.objects.filter(inbound_id__in=inbound_ids).exists():
            raise CommandError("待检入库已生成退货单，禁止执行自动回退。")
        if MaterialStockMovement.objects.filter(
            source_type="MATERIAL_INBOUND",
            source_id__in=inbound_ids,
        ).exists():
            raise CommandError("待检入库已形成库存流水，禁止执行自动回退。")
        if MaterialStockMovement.objects.filter(
            source_type="MATERIAL_INBOUND",
            source_line_id__in=inbound_line_ids,
        ).exists():
            raise CommandError("待检入库明细已形成库存流水，禁止执行自动回退。")
        if len(sheets) != 6 or any(
            sheet.archived_at is not None
            or not sheet.is_current
            or sheet.status != SupplierPurchaseSheetStatus.PUBLISHED
            for sheet in sheets
        ):
            raise CommandError("目标采购订单必须且只能有 6 张当前有效的已发布采购表。")
        if PurchaseRequestAllocation.objects.filter(
            supplier_purchase_sheet__in=sheets
        ).exists():
            raise CommandError("采购表已关联采购申请分配，禁止执行自动回退。")
        if order.returns.exists():
            raise CommandError("目标采购订单已生成退货单，禁止执行自动回退。")

    @staticmethod
    def _flow_bom_index(target_bom):
        boms = list(
            Bom.objects.filter(
                product_number_snapshot__startswith=PRODUCT_NUMBER_PREFIX,
                archived_at__isnull=True,
            ).order_by("created_at", "id")
        )
        if len(boms) != 60:
            raise CommandError(f"流程模拟 BOM 应为 60 份，实际为 {len(boms)} 份。")
        try:
            return [item.pk for item in boms].index(target_bom.pk) + 1
        except ValueError as exc:
            raise CommandError("目标采购订单关联的 BOM 不属于本次流程模拟数据。") from exc

    @staticmethod
    def _inbound_snapshot(inbound):
        return {
            "id": str(inbound.pk),
            "inbound_number": inbound.inbound_number,
            "status": inbound.status,
            "line_count": inbound.lines.count(),
        }

    @staticmethod
    def _sheet_snapshot(sheet):
        return {
            "id": str(sheet.pk),
            "sheet_number": sheet.sheet_number,
            "version_number": sheet.version_number,
            "status": sheet.status,
            "is_current": sheet.is_current,
            "archived_at": sheet.archived_at,
            "pdf_file_id": str(sheet.pdf_file_id) if sheet.pdf_file_id else None,
        }

    @classmethod
    def _postflight(cls, order, bom):
        unresolved = 0
        unit_mismatches = 0
        bom.refresh_from_db()
        for section in bom.sections.prefetch_related("lines").all():
            if section.title.strip() not in PURCHASABLE_SECTION_TITLES:
                continue
            for line in section.lines.all():
                material, _ = resolve_bom_line_raw_material(line)
                if material is None:
                    unresolved += 1
                    continue
                if (line.unit or "").strip() not in {
                    material.unit.unit_name.strip(),
                    material.unit.unit_code.strip(),
                }:
                    unit_mismatches += 1
        order.refresh_from_db()
        return {
            "order_status": order.status,
            "active_supplier_sheet_count": SupplierPurchaseSheet.objects.filter(
                purchase_order=order,
                archived_at__isnull=True,
                is_current=True,
            ).count(),
            "archived_supplier_sheet_count": SupplierPurchaseSheet.objects.filter(
                purchase_order=order,
                archived_at__isnull=False,
            ).count(),
            "material_inbound_count": MaterialInbound.objects.filter(
                purchase_order=order
            ).count(),
            "unresolved_identity_count": unresolved,
            "unit_mismatch_count": unit_mismatches,
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


class _EtagRequest:
    def __init__(self, instance):
        from apps.core.api.concurrency import etag_for_instance

        self.headers = {"If-Match": etag_for_instance(instance)}
        self.META = {}
        self.request_id = None
