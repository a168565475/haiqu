import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ...models import Craft, CraftType, Operation, PlanCategory, RecordStatus
from ...workbook_import import analyze_operation_correction_workbook


class Command(BaseCommand):
    help = "从已核对的工序修正表定向导入金工车间管材加工工序；默认仅预检。"

    def add_arguments(self, parser):
        parser.add_argument("--operations", required=True, help="工序修正工作簿路径")
        parser.add_argument("--expect-source-operations", type=int, default=947)
        parser.add_argument("--expect-import-operations", type=int, default=776)
        parser.add_argument("--expect-duplicate-business-exclusions", type=int, default=117)
        parser.add_argument("--expect-missing-product-exclusions", type=int, default=21)
        parser.add_argument("--expect-placeholder-product-exclusions", type=int, default=33)
        parser.add_argument("--expect-metal-operations", type=int, default=33)
        parser.add_argument("--expect-existing-operations", type=int)
        parser.add_argument("--expect-existing-metal-operations", type=int)
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

        rows = [
            row for row in plan.excluded_operations
            if row["类型"] == "厂内"
            and row["车间"] == "金工车间"
            and row["工艺"] == "管材加工"
            and row["最终品名"] == "-"
            and row["修正状态"] == "待确认占位品名"
        ]
        crafts = list(Craft.objects.filter(
            craft_type=CraftType.INTERNAL,
            workshop__name="金工车间",
            name="管材加工",
            plan_category=PlanCategory.METAL,
            status=RecordStatus.ACTIVE,
        ))
        operation_numbers = [str(row["最终工序编号"] or "").strip().upper() for row in rows]
        operation_names = [str(row["工序"] or "").strip() for row in rows]
        blockers = list(plan.report["blockers"])
        if len(rows) != options["expect_metal_operations"]:
            blockers.append({
                "code": "UNEXPECTED_METAL_OPERATION_COUNT",
                "message": "金工工序数量与预期不一致。",
                "expected": options["expect_metal_operations"],
                "actual": len(rows),
            })
        if len(crafts) != 1:
            blockers.append({
                "code": "METAL_CRAFT_NOT_UNIQUE",
                "message": "无法唯一匹配启用的金工车间管材加工工艺。",
                "actual": len(crafts),
            })
        invalid_rows = []
        for row, operation_number, operation_name in zip(rows, operation_numbers, operation_names):
            errors = []
            if not operation_number:
                errors.append("工序编号为空")
            elif len(operation_number) > Operation._meta.get_field("operation_number").max_length:
                errors.append("工序编号过长")
            if not operation_name:
                errors.append("工序名称为空")
            elif len(operation_name) > Operation._meta.get_field("name").max_length:
                errors.append("工序名称过长")
            if errors:
                invalid_rows.append({"source_row": row["源行号"], "errors": errors})
        duplicate_numbers = sorted({number for number in operation_numbers if operation_numbers.count(number) > 1})
        duplicate_names = sorted({name for name in operation_names if operation_names.count(name) > 1})
        if invalid_rows:
            blockers.append({
                "code": "INVALID_METAL_OPERATION_FIELDS",
                "message": "待导入金工工序存在空值或超长字段。",
                "count": len(invalid_rows),
                "sample_rows": invalid_rows[:20],
            })
        if duplicate_numbers or duplicate_names:
            blockers.append({
                "code": "DUPLICATE_METAL_OPERATION_KEYS",
                "message": "待导入金工工序中存在重复编号或重复名称。",
                "duplicate_operation_numbers": duplicate_numbers[:20],
                "duplicate_operation_names": duplicate_names[:20],
            })

        actual_existing_operations = Operation.objects.count()
        craft = crafts[0] if len(crafts) == 1 else None
        actual_existing_metal_operations = Operation.objects.filter(craft=craft).count() if craft else 0
        expected_existing_operations = options.get("expect_existing_operations")
        expected_existing_metal_operations = options.get("expect_existing_metal_operations")
        existing_by_number = {
            item.operation_number: item
            for item in Operation.objects.filter(operation_number__in=operation_numbers)
        }
        exact_existing_numbers = set()
        collisions = []
        if craft:
            for operation_number, operation_name in zip(operation_numbers, operation_names):
                existing = existing_by_number.get(operation_number)
                if existing is None:
                    continue
                if (
                    existing.craft_id == craft.pk
                    and existing.product_name == ""
                    and existing.name == operation_name
                    and existing.reporting_unit_id is None
                    and existing.status == RecordStatus.ACTIVE
                ):
                    exact_existing_numbers.add(operation_number)
                else:
                    collisions.append(operation_number)
        else:
            collisions = list(existing_by_number)
        already_imported = bool(rows) and len(exact_existing_numbers) == len(rows)
        if expected_existing_operations is not None:
            allowed_operation_counts = {expected_existing_operations}
            if already_imported:
                allowed_operation_counts.add(expected_existing_operations + len(rows))
            if actual_existing_operations not in allowed_operation_counts:
                blockers.append({
                    "code": "UNEXPECTED_DATABASE_OPERATION_COUNT",
                    "message": "数据库工序总数与预期不一致。",
                    "expected": sorted(allowed_operation_counts),
                    "actual": actual_existing_operations,
                })
        if expected_existing_metal_operations is not None:
            allowed_metal_counts = {expected_existing_metal_operations}
            if already_imported:
                allowed_metal_counts.add(expected_existing_metal_operations + len(rows))
            if actual_existing_metal_operations not in allowed_metal_counts:
                blockers.append({
                    "code": "UNEXPECTED_DATABASE_METAL_OPERATION_COUNT",
                    "message": "数据库金工工序数与预期不一致。",
                    "expected": sorted(allowed_metal_counts),
                    "actual": actual_existing_metal_operations,
                })
        if exact_existing_numbers and not already_imported:
            blockers.append({
                "code": "PARTIAL_METAL_OPERATION_IMPORT",
                "message": "数据库只存在部分完全一致的金工工序，禁止继续补写。",
                "count": len(exact_existing_numbers),
                "sample_operation_numbers": sorted(exact_existing_numbers)[:20],
            })
        if collisions:
            blockers.append({
                "code": "METAL_OPERATION_NUMBER_COLLISION",
                "message": "待导入金工工序编号已被不一致的数据占用。",
                "count": len(collisions),
                "sample_operation_numbers": sorted(collisions)[:20],
            })
        business_collisions = list(
            Operation.objects.filter(
                craft=craft,
                product_name="",
                name__in=operation_names,
            ).values_list("name", flat=True)
        ) if craft else []
        business_collisions = [
            name for name in business_collisions
            if name not in {
                operation_name
                for operation_number, operation_name in zip(operation_numbers, operation_names)
                if operation_number in exact_existing_numbers
            }
        ]
        if business_collisions:
            blockers.append({
                "code": "METAL_OPERATION_BUSINESS_COLLISION",
                "message": "待导入金工工序名称已存在于同一工艺。",
                "count": len(business_collisions),
                "sample_operation_names": business_collisions[:20],
            })

        report = {
            "mode": "apply" if options["apply"] else "dry-run",
            "can_apply": not blockers,
            "counts": {
                "metal_operations_to_import": len(rows),
                "metal_operations_to_create": 0 if already_imported else len(rows),
                "database_operations_before_import": actual_existing_operations,
                "database_metal_operations_before_import": actual_existing_metal_operations,
            },
            "already_imported": already_imported,
            "blockers": blockers,
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))

        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS("金工工序 dry-run 完成：未写入数据库。"))
            return
        if not report["can_apply"]:
            raise CommandError("金工工序预检存在阻断项，禁止写入数据库。")
        if expected_existing_operations is None or expected_existing_metal_operations is None:
            raise CommandError("--apply 必须同时提供数据库工序总数和金工工序数预期值。")

        with transaction.atomic():
            locked_craft = Craft.objects.select_for_update().get(pk=craft.pk)
            if not (
                locked_craft.craft_type == CraftType.INTERNAL
                and locked_craft.workshop.name == "金工车间"
                and locked_craft.name == "管材加工"
                and locked_craft.plan_category == PlanCategory.METAL
                and locked_craft.status == RecordStatus.ACTIVE
            ):
                raise CommandError("事务开始前目标金工工艺配置发生变化，已取消导入。")
            if Operation.objects.count() != actual_existing_operations:
                raise CommandError("事务开始前数据库工序总数发生变化，已取消导入。")
            if Operation.objects.filter(craft=locked_craft).count() != actual_existing_metal_operations:
                raise CommandError("事务开始前金工工序数发生变化，已取消导入。")
            locked_existing = {
                item.operation_number: item
                for item in Operation.objects.select_for_update().filter(operation_number__in=operation_numbers)
            }
            if already_imported:
                still_consistent = len(locked_existing) == len(rows)
                for operation_number, operation_name in zip(operation_numbers, operation_names):
                    item = locked_existing.get(operation_number)
                    if item is None or (
                        item.craft_id != locked_craft.pk
                        or item.product_name != ""
                        or item.name != operation_name
                        or item.reporting_unit_id is not None
                        or item.status != RecordStatus.ACTIVE
                    ):
                        still_consistent = False
                        break
                if not still_consistent:
                    raise CommandError("事务开始前已导入工序发生变化，已取消操作。")
                self.stdout.write(self.style.SUCCESS(f"金工工序已存在且内容一致：{len(rows)} 条，未重复写入。"))
                return
            if Operation.objects.filter(operation_number__in=operation_numbers).exists():
                raise CommandError("事务开始前出现工序编号冲突，已取消导入。")
            if Operation.objects.filter(
                craft=locked_craft,
                product_name="",
                name__in=operation_names,
            ).exists():
                raise CommandError("事务开始前出现同工艺同名工序冲突，已取消导入。")
            Operation.objects.bulk_create([
                Operation(
                    operation_number=row["最终工序编号"].upper(),
                    product_name="",
                    craft=locked_craft,
                    name=row["工序"],
                    reporting_unit=None,
                    status=RecordStatus.ACTIVE,
                )
                for row in rows
            ])

        self.stdout.write(self.style.SUCCESS(f"金工工序正式导入完成：{len(rows)} 条。"))
