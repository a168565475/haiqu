import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory.models import MaterialInboundLine, MaterialInboundStatus, MaterialStockMovement, PublicStockMovement
from apps.inventory.public_stock_mode import public_flow_enabled
from apps.inventory.stock_services import credit_confirmed_inbound_line, inbound_line_material, validate_inbound_stock_identity


class Command(BaseCommand):
    help = "核对已确认材料入库与净库存账；默认 dry-run，--apply 才会写入余额和流水。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="写入可解析的期初库存余额与流水。")

    @transaction.atomic
    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        if apply_changes and public_flow_enabled():
            raise CommandError("公共库存已启用，旧补账工具仅允许只读检查；须按原单接续核验，不能批量重放旧入库。")
        rows = list(
            MaterialInboundLine.objects.filter(inbound__status=MaterialInboundStatus.CONFIRMED)
            .select_related(
                "inbound",
                "purchase_order_line",
                "purchase_order_line__purchase_order",
                "purchase_order_line__purchase_order__production_task",
                "purchase_order_line__bom_line",
                "raw_material_information",
                "raw_material_information__unit",
                "zone",
                "zone__warehouse",
            )
            .order_by("id")
        )
        report = {
            "mode": "apply" if apply_changes else "dry-run",
            "confirmed_line_count": len(rows),
            "ready_count": 0,
            "already_posted_count": 0,
            "posted_count": 0,
            "zero_accepted_count": 0,
            "blocked_count": 0,
            "blocked": [],
        }
        for line in rows:
            if line.accepted_quantity <= 0:
                report["zero_accepted_count"] += 1
                continue
            existing = MaterialStockMovement.objects.filter(
                source_type="MATERIAL_INBOUND", source_line_id=line.pk, direction="IN"
            ).exists() or PublicStockMovement.objects.filter(
                source_type="MATERIAL_INBOUND", source_line_id=line.pk, direction="IN"
            ).exists()
            if existing:
                report["already_posted_count"] += 1
                continue
            material = inbound_line_material(line)
            if material and not line.raw_material_information_id:
                line.raw_material_information = material
            try:
                validate_inbound_stock_identity(line)
            except Exception as exc:
                detail = getattr(exc, "detail", str(exc))
                report["blocked"].append(
                    {
                        "inbound_line_id": str(line.pk),
                        "inbound_number": line.inbound.inbound_number,
                        "material": line.part_name_snapshot or line.material_snapshot,
                        "unit": line.source_unit_text_snapshot,
                        "warehouse": line.zone.warehouse.warehouse_number,
                        "reason": detail,
                    }
                )
                continue
            report["ready_count"] += 1
            if apply_changes:
                if not line.raw_material_information_id:
                    raise CommandError("内部错误：可入账行缺少稳定原料 ID。")
                line.save(update_fields=["raw_material_information", "updated_at"])
                credit_confirmed_inbound_line(
                    line=line,
                    actor_employee=line.inbound.quality_confirmed_by_employee or line.inbound.received_by_employee,
                )
                report["posted_count"] += 1
        report["blocked_count"] = len(report["blocked"])
        if not apply_changes:
            transaction.set_rollback(True)
        self.stdout.write(json.dumps(report, ensure_ascii=False, default=str, indent=2))
