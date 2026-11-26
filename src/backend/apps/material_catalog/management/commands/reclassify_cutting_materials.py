import json
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.boms.catalog_selection import required_fields
from apps.core.api.concurrency import etag_for_instance
from apps.core.audit import write_audit_log
from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
from apps.inventory.catalog_stock_queries import available_catalog_balances
from apps.inventory.models import PublicStockBalance
from apps.material_catalog.editing import archive_catalog, create_catalog
from apps.material_catalog.models import MaterialAttributeValue, MaterialCatalog
from apps.material_catalog.selectors import catalog_detail, require_catalog_attribute, require_catalog_unit
from apps.material_catalog.snapshots import build_material_snapshot


ARCHIVE_NAMES = ("外袋布", "椅面布", "管套", "背贴", "裁片")
FABRIC_TEMPLATES = {"珍珠棉": "COTTON", "网布": "AUXILIARY_GENERAL"}


def check_stock(catalog, apply, changes):
    checks = []
    for balance in PublicStockBalance.objects.filter(material_catalog=catalog):
        old = balance.identity_snapshot["material_selection_snapshot"]
        attrs = old["attributes"]
        thickness_missing = (catalog.name == "珍珠棉" and attrs.get("thickness") == "1.5"
                             and not catalog.attribute_values.filter(scope="BASE", field_key="thickness", value="1.5").exists())
        if thickness_missing:
            changes.append("从本库珍珠棉已有库存补回厚度选项：1.5")
            if apply:
                MaterialAttributeValue.objects.create(catalog=catalog, scope="BASE", field_key="thickness", value="1.5")
        if thickness_missing and not apply:
            selection = {**old, "category_key": catalog.category_key}
        else:
            color = require_catalog_attribute(catalog, "BASE", "color", attrs["color"], color=old) if attrs.get("color") else None
            selection = build_material_snapshot(
                catalog=catalog, scope="BASE", processing_state="RAW", attributes=attrs,
                unit_id=old["unit_id"], required_fields=required_fields(catalog.template_key, attrs), color_option=color,
            )
        identity = build_catalog_stock_identity(material_catalog_id=catalog.pk, material_selection_snapshot=selection)
        if identity["identity_key"] != balance.identity_key:
            raise CommandError(f"{catalog.name} 新选择与既有余额身份不同。")
        kwargs = {"material_catalog_id": catalog.pk, "zone_id": balance.zone_id}
        old_stock = available_catalog_balances(**kwargs, material_selection_snapshot=old)
        new_stock = available_catalog_balances(**kwargs, material_selection_snapshot=selection)
        if old_stock != new_stock:
            raise CommandError(f"{catalog.name} 新旧选料的领料可用库存不同。")
        item = next((row for row in new_stock if row["balance_id"] == str(balance.pk)), None)
        checks.append({"余额": str(balance.quantity), "可用": str(item["available_quantity"]) if item else "0",
                       "单位": old["unit_name"], "身份一致": True})
    return checks


class Command(BaseCommand):
    help = "调整已确认的面料和裁片名录。默认只读核对，--apply 在一个事务内写入。"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        apply = options["apply"]
        query = MaterialCatalog.objects.filter(
            Q(category_key="FABRIC", name__in=ARCHIVE_NAMES)
            | Q(category_key__in=["AUXILIARY", "FABRIC"], name__in=FABRIC_TEMPLATES)
            | Q(category_key="FABRIC_SEMI", name__in=["网布", "珍珠棉片"])
        ).order_by("pk")
        rows = {(item.category_key, item.name): item for item in (query.select_for_update() if apply else query)}
        changes = []
        stock = {}
        for name, template in FABRIC_TEMPLATES.items():
            old, current = rows.get(("AUXILIARY", name)), rows.get(("FABRIC", name))
            if (old is None) == (current is None):
                raise CommandError(f"{name} 来源或目标不唯一。")
            catalog = old or current
            if catalog.archived_at or catalog.template_key != template:
                raise CommandError(f"{name} 状态或模板不符合本次已确认范围。")
            require_catalog_unit(catalog, "BASE", unit_name="米")
            if old:
                before = catalog_detail(catalog) if apply else None
                catalog.category_key = "FABRIC"
                changes.append(f"转入面料：{name}")
                if apply:
                    catalog.save(update_fields=["category_key", "updated_at"])
            stock[name] = check_stock(catalog, apply, changes)
            if old and apply:
                write_audit_log(object_type="MATERIAL_CATALOG", object_id=catalog.pk, action="RECLASSIFIED",
                                before_data=before, after_data=catalog_detail(catalog))

        mesh = rows.get(("FABRIC_SEMI", "网布"))
        if mesh is None or mesh.archived_at:
            raise CommandError("应沿用的裁片网布不存在或已归档。")
        piece = rows.get(("FABRIC_SEMI", "珍珠棉片"))
        if piece and piece.archived_at:
            raise CommandError("裁片珍珠棉片已归档，请核对。")
        if piece is None:
            changes.append("新增裁片品名：珍珠棉片")
            if apply:
                create_catalog(data={"category_key": "FABRIC_SEMI", "template_key": "FABRIC_SEMI",
                                     "name": "珍珠棉片", "values": []}, request=None)
        for name in ARCHIVE_NAMES:
            item = rows.get(("FABRIC", name))
            if item is not None and item.archived_at is None:
                changes.append(f"归档面料品名：{name}")
                if apply:
                    request = SimpleNamespace(headers={"If-Match": etag_for_instance(item)}, META={})
                    archive_catalog(catalog_id=item.pk, request=request)
        self.stdout.write(json.dumps({"模式": "执行" if apply else "预览", "变更": changes, "库存": stock},
                                     ensure_ascii=False))
