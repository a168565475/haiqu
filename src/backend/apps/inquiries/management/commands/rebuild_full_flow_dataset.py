import hashlib
import json
import re
import uuid
import zipfile
from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count, F, ProtectedError, Q
from django.utils import timezone

from apps.boms.models import Bom, BomCreationMethod, BomSectionType, BomStatus
from apps.boms.api.serializers import BomUpdateInputSerializer
from apps.boms.workbook_import import BomWorkbookError, parse_bom_workbook
from apps.boms.simulation_data import (
    build_bom_simulation_sections,
    load_bom_simulation_catalog,
    summarize_bom_simulation_sections,
)
from apps.boms.services import create_bom, update_bom_lines, verify_bom
from apps.core.api.concurrency import etag_for_instance
from apps.core.database_backup import backup_sha256, validate_database_backup
from apps.customers.models import (
    ContactStatus,
    CustomerAccount,
    CustomerContact,
    CustomerEntityAddress,
    CustomerTransactionEntity,
)
from apps.files.models import BusinessFile
from apps.files.uploads import save_scanned_image
from apps.inventory.models import (
    MaterialInbound,
    MaterialInboundStatus,
    Warehouse,
    WarehouseLocation,
    WarehouseType,
    WarehouseZone,
)
from apps.inventory.services import create_material_inbound, confirm_material_quality
from apps.inquiries.models import Inquiry, InquiryFileLink, InquiryStatus, format_inquiry_item_specification
from apps.inquiries.services import create_inquiry, link_inquiry_file, transition_inquiry
from apps.organizations.models import Employee, EmployeeStatus
from apps.procurement.models import (
    PurchaseContractTemplateVersion,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SupplierPurchaseSheet,
    Supplier,
)
from apps.procurement.purchase_sheet_services import (
    generate_supplier_purchase_sheets,
    publish_supplier_purchase_sheet,
)
from apps.procurement.services import (
    confirm_purchase_order,
    create_purchase_order,
    evaluate_purchase_source,
)
from apps.production_tasks.api.serializers import ProductionTaskCreateFromSalesOrderSerializer
from apps.production_tasks.models import ProductionTask, ProductionTaskStatus
from apps.production_tasks.services import (
    create_production_order_from_sales_order,
    decide_production_order_by_pmc,
    submit_production_task,
)
from apps.products.models import ProductInformation, ProductScale, ProductStatus
from apps.quotations.models import (
    Quotation,
    QuotationAcceptanceSource,
    QuotationLinePrice,
    QuotationOutcomeStatus,
    QuotationPriceBasis,
    QuotationVersionStatus,
)
from apps.quotations.services import (
    confirm_manual_dispatch,
    create_quotation_from_inquiry,
    issue_version,
    lock_version,
    set_line_product_image,
    transition_quotation,
    update_line,
)
from apps.reference_data.models import Currency, ProductCategory, ProductItem, ReferenceStatus
from apps.sales_orders.api.serializers import SalesOrderWriteSerializer
from apps.sales_orders.models import CustomerConfirmationMethod, SalesOrder, SalesOrderSource
from apps.sales_orders.services import confirm_sales_order, create_sales_order
from apps.samples.models import SampleRequest, SampleType
from apps.samples.services import create_sample_from_quotation_version
from apps.workflow.models import ApprovalRequest, BusinessTask, SlaTracking


CONFIRM_TOKEN = "RESET-AND-SEED-FLOW-20261003"
DATASET_MARKER = "FLOW-20261003"
PRODUCT_NUMBER_PREFIX = "FLOW261003-P"

# 本批验收数据的业务终点由用户确认：
# 询盘 100 -> 报价 100 -> 销售订单 100；其中 80 条进入生产，70 条完成 BOM
# 并生成采购订单。样品不参与本批造数，避免把未确认的样品资料写入交易库。
EXPECTED_COUNTS = {
    "inquiries": 100,
    "quotations": 100,
    "samples": 0,
    "sales_orders": 100,
    "production_tasks": 80,
    "verified_boms": 70,
    "purchase_orders": 70,
    "material_inbounds": 70,
}
TARGET_PURCHASE_ORDER_STATUS = PurchaseOrderStatus.PURCHASING

# 仅列出用户要求清理的交易表。客户、产品、供应商、仓库、委外工厂、报价模板等主数据不在此范围。
RESET_TABLES = [
    "inquiry",
    "inquiry_item",
    "inquiry_draft_revision",
    "inquiry_task_link",
    "inquiry_sla_link",
    "inquiry_assignment_history",
    "inquiry_file_link",
    "quotation",
    "quotation_version",
    "quotation_line",
    "quotation_price_basis",
    "quotation_line_price",
    "quotation_line_packaging",
    "quotation_container_tier",
    "quotation_quantity_tier",
    "quotation_document",
    "quotation_dispatch_record",
    "quotation_email_dispatch_attempt",
    "quotation_acceptance",
    "quotation_version_task_link",
    "quotation_version_sla_link",
    "quotation_version_approval_link",
    "quotation_file_link",
    "sample_request",
    "sample_material_request",
    "sample_material_procurement_request",
    "sample_material_purchase_source",
    "sample_material_arrival",
    "sample_collaborator",
    "sample_product",
    "sample_product_sampling_detail",
    "sample_item",
    "sample_workflow_record",
    "sample_fee_record",
    "sample_shipment",
    "sample_shipment_event",
    "sample_shipment_item",
    "sample_feedback",
    "sample_task_link",
    "sample_sla_link",
    "sample_approval_link",
    "sample_file_link",
    "sample_inventory_receipt",
    "sample_inventory_line",
    "sample_inventory_outbound",
    "sample_inventory_outbound_line",
    "sample_inventory_loan",
    "sample_inventory_loan_line",
    "sales_order",
    "sales_order_line",
    "sales_order_delivery_batch",
    "sales_order_delivery_batch_line",
    "sales_order_evidence",
    "sales_order_price_exception",
    "sales_order_version",
    "sales_order_collaboration_event",
    "production_task",
    "production_task_follower",
    "production_task_product",
    "production_task_product_image",
    "production_task_detail",
    "production_delivery_batch",
    "production_run_batch",
    "bom",
    "bom_section",
    "bom_line",
    "bom_line_image",
    "bom_line_image_draft",
    "production_schedule",
    "production_schedule_product",
    "production_schedule_product_craft",
    "outsourcing_order",
    "outsourcing_order_product",
    "outsourcing_processing_item",
    "outsourcing_factory_allocation",
    "outsourcing_material_item",
    "outsourcing_dispatch",
    "outsourcing_dispatch_line",
    "outsourcing_return",
    "outsourcing_return_line",
    "procurement_purchase_order",
    "procurement_purchase_return",
    "procurement_purchase_return_line",
    "procurement_purchase_order_line",
    "purchase_request",
    "purchase_request_line",
    "purchase_request_allocation",
    "procurement_supplier_purchase_sheet",
    "procurement_supplier_purchase_sheet_line_image",
    "procurement_supplier_purchase_sheet_seal_image",
    "inventory_finished_goods_receipt",
    "inventory_finished_goods_outbound",
    "inventory_finished_goods_outbound_line",
    "inventory_material_inbound",
    "inventory_material_inbound_line",
    "inventory_material_stock_balance",
    "inventory_material_stock_movement",
    "inventory_semi_finished_stock_balance",
    "inventory_semi_finished_stock_movement",
    "material_issue_order_requirement",
    "material_issue_requirement_contribution",
    "material_issue",
    "material_issue_line",
    "material_issue_audit_event",
    # 后续生产/委外/内部入库功能新增的交易关联表；这些记录引用本次清理的
    # 生产任务、BOM、采购入库或领料单，必须在同一事务内清理，不能留下悬挂外键。
    "inventory_assembly_receipt_source",
    "inventory_internal_semi_receipt",
    "inventory_internal_semi_receipt_line",
    "inventory_public_stock_movement",
    "material_issue_batch_allocation",
    "material_issue_public_stock_allocation",
    "metal_processing_original_handoff",
    "metal_processing_source",
    "order_semi_finished_requirement",
    "outsourcing_raw_return",
    "outsourcing_raw_return_line",
    "outsourcing_reconciliation",
    "outsourcing_reconciliation_entry",
    "sample_material_issue",
    "sample_parameter_image",
    "tube_outsourcing_line",
    "tube_outsourcing_order",
    "workshop_plan_execution",
    "workshop_wage_scheme",
    "workshop_work_item",
    "workshop_work_report",
    "metal_original_handoff_public_transition",
    "metal_processing_closure",
    "metal_processing_completion",
    "metal_processing_external_good_return",
    "metal_processing_external_order",
    "metal_processing_external_closure",
    "metal_processing_external_handoff",
    "metal_processing_rework",
    "metal_processing_unsprayed_return",
    "sample_material_issue_line",
    "tube_outsourcing_action",
    "tube_outsourcing_receipt",
    "tube_outsourcing_receipt_line",
    "workshop_wage_scheme_craft",
    "workshop_wage_scheme_event",
    "workshop_wage_scheme_line",
    "workshop_work_report_line",
]

ALLOWED_EXTERNAL_DEPENDENCIES = {
    "communication_inquiry_link",
    "communication_quotation_version_link",
    "communication_sample_request_link",
}

# 排产表正常业务禁止物理删除。仅本命令在已备份、单事务重建期间临时停用这些指定触发器；
# 成功路径会立即恢复，失败路径由 PostgreSQL 事务回滚恢复。
RESET_GUARDED_TRIGGERS = [
    ("production_schedule_product_craft", "ps_schedule_craft_no_delete"),
    ("production_schedule_product", "ps_schedule_product_no_delete"),
    ("production_schedule", "ps_schedule_no_delete"),
    ("production_task_product", "ps_source_product_guard"),
]


def _etag_request(instance):
    return SimpleNamespace(headers={"If-Match": etag_for_instance(instance)}, META={})


def _product_name(path):
    stem = path.stem
    return stem.split("-", 1)[1] if "-" in stem else stem


class Command(BaseCommand):
    help = "清理指定交易数据，并按真实业务服务重建询盘到采购订单的模拟数据。默认只预检。"

    def add_arguments(self, parser):
        parser.add_argument("--image-dir", required=True, help="包含30张产品设计PNG的目录。")
        parser.add_argument(
            "--reference-workbook",
            dest="reference_workbooks",
            action="append",
            required=True,
            help="生产任务单参考文件路径；必须重复传入5份 XLS/XLSX 文件。",
        )
        parser.add_argument("--backup-path", help="执行写入前已验证的数据库备份文件路径。")
        parser.add_argument(
            "--backup-attestation-path",
            help="外部 pg_restore --list 与恢复演练完成后生成的备份验证 JSON。",
        )
        parser.add_argument("--media-backup-path", help="执行写入前保存交易附件的ZIP备份路径。")
        parser.add_argument("--media-root", help="可选的独立媒体目录，仅用于隔离数据库演练。")
        parser.add_argument("--apply", action="store_true", help="执行真实删除与写入。")
        parser.add_argument("--confirm", help=f"写入时必须传入 {CONFIRM_TOKEN}。")
        parser.add_argument("--report", help="JSON验收报告输出路径。")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("仅允许在 DEBUG 开发环境执行交易数据重建。")

        if options.get("media_root"):
            isolated_media_root = Path(options["media_root"]).resolve()
            isolated_media_root.mkdir(parents=True, exist_ok=True)
            settings.MEDIA_ROOT = isolated_media_root

        started_at = perf_counter()
        image_dir = Path(options["image_dir"]).resolve()
        image_paths = sorted(image_dir.glob("*.png"))
        reference_workbook_paths = [Path(item).resolve() for item in options["reference_workbooks"]]
        dependencies = self._validate_dependencies(
            image_dir,
            image_paths,
            reference_workbook_paths,
        )
        preflight = self._preflight_summary(dependencies, image_paths)

        if not options["apply"]:
            self.stdout.write(json.dumps(preflight, ensure_ascii=False, indent=2, default=str))
            self.stdout.write(self.style.SUCCESS(
                f"预检通过；写入需追加 --apply --confirm {CONFIRM_TOKEN}，并提供已验证的 "
                "--backup-path 与 --media-backup-path。"
            ))
            return

        if options.get("confirm") != CONFIRM_TOKEN:
            raise CommandError(f"请明确追加 --confirm {CONFIRM_TOKEN}。")
        try:
            backup_path = Path(options.get("backup_path") or "").resolve()
            backup_attestation = validate_database_backup(
                backup_path,
                options.get("backup_attestation_path") or "",
            )
        except ValueError as exc:
            raise CommandError(f"数据库备份验证失败：{exc} 禁止执行删除。") from exc
        actual_backup_sha256 = backup_sha256(backup_path)
        media_backup_path = Path(options.get("media_backup_path") or "").resolve()
        if not options.get("media_backup_path"):
            raise CommandError("缺少 --media-backup-path；数据库备份不能恢复媒体附件，禁止执行删除。")
        media_root = Path(settings.MEDIA_ROOT).resolve()
        if media_backup_path == media_root or media_root in media_backup_path.parents:
            raise CommandError("媒体备份必须放在 MEDIA_ROOT 之外，避免随附件清理一起删除。")
        if not options.get("report"):
            raise CommandError("写入模式必须提供 --report；用于持久化数据库提交与媒体清理结果。")

        created_storage_paths = []
        deleted_storage_paths = []
        stage_seconds = {}
        issues = []
        cleanup_summary = {}
        try:
            with transaction.atomic():
                stage_started = perf_counter()
                cleanup_summary, deleted_storage_paths = self._clear_transaction_data(media_backup_path)
                stage_seconds["cleanup"] = round(perf_counter() - stage_started, 3)

                stage_started = perf_counter()
                dataset = self._create_dataset(
                    dependencies=dependencies,
                    image_paths=image_paths,
                    created_storage_paths=created_storage_paths,
                    issues=issues,
                    stage_seconds=stage_seconds,
                )
                stage_seconds["seed_total"] = round(perf_counter() - stage_started, 3)

                report = self._build_report(
                    preflight=preflight,
                    cleanup_summary=cleanup_summary,
                    dataset=dataset,
                    image_paths=image_paths,
                    backup_path=backup_path,
                    backup_sha256=actual_backup_sha256,
                    backup_attestation=backup_attestation,
                    issues=issues,
                    stage_seconds=stage_seconds,
                    total_seconds=round(perf_counter() - started_at, 3),
                )
                if not report["checks"]["all_passed"]:
                    raise CommandError("写入后完整性验收未通过，数据库事务已回滚。")
        except Exception:
            for storage_path in created_storage_paths:
                try:
                    storage_path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    self.stderr.write(f"回滚后临时附件清理失败：{storage_path}：{cleanup_error}")
            raise

        media_cleanup_failures = []
        removed_file_count = 0
        for storage_path in deleted_storage_paths:
            try:
                storage_path.unlink(missing_ok=True)
                removed_file_count += 1
            except OSError as cleanup_error:
                media_cleanup_failures.append({
                    "path": str(storage_path),
                    "error": str(cleanup_error),
                })
        report["database_committed"] = True
        report["media_cleanup"] = {
            "requested_file_count": len(deleted_storage_paths),
            "removed_file_count": removed_file_count,
            "failures": media_cleanup_failures,
            "backup": cleanup_summary["media_backup"],
        }
        report["checks"]["media_cleanup_complete"] = not media_cleanup_failures
        report["checks"]["all_passed"] = all(
            value for key, value in report["checks"].items() if key != "all_passed"
        )
        try:
            self._write_report(options.get("report"), report)
        except OSError as report_error:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            raise CommandError(
                f"数据库已提交，但验收报告写入失败：{report_error}。完整报告已输出到标准输出；"
                "禁止重跑数据重建命令。"
            ) from report_error
        if media_cleanup_failures:
            raise CommandError(
                f"数据库已提交，但有 {len(media_cleanup_failures)} 个旧附件清理失败。"
                f"失败路径已写入 {options['report']}；禁止重跑数据重建命令，"
                "请仅按 media_cleanup.failures 重试文件清理。"
            )
        self.stdout.write(self.style.SUCCESS(
            "真实流程数据重建完成：询盘100、报价100、样品申请0、销售订单100、"
            "生产订单80、已确认BOM 70、采购订单70、已确认材料入库70。"
        ))

    def _validate_dependencies(self, image_dir, image_paths, reference_workbook_paths):
        if not image_dir.is_dir():
            raise CommandError(f"图片目录不存在：{image_dir}")
        if len(image_paths) != 30:
            raise CommandError(f"图片目录必须恰好包含30张PNG，当前为 {len(image_paths)} 张。")
        for image_path in image_paths:
            size = image_path.stat().st_size
            if size <= 0 or size > 5 * 1024 * 1024:
                raise CommandError(f"图片大小不合法：{image_path.name}（{size}字节）。")
            if image_path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                raise CommandError(f"PNG文件签名不正确：{image_path.name}")

        if len(reference_workbook_paths) != 5:
            raise CommandError(
                f"生产任务单参考文件必须恰好传入5份，当前为 {len(reference_workbook_paths)} 份。"
            )
        reference_variants = self._load_reference_variants(reference_workbook_paths)
        if len(reference_variants) < 3:
            raise CommandError("生产任务单至少要解析出3个产品变体，不能继续造数。")

        customers = list(
            CustomerAccount.objects.filter(archived_at__isnull=True)
            .order_by("account_code", "id")
        )
        if not customers:
            raise CommandError("没有有效客户，无法创建询盘。")
        if len(customers) > EXPECTED_COUNTS["inquiries"]:
            raise CommandError(
                f"有效客户有 {len(customers)} 个，超过100条询盘，无法满足每个客户至少一条。"
            )

        contexts = {}
        for customer in customers:
            entity = (
                customer.transaction_entities.filter(
                    archived_at__isnull=True,
                    addresses__isnull=False,
                    addresses__archived_at__isnull=True,
                )
                .prefetch_related("addresses")
                .distinct()
                .order_by("entity_code", "id")
                .first()
            )
            address = (
                entity.addresses.filter(archived_at__isnull=True)
                .order_by("address_code", "id")
                .first()
                if entity else None
            )
            contact = (
                customer.contacts.filter(
                    status=ContactStatus.ACTIVE,
                    archived_at__isnull=True,
                )
                .order_by("-is_primary_contact", "display_name", "id")
                .first()
            )
            if entity and address and contact:
                contexts[customer.pk] = {
                    "entity": entity,
                    "address": address,
                    "contact": contact,
                }
        employees = list(
            Employee.objects.filter(status=EmployeeStatus.ACTIVE, archived_at__isnull=True)
            .select_related("user")
            .order_by("employee_code", "id")
        )
        if len(employees) < 3:
            raise CommandError("至少需要3名有效员工用于业务、跟单和计划角色。")
        actor = next((employee for employee in employees if employee.user_id and employee.user.is_superuser), employees[0])

        reference_product = (
            ProductInformation.objects.filter(
                status=ProductStatus.ACTIVE,
                archived_at__isnull=True,
                category__archived_at__isnull=True,
                unit__archived_at__isnull=True,
                product_item__archived_at__isnull=True,
            )
            .select_related("category", "unit", "product_item")
            .order_by("product_number", "id")
            .first()
        )
        if reference_product is None:
            raise CommandError("缺少可复用的有效产品类别、单位和产品项目。")
        product_categories = {
            name: ProductCategory.objects.filter(
                category_name=name,
                item_type="FINISHED",
                status=ReferenceStatus.ACTIVE,
                archived_at__isnull=True,
            ).order_by("id").first()
            for name in {variant["display_name"] for variant in reference_variants}
        }
        missing_categories = [name for name, category in product_categories.items() if category is None]
        if missing_categories:
            raise CommandError(
                f"产品主数据缺少已确认品类：{'、'.join(sorted(missing_categories))}，禁止使用其他品类替代。"
            )
        product_items = {}
        for name, category in product_categories.items():
            product_items[name] = ProductItem.objects.filter(
                category=category,
                status=ReferenceStatus.ACTIVE,
                archived_at__isnull=True,
            ).order_by("sort_order", "item_number", "id").first()
            if product_items[name] is None:
                raise CommandError(f"产品品类“{name}”没有可用货号主数据，禁止继续造数。")

        cny = Currency.objects.filter(
            code="CNY",
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).first()
        if cny is None:
            raise CommandError("缺少有效人民币币种 CNY。")
        suppliers = list(
            Supplier.objects.filter(archived_at__isnull=True, is_disabled=False)
            .order_by("supplier_number", "id")
        )
        if not suppliers:
            raise CommandError("没有有效供应商，无法创建采购订单。")
        purchase_template_versions = self._load_purchase_template_versions()
        material_zones = self._load_material_zones()

        self._validate_reset_foreign_keys()
        return {
            "customers": customers,
            "contexts": contexts,
            "employees": employees,
            "actor": actor,
            "reference_product": reference_product,
            "cny": cny,
            "suppliers": suppliers,
            "reference_variants": reference_variants,
            "product_categories": product_categories,
            "product_items": product_items,
            "purchase_template_versions": purchase_template_versions,
            "material_zones": material_zones,
        }

    @staticmethod
    def _load_material_zones():
        zones = list(
            WarehouseZone.objects.filter(
                status="ACTIVE",
                warehouse__status="ACTIVE",
                warehouse__warehouse_type=WarehouseType.MATERIAL,
            )
            .select_related("warehouse")
            .order_by("warehouse__warehouse_number", "zone_name", "id")
        )
        if not zones:
            raise CommandError("没有可用的材料仓库区，不能生成采购入库。")
        by_category = {}
        for zone in zones:
            warehouse_name = f"{zone.warehouse.warehouse_number} {zone.warehouse.warehouse_name}"
            if "管" in warehouse_name and "管材" not in by_category:
                by_category["管材"] = zone
            if "布" in warehouse_name and "面料" not in by_category:
                by_category["面料"] = zone
            if "五金" in warehouse_name and "五金" not in by_category:
                by_category["五金"] = zone
            if "包材" in warehouse_name and "包材" not in by_category:
                by_category["包材"] = zone
            if "辅料" in warehouse_name and "辅料" not in by_category:
                by_category["辅料"] = zone
        # 塑料件按五金仓收货；若主数据没有单独塑料件仓，不临时创建仓库。
        if "五金" in by_category:
            by_category["塑料件"] = by_category["五金"]
        missing = [category for category in ("管材", "面料", "五金", "塑料件", "包材", "辅料") if category not in by_category]
        if missing:
            raise CommandError(f"缺少可用材料仓库区：{'、'.join(missing)}")
        by_category["_default"] = zones[0]
        return by_category

    @staticmethod
    def _load_purchase_template_versions():
        versions = (
            PurchaseContractTemplateVersion.objects.filter(
                template__status="ACTIVE",
                template__archived_at__isnull=True,
            )
            .select_related("template")
            .order_by("template_id", "-version_number", "-id")
        )
        by_category = {}
        for version in versions:
            for category in version.template.supplier_categories or []:
                by_category.setdefault(category, version)
        return by_category

    def _load_reference_variants(self, reference_workbook_paths):
        """读取用户提供的生产任务单，生成询盘/BOM共用的产品变体清单。

        这里仅读取文件，不写入产品主数据。一个任务单有多个面辅料颜色分区时，
        每个颜色分区作为一个变体；规格、颜色和 BOM 原始明细都保留在内存中，
        后续事务阶段再按本批规则创建交易数据。
        """
        variants = []
        for source_path in reference_workbook_paths:
            try:
                plan = parse_bom_workbook(source_path, source_path.name)
            except (BomWorkbookError, OSError, ValueError) as exc:
                raise CommandError(f"生产任务单无法解析：{source_path.name}：{exc}") from exc
            metadata = plan.get("metadata") or {}
            product_name = str(metadata.get("product_name") or "").strip()
            specification = str(metadata.get("specification") or "").strip()
            if not product_name or not specification:
                raise CommandError(f"生产任务单缺少产品名称或规格：{source_path.name}")
            if "导演椅" in product_name:
                display_name = "沙滩椅"
            elif "扶手椅" in product_name:
                display_name = "扶手椅"
            elif "行军床" in product_name:
                display_name = "行军床"
            else:
                raise CommandError(
                    f"生产任务单产品“{product_name}”不在已确认范围（沙滩椅、扶手椅、行军床）：{source_path.name}"
                )

            fabric_sections = [
                section for section in plan["sections"] if section["section_type"] == "FABRIC"
            ]
            if not fabric_sections:
                raise CommandError(f"生产任务单没有面辅料/颜色分区：{source_path.name}")
            for variant_index, fabric_section in enumerate(fabric_sections, start=1):
                color_text = self._reference_color_text(plan, fabric_section)
                variants.append({
                    "source_path": str(source_path),
                    "source_name": source_path.name,
                    "source_plan": plan,
                    "fabric_section_title": fabric_section["title"],
                    "display_name": display_name,
                    "source_product_name": product_name,
                    "product_code": str(metadata.get("product_code") or "").strip(),
                    "specification": specification,
                    "color": color_text,
                    "variant_key": f"{metadata.get('production_task_number', source_path.stem)}-{variant_index}",
                })
        return variants

    @staticmethod
    def _reference_color_text(plan, fabric_section):
        title = str(fabric_section.get("title") or "").strip()
        # 任务单的颜色通常位于“面辅料清单”之前；若没有颜色标题，使用型材表面的处理颜色。
        for marker in ("-面辅料", " 面辅料", "/面辅料", "-布料", " 布料"):
            if marker in title:
                prefix = title.split(marker, 1)[0].strip(" -/")
                if prefix and re.search(r"(?:颜色|黑|灰|绿|蓝|红|白|黄|棕|紫|银|金|#[0-9])", prefix):
                    return prefix
        for section in plan.get("sections") or []:
            for line in section.get("lines") or []:
                if str(line.get("part_name") or "").strip() in {"塑粉", "表面处理"}:
                    value = str(line.get("specification") or "").strip()
                    if value:
                        return value
        return "未标注颜色"

    def _validate_reset_foreign_keys(self):
        placeholders = ",".join(["%s"] * len(RESET_TABLES))
        sql = f"""
            SELECT child.relname, parent.relname, con.condeferrable
            FROM pg_constraint con
            JOIN pg_class child ON child.oid = con.conrelid
            JOIN pg_class parent ON parent.oid = con.confrelid
            WHERE con.contype = 'f'
              AND parent.relname IN ({placeholders})
              AND child.relname NOT IN ({placeholders})
            ORDER BY child.relname, parent.relname
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [*RESET_TABLES, *RESET_TABLES])
            rows = cursor.fetchall()
        unexpected = [row for row in rows if row[0] not in ALLOWED_EXTERNAL_DEPENDENCIES]
        if unexpected:
            raise CommandError(f"发现未纳入清理范围的外键依赖，禁止删除：{unexpected}")
        non_deferrable = [row for row in rows if not row[2]]
        if non_deferrable:
            raise CommandError(f"外部依赖不是延迟约束，无法安全事务删除：{non_deferrable}")

    def _preflight_summary(self, dependencies, image_paths):
        current_counts = {
            "inquiries": Inquiry.objects.count(),
            "quotations": Quotation.objects.count(),
            "samples": SampleRequest.objects.count(),
            "sales_orders": SalesOrder.objects.count(),
            "production_tasks": ProductionTask.objects.count(),
            "boms": Bom.objects.count(),
            "purchase_orders": PurchaseOrder.objects.count(),
            "material_inbounds": MaterialInbound.objects.count(),
        }
        incomplete = [
            {
                "customer_id": str(customer.pk),
                "account_code": customer.account_code,
                "account_name": customer.account_name,
            }
            for customer in dependencies["customers"]
            if customer.pk not in dependencies["contexts"]
        ]
        missing_contact_count = sum(
            not customer.contacts.filter(
                status=ContactStatus.ACTIVE,
                archived_at__isnull=True,
            ).exists()
            for customer in dependencies["customers"]
        )
        missing_address_count = sum(
            not customer.transaction_entities.filter(
                archived_at__isnull=True,
                addresses__isnull=False,
                addresses__archived_at__isnull=True,
            ).exists()
            for customer in dependencies["customers"]
        )
        missing_entity_count = sum(
            not customer.transaction_entities.filter(archived_at__isnull=True).exists()
            for customer in dependencies["customers"]
        )
        return {
            "dataset": DATASET_MARKER,
            "mode": "preflight",
            "active_customer_count": len(dependencies["customers"]),
            "complete_customer_context_count": len(dependencies["contexts"]),
            "customers_missing_contact_or_transaction_context": incomplete,
            "customer_master_data_to_create": {
                "transaction_entities": missing_entity_count,
                "contacts": missing_contact_count,
                "addresses": missing_address_count,
            },
            "image_count": len(image_paths),
            "image_names": [path.name for path in image_paths],
            "reference_workbooks": [variant["source_name"] for variant in dependencies["reference_variants"]],
            "reference_variants": [
                {
                    "display_name": variant["display_name"],
                    "source_product_name": variant["source_product_name"],
                    "specification": variant["specification"],
                    "color": variant["color"],
                    "source_name": variant["source_name"],
                }
                for variant in dependencies["reference_variants"]
            ],
            "current_counts": current_counts,
            "target_counts": EXPECTED_COUNTS,
            "preserved_master_data": [
                "客户及联系人/交易主体/地址",
                "非 FLOW261003-P 前缀的既有产品主数据",
                "供应商与采购合同模板",
                "仓库/库区/库位",
                "委外工厂与工艺配置",
                "报价模板及其他系统配置",
                "中央不可变审计日志（本次范围内的交易流程事件会随交易清理）",
            ],
        }

    def _collect_cleanup_references(self):
        task_ids = set()
        sla_ids = set()
        approval_ids = set()
        file_ids = set()
        for table in ("inquiry_task_link", "quotation_version_task_link", "sample_task_link"):
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT business_task_id FROM "{table}"')
                task_ids.update(row[0] for row in cursor.fetchall())
        for table in ("inquiry_sla_link", "quotation_version_sla_link", "sample_sla_link"):
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT sla_tracking_id FROM "{table}"')
                sla_ids.update(row[0] for row in cursor.fetchall())
        for table in ("quotation_version_approval_link", "sample_approval_link"):
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT approval_request_id FROM "{table}"')
                approval_ids.update(row[0] for row in cursor.fetchall())

        file_queries = [
            ("inquiry_file_link", "business_file_id"),
            ("sample_request", "reference_image_id"),
            ("sample_product", "task_sheet_file_id"),
            ("sample_product_sampling_detail", "image_file_id"),
            ("sample_parameter_image", "business_file_id"),
            ("sample_workflow_record", "business_file_id"),
            ("quotation_line", "product_image_id"),
            ("quotation_document", "business_file_id"),
            ("quotation_dispatch_record", "evidence_file_id"),
            ("quotation_file_link", "business_file_id"),
            ("sample_file_link", "business_file_id"),
            ("sales_order_evidence", "business_file_id"),
            ("sales_order_collaboration_event", "evidence_file_id"),
            ("production_task_product_image", "image_file_id"),
            ("production_task_product", "image_file_id"),
            ("production_task_detail", "image_file_id"),
            ("bom", "source_file_id"),
            ("bom_line_image", "business_file_id"),
            ("bom_line_image_draft", "business_file_id"),
            ("production_schedule_product", "image_file_id"),
            ("procurement_supplier_purchase_sheet", "pdf_file_id"),
            ("procurement_supplier_purchase_sheet_line_image", "image_file_id"),
            ("procurement_supplier_purchase_sheet_seal_image", "image_file_id"),
        ]
        placeholders = ",".join(["%s"] * len(RESET_TABLES))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT child.relname, child_column.attname
                FROM pg_constraint constraint_info
                JOIN pg_class child ON child.oid = constraint_info.conrelid
                JOIN pg_class parent ON parent.oid = constraint_info.confrelid
                JOIN pg_attribute child_column
                  ON child_column.attrelid = child.oid
                 AND child_column.attnum = constraint_info.conkey[1]
                WHERE constraint_info.contype = 'f'
                  AND parent.relname = 'business_file'
                  AND child.relname IN ({placeholders})
                ORDER BY child.relname, child_column.attname
                """,
                RESET_TABLES,
            )
            database_file_references = set(cursor.fetchall())
        configured_file_references = set(file_queries)
        missing_file_references = sorted(database_file_references - configured_file_references)
        if missing_file_references:
            raise CommandError(
                f"清理范围新增了未枚举的附件外键，禁止删除：{missing_file_references}"
            )
        for table, column in file_queries:
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL')
                file_ids.update(row[0] for row in cursor.fetchall())
        return task_ids, sla_ids, approval_ids, file_ids

    def _create_media_backup(self, file_ids, media_backup_path):
        if media_backup_path.exists():
            raise CommandError(f"媒体备份文件已存在，禁止覆盖：{media_backup_path}")
        media_backup_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path = media_backup_path.with_suffix(f"{media_backup_path.suffix}.partial")
        partial_path.unlink(missing_ok=True)
        media_root = Path(settings.MEDIA_ROOT).resolve()
        manifest = []
        try:
            with zipfile.ZipFile(partial_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for business_file in BusinessFile.objects.filter(pk__in=file_ids).order_by("id"):
                    storage_path = (media_root / business_file.storage_key).resolve()
                    if storage_path != media_root and media_root not in storage_path.parents:
                        raise CommandError(f"附件路径越界：{business_file.storage_key}")
                    if not storage_path.is_file():
                        raise CommandError(f"交易附件缺失，无法形成完整媒体备份：{business_file.storage_key}")
                    digest = hashlib.sha256(storage_path.read_bytes()).hexdigest().upper()
                    archive.write(storage_path, arcname=f"files/{business_file.storage_key}")
                    manifest.append({
                        "business_file_id": str(business_file.pk),
                        "storage_key": business_file.storage_key,
                        "size_bytes": storage_path.stat().st_size,
                        "sha256": digest,
                    })
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
            with zipfile.ZipFile(partial_path, "r") as archive:
                broken_member = archive.testzip()
                if broken_member:
                    raise CommandError(f"媒体备份校验失败：{broken_member}")
            partial_path.replace(media_backup_path)
        except Exception:
            partial_path.unlink(missing_ok=True)
            raise
        archive_digest = hashlib.sha256(media_backup_path.read_bytes()).hexdigest().upper()
        return {
            "path": str(media_backup_path),
            "file_count": len(manifest),
            "size_bytes": media_backup_path.stat().st_size,
            "sha256": archive_digest,
            "zip_test_passed": True,
        }

    def _clear_transaction_data(self, media_backup_path):
        lock_tables = sorted(set(RESET_TABLES) | ALLOWED_EXTERNAL_DEPENDENCIES | {
            "business_file", "customer_timeline_event",
        })
        with connection.cursor() as cursor:
            quoted_tables = ", ".join(f'"{table}"' for table in lock_tables)
            cursor.execute(f"LOCK TABLE {quoted_tables} IN ACCESS EXCLUSIVE MODE")
        task_ids, sla_ids, approval_ids, file_ids = self._collect_cleanup_references()
        media_backup = self._create_media_backup(file_ids, media_backup_path)
        deleted_counts = {}
        deleted_storage_paths = []
        skipped_shared_files = 0
        skipped_shared_tasks = 0

        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
            for table, trigger in RESET_GUARDED_TRIGGERS:
                cursor.execute(f'ALTER TABLE "{table}" DISABLE TRIGGER "{trigger}"')
            for table in sorted(ALLOWED_EXTERNAL_DEPENDENCIES):
                cursor.execute(f'DELETE FROM "{table}"')
                deleted_counts[table] = cursor.rowcount
            cursor.execute(
                "DELETE FROM customer_timeline_event WHERE source_type = ANY(%s)",
                [[
                    "INQUIRY", "QUOTATION", "QUOTATION_VERSION", "SAMPLE_REQUEST",
                    "SALES_ORDER", "PRODUCTION_TASK", "BOM", "PURCHASE_ORDER",
                    "SAMPLE_FEE_RECORD", "SAMPLE_FEEDBACK",
                ]],
            )
            deleted_counts["customer_timeline_event"] = cursor.rowcount
            for table in RESET_TABLES:
                cursor.execute(f'DELETE FROM "{table}"')
                deleted_counts[table] = cursor.rowcount
            # 先结算删除产生的延迟约束事件，否则 PostgreSQL 不允许重新启用相关触发器。
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            for table, trigger in reversed(RESET_GUARDED_TRIGGERS):
                cursor.execute(f'ALTER TABLE "{table}" ENABLE TRIGGER "{trigger}"')

        deleted_task_ids = []
        for task_id in task_ids:
            try:
                deleted, _ = BusinessTask.objects.filter(pk=task_id).delete()
                if not deleted:
                    skipped_shared_tasks += 1
                else:
                    deleted_task_ids.append(task_id)
            except ProtectedError:
                skipped_shared_tasks += 1
        if deleted_task_ids:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM customer_timeline_event
                    WHERE source_type = 'BUSINESS_TASK' AND source_id = ANY(%s)
                    """,
                    [deleted_task_ids],
                )
                deleted_counts["customer_timeline_event"] += cursor.rowcount
        if sla_ids:
            SlaTracking.objects.filter(pk__in=sla_ids).delete()
        if approval_ids:
            deleted_approval_ids = list(
                ApprovalRequest.objects.filter(pk__in=approval_ids).values_list("pk", flat=True)
            )
            ApprovalRequest.objects.filter(pk__in=deleted_approval_ids).delete()
            if deleted_approval_ids:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM customer_timeline_event
                        WHERE source_type = 'APPROVAL_REQUEST' AND source_id = ANY(%s)
                        """,
                        [deleted_approval_ids],
                    )
                    deleted_counts["customer_timeline_event"] += cursor.rowcount

        for business_file in BusinessFile.objects.filter(pk__in=file_ids):
            storage_path = Path(settings.MEDIA_ROOT) / business_file.storage_key
            try:
                deleted, _ = BusinessFile.objects.filter(pk=business_file.pk).delete()
            except ProtectedError:
                skipped_shared_files += 1
                continue
            if deleted:
                deleted_storage_paths.append(storage_path)
            else:
                skipped_shared_files += 1

        return {
            "deleted_rows_by_table": deleted_counts,
            "workflow_task_candidates": len(task_ids),
            "workflow_tasks_preserved_because_shared": skipped_shared_tasks,
            "business_file_candidates": len(file_ids),
            "business_files_preserved_because_shared": skipped_shared_files,
            "central_audit_logs_preserved": True,
            "material_issue_process_audit_events_deleted": deleted_counts.get(
                "material_issue_audit_event", 0
            ),
            "media_backup": media_backup,
        }, deleted_storage_paths

    def _create_dataset(self, *, dependencies, image_paths, created_storage_paths, issues, stage_seconds):
        stage_started = perf_counter()
        customer_context_summary = self._ensure_customer_contexts(dependencies)
        stage_seconds["customer_context_completion"] = round(perf_counter() - stage_started, 3)
        if (
            customer_context_summary["created_entities"]
            or customer_context_summary["created_contacts"]
            or customer_context_summary["created_addresses"]
        ):
            issues.append({
                "code": "CUSTOMER_MASTER_DATA_COMPLETED",
                "severity": "INFO",
                "stage": "customer_context",
                "created_entities": customer_context_summary["created_entities"],
                "created_contacts": customer_context_summary["created_contacts"],
                "created_addresses": customer_context_summary["created_addresses"],
                "impact": "为满足真实报价、销售订单门禁补齐缺失联系人和地址；未修改既有资料。",
            })

        stage_started = perf_counter()
        business_files = self._create_image_files(image_paths, dependencies["actor"], created_storage_paths)
        products = self._create_products(
            image_paths,
            dependencies["reference_product"],
            dependencies["reference_variants"],
            dependencies["product_categories"],
            dependencies["product_items"],
        )
        stage_seconds["images_and_products"] = round(perf_counter() - stage_started, 3)

        stage_started = perf_counter()
        inquiries = self._create_inquiries(
            dependencies,
            image_paths,
            business_files,
            products,
            issues,
        )
        stage_seconds["inquiries"] = round(perf_counter() - stage_started, 3)

        stage_started = perf_counter()
        quotations = self._create_quotations(dependencies, inquiries, business_files)
        stage_seconds["quotations"] = round(perf_counter() - stage_started, 3)

        # 本批验收明确“不创建样品”，仍保留变量和阶段耗时，方便报告统一读取。
        stage_started = perf_counter()
        samples = []
        stage_seconds["samples"] = round(perf_counter() - stage_started, 3)

        stage_started = perf_counter()
        sales_orders = self._create_sales_orders(dependencies, quotations, products)
        stage_seconds["sales_orders"] = round(perf_counter() - stage_started, 3)

        stage_started = perf_counter()
        production_tasks = self._create_production_tasks(dependencies, sales_orders)
        stage_seconds["production_tasks"] = round(perf_counter() - stage_started, 3)

        stage_started = perf_counter()
        boms = self._create_boms(dependencies, production_tasks, products)
        stage_seconds["boms"] = round(perf_counter() - stage_started, 3)

        stage_started = perf_counter()
        purchase_orders = self._create_purchase_orders(
            dependencies,
            production_tasks,
            boms,
            created_storage_paths,
        )
        stage_seconds["purchase_orders"] = round(perf_counter() - stage_started, 3)

        stage_started = perf_counter()
        material_inbounds = self._create_material_inbounds(dependencies, purchase_orders)
        stage_seconds["material_inbounds"] = round(perf_counter() - stage_started, 3)

        return {
            "business_files": business_files,
            "products": products,
            "inquiries": inquiries,
            "quotations": quotations,
            "samples": samples,
            "sales_orders": sales_orders,
            "production_tasks": production_tasks,
            "boms": boms,
            "purchase_orders": purchase_orders,
            "material_inbounds": material_inbounds,
            "customer_context_summary": customer_context_summary,
        }

    def _ensure_customer_contexts(self, dependencies):
        contexts = {}
        created_entities = []
        created_contacts = []
        created_addresses = []
        for index, customer in enumerate(dependencies["customers"], start=1):
            entity = (
                customer.transaction_entities.filter(
                    archived_at__isnull=True,
                    addresses__isnull=False,
                    addresses__archived_at__isnull=True,
                )
                .distinct()
                .order_by("entity_code", "id")
                .first()
            )
            if entity is None:
                entity = (
                    customer.transaction_entities.filter(archived_at__isnull=True)
                    .order_by("entity_code", "id")
                    .first()
                )
            if entity is None:
                base_code = f"{customer.account_code}-LEGAL"[:50]
                entity_code = base_code
                suffix = 1
                while CustomerTransactionEntity.objects.filter(entity_code=entity_code).exists():
                    suffix += 1
                    suffix_text = f"-{suffix}"
                    entity_code = f"{base_code[:50 - len(suffix_text)]}{suffix_text}"
                country_code = (customer.primary_country_code or "CN").upper()[:2]
                entity = CustomerTransactionEntity.objects.create(
                    customer_account=customer,
                    entity_code=entity_code,
                    legal_name=customer.account_name,
                    english_legal_name="",
                    registration_country_code=country_code,
                    registration_number="",
                    tax_country_code=country_code,
                    tax_identifier="",
                    notes="",
                )
                created_entities.append({
                    "customer_id": str(customer.pk),
                    "customer_code": customer.account_code,
                    "entity_id": str(entity.pk),
                })

            address = (
                entity.addresses.filter(archived_at__isnull=True)
                .order_by("address_code", "id")
                .first()
            )
            if address is None:
                existing_codes = set(entity.addresses.values_list("address_code", flat=True))
                address_sequence = 1
                address_code = f"SHIP{address_sequence:03d}"
                while address_code in existing_codes:
                    address_sequence += 1
                    address_code = f"SHIP{address_sequence:03d}"
                country_code = (entity.registration_country_code or "CN").upper()[:2]
                if country_code == "CN":
                    state_province = "浙江省"
                    city = "宁波市"
                    address_line1 = f"鄞州区中山东路{100 + index}号"
                else:
                    state_province = ""
                    city = "Central City"
                    address_line1 = f"{100 + index} Market Street"
                address = CustomerEntityAddress.objects.create(
                    transaction_entity=entity,
                    address_code=address_code,
                    label="收货地址",
                    country_code=country_code,
                    state_province=state_province,
                    city=city,
                    postal_code="315000" if country_code == "CN" else "10001",
                    address_line1=address_line1,
                    address_line2="",
                    recipient_name="采购负责人",
                    recipient_phone="",
                    is_verified=False,
                )
                created_addresses.append({
                    "customer_id": str(customer.pk),
                    "customer_code": customer.account_code,
                    "entity_id": str(entity.pk),
                    "address_id": str(address.pk),
                })

            contact = (
                customer.contacts.filter(
                    status=ContactStatus.ACTIVE,
                    archived_at__isnull=True,
                )
                .order_by("-is_primary_contact", "display_name", "id")
                .first()
            )
            if contact is None:
                contact = CustomerContact.objects.create(
                    customer_account=customer,
                    transaction_entity=entity,
                    display_name="采购负责人",
                    english_name="Purchasing Manager",
                    position_title="采购经理",
                    department_name="采购部",
                    preferred_language_code="ZH-HANS",
                    timezone_code="Asia/Shanghai",
                    is_key_contact=True,
                    is_primary_contact=True,
                    status=ContactStatus.ACTIVE,
                    notes="",
                )
                created_contacts.append({
                    "customer_id": str(customer.pk),
                    "customer_code": customer.account_code,
                    "contact_id": str(contact.pk),
                })
            contexts[customer.pk] = {
                "entity": entity,
                "address": address,
                "contact": contact,
            }
        dependencies["contexts"] = contexts
        return {
            "created_entities": created_entities,
            "created_contacts": created_contacts,
            "created_addresses": created_addresses,
        }

    def _create_image_files(self, image_paths, actor, created_storage_paths):
        files = []
        for image_path in image_paths:
            with image_path.open("rb") as source:
                business_file = save_scanned_image(
                    File(source, name=image_path.name),
                    actor,
                    storage_folder=f"flow-simulation/{DATASET_MARKER}",
                    field_label="询盘产品设计图",
                )
            created_storage_paths.append(Path(settings.MEDIA_ROOT) / business_file.storage_key)
            files.append(business_file)
        return files

    def _create_products(
        self,
        image_paths,
        reference_product,
        reference_variants,
        product_categories,
        product_items,
    ):
        """只复用启用中的产品主数据，不因本批造数新增产品主数据。

        用户已选择不新增任务单中的大号行军床变体，因此任务单规格只用于
        询盘/BOM参考，销售订单产品外键必须绑定到现有、最接近的产品记录。
        """
        products = []
        for variant in reference_variants:
            product = self._match_existing_product(variant)
            variant["product_id"] = product.pk
            variant["matched_product_number"] = product.product_number
            products.append(product)
        return products

    @staticmethod
    def _normalized_dimensions(value):
        text = str(value or "").upper().replace("×", "*").replace("X", "*")
        text = re.sub(r"CM|厘米", "", text)
        return re.findall(r"\d+(?:\.\d+)?", text)

    def _match_existing_product(self, variant):
        source_name = str(variant.get("source_product_name") or "")
        display_name = str(variant.get("display_name") or "")
        if "扶手椅" in source_name or display_name == "扶手椅":
            name_filter = Q(product_name="扶手椅")
        elif "高脚导演椅" in source_name:
            name_filter = Q(product_name="高脚导演椅")
        elif "导演椅" in source_name:
            name_filter = Q(product_name__contains="导演椅") & ~Q(product_name__contains="高脚")
        elif "行军床" in source_name or display_name == "行军床":
            name_filter = Q(product_name__contains="行军床")
        else:
            raise CommandError(f"无法为任务单产品匹配现有产品主数据：{source_name}")

        candidates = list(
            ProductInformation.objects.filter(
                name_filter,
                status=ProductStatus.ACTIVE,
                archived_at__isnull=True,
                unit__archived_at__isnull=True,
                product_item__archived_at__isnull=True,
            ).order_by("product_number", "id")
        )
        if not candidates:
            raise CommandError(
                f"产品主数据缺少可复用的启用产品：{source_name}（{variant.get('specification')}）"
            )
        target = [float(item) for item in self._normalized_dimensions(variant.get("specification"))[:4]]
        if not target:
            raise CommandError(f"任务单规格无法解析：{variant.get('specification')}")

        def score(product):
            candidate = [
                float(item)
                for item in self._normalized_dimensions(product.specification)[:len(target)]
            ]
            if not candidate:
                return (10**9, len(product.specification or ""), product.product_number)
            length_penalty = abs(len(candidate) - len(target)) * 1000
            distance = sum((left - right) ** 2 for left, right in zip(target, candidate))
            return (length_penalty + distance, len(product.specification or ""), product.product_number)

        return min(candidates, key=score)

    def _inquiry_customer_sequence(self, customers, contexts):
        complete = [customer for customer in customers if customer.pk in contexts]
        sequence = list(customers)
        index = 0
        while len(sequence) < EXPECTED_COUNTS["inquiries"]:
            sequence.append(complete[index % len(complete)])
            index += 1
        return sequence

    def _create_inquiries(self, dependencies, image_paths, business_files, products, issues):
        actor = dependencies["actor"]
        contexts = dependencies["contexts"]
        customers = self._inquiry_customer_sequence(dependencies["customers"], contexts)
        if not products:
            raise CommandError("没有从参考生产任务单创建产品变体，无法创建询盘。")
        now = timezone.now()
        inquiries = []
        blocked_customers = []
        for index, customer in enumerate(customers, start=1):
            context = contexts.get(customer.pk)
            image_index = (index - 1) % len(image_paths)
            variant = dependencies["reference_variants"][(index - 1) % len(dependencies["reference_variants"])]
            product = products[(index - 1) % len(products)]
            reference_specification = variant["specification"]
            reference_color = variant["color"]
            reference_specification_text = format_inquiry_item_specification(
                reference_specification,
                reference_color,
                variant.get("material", ""),
            )
            quantity = Decimal(100 + index * 5)
            inquiry = create_inquiry(
                validated_data={
                    "customer_account": customer,
                    "transaction_entity": context["entity"] if context else None,
                    "customer_contact": context["contact"] if context else None,
                    "subject": f"{DATASET_MARKER}-{index:03d} {product.product_name} {reference_specification_text}",
                    "description": (
                        f"真实流程模拟；产品：{product.product_name}；"
                        f"参考规格颜色：{reference_specification_text}；"
                        f"实际绑定产品：{product.product_number} {product.specification}；"
                        f"设计图：{image_paths[image_index].name}"
                    ),
                    "received_at": now - timedelta(days=index % 15),
                    "requested_due_at": now + timedelta(days=20 + index % 20),
                    "priority": "HIGH" if index % 10 == 0 else "MEDIUM",
                    "inquiry_source": "SIMULATION",
                    "customer_language_code": "ZH-HANS",
                    "trade_term_code": "FOB",
                    "trade_term_place": "宁波",
                    "delivery_requirement": "按确认样和约定交期交付",
                    "estimated_amount_min": quantity * Decimal("35"),
                    "estimated_amount_max": quantity * Decimal("45"),
                    "estimated_currency_code": "CNY",
                    "idempotency_key": f"FLOW261003-I-{index:03d}",
                    "items": [{
                        "line_number": 1,
                        "product_description": product.product_name,
                        "specification": reference_specification,
                        "color": reference_color,
                        "material": variant.get("material", ""),
                        "quantity": quantity,
                        "unit_code": dependencies["reference_product"].unit.unit_code,
                        "target_unit_price": Decimal("40.0000") + Decimal(index % 7),
                        "target_currency_code": "CNY",
                        "expected_date": timezone.localdate() + timedelta(days=30 + index % 15),
                        "notes": f"图片来源：{image_paths[image_index].name}",
                    }],
                },
                actor_employee=actor,
                request=None,
            )
            _link, inquiry = link_inquiry_file(
                inquiry=inquiry,
                business_file=business_files[image_index],
                file_role="PRODUCT_DESIGN_IMAGE",
                actor_employee=actor,
                request=_etag_request(inquiry),
            )
            if context:
                for action, note in (
                    ("SUBMITTED", "真实模拟：业务员提交询盘。"),
                    ("STARTED", "真实模拟：开始需求分析。"),
                    ("CONFIRMED_REQUIREMENTS", "真实模拟：客户需求已确认，可进入报价。"),
                ):
                    inquiry = transition_inquiry(
                        inquiry=inquiry,
                        action=action,
                        note=note,
                        actor_employee=actor,
                        request=_etag_request(inquiry),
                    )
            else:
                blocked_customers.append({
                    "customer_id": str(customer.pk),
                    "account_code": customer.account_code,
                    "account_name": customer.account_name,
                    "reason": "客户缺少有效联系人或完整交易主体/地址，询盘不能正式提交。",
                })
            inquiries.append(inquiry)
        if blocked_customers:
            issues.append({
                "code": "CUSTOMER_CONTEXT_INCOMPLETE",
                "severity": "BLOCKED_SINGLE_RECORD",
                "stage": "inquiry_submit",
                "count": len(blocked_customers),
                "records": blocked_customers,
                "impact": "对应询盘保留为草稿；报价阶段会按已确认的100条目标验收，不会用草稿冒充正式报价。",
            })
        return inquiries

    def _create_quotations(self, dependencies, inquiries, business_files):
        actor = dependencies["actor"]
        candidates = [
            inquiry for inquiry in inquiries
            if inquiry.status == InquiryStatus.READY_FOR_QUOTE
        ][:EXPECTED_COUNTS["quotations"]]
        if len(candidates) != EXPECTED_COUNTS["quotations"]:
            raise CommandError(f"可进入报价的询盘只有 {len(candidates)} 条。")
        created = []
        now = timezone.now()
        for index, inquiry in enumerate(candidates, start=1):
            context = dependencies["contexts"][inquiry.customer_account_id]
            quotation, version, replayed = create_quotation_from_inquiry(
                inquiry_id=inquiry.pk,
                entity_id=context["entity"].pk,
                entity_data=None,
                subject=f"{DATASET_MARKER}-Q-{index:03d} {inquiry.subject}",
                currency_code="CNY",
                due_at=now + timedelta(days=3),
                idempotency_key=f"FLOW261003-Q-{index:03d}",
                create_another=False,
                actor_employee=actor,
                request=_etag_request(inquiry),
            )
            if replayed:
                raise CommandError("清理后不应命中报价幂等重放。")
            line = version.lines.get()
            line, version = update_line(
                line=line,
                validated_data={
                    "unit_price": Decimal("48.0000") + Decimal(index % 12),
                    "discount_rate": Decimal("0.000000"),
                },
                actor_employee=actor,
                request=_etag_request(version),
            )
            line, version = set_line_product_image(
                line=line,
                business_file=business_files[(index - 1) % len(business_files)],
                actor_employee=actor,
                request=_etag_request(version),
            )
            basis = QuotationPriceBasis.objects.create(
                quotation_version=version,
                label="FOB宁波模拟成交价",
                incoterm_code="FOB",
                named_place="宁波",
                currency_code="CNY",
                is_default=True,
                sort_order=1,
                notes="30%订金，70%发货前付清",
            )
            QuotationLinePrice.objects.create(
                quotation_line=line,
                price_basis=basis,
                unit_price=line.unit_price,
            )
            version.refresh_from_db()
            version = lock_version(
                version=version,
                address=context["address"],
                contact=context["contact"],
                tax_rate=Decimal("0"),
                terms={
                    "incoterm_code": "FOB",
                    "payment_terms": "30%订金，70%发货前付清",
                    "price_validity": "45天",
                },
                actor_employee=actor,
                request=_etag_request(version),
            )
            version = issue_version(
                version=version,
                actor_employee=actor,
                request=_etag_request(version),
                note="真实流程模拟：签发正式报价。",
            )
            _dispatch, version = confirm_manual_dispatch(
                version=version,
                price_basis=basis,
                recipient_snapshot={
                    "name": context["contact"].display_name,
                    "email": "flow-simulation@example.invalid",
                },
                evidence_file=None,
                external_reference=f"FLOW-MANUAL-{index:03d}",
                follow_up_due_at=now + timedelta(days=5),
                evidence_note="本地真实流程模拟：只登记人工发送事实，不向外部发送邮件。",
                actor_employee=actor,
                request=_etag_request(version),
            )
            quotation.refresh_from_db()
            quotation = transition_quotation(
                quotation=quotation,
                action="ACCEPTED",
                accepted_version=version,
                accepted_price_basis=basis,
                customer_contact=context["contact"],
                accepted_at=now,
                acceptance_source=QuotationAcceptanceSource.EMAIL,
                note="真实流程模拟：客户书面接受报价。",
                actor_employee=actor,
                request=_etag_request(quotation),
            )
            created.append({
                "quotation": quotation,
                "version": version,
                "line": line,
                "context": context,
                "inquiry": inquiry,
            })
        return created

    def _create_samples(self, dependencies, quotations):
        created = []
        for index, quote_data in enumerate(quotations, start=1):
            sample, replayed = create_sample_from_quotation_version(
                quotation_version_id=quote_data["version"].pk,
                validated_data={
                    "sample_type": SampleType.PRE_SALES,
                    "purpose": "验证设计图、结构、颜色及包装要求。",
                    "sample_due_date": timezone.localdate() + timedelta(days=10 + index % 10),
                    "idempotency_key": f"FLOW261003-SR-{index:03d}",
                    "items": [{
                        "source_line": quote_data["line"],
                        "requested_quantity": 1 + index % 3,
                    }],
                },
                actor_employee=dependencies["actor"],
                request=None,
            )
            if replayed:
                raise CommandError("清理后不应命中样品申请幂等重放。")
            created.append(sample)
        return created

    def _create_sales_orders(self, dependencies, quotations, products):
        actor = dependencies["actor"]
        employees = dependencies["employees"]
        created = []
        base_date = timezone.localdate()
        for index, quote_data in enumerate(quotations[:EXPECTED_COUNTS["sales_orders"]], start=1):
            line = quote_data["line"]
            version = quote_data["version"]
            quotation = quote_data["quotation"]
            context = quote_data["context"]
            product = products[(index - 1) % len(products)]
            salesperson = employees[(index - 1) % len(employees)]
            merchandiser = employees[index % len(employees)]
            line_key = f"line-{index:03d}"
            delivery_date = base_date + timedelta(days=35 + index % 20)
            payload = {
                "source_type": SalesOrderSource.QUOTATION,
                "source_quotation_version_id": str(version.pk),
                "customer_account_id": str(quotation.customer_account_id),
                "transaction_entity_id": str(context["entity"].pk),
                "buyer_address_id": str(context["address"].pk),
                "salesperson_id": str(salesperson.pk),
                "merchandiser_id": str(merchandiser.pk),
                "customer_po_number": f"{DATASET_MARKER}-PO-{index:03d}",
                "contract_number": f"{DATASET_MARKER}-CON-{index:03d}",
                "order_date": base_date.isoformat(),
                "currency_code": "CNY",
                "exchange_rate": "1.000000",
                "incoterm_code": "FOB",
                "payment_terms": "30%订金，70%发货前付清",
                "deposit_required": True,
                "includes_tax": False,
                "tax_basis": "未税模拟订单",
                "order_tolerance_percent": "0",
                "preproduction_sample_required": True,
                "seller_snapshot": version.template_snapshot,
                "terms_snapshot": version.terms_snapshot,
                "customer_requirement_snapshot": version.customer_requirement_snapshot,
                "confirmation_method": CustomerConfirmationMethod.EMAIL,
                "customer_confirmer": context["contact"].display_name,
                "customer_confirmed_at": timezone.now().isoformat(),
                "confirmation_summary": "客户已确认产品、设计图、数量、价格与交期。",
                "lines": [{
                    "client_key": line_key,
                    "source_quotation_line_id": str(line.pk),
                    "product_id": str(product.pk),
                    "quantity": str(line.quantity),
                    "unit_price": str(line.unit_price),
                    "lower_price_reason": "",
                    "quality_requirements": "结构、尺寸、颜色按确认样验收。",
                    "packaging_requirements": "五层瓦楞纸箱并附追溯标签。",
                    "shipping_mark_requirements": f"外箱标记 {DATASET_MARKER}-{index:03d}。",
                }],
                "delivery_batches": [{
                    "client_key": f"batch-{index:03d}",
                    "planned_delivery_date": delivery_date.isoformat(),
                    "notes": "单批交付。",
                    "lines": [{
                        "sales_order_line_client_key": line_key,
                        "quantity": str(line.quantity),
                    }],
                }],
            }
            serializer = SalesOrderWriteSerializer(data=payload)
            serializer.is_valid(raise_exception=True)
            order = create_sales_order(
                validated_data=dict(serializer.validated_data),
                actor_employee=actor,
                request=None,
            )
            order = confirm_sales_order(
                order=order,
                actor_employee=actor,
                request=_etag_request(order),
            )
            created.append(order)
        return created

    def _create_production_tasks(self, dependencies, sales_orders):
        actor = dependencies["actor"]
        employees = dependencies["employees"]
        created = []
        base_date = timezone.localdate()
        for index, order in enumerate(sales_orders[:EXPECTED_COUNTS["production_tasks"]], start=1):
            batch_line = order.delivery_batches.get().lines.get()
            payload = {
                "request_key": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{DATASET_MARKER}:production:{index}")),
                "delivery_batch_line_id": str(batch_line.pk),
                "quantity": int(batch_line.quantity),
                "planned_start_date": (base_date + timedelta(days=1 + index % 5)).isoformat(),
                "planned_end_date": (base_date + timedelta(days=25 + index % 10)).isoformat(),
                "production_priority": "HIGH" if index % 10 == 0 else "NORMAL",
                "production_batch_number": f"FLOW-BATCH-{index:03d}",
                "planner_id": str(employees[(index + 1) % len(employees)].pk),
            }
            serializer = ProductionTaskCreateFromSalesOrderSerializer(data=payload)
            serializer.is_valid(raise_exception=True)
            task = create_production_order_from_sales_order(
                validated_data=dict(serializer.validated_data),
                actor_employee=actor,
                request=None,
            )
            task = submit_production_task(task=task, actor_employee=actor, request=None)
            task = decide_production_order_by_pmc(
                task=task,
                validated_data={
                    "decision": "CONFIRM",
                    "planned_start_date": base_date + timedelta(days=1 + index % 5),
                    "planned_end_date": base_date + timedelta(days=25 + index % 10),
                    "production_priority": "HIGH" if index % 10 == 0 else "NORMAL",
                    "production_batch_number": f"FLOW-BATCH-{index:03d}",
                    "planner": employees[(index + 1) % len(employees)],
                },
                actor_employee=actor,
                request=_etag_request(task),
            )
            created.append(task)
        return created

    def _create_boms(self, dependencies, production_tasks, products):
        actor = dependencies["actor"]
        created = []
        catalog = load_bom_simulation_catalog()
        for index, task in enumerate(production_tasks[:EXPECTED_COUNTS["verified_boms"]], start=1):
            product_line = task.products.get()
            bom = create_bom(
                product_line=product_line,
                creation_method=BomCreationMethod.BLANK,
                actor_employee=actor,
                request=None,
            )
            sections = self._build_reference_bom_sections(
                bom=bom,
                index=index,
                catalog=catalog,
                # 同一产品主数据可能被多个颜色变体复用，不能按 product_id
                # 反查，否则最后一个颜色会覆盖前面的 BOM 参考。
                variant=dependencies["reference_variants"][
                    (index - 1) % len(dependencies["reference_variants"])
                ],
            )
            input_serializer = BomUpdateInputSerializer(
                data={"sections": sections},
                context={"bom": bom},
            )
            input_serializer.is_valid(raise_exception=True)
            bom = update_bom_lines(
                bom=bom,
                sections=input_serializer.validated_data["sections"],
                actor_employee=actor,
                request=_etag_request(bom),
            )

            # 裁剪明细必须引用本 BOM 已保存的面料行。新建时面料行还没有主键，
            # 因此先保存一次，再补齐行 ID 和每套耗米后保存第二次。
            persisted_sections = {
                (section.title.strip(), section.section_type): list(
                    section.lines.order_by("line_number", "id")
                )
                for section in bom.sections.all()
            }
            for section in sections:
                stored_section = bom.sections.get(
                    title=section["title"],
                    section_type=section["section_type"],
                )
                section["id"] = stored_section.pk
                stored_lines = persisted_sections[(section["title"].strip(), section["section_type"])]
                if len(stored_lines) != len(section["lines"]):
                    raise CommandError(
                        f"BOM {bom.pk} 分区“{section['title']}”保存行数不一致，不能建立裁剪面料来源。"
                    )
                for line_data, stored_line in zip(section["lines"], stored_lines):
                    line_data["id"] = stored_line.pk
            fabric_lines = persisted_sections[("面料类", BomSectionType.FABRIC)]
            cutting_section = next(section for section in sections if section["title"] == "裁剪明细")
            for line_index, line_data in enumerate(cutting_section["lines"]):
                # 只有委外布面才关联面料来源并使用每套耗米；喷塑管材属于根/支口径，
                # 不能被测试造数误绑到面料行，否则后续裁剪计算会把管材当成布料。
                stored_cutting_line = persisted_sections[("裁剪明细", BomSectionType.FABRIC)][line_index]
                if (stored_cutting_line.category or "").strip() != "委外布面":
                    line_data.pop("fabric_source_line_id", None)
                    line_data.pop("fabric_meters_per_set", None)
                    continue
                source_line = fabric_lines[line_index % len(fabric_lines)]
                line_data["fabric_source_line_id"] = source_line.pk
                line_data["fabric_meters_per_set"] = Decimal("0.40")
            second_serializer = BomUpdateInputSerializer(
                data={"sections": sections},
                context={"bom": bom},
            )
            second_serializer.is_valid(raise_exception=True)
            bom = update_bom_lines(
                bom=bom,
                sections=second_serializer.validated_data["sections"],
                actor_employee=actor,
                request=_etag_request(bom),
            )
            bom = verify_bom(
                bom=bom,
                quantity_confirmation_reason="生产任务、产品行与交付批次数量一致。",
                actor_employee=actor,
                request=_etag_request(bom),
            )
            created.append(bom)
        return created

    def _build_reference_bom_sections(self, *, bom, index, catalog, variant):
        """以既有 BOM 模拟器保证可采购字段，再覆盖任务单中的名称、规格、颜色和备注。

        任务单里的原材料文字不一定已经在主数据中登记，因此不能把未知名称直接当作
        原料主数据外键。采购所需外键仍由启用的原料目录提供，用户文件的值保留在快照
        文本中，避免造出无法追溯或无法采购的 BOM。
        """
        sections = build_bom_simulation_sections(bom=bom, index=index, catalog=catalog)
        if not variant:
            return sections
        plan = variant["source_plan"]
        reference_sections = {
            "PROFILE": [section for section in plan["sections"] if section["section_type"] == "PROFILE"],
            "ACCESSORY": [section for section in plan["sections"] if section["section_type"] == "ACCESSORY"],
            "FABRIC": [
                section for section in plan["sections"]
                if section["section_type"] == "FABRIC"
                and section["title"] == variant["fabric_section_title"]
            ],
        }
        if not reference_sections["FABRIC"]:
            reference_sections["FABRIC"] = [
                section for section in plan["sections"] if section["section_type"] == "FABRIC"
            ][:1]
        source_lines = {
            key: [line for section in values for line in section.get("lines") or []]
            for key, values in reference_sections.items()
        }
        offsets = {key: 0 for key in source_lines}
        for section in sections:
            if section["title"] == "管材类":
                source_key = "PROFILE"
            elif section["title"] in {"五金件", "塑料件类", "包材类"}:
                source_key = "ACCESSORY"
            else:
                source_key = "FABRIC"
            rows = source_lines.get(source_key) or []
            if not rows:
                continue
            for line in section["lines"]:
                source = rows[offsets[source_key] % len(rows)]
                offsets[source_key] += 1
                original_part_name = str(source.get("part_name") or "").strip()
                original_specification = str(source.get("specification") or "").strip()
                original_material = str(source.get("material") or "").strip()
                original_notes = str(source.get("notes") or "").strip()
                if original_part_name:
                    line["part_name"] = original_part_name
                if original_specification:
                    line["specification"] = original_specification
                if original_material:
                    line["material"] = original_material
                if original_notes:
                    line["notes"] = (
                        f"{line.get('notes', '').strip()}；参考任务单：{variant['source_name']}；"
                        f"{original_notes}"
                    ).strip("；")
                line["notes"] = (
                    f"{line.get('notes', '').strip()}；颜色参考：{variant['color']}"
                ).strip("；")
        return sections

    def _supplier_for_line(self, suppliers, source_line):
        suggested = source_line.get("suggested_supplier_category")
        if suggested:
            for supplier in suppliers:
                if suggested in supplier.supplier_categories:
                    return supplier
        return suppliers[0]

    def _create_purchase_orders(
        self,
        dependencies,
        production_tasks,
        boms,
        created_storage_paths,
    ):
        created = []
        allowed_task_ids = [task.pk for task in production_tasks]
        for index, (task, bom) in enumerate(
            zip(
                production_tasks[:EXPECTED_COUNTS["purchase_orders"]],
                boms[:EXPECTED_COUNTS["purchase_orders"]],
            ),
            start=1,
        ):
            source = evaluate_purchase_source(task, bom_id=bom.pk)
            if not source["can_create"]:
                raise CommandError(
                    f"第{index}条采购订单来源被门禁阻止：{source['blockers']}"
                )
            lines = []
            for source_line in source["lines"]:
                required_quantity = source_line.get("required_quantity")
                if required_quantity is None or Decimal(required_quantity) <= 0:
                    raise CommandError(f"第{index}条采购来源缺少可采购数量：{source_line}")
                supplier = self._supplier_for_line(dependencies["suppliers"], source_line)
                line_data = {
                    "bom_line_id": source_line["bom_line_id"],
                    "supplier_id": supplier.pk,
                    "delivery_date": timezone.localdate() + timedelta(days=15 + index % 10),
                    "actual_purchase_quantity": Decimal(required_quantity),
                    "unit_price": Decimal("8.5000") + Decimal(index % 9),
                }
                if source_line.get("section_type") == "PROFILE":
                    # 管材采购按根数提交，米数由系统根据 BOM 的根长计算，
                    # 不能把米数直接伪装成实际根数。
                    line_data["actual_bar_count"] = int(source_line["suggested_bar_count"])
                lines.append(line_data)
            order = create_purchase_order(
                validated_data={
                    "production_task_id": task.pk,
                    "bom_id": bom.pk,
                    "source_revision": source["source_revision"],
                    "currency_id": dependencies["cny"].pk,
                    "is_mailed": False,
                    "lines": lines,
                },
                allowed_task_ids=allowed_task_ids,
                actor_employee=dependencies["actor"],
                request=None,
            )
            order = confirm_purchase_order(
                order_id=order.pk,
                allowed_task_ids=allowed_task_ids,
                actor_employee=dependencies["actor"],
                request=None,
            )
            assignments = self._purchase_sheet_assignments(
                order_lines=lines,
                suppliers=dependencies["suppliers"],
                template_versions=dependencies["purchase_template_versions"],
            )
            sheets = generate_supplier_purchase_sheets(
                order_id=order.pk,
                assignments=assignments,
                allowed_task_ids=allowed_task_ids,
                actor_employee=dependencies["actor"],
                request=None,
            )
            for sheet in sheets:
                published_sheet = publish_supplier_purchase_sheet(
                    sheet_id=sheet.pk,
                    allowed_task_ids=allowed_task_ids,
                    actor_employee=dependencies["actor"],
                    request=_etag_request(sheet),
                )
                if published_sheet.pdf_file_id:
                    created_storage_paths.append(
                        Path(settings.MEDIA_ROOT) / published_sheet.pdf_file.storage_key
                    )
            order.refresh_from_db()
            if order.status != TARGET_PURCHASE_ORDER_STATUS:
                raise CommandError(
                    f"采购订单 {order.order_number} 未进入{TARGET_PURCHASE_ORDER_STATUS.label}，实际状态为 {order.status}。"
                )
            created.append(order)
        return created

    @staticmethod
    def _simulation_request(actor):
        return SimpleNamespace(
            user=actor.user,
            employee=actor,
            headers={},
            META={},
        )

    @staticmethod
    def _material_zone_for_line(line, material_zones):
        category = str(line.category_snapshot or "").strip()
        return material_zones.get(category) or material_zones["_default"]

    def _create_material_inbounds(self, dependencies, purchase_orders):
        """每张采购单创建一批全量到货并完成品质确认，停在采购中。

        采购单不调用“采购完成”动作；入库只写真实的待检、质检确认和库存流水，
        让验收可以从采购入库之后继续验证领料等后续流程。
        """
        actor = dependencies["actor"]
        request = self._simulation_request(actor)
        created = []
        for order in purchase_orders:
            lines = list(order.lines.select_related("bom_line").order_by("line_number", "id"))
            if not lines:
                raise CommandError(f"采购单 {order.order_number} 没有采购明细，不能办理入库。")
            items = []
            for line in lines:
                item = {
                    "purchase_order_line_id": line.pk,
                    "expected_remaining_quantity": line.actual_purchase_quantity,
                    "received_quantity": line.actual_purchase_quantity,
                    "zone_id": self._material_zone_for_line(line, dependencies["material_zones"]).pk,
                    "location_id": None,
                    "remark": "流程验收数据：采购订单全量到货。",
                }
                if line.section_type_snapshot == "PROFILE":
                    if line.actual_bar_count is None or line.raw_bar_length_m is None:
                        raise CommandError(f"采购单 {order.order_number} 的管材明细缺少根米参数。")
                    item["received_bar_count"] = int(line.actual_bar_count)
                    item["raw_bar_length_m"] = line.raw_bar_length_m
                items.append(item)
            inbound = create_material_inbound(
                inbound_date=timezone.localdate(),
                remark="流程验收数据：采购订单全量到货，待品质确认。",
                items=items,
                actor_employee=actor,
                request=request,
            )
            confirmation_items = []
            for inbound_line in inbound.lines.order_by("id"):
                quality_item = {
                    "line_id": inbound_line.pk,
                    "expected_received_quantity": inbound_line.received_quantity,
                }
                if inbound_line.measurement_kind == "PIPE":
                    quality_item["return_bar_count"] = 0
                else:
                    quality_item["return_quantity"] = Decimal("0")
                confirmation_items.append(quality_item)
            inbound = confirm_material_quality(
                inbound_id=inbound.pk,
                items=confirmation_items,
                actor_employee=actor,
                request=request,
            )
            inbound.refresh_from_db()
            if inbound.status != MaterialInboundStatus.CONFIRMED:
                raise CommandError(
                    f"采购单 {order.order_number} 的材料入库未完成品质确认，实际状态为 {inbound.status}。"
                )
            created.append(inbound)
        if len(created) != EXPECTED_COUNTS["material_inbounds"]:
            raise CommandError(f"已确认材料入库只有 {len(created)} 批。")
        return created

    @staticmethod
    def _purchase_sheet_assignments(*, order_lines, suppliers, template_versions):
        supplier_by_id = {str(supplier.pk): supplier for supplier in suppliers}
        supplier_ids = {str(line["supplier_id"]) for line in order_lines if line.get("supplier_id")}
        assignments = []
        for supplier_id in sorted(supplier_ids):
            supplier = supplier_by_id.get(supplier_id)
            if supplier is None:
                raise CommandError(f"采购明细引用了不存在的供应商：{supplier_id}")
            template_version = next(
                (
                    template_versions[category]
                    for category in supplier.supplier_categories or []
                    if category in template_versions
                ),
                None,
            )
            if template_version is None:
                raise CommandError(
                    f"供应商 {supplier.supplier_number} 没有可用的启用采购合同模板，不能发布采购表。"
                )
            assignments.append({
                "supplier_id": supplier.pk,
                "template_version_id": template_version.pk,
            })
        if not assignments:
            raise CommandError("采购订单没有可生成供应商采购表的供应商明细。")
        return assignments

    def _build_report(
        self,
        *,
        preflight,
        cleanup_summary,
        dataset,
        image_paths,
        backup_path,
        backup_sha256,
        backup_attestation,
        issues,
        stage_seconds,
        total_seconds,
    ):
        inquiry_count = Inquiry.objects.count()
        quotation_count = Quotation.objects.count()
        sample_count = SampleRequest.objects.count()
        order_count = SalesOrder.objects.count()
        task_count = ProductionTask.objects.count()
        verified_bom_count = Bom.objects.filter(status=BomStatus.VERIFIED).count()
        purchase_count = PurchaseOrder.objects.count()
        material_inbound_count = MaterialInbound.objects.count()
        confirmed_material_inbound_count = MaterialInbound.objects.filter(
            status=MaterialInboundStatus.CONFIRMED,
        ).count()
        bom_section_summary = summarize_bom_simulation_sections(
            list(Bom.objects.prefetch_related("sections__lines")),
            expected_bom_count=EXPECTED_COUNTS["verified_boms"],
        )
        bom_section_ranges_valid = bom_section_summary["all_valid"]
        invalid_purchase_lines = PurchaseOrderLine.objects.filter(
            Q(bom_line__isnull=True)
            | ~Q(bom_line__section__bom_id=F("bom_id"))
            | ~Q(bom__production_task_id=F("purchase_order__production_task_id"))
        ).exists()
        purchase_source_lines_complete = self._purchase_sources_complete(
            list(
                PurchaseOrder.objects.select_related("production_task")
                .prefetch_related("lines")
                .order_by("created_at", "id")
            )
        )
        covered_customers = Inquiry.objects.values("customer_account_id").distinct().count()
        inquiry_status_counts = Counter(Inquiry.objects.values_list("status", flat=True))
        task_status_counts = Counter(ProductionTask.objects.values_list("status", flat=True))
        purchase_status_counts = Counter(PurchaseOrder.objects.values_list("status", flat=True))
        material_inbound_status_counts = Counter(
            MaterialInbound.objects.values_list("status", flat=True)
        )
        later_operation_counts = self._later_operation_counts()
        image_links = InquiryFileLink.objects.filter(file_role="PRODUCT_DESIGN_IMAGE")
        image_storage_keys = list(
            image_links.values_list("business_file__storage_key", flat=True).distinct()
        )
        image_link_counts = image_links.values("inquiry_id").annotate(link_count=Count("id"))
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT count(*) FROM customer_timeline_event event
                WHERE (event.source_type = 'SAMPLE_FEE_RECORD' AND NOT EXISTS (
                    SELECT 1 FROM sample_fee_record target WHERE target.id = event.source_id
                )) OR (event.source_type = 'SAMPLE_FEEDBACK' AND NOT EXISTS (
                    SELECT 1 FROM sample_feedback target WHERE target.id = event.source_id
                )) OR (event.source_type = 'BUSINESS_TASK' AND NOT EXISTS (
                    SELECT 1 FROM business_task target WHERE target.id = event.source_id
                )) OR (event.source_type = 'APPROVAL_REQUEST' AND NOT EXISTS (
                    SELECT 1 FROM approval_request target WHERE target.id = event.source_id
                ))
            """)
            orphan_timeline_count = cursor.fetchone()[0]
            cursor.execute("""
                SELECT count(*) FROM pg_trigger
                WHERE tgname IN (
                    'ps_schedule_craft_no_delete', 'ps_schedule_product_no_delete',
                    'ps_schedule_no_delete', 'ps_source_product_guard'
                ) AND tgenabled = 'O'
            """)
            enabled_guard_trigger_count = cursor.fetchone()[0]
        checks = {
            "inquiry_count_100": inquiry_count == EXPECTED_COUNTS["inquiries"],
            "quotation_count_100": quotation_count == EXPECTED_COUNTS["quotations"],
            "sample_count_0": sample_count == EXPECTED_COUNTS["samples"],
            "sales_order_count_100": order_count == EXPECTED_COUNTS["sales_orders"],
            "production_task_count_80": task_count == EXPECTED_COUNTS["production_tasks"],
            "verified_bom_count_70": verified_bom_count == EXPECTED_COUNTS["verified_boms"],
            "purchase_order_count_70": purchase_count == EXPECTED_COUNTS["purchase_orders"],
            "all_purchase_orders_at_purchasing": not PurchaseOrder.objects.exclude(
                status=TARGET_PURCHASE_ORDER_STATUS
            ).exists(),
            "all_supplier_purchase_sheets_published": (
                SupplierPurchaseSheet.objects.filter(
                    purchase_order__isnull=False,
                    status="PUBLISHED",
                ).values("purchase_order_id").distinct().count() == EXPECTED_COUNTS["purchase_orders"]
                and not SupplierPurchaseSheet.objects.filter(
                    purchase_order__isnull=False,
                ).exclude(status="PUBLISHED").exists()
            ),
            "all_active_customers_have_inquiry": covered_customers == preflight["active_customer_count"],
            "all_quotes_link_to_inquiry": not Quotation.objects.filter(source_inquiry__isnull=True).exists(),
            "quotes_use_100_distinct_inquiries": Quotation.objects.values(
                "source_inquiry_id"
            ).distinct().count() == EXPECTED_COUNTS["quotations"],
            "all_samples_link_to_quote": not SampleRequest.objects.filter(source_quotation_version__isnull=True).exists(),
            "samples_use_0_distinct_quotes": SampleRequest.objects.values(
                "source_quotation_version_id"
            ).distinct().count() == EXPECTED_COUNTS["samples"],
            "all_sales_orders_link_to_quote": not SalesOrder.objects.filter(source_quotation_version__isnull=True).exists(),
            "sales_orders_use_100_distinct_quotes": SalesOrder.objects.values(
                "source_quotation_version_id"
            ).distinct().count() == EXPECTED_COUNTS["sales_orders"],
            "all_production_tasks_link_to_sales_order": not ProductionTask.objects.filter(sales_order__isnull=True).exists(),
            "production_tasks_use_80_distinct_sales_orders": ProductionTask.objects.values(
                "sales_order_id"
            ).distinct().count() == EXPECTED_COUNTS["production_tasks"],
            "all_boms_verified": verified_bom_count == Bom.objects.count(),
            "all_boms_match_requested_section_ranges": bom_section_ranges_valid,
            "boms_use_70_distinct_production_tasks": Bom.objects.values(
                "production_task_id"
            ).distinct().count() == EXPECTED_COUNTS["verified_boms"],
            "all_purchase_orders_link_to_task": not PurchaseOrder.objects.filter(production_task__isnull=True).exists(),
            "purchase_orders_use_70_distinct_production_tasks": PurchaseOrder.objects.values(
                "production_task_id"
            ).distinct().count() == EXPECTED_COUNTS["purchase_orders"],
            "material_inbound_count_70": material_inbound_count == EXPECTED_COUNTS["material_inbounds"],
            "all_material_inbounds_confirmed": (
                confirmed_material_inbound_count == EXPECTED_COUNTS["material_inbounds"]
                and not MaterialInbound.objects.exclude(status=MaterialInboundStatus.CONFIRMED).exists()
            ),
            "each_purchase_order_has_confirmed_inbound": (
                MaterialInbound.objects.filter(status=MaterialInboundStatus.CONFIRMED)
                .values("purchase_order_id").distinct().count()
                == EXPECTED_COUNTS["purchase_orders"]
            ),
            "purchase_lines_match_task_bom": PurchaseOrder.objects.filter(
                lines__bom__production_task_id=F("production_task_id")
            ).distinct().count() == EXPECTED_COUNTS["purchase_orders"] and not invalid_purchase_lines,
            "all_purchase_source_lines_complete": purchase_source_lines_complete,
            "image_source_count_30": len(image_paths) == 30,
            "each_inquiry_has_exactly_one_design_image": (
                image_links.count() == EXPECTED_COUNTS["inquiries"]
                and image_link_counts.count() == EXPECTED_COUNTS["inquiries"]
                and not image_link_counts.exclude(link_count=1).exists()
            ),
            "all_30_design_files_used": len(image_storage_keys) == 30,
            "all_design_files_exist": all(default_storage.exists(key) for key in image_storage_keys),
            "no_post_inbound_operations": not any(
                later_operation_counts[key]
                for key in later_operation_counts
                if key not in {
                    "material_inbounds",
                    "material_inbound_lines",
                    "material_stock_balances",
                    "material_stock_movements",
                }
            ),
            "no_orphan_timeline_events": orphan_timeline_count == 0,
            "all_schedule_guard_triggers_enabled": enabled_guard_trigger_count == 4,
        }
        checks["all_passed"] = all(checks.values())
        issues.extend([
            {
                "code": "MANUAL_DISPATCH_IS_LOCAL_RECORD_ONLY",
                "severity": "INFO",
                "stage": "quotation_dispatch",
                "impact": "100条报价走了正式签发和人工发送登记，但没有向外部邮箱发送消息。",
            },
            {
                "code": "CENTRAL_AUDIT_LOGS_RETAINED",
                "severity": "INFO",
                "stage": "cleanup",
                "impact": (
                    "中央不可变审计日志按合规要求保留；属于本次清理范围的领料流程审计事件"
                    "随领料交易一并删除。"
                ),
            },
        ])
        return {
            "dataset": DATASET_MARKER,
            "generated_at": timezone.now().isoformat(),
            "backup_path": str(backup_path),
            "backup_size_bytes": backup_path.stat().st_size,
            "backup_sha256": backup_sha256,
            "backup_attestation": backup_attestation,
            "preflight": preflight,
            "cleanup": cleanup_summary,
            "created_counts": {
                "inquiries": inquiry_count,
                "quotations": quotation_count,
                "samples": sample_count,
                "sales_orders": order_count,
                "production_tasks": task_count,
                "verified_boms": verified_bom_count,
                "purchase_orders": purchase_count,
                "material_inbounds": material_inbound_count,
                "confirmed_material_inbounds": confirmed_material_inbound_count,
                "reused_design_products": len(dataset["products"]),
                "uploaded_design_files": len(dataset["business_files"]),
            },
            "status_counts": {
                "inquiries": dict(sorted(inquiry_status_counts.items())),
                "production_tasks": dict(sorted(task_status_counts.items())),
                "purchase_orders": dict(sorted(purchase_status_counts.items())),
                "material_inbounds": dict(sorted(material_inbound_status_counts.items())),
            },
            "later_operation_counts": later_operation_counts,
            "checks": checks,
            "flow_issues": issues,
            "stage_seconds": stage_seconds,
            "total_seconds": total_seconds,
        }

    @staticmethod
    def _purchase_sources_complete(purchase_orders):
        for order in purchase_orders:
            order_lines = list(order.lines.all())
            bom_ids = {line.bom_id for line in order_lines if line.bom_id}
            if len(bom_ids) != 1 or any(line.bom_line_id is None for line in order_lines):
                return False
            source = evaluate_purchase_source(order.production_task, bom_id=bom_ids.pop())
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

    def _later_operation_counts(self):
        from apps.inventory.models import (
            FinishedGoodsOutbound,
            FinishedGoodsOutboundLine,
            FinishedGoodsReceipt,
            MaterialInbound,
            MaterialInboundLine,
            MaterialStockBalance,
            MaterialStockMovement,
            SemiFinishedStockBalance,
            SemiFinishedStockMovement,
        )
        from apps.material_issues.models import MaterialIssue, MaterialIssueAuditEvent, MaterialIssueLine
        from apps.outsourcing.models import OutsourcingOrder
        from apps.procurement.models import PurchaseReturn
        from apps.production_scheduling.models import ProductionSchedule
        from apps.samples.models import (
            SampleInventoryLine,
            SampleInventoryLoan,
            SampleInventoryLoanLine,
            SampleInventoryOutbound,
            SampleInventoryOutboundLine,
            SampleInventoryReceipt,
        )

        return {
            "production_schedules": ProductionSchedule.objects.count(),
            "outsourcing_orders": OutsourcingOrder.objects.count(),
            "purchase_returns": PurchaseReturn.objects.count(),
            "finished_goods_receipts": FinishedGoodsReceipt.objects.count(),
            "finished_goods_outbounds": FinishedGoodsOutbound.objects.count(),
            "finished_goods_outbound_lines": FinishedGoodsOutboundLine.objects.count(),
            "material_inbounds": MaterialInbound.objects.count(),
            "material_inbound_lines": MaterialInboundLine.objects.count(),
            "material_stock_balances": MaterialStockBalance.objects.count(),
            "material_stock_movements": MaterialStockMovement.objects.count(),
            "semi_finished_stock_balances": SemiFinishedStockBalance.objects.count(),
            "semi_finished_stock_movements": SemiFinishedStockMovement.objects.count(),
            "material_issues": MaterialIssue.objects.count(),
            "material_issue_lines": MaterialIssueLine.objects.count(),
            "material_issue_audit_events": MaterialIssueAuditEvent.objects.count(),
            "sample_inventory_receipts": SampleInventoryReceipt.objects.count(),
            "sample_inventory_lines": SampleInventoryLine.objects.count(),
            "sample_inventory_outbounds": SampleInventoryOutbound.objects.count(),
            "sample_inventory_outbound_lines": SampleInventoryOutboundLine.objects.count(),
            "sample_inventory_loans": SampleInventoryLoan.objects.count(),
            "sample_inventory_loan_lines": SampleInventoryLoanLine.objects.count(),
        }

    def _write_report(self, report_path, report):
        if not report_path:
            return
        path = Path(report_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self.stdout.write(f"验收报告：{path}")
