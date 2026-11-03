"""打样填料所需的只读品名、公共属性和工艺，不提供主档维护能力。"""

from django.db.models import Q

from apps.material_catalog import selectors
from apps.material_catalog.definitions import CATEGORIES, SPRAY_FIELDS


def source_options():
    return {"categories": CATEGORIES, "spray_fields": SPRAY_FIELDS, "units": [], "warehouses": []}


def source_detail(catalog):
    data = selectors.catalog_detail(catalog)
    # 打样只选择属性与单位，不暴露主档的仓库配置。
    data["base_warehouse_id"] = None
    data["semi_warehouse_id"] = None
    return data


def source_crafts():
    from apps.inventory.public_stock_identity import _craft
    from apps.workshop_config.models import Craft

    crafts = Craft.objects.filter(status="ACTIVE").filter(
        Q(craft_type="INTERNAL", plan_category__in=["CUTTING", "SEWING"])
        | Q(craft_type="EXTERNAL", outsourcing_code__in=["CUTTING", "SEWING", "EMBROIDERY", "SCREEN_PRINTING"])
    )
    return {"crafts": [{**_craft(craft), "name": craft.name} for craft in crafts]}
