"""只追加公共配置；不更新目录、历史快照或旧原料组合行。"""
import json
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.material_catalog.models import MaterialAllowedUnit, MaterialAttributeValue
from apps.material_catalog.colors import color_metadata
from apps.material_catalog.public_configuration import ensure_public_value


class Command(BaseCommand):
    help = "从有效新原料使用值提取公共配置；默认只读，--apply 才追加，重复运行不会复制。"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        apply = options["apply"]
        seen = set()
        counts = Counter()
        groups = Counter()
        conflicts = []
        values = MaterialAttributeValue.objects.filter(
            archived_at__isnull=True, catalog__archived_at__isnull=True,
        ).select_related("catalog", "parent", "product_color").order_by("catalog_id", "created_at", "id")
        units = MaterialAllowedUnit.objects.filter(
            archived_at__isnull=True, catalog__archived_at__isnull=True,
        ).select_related("catalog", "unit").order_by("catalog_id", "id")
        for row in values.iterator():
            parent_value = row.parent.value if row.parent_id else None
            color = color_metadata(row.product_color) if row.product_color_id else None
            value = row.product_color.color_name if row.product_color_id else row.value
            key = (row.catalog.category_key, row.catalog.template_key, row.scope, row.field_key, value, parent_value, row.product_color_id)
            if key in seen:
                counts["deduplicated"] += 1
                continue
            seen.add(key)
            group = "/".join(key[:4])
            try:
                if row.parent_id and (row.parent.archived_at is not None or row.parent.catalog_id != row.catalog_id):
                    raise ValidationError("尺寸对应的目录形状已移除或不属于当前品名。")
                with transaction.atomic():
                    existed = ensure_public_value(row.catalog, row.scope, row.field_key, value,
                                                  parent_value=parent_value, persist=False, color=color)
                    if apply:
                        ensure_public_value(row.catalog, row.scope, row.field_key, value, parent_value=parent_value, color=color)
                counts["existing" if existed is not None else ("appended" if apply else "would_append")] += 1
                groups[group] += 1
            except ValidationError as exc:
                counts["conflicts"] += 1
                conflicts.append({"category": group, "catalog_id": str(row.catalog_id), "attribute_id": str(row.pk), "reason": str(exc.detail)})
        for row in units.iterator():
            key = (row.catalog.category_key, row.catalog.template_key, row.scope, "unit", row.unit.unit_name, None)
            if key in seen:
                counts["deduplicated"] += 1
                continue
            seen.add(key)
            try:
                ensure_public_value(row.catalog, row.scope, "unit", row.unit.unit_name, persist=False)
                counts["existing_units"] += 1
            except ValidationError as exc:
                counts["conflicts"] += 1
                conflicts.append({"category": "/".join(key[:4]), "catalog_id": str(row.catalog_id), "unit_id": str(row.unit_id), "reason": str(exc.detail)})
        self.stdout.write(json.dumps({"mode": "apply" if apply else "dry-run", "counts": dict(counts),
                                      "groups": dict(groups), "conflicts": conflicts}, ensure_ascii=False, indent=2))
