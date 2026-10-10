import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ...models import Craft, CraftType, Operation, RecordStatus
from ...workbook_import import analyze_operation_correction_workbook


class Command(BaseCommand):
    help = "预检或从工序修正表导入已确认保留的工序；默认只执行 dry-run。"

    def add_arguments(self, parser):
        parser.add_argument("--operations", required=True, help="工序修正工作簿路径")
        parser.add_argument("--expect-source-operations", type=int, default=947)
        parser.add_argument("--expect-import-operations", type=int, default=776)
        parser.add_argument("--expect-duplicate-business-exclusions", type=int, default=117)
        parser.add_argument("--expect-missing-product-exclusions", type=int, default=21)
        parser.add_argument("--expect-placeholder-product-exclusions", type=int, default=33)
        parser.add_argument("--expect-existing-crafts", type=int, default=10)
        parser.add_argument("--expect-existing-operations", type=int)
        parser.add_argument("--apply", action="store_true", help="通过全部校验后写入数据库")

    def handle(self, *args, **options):
        try:
            plan = analyze_operation_correction_workbook(
                operation_path=options["operations"],
                expected_source_operations=options["expect_source_operations"],
                expected_import_operations=options["expect_import_operations"],
                expected_duplicate_business_exclusions=options["expect_duplicate_business_exclusions"],
                expected_missing_product_exclusions=options["expect_missing_product_exclusions"],
                expected_placeholder_product_exclusions=options["expect_placeholder_product_exclusions"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        crafts = list(Craft.objects.select_related("workshop"))
        craft_map = {
            (
                craft.get_craft_type_display(),
                craft.workshop.name if craft.workshop_id else "",
                craft.name,
            ): craft
            for craft in crafts
        }
        database_blockers = []
        if len(crafts) != options["expect_existing_crafts"]:
            database_blockers.append(
                {
                    "code": "UNEXPECTED_DATABASE_CRAFT_COUNT",
                    "message": (
                        "数据库现有工艺数变化，"
                        f"预期 {options['expect_existing_crafts']}，实际 {len(crafts)}。"
                    ),
                    "count": abs(len(crafts) - options["expect_existing_crafts"]),
                }
            )

        missing_craft_rows = []
        inactive_craft_rows = []
        for row in plan.operations:
            craft = craft_map.get((row["类型"], row["车间"], row["工艺"]))
            if craft is None:
                missing_craft_rows.append(row["源行号"])
            elif craft.status != RecordStatus.ACTIVE:
                inactive_craft_rows.append(row["源行号"])
        if missing_craft_rows:
            database_blockers.append(
                {
                    "code": "OPERATION_CRAFT_NOT_FOUND",
                    "message": "待导入工序无法精确匹配数据库中的类型、车间和工艺。",
                    "count": len(missing_craft_rows),
                    "sample_source_rows": missing_craft_rows[:20],
                }
            )
        if inactive_craft_rows:
            database_blockers.append(
                {
                    "code": "OPERATION_CRAFT_INACTIVE",
                    "message": "待导入工序关联了已停用工艺。",
                    "count": len(inactive_craft_rows),
                    "sample_source_rows": inactive_craft_rows[:20],
                }
            )

        actual_existing_operations = Operation.objects.count()
        expected_existing_operations = options.get("expect_existing_operations")
        if (
            expected_existing_operations is not None
            and actual_existing_operations != expected_existing_operations
        ):
            database_blockers.append(
                {
                    "code": "UNEXPECTED_DATABASE_OPERATION_COUNT",
                    "message": (
                        "数据库现有工序数变化，"
                        f"预期 {expected_existing_operations}，实际 {actual_existing_operations}。"
                    ),
                    "count": abs(actual_existing_operations - expected_existing_operations),
                }
            )

        report = {
            **plan.report,
            "can_apply": plan.report["can_apply"] and not database_blockers,
            "counts": {
                **plan.report["counts"],
                "database_crafts": len(crafts),
                "database_operations_before_import": actual_existing_operations,
            },
            "blockers": [*plan.report["blockers"], *database_blockers],
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))

        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS("工序 dry-run 完成：未写入数据库。"))
            return
        if not report["can_apply"]:
            raise CommandError("工序修正表或数据库前置条件存在阻断项，禁止写入数据库。")
        if expected_existing_operations is None:
            raise CommandError("--apply 必须提供 --expect-existing-operations 参数。")
        if actual_existing_operations:
            raise CommandError("初始工序导入只允许写入空工序表，禁止覆盖现有配置。")

        with transaction.atomic():
            if Operation.objects.count() != expected_existing_operations:
                raise CommandError("事务开始前工序数量发生变化，已取消本次导入。")
            Operation.objects.bulk_create(
                [
                    Operation(
                        operation_number=row["最终工序编号"].upper(),
                        product_name=row["最终品名"],
                        craft=craft_map[(row["类型"], row["车间"], row["工艺"])],
                        name=row["工序"],
                        status=RecordStatus.ACTIVE,
                    )
                    for row in plan.operations
                ],
                batch_size=500,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"工序正式导入完成：{len(plan.operations)} 条，排除 {len(plan.excluded_operations)} 条问题行。"
            )
        )
