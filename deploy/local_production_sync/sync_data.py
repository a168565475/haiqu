"""Read production data on the server and replace its counterpart in the local database."""

import base64
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime
from pathlib import PurePosixPath

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection, transaction
from psycopg import sql


PROCESS_TABLE = re.compile(
    r"^(?:production_(?:task|schedule|delivery_batch|run_batch)(?:_|$)|production_tasks_productiontaskexpense$|"
    r"bom(?:_|$)|procurement_(?:purchase_(?:group|order|return)|supplier_purchase_sheet|tracking_(?:issue|notice))(?:_|$)|"
    r"purchase_request(?:_|$)|inventory_(?:assembly_receipt_source|finished_goods|internal_semi_receipt|"
    r"material_(?:inbound|stock|transfer)|public_stock_(?:balance|movement)|semi_finished_stock)(?:_|$)|"
    r"material_issue(?:_|$)|order_semi_finished_requirement$|metal_(?:processing|original_handoff)_|"
    r"outsourcing_(?:order|factory_allocation|dispatch|return|raw_return|reconciliation|material_item|processing_item)(?:_|$)|"
    r"tube_(?:outsourcing|plan)_|workshop_(?:plan_execution|wage_scheme|work_item|work_report)(?:_|$)|"
    r"finance_(?:purchase_payable(?:_line)?|supplier_(?:allocation|offset|payment(?:_application(?:_line)?)?))$)"
)
# Shared documents are owned by their selected lines, or by their selected stock movements.
SHARED_LINKS = {
    ("inventory_finished_goods_outbound_line", "outbound_id"),
    ("inventory_public_stock_movement", "balance_id"),
    ("finance_supplier_allocation", "offset_id"),
    ("finance_supplier_offset", "payment_id"),
    ("finance_supplier_payment", "application_id"),
    ("finance_supplier_payment_application_line", "application_id"),
}
STOCK_SOURCES = {
    "MATERIAL_INBOUND": "inventory_material_inbound",
    "MATERIAL_ISSUE": "material_issue",
    "MATERIAL_TRANSFER": "inventory_material_transfer",
    "INTERNAL_SEMI_RECEIPT": "inventory_internal_semi_receipt",
    "OUTSOURCING_DISPATCH": "outsourcing_dispatch",
    "OUTSOURCING_RETURN": "outsourcing_return",
    "OUTSOURCING_RAW_RETURN": "outsourcing_raw_return",
    "TUBE_OUTSOURCING_RECEIPT": "tube_outsourcing_receipt",
    "PURCHASE_RETURN": "procurement_purchase_return",
}
HISTORY_GUARDS = {
    "production_schedule": "ps_schedule_no_delete",
    "production_schedule_product": "ps_schedule_product_no_delete",
    "production_schedule_product_craft": "ps_schedule_craft_no_delete",
}
MASTER_KEYS = {
    "business_file": ("storage_key",),
    "customer_account": ("account_code",),
    "employee": ("employee_code",),
    "finance_account": ("code",),
    "inventory_warehouse": ("warehouse_number",),
    "inventory_warehouse_zone": ("warehouse_id", "zone_name"),
    "inventory_warehouse_location": ("zone_id", "location_number"),
    "material_catalog": ("category_key", "template_key", "name"),
    "procurement_purchase_contract_template": ("template_code",),
    "procurement_purchase_contract_template_version": ("template_id", "version_number"),
    "procurement_supplier": ("supplier_number",),
    "product_catalog": ("product_code",),
    "product_catalog_category": ("name",),
    "product_catalog_name": ("category_id", "name"),
    "product_information": ("product_number",),
    "raw_material_information": ("material_number",),
    "reference_currency": ("code",),
    "reference_product_category": ("category_name",),
    "reference_product_color": ("color_code",),
    "reference_production_unit": ("unit_code", "catalog_owner_id"),
    "sales_order": ("order_number",),
    "sales_order_line": ("sales_order_id", "line_number"),
    "sales_order_delivery_batch": ("sales_order_id", "line_number"),
    "sales_order_delivery_batch_line": ("delivery_batch_id", "sales_order_line_id"),
    "workshop_config_craft": ("workshop_id", "name"),
    "workshop_config_operation": ("operation_number",),
    "workshop_config_workshop": ("name",),
}
COPY_MASTERS = frozenset({
    "business_file", "material_catalog", "material_catalog_attribute_value", "material_catalog_allowed_unit",
    "procurement_purchase_contract_template", "procurement_purchase_contract_template_version",
    "product_catalog", "product_catalog_category", "product_catalog_name", "product_catalog_color",
    "raw_material_information", "reference_product_color", "reference_production_unit",
})
MASTER_CHILDREN = {
    "material_catalog_attribute_value": "catalog_id", "material_catalog_allowed_unit": "catalog_id",
    "product_catalog_color": "product_id",
}
LOCAL_ONLY = frozenset({"bom_nesting_job", "production_task_import", "procurement_tracking_notice"})
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)
MAX_FILE_BYTES = 100 * 1024 * 1024
MOVEMENT_TABLES = (
    "inventory_public_stock_movement", "inventory_material_stock_movement", "inventory_semi_finished_stock_movement",
)
MODEL_TABLES = {model._meta.db_table: model for model in apps.get_models()}


class SyncError(Exception):
    pass


class Database:
    def __init__(self, cursor):
        self.cursor = cursor
        self.columns = defaultdict(dict)
        for table, name, typ, required, generated, kind in self.query("""
            SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                   a.attgenerated, t.typname
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid JOIN pg_type t ON t.oid=a.atttypid
            WHERE n.nspname='public' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY c.relname, a.attnum
        """):
            if not generated:
                self.columns[table][name] = (typ, required, kind)
        self.links = self.query("""
            SELECT child.relname, a.attname, parent.relname, a.attnotnull
            FROM pg_constraint c
            JOIN pg_class child ON child.oid=c.conrelid JOIN pg_class parent ON parent.oid=c.confrelid
            JOIN pg_namespace n ON n.oid=child.relnamespace
            JOIN pg_attribute a ON a.attrelid=child.oid AND a.attnum=c.conkey[1]
            JOIN pg_attribute k ON k.attrelid=parent.oid AND k.attnum=c.confkey[1]
            WHERE n.nspname='public' AND c.contype='f' AND cardinality(c.conkey)=1 AND k.attname='id'
            ORDER BY child.relname,a.attname
        """)
        self.fks = defaultdict(dict)
        for child, field, parent, required in self.links:
            self.fks[child][field] = (parent, required)
        self.tables = {table for table, columns in self.columns.items() if "id" in columns and PROCESS_TABLE.match(table)}

    def query(self, statement, args=()):
        self.cursor.execute(statement, args)
        return self.cursor.fetchall()

    def values(self, table, columns, filters):
        projection = sql.SQL(",").join(sql.SQL("{}::text").format(sql.Identifier(c)) for c in columns)
        where = sql.SQL(" AND ").join(sql.SQL("{}::text = ANY(%s)").format(sql.Identifier(c)) for c in filters)
        return self.query(sql.SQL("SELECT {} FROM {} WHERE {}").format(projection, sql.Identifier(table), where),
                          [list(v) for v in filters.values()])

    def rows(self, table, ids):
        columns = list(self.columns[table])
        return {row[columns.index("id")]: dict(zip(columns, row, strict=True))
                for row in self.values(table, columns, {"id": ids})}

    def related_ids(self, table, field, ids):
        if not ids:
            return set()
        return {row[0] for row in self.values(table, ["id"], {field: ids})}

    def insert(self, table, row):
        fields = list(row)
        statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, fields)),
            sql.SQL(",").join(sql.SQL("%s::") + sql.SQL(self.columns[table][field][0]) for field in fields),
        )
        self.cursor.execute(statement, [row[field] for field in fields])


def production_ids(db, remote):
    root = "SELECT id::text FROM production_task"
    selected = defaultdict(set, production_task={r[0] for r in db.query(root)})
    edges = [edge for edge in db.links if edge[0] in db.tables and edge[2] in db.tables]
    while True:
        before = sum(map(len, selected.values()))
        for child, field, parent, _ in edges:
            if remote and child in LOCAL_ONLY:
                continue
            if (child, field) in SHARED_LINKS:
                if selected[child]:
                    selected[parent].update(value for value, in db.values(child, [field], {"id": selected[child]}) if value)
                continue
            selected[child].update(db.related_ids(child, field, selected[parent]))
        for table in MOVEMENT_TABLES:
            if {"source_type", "source_id"} <= db.columns[table].keys():
                for kind, parent in STOCK_SOURCES.items():
                    if selected[parent]:
                        selected[table].update(
                            value for value, in db.values(table, ["id"],
                                {"source_id": selected[parent], "source_type": {kind}})
                        )
                if selected[table]:
                    selected["inventory_material_transfer"].update(
                        value for value, in db.values(
                            table, ["source_id"], {"id": selected[table], "source_type": {"MATERIAL_TRANSFER"}},
                        ) if value
                    )
        if "workshop_work_report_history" in db.tables:
            selected["workshop_work_report_history"].update(
                db.related_ids("workshop_work_report_history", "report_id", selected["workshop_work_report"]))
            if selected["production_schedule_product"]:
                selected["workshop_work_report_history"].update(
                    value for value, in db.query("""
                        SELECT id::text FROM workshop_work_report_history
                        WHERE deletion_snapshot->>'schedule_product_id' = ANY(%s)
                    """, [list(selected["production_schedule_product"])])
                )
        if before == sum(map(len, selected.values())):
            break
    for child, field, parent, _ in edges:
        if (child, field) in SHARED_LINKS and db.related_ids(child, field, selected[parent]) - selected[child]:
            raise SyncError(f"{parent} 同时关联生产和其他业务，无法只替换生产部分。")
    return {table: ids for table, ids in selected.items() if ids}


def export_data(db):
    selected = production_ids(db, remote=True)
    rows = {table: db.rows(table, ids) for table, ids in selected.items()}
    masters = defaultdict(dict)
    desired = defaultdict(set)
    pending = list(rows.items())
    while pending:
        for table, entries in pending:
            for field, (parent, _) in db.fks[table].items():
                if parent not in db.tables and parent in (MASTER_KEYS.keys() | COPY_MASTERS):
                    desired[parent].update(row[field] for row in entries.values() if row[field] is not None)
            for child, field in MASTER_CHILDREN.items():
                if child in db.columns and db.fks[child].get(field, (None,))[0] == table:
                    desired[child].update(db.related_ids(child, field, entries))
        # Keep source and target schemas independent, including which references actually exist.
        pending = [(table, db.rows(table, ids - masters[table].keys())) for table, ids in desired.items()
                   if ids - masters[table].keys()]
        for table, entries in pending:
            if not entries or entries.keys() != desired[table] - masters[table].keys():
                raise SyncError(f"服务器关联数据不完整：{table}")
            masters[table].update(entries)

    files = {}
    remaining = MAX_FILE_BYTES
    for row in masters.get("business_file", {}).values():
        if row["scan_status"] not in {"CLEAN", "SKIPPED"}:
            continue
        key = row["storage_key"]
        with default_storage.open(key, "rb") as file:
            data = file.read(remaining + 1)
        remaining -= len(data)
        if remaining < 0 or len(data) != int(row["size_bytes"]):
            raise SyncError("服务器附件过大或读取不完整。")
        files[key] = base64.b64encode(data).decode("ascii")
    return {"rows": rows, "masters": masters, "files": files}


def local_match(db, table, row):
    existing = db.rows(table, [row["id"]]).get(row["id"])
    keys = MASTER_KEYS.get(table, ())
    if existing and all(existing.get(key) == row.get(key) for key in keys):
        return row["id"]
    if keys and all(key in db.columns[table] for key in keys):
        clauses = sql.SQL(" AND ").join(sql.SQL("{}::text IS NOT DISTINCT FROM %s").format(sql.Identifier(key)) for key in keys)
        active = sql.SQL(" AND archived_at IS NULL") if "archived_at" in db.columns[table] and not row.get("archived_at") else sql.SQL("")
        matches = db.query(sql.SQL("SELECT id::text FROM {} WHERE {}{} LIMIT 2").format(
            sql.Identifier(table), clauses, active), [row.get(key) for key in keys])
        if len(matches) == 1:
            return matches[0][0]
        if len(matches) > 1:
            raise SyncError(f"本地档案匹配到多条：{table}")
    if existing:
        raise SyncError(f"本地档案编号冲突：{table}")
    return None


def map_masters(db, masters):
    ids = {}
    new = defaultdict(dict)

    def find(table, key):
        if key in ids:
            return ids[key]
        row = masters.get(table, {}).get(key)
        if row is None or table not in db.columns:
            return None
        identity = dict(row)
        for field in MASTER_KEYS.get(table, ()):
            if field in db.fks[table] and row.get(field):
                identity[field] = find(db.fks[table][field][0], row[field])
                if identity[field] is None:
                    break
        else:
            ids[key] = local_match(db, table, identity)
        if not ids.get(key) and table in COPY_MASTERS:
            # Supplemental detail belongs to a newly copied parent. Existing local master data stays intact.
            owner = MASTER_CHILDREN.get(table)
            if owner is None or row[owner] in new[db.fks[table][owner][0]]:
                ids[key] = key
                new[table][key] = row
        return ids.get(key)

    for table, entries in masters.items():
        for key in entries:
            find(table, key)
    return ids, new


def row_values(db, table, row, mapping, process_rows):
    values = {name: row[name] for name in db.columns[table] if name in row}
    for field, (parent, required) in db.fks[table].items():
        key = values.get(field)
        if key is None:
            continue
        if key in process_rows.get(parent, {}) or db.related_ids(parent, "id", {key}):
            values[field] = mapping.get(key) or key
        elif mapping.get(key):
            values[field] = mapping[key]
        elif required:
            raise SyncError(f"本地缺少必需关联：{table}.{field}（{parent}）")
        else:
            values[field] = None
    # Remap IDs also stored in JSON snapshots without altering decimal literals.
    for name, value in values.items():
        if value is not None and db.columns[table][name][2] in {"json", "jsonb"}:
            values[name] = UUID.sub(lambda match: mapping.get(match.group()) or match.group(), value)
    model = MODEL_TABLES.get(table)
    for name in db.columns[table].keys() - values.keys():
        field = next((field for field in model._meta.local_fields if field.column == name), None) if model else None
        if field is not None and field.has_default():
            default = field.get_prep_value(field.get_default())
            if db.columns[table][name][2] in {"json", "jsonb"}:
                default = json.dumps(default, cls=field.encoder)
            values[name] = default
    return values


def import_files(payload, new, cleanup):
    needed = {row["storage_key"]: row for row in new.get("business_file", {}).values()}
    for key, row in needed.items():
        if key not in payload["files"]:
            continue
        path = PurePosixPath(key)
        if path.is_absolute() or ".." in path.parts or "\\" in key:
            raise SyncError("服务器附件路径无效。")
        data = base64.b64decode(payload["files"][key], validate=True)
        if row["content_hash"] and hashlib.sha256(data).hexdigest() != row["content_hash"]:
            raise SyncError("服务器附件内容不完整。")
        if default_storage.exists(key):
            with default_storage.open(key, "rb") as file:
                if hashlib.file_digest(file, "sha256").digest() != hashlib.sha256(data).digest():
                    raise SyncError("本地存在同路径的不同附件。")
        else:
            saved = default_storage.save(key, ContentFile(data))
            cleanup.callback(default_storage.delete, saved)
            if saved != key:
                raise SyncError("本地附件路径已占用。")


def insert_rows(db, rows, prepared):
    order = {
        # Immediate row triggers on schedules require these parents first.
        "production_task": 0, "production_task_product": 1, "production_schedule": 2,
        "production_schedule_product": 3, "production_schedule_product_craft": 4,
    }
    for table in sorted(rows, key=lambda name: order.get(name, 5)):
        for key in rows[table]:
            db.insert(table, prepared[table][key])


def replace_local(db, payload, cleanup):
    source = payload["rows"]
    if source.keys() - db.tables:
        raise SyncError("本地缺少服务器已使用的表：" + "、".join(sorted(source.keys() - db.tables)))
    before = production_ids(db, remote=False)
    mapping, new = map_masters(db, payload["masters"])
    # Resolve references while the current database is intact and before making any deletion.
    prepared = {table: {key: row_values(db, table, row, mapping, source) for key, row in entries.items()}
                for table, entries in (new | source).items()}
    import_files(payload, new, cleanup)

    for table, trigger in HISTORY_GUARDS.items():
        if before.get(table):
            db.cursor.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER {}").format(
                sql.Identifier(table), sql.Identifier(trigger)))
    for table in sorted(before, key=lambda name: (name == "production_task_product", name == "production_task")):
        db.cursor.execute(sql.SQL("DELETE FROM {} WHERE id::text = ANY(%s)").format(sql.Identifier(table)),
                          [sorted(before[table])])
    db.cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    for table, trigger in HISTORY_GUARDS.items():
        if before.get(table):
            db.cursor.execute(sql.SQL("ALTER TABLE {} ENABLE TRIGGER {}").format(
                sql.Identifier(table), sql.Identifier(trigger)))
    db.cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    insert_rows(db, new, prepared)
    insert_rows(db, source, prepared)
    advance_numbering(db, source)
    db.cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    return {"tasks": len(source.get("production_task", ())), "boms": len(source.get("bom", ()))}


def advance_numbering(db, source):
    from apps.core.daily_numbering import DAILY_NUMBER_RULES

    prefixes = {value: name for name, value in DAILY_NUMBER_RULES.items()}
    counters = {}
    for entries in source.values():
        for row in entries.values():
            for field, value in row.items():
                if not field.endswith("_number") or not value:
                    continue
                match = re.fullmatch(r"([A-Z]+)([0-9]{6})([0-9]{3,})", value)
                if match and match[1] in prefixes:
                    try:
                        date = datetime.strptime(match[2], "%y%m%d").date().replace(year=2000 + int(match[2][:2]))
                    except ValueError:
                        continue
                    key = (prefixes[match[1]], date)
                    counters[key] = max(counters.get(key, 0), int(match[3]))
    db.cursor.executemany("""
        INSERT INTO core_daily_business_number_counter AS current (number_type,business_date,last_value)
        VALUES (%s,%s,%s) ON CONFLICT (number_type,business_date)
        DO UPDATE SET last_value=greatest(current.last_value, excluded.last_value)
    """, [(*key, value) for key, value in counters.items()])


def main(mode):
    if mode == "export":
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            print(json.dumps(export_data(Database(cursor)), ensure_ascii=True, separators=(",", ":")))
        return
    if mode != "replace" or not settings.DEBUG or connection.settings_dict["HOST"] != "postgres":
        raise SyncError("只允许覆盖本地开发数据库。")
    payload = json.load(sys.stdin)
    with ExitStack() as cleanup:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute("SET LOCAL lock_timeout = '8s'")
            cursor.execute("SET LOCAL statement_timeout = '60s'")
            result = replace_local(Database(cursor), payload, cleanup)
        cleanup.pop_all()
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except SyncError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
