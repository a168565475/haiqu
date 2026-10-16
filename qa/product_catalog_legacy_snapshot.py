"""通过 manage.py shell 在当前真实数据库只读摘要旧产品及受保护下游表。"""
import hashlib
import json

from django.apps import apps
from django.db import connection, transaction


protected_apps = {
    "products", "reference_data", "material_catalog", "sales_orders", "boms",
    "procurement", "production_tasks", "production_scheduling", "inventory",
    "material_issues", "outsourcing", "workshop_config", "workshop_reporting",
}
tables = sorted({
    model._meta.db_table
    for model in apps.get_models()
    if model._meta.app_label in protected_apps and model._meta.managed
})
result = {"mode": "read-only-protected-data-snapshot", "tables": []}
with transaction.atomic(), connection.cursor() as cursor:
    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    for table in tables:
        quoted = connection.ops.quote_name(table)
        cursor.execute(
            f"SELECT count(*), coalesce(string_agg(row_hash, '' ORDER BY row_hash), '') "
            f"FROM (SELECT md5(to_jsonb(row_data)::text) AS row_hash FROM {quoted} row_data) hashed"
        )
        count, contents = cursor.fetchone()
        result["tables"].append({"table": table, "count": count, "sha256": hashlib.sha256(contents.encode()).hexdigest()})
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
