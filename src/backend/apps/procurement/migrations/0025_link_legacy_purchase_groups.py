"""只增加旧生产采购归属，不替换订单、明细、合同、入库或审计主键。"""
import json
from decimal import Decimal
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db import migrations


SOURCE_FIELDS = (
    "bom_id", "bom_line_id", "source_bom_line_id_snapshot", "product_line_id_snapshot",
    "bom_number_snapshot", "product_number_snapshot", "product_code_snapshot", "product_name_snapshot",
    "product_specification_snapshot", "section_type_snapshot", "section_title_snapshot",
    "category_snapshot", "material_snapshot", "part_name_snapshot", "specification_snapshot",
    "raw_material_snapshot", "material_attributes_snapshot", "required_quantity",
    "source_quantity_field", "source_quantity_text", "source_unit_text", "quantity_parse_status",
    "raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters", "calculation_snapshot",
)


def forwards(apps, schema_editor):
    alias = schema_editor.connection.alias
    Order = apps.get_model("procurement", "PurchaseOrder")
    Line = apps.get_model("procurement", "PurchaseOrderLine")
    Group = apps.get_model("procurement", "PurchaseGroup")
    GroupLine = apps.get_model("procurement", "PurchaseGroupLine")
    Material = apps.get_model("products", "RawMaterialInformation")
    for order in Order.objects.using(alias).filter(source_type="PRODUCTION", purchase_group__isnull=True).iterator():
        lines = list(Line.objects.using(alias).filter(purchase_order_id=order.pk).order_by("line_number", "id"))
        products = {line.product_line_id_snapshot for line in lines}
        boms = {line.bom_id for line in lines}
        group_issues = [] if lines else ["SOURCE_LINES_MISSING"]
        if lines and (len(products) != 1 or None in products):
            group_issues.append("SOURCE_PRODUCT_AMBIGUOUS")
        if lines and (len(boms) != 1 or None in boms):
            group_issues.append("SOURCE_BOM_AMBIGUOUS")
        group = Group.objects.using(alias).create(
            group_number="CGZD" + order.order_number[4:], production_task_id=order.production_task_id,
            product_line_id_snapshot=next(iter(products)) if len(products) == 1 else None,
            source_bom_id_snapshot=next(iter(boms)) if len(boms) == 1 else None,
            production_task_number_snapshot=order.production_task_number_snapshot,
            sales_order_number_snapshot=order.sales_order_number_snapshot,
            customer_name_snapshot=order.customer_name_snapshot, source_revision=order.source_revision,
            created_by_employee_id=order.created_by_employee_id,
            archived_at=order.archived_at, archived_by_employee_id=order.archived_by_employee_id,
            archive_reason=order.archive_reason,
            compatibility_issues=group_issues,
        )
        Group.objects.using(alias).filter(pk=group.pk).update(created_at=order.created_at, updated_at=order.updated_at)
        for line in lines:
            snapshot = json.loads(json.dumps({field: getattr(line, field) for field in SOURCE_FIELDS}, cls=DjangoJSONEncoder))
            issues = []
            if not line.source_bom_line_id_snapshot or not line.product_line_id_snapshot:
                issues.append("SOURCE_ID_MISSING")
            if line.required_quantity is None or line.required_quantity <= Decimal("0"):
                issues.append("SUGGESTED_QUANTITY_MISSING")
            if line.quantity_parse_status != "READY":
                issues.append("SUGGESTED_QUANTITY_UNRESOLVED")
            if not line.source_unit_text.strip():
                issues.append("UNIT_MISSING")
            identity = snapshot.get("calculation_snapshot") or {}
            if not isinstance(identity, dict):
                identity = {}
                issues.append("MATERIAL_SNAPSHOT_INVALID")
            if "raw_material_id" not in identity and line.raw_material_snapshot:
                matches = list(Material.objects.using(alias).filter(material_number=line.raw_material_snapshot)
                               .values("id", "item_type", "archived_at", "unit_id")[:2])
                if len(matches) == 1 and matches[0]["item_type"] == "MATERIAL" and matches[0]["archived_at"] is None:
                    identity = {**identity, "raw_material_id": str(matches[0]["id"]), "unit_id": str(matches[0]["unit_id"])}
            try:
                material_id = UUID(str(identity.get("raw_material_id")))
            except (TypeError, ValueError):
                issues.append("MATERIAL_IDENTITY_MISSING")
            else:
                material = Material.objects.using(alias).select_related("unit").filter(
                    pk=material_id, item_type="MATERIAL", archived_at__isnull=True,
                ).first()
                if material is None:
                    issues.append("MATERIAL_IDENTITY_MISSING")
                elif line.section_type_snapshot != "PROFILE" and (
                    line.source_unit_text not in {material.unit.unit_name, material.unit.unit_code}
                    or str(identity.get("unit_id") or material.unit_id) != str(material.unit_id)
                ):
                    issues.append("UNIT_MISMATCH")
            snapshot["calculation_snapshot"] = identity
            if line.section_type_snapshot == "PROFILE" and not line.raw_bar_length_m:
                issues.append("PIPE_PARAMETERS_MISSING")
            group_line = GroupLine.objects.using(alias).create(
                purchase_group_id=group.pk, line_number=line.line_number,
                source_bom_line_id_snapshot=line.source_bom_line_id_snapshot,
                product_line_id_snapshot=line.product_line_id_snapshot,
                required_quantity=line.required_quantity, source_unit_text=line.source_unit_text,
                source_snapshot=snapshot, compatibility_issues=issues,
            )
            Line.objects.using(alias).filter(pk=line.pk).update(purchase_group_line_id=group_line.pk)
        Order.objects.using(alias).filter(pk=order.pk).update(purchase_group_id=group.pk, batch_number=1, batch_type="NORMAL")


def backwards(apps, schema_editor):
    alias = schema_editor.connection.alias
    Order = apps.get_model("procurement", "PurchaseOrder")
    Group = apps.get_model("procurement", "PurchaseGroup")
    # 一旦启用新批次，不允许回退掉归属；应停写并按已审计划恢复，而不是抹掉新履约。
    if (Order.objects.using(alias).filter(batch_request_id__isnull=False).exists()
            or Group.objects.using(alias).filter(batches__isnull=True).exists()):
        raise RuntimeError("已有新采购批次，不能自动回退总单归属；请先制定并确认数据恢复计划。")
    # 无新批次时保留附加归属供旧代码兼容运行。回退0024才移除新增字段/表，不触原履约数据。


class Migration(migrations.Migration):
    dependencies = [("procurement", "0024_purchase_groups")]
    operations = [migrations.RunPython(forwards, backwards)]
