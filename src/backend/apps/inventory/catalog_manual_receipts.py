"""手工入库复用目录选料校验；原始请求用于重试，不用补录后的目录版本比较。"""
import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace

from django.db import connection
from rest_framework.exceptions import ValidationError

from apps.boms.catalog_selection import SECTION_CATEGORIES, apply_catalog_selection
from apps.material_catalog.models import MaterialCatalog
from apps.procurement.pipe_purchase import pipe_meters


def manual_request_snapshot(*, inbound_date, remark, items):
    def encode(value):
        if isinstance(value, Decimal):
            return format(value.normalize(), "f")
        return str(value)
    lines = [json.dumps(item, default=encode, ensure_ascii=False, sort_keys=True) for item in items]
    return {"inbound_date": str(inbound_date), "remark": remark,
            "items": [json.loads(value) for value in sorted(lines)]}


def lock_manual_request(client_request_id):
    key = hashlib.sha256(f"manual-material-inbound:{client_request_id}".encode()).digest()
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [int.from_bytes(key[:8], "big", signed=True)])


def resolve_manual_catalog(item, *, request, versions):
    """仅做选料投影，不创建BOM；权限、版本、属性补录全部走U2正式服务。"""
    selection = item.get("material_selection")
    if not selection or selection.get("processing_state") != "RAW":
        raise ValidationError({"material_selection": "手工原料入库须选择原料；加工结果须经保存实际加工属性的来源入库。"})
    catalog = MaterialCatalog.objects.filter(pk=item["material_catalog_id"], archived_at__isnull=True).first()
    if catalog is None:
        raise ValidationError({"material_catalog_id": "原料品名不存在或已归档。"})
    title = next((name for name, category in SECTION_CATEGORIES.items() if category == catalog.category_key), None)
    if not title or catalog.category_key == "FABRIC_SEMI":
        raise ValidationError({"material_catalog_id": "该品名不是可手工入库的基础原料。"})
    projection = SimpleNamespace(section=SimpleNamespace(title=title, section_type="PROFILE" if catalog.category_key == "TUBE" else "GENERAL"), raw_values={})
    apply_catalog_selection(projection, item, old=None, request=request, persist=True, versions=versions)
    selected = projection.material_selection_snapshot
    auxiliary = {}
    bars, length = item.get("received_bar_count"), item.get("raw_bar_length_m")
    if selected["category_key"] == "TUBE" or bars is not None or length is not None:
        if selected["category_key"] != "TUBE" or selected["unit_name"] != "根":
            raise ValidationError({"received_bar_count": "仅按根入库的管材可以填写根米辅助参数。"})
        _, meters = pipe_meters(bars, length, field="received_bar_count")
        item["received_quantity"] = meters
        auxiliary = {"received_bar_count": bars, "raw_bar_length_m": str(length), "received_meters": str(meters)}
    quantity = item.get("received_quantity")
    if quantity is None or quantity <= 0:
        raise ValidationError({"received_quantity": "请填写所选单位下的实际到货数量。"})
    if selected["category_key"] != "TUBE" and selected["unit_name"] in {"根", "支", "套"} and quantity != quantity.to_integral_value():
        raise ValidationError({"received_quantity": "根、支、套数量须为整数。"})
    item["material_selection_snapshot"] = selected
    item["section_title"] = title
    item["specification"] = projection.specification
    item["calculation_snapshot"] = auxiliary
    return selected
