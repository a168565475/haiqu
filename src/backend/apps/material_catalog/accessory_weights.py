"""辅料克重的单一候选视图：规格事实只读派生，独立补录沿用公共属性表。"""
from apps.reference_data.models import AccessorySpecification, MaterialAttributePublicValue


WEIGHT_FIELDS = {"category_key": "AUXILIARY", "template_key": "COTTON", "scope": "BASE", "field_key": "gram_weight"}


def is_accessory_weight(category_key, template_key, scope, field_key):
    return (category_key, template_key, scope, field_key) == ("AUXILIARY", "COTTON", "BASE", "gram_weight")


def specification_weights():
    return AccessorySpecification.objects.filter(
        status="ACTIVE", archived_at__isnull=True,
        product_name__status="ACTIVE", product_name__archived_at__isnull=True,
    )


def find_specification_weight(value, *, lock=False):
    for row in specification_weights().order_by("id"):
        if row.weight.strip() != value:
            continue
        if not lock:
            return row
        current = specification_weights().select_related("product_name").select_for_update().filter(pk=row.pk).first()
        if current is not None and current.weight.strip() == value:
            return current
    return None


def accessory_weight_records():
    """全状态补录值覆盖同值派生项；停用/归档记录不能由旧规格隐式复活。"""
    entries = {}
    for row in specification_weights().order_by("id"):
        value = row.weight.strip()
        if value in {"", "/", "-", "—"}:
            continue
        if value in entries:
            entries[value]["source_count"] += 1
            entries[value]["updated_at"] = max(entries[value]["updated_at"], row.updated_at.isoformat())
        else:
            entries[value] = {
                "id": str(row.pk), **WEIGHT_FIELDS, "value": value,
                "status": "ACTIVE", "sort_order": 0, "description": "",
                "updated_at": row.updated_at.isoformat(), "archived_at": None,
                "source_kind": "SPECIFICATION", "editable": False, "source_count": 1,
            }
    for row in MaterialAttributePublicValue.objects.filter(**WEIGHT_FIELDS):
        value = row.value.strip()
        entries[value] = {
            "id": str(row.pk), **WEIGHT_FIELDS, "value": value,
            "status": row.status, "sort_order": row.sort_order, "description": row.description,
            "updated_at": row.updated_at.isoformat(), "archived_at": row.archived_at.isoformat() if row.archived_at else None,
            "source_kind": "PUBLIC", "editable": True, "source_count": entries.get(value, {}).get("source_count", 0),
        }
    return sorted(entries.values(), key=lambda row: (row["sort_order"], row["value"], row["id"]))
