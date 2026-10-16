"""BOM 确认只允许回写当前来源报价行的产品信息。"""

from django.db import connection, transaction


BOM_PRODUCT_FIELDS = [
    "product", "product_category", "product_unit", "product_color",
    "product_number_snapshot", "product_code_snapshot", "item_number_snapshot",
    "product_description_snapshot", "specification_snapshot", "color_snapshot",
    "material_snapshot", "unit_code", "updated_at",
]


def save_bom_product_information(line):
    # 标记仅在当前事务、当前报价行内有效；触发器另外检查字段白名单。
    # 保存点保证数据库拒绝更新后仍能恢复标记，不将特殊权限留给后续操作。
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('haiqu.bom_product_writeback_line', true)")
            previous = cursor.fetchone()[0] or ""
            cursor.execute("SELECT set_config('haiqu.bom_product_writeback_line', %s, true)", [str(line.pk)])
        try:
            with transaction.atomic():
                line.save(update_fields=BOM_PRODUCT_FIELDS)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('haiqu.bom_product_writeback_line', %s, true)", [previous])
