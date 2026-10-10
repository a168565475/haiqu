import json

from django.core.management.base import BaseCommand, CommandError

from apps.inventory.workbook_import import WarehouseWorkbookImportError, build_warehouse_import_plan, execute_warehouse_import


class Command(BaseCommand):
    help = "预检或导入仓库与库位 XLSX；默认只读，写入必须传完整保护参数。"

    def add_arguments(self, parser):
        parser.add_argument("warehouse_file")
        parser.add_argument("location_file")
        parser.add_argument("--expect-warehouses", type=int, required=True)
        parser.add_argument("--expect-location-rows", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expect-existing-warehouses", type=int)
        parser.add_argument("--expect-existing-locations", type=int)

    def handle(self, *args, **options):
        try:
            plan = build_warehouse_import_plan(options["warehouse_file"], options["location_file"])
            if len(plan.warehouses) != options["expect_warehouses"]:
                raise WarehouseWorkbookImportError("仓库行数与预期不一致。")
            if plan.source_location_rows != options["expect_location_rows"]:
                raise WarehouseWorkbookImportError("库位维护行数与预期不一致。")
            summary = {"mode": "dry-run", "warehouse_count": len(plan.warehouses), "zone_count": len(plan.zones), "location_count": len(plan.locations), "duplicate_location_keys": plan.duplicate_location_keys}
            if options["apply"]:
                if options["expect_existing_warehouses"] is None or options["expect_existing_locations"] is None:
                    raise WarehouseWorkbookImportError("正式导入必须传入两项现有数据保护参数。")
                summary["mode"] = "apply"
                summary["result"] = execute_warehouse_import(plan, expected_existing_warehouses=options["expect_existing_warehouses"], expected_existing_locations=options["expect_existing_locations"])
            self.stdout.write(json.dumps(summary, ensure_ascii=False))
        except WarehouseWorkbookImportError as exc:
            raise CommandError(str(exc)) from exc
