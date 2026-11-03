"""成品库存以具体属性分组，不把主档维护版本当成库存差异。"""
from django.db.models import F, TextField
from django.db.models.functions import Cast, JSONObject, MD5


def finished_product_selection_key(snapshot_field="production_task_product__product_selection_snapshot"):
    return MD5(Cast(JSONObject(**{
        field: F(f"{snapshot_field}__{field}")
        for field in ("color_id", "color_name", "material", "thickness")
    }), output_field=TextField()))
