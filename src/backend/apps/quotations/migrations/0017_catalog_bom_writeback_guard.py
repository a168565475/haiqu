from importlib import import_module

from django.db import migrations


# 保留原触发器的事务标记和商业字段保护，只扩展产品身份字段白名单。
REVERSE_SQL = import_module("apps.quotations.migrations.0015_bom_product_writeback_guard").FORWARD_SQL
FORWARD_SQL = REVERSE_SQL.replace(
    "'product_id', 'product_category_id'",
    "'product_catalog_id', 'product_selection_snapshot', 'product_id', 'product_category_id'",
)


class Migration(migrations.Migration):
    dependencies = [("quotations", "0016_product_catalog_selection")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
