import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ...constants import FIXED_WORKSHOP_NAMES
from ...models import Craft, CraftType, RecordStatus, Workshop
from ...workbook_import import analyze_craft_workbook


class Command(BaseCommand):
    help = "预检或单独导入工艺工作簿；默认只执行 dry-run。"

    def add_arguments(self, parser):
        parser.add_argument("--crafts", required=True, help="工艺工作簿路径")
        parser.add_argument("--expect-crafts", type=int, default=11)
        parser.add_argument("--expect-import-crafts", type=int, required=True)
        parser.add_argument(
            "--exclude-craft",
            action="append",
            default=[],
            help="明确排除的工艺，格式为：类型|车间|工艺；可重复传入",
        )
        parser.add_argument("--apply", action="store_true", help="通过全部校验后写入数据库")
        parser.add_argument("--expect-existing-crafts", type=int)

    def handle(self, *args, **options):
        excluded_craft_keys = set()
        for value in options["exclude_craft"]:
            parts = tuple(part.strip() for part in value.split("|"))
            if len(parts) != 3 or not parts[0] or not parts[2]:
                raise CommandError("--exclude-craft 格式必须为：类型|车间|工艺。")
            if parts in excluded_craft_keys:
                raise CommandError(f"重复的 --exclude-craft：{value}")
            excluded_craft_keys.add(parts)

        try:
            plan = analyze_craft_workbook(
                craft_path=options["crafts"],
                expected_crafts=options["expect_crafts"],
                excluded_craft_keys=excluded_craft_keys,
                expected_import_crafts=options["expect_import_crafts"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(plan.report, ensure_ascii=False, indent=2))
        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS("工艺 dry-run 完成：未写入数据库。"))
            return
        if not plan.report["can_apply"]:
            raise CommandError("工艺工作簿存在阻断项，禁止写入数据库。")

        expected_existing = options.get("expect_existing_crafts")
        if expected_existing is None:
            raise CommandError("--apply 必须提供 --expect-existing-crafts 参数。")
        actual_existing = Craft.objects.count()
        if actual_existing != expected_existing:
            raise CommandError(f"数据库现有工艺数变化，预期 {expected_existing}，实际 {actual_existing}。")
        if actual_existing:
            raise CommandError("初始工艺导入只允许写入空工艺表，禁止覆盖现有配置。")

        workshops = {item.name: item for item in Workshop.objects.all()}
        if set(workshops) != set(FIXED_WORKSHOP_NAMES) or any(
            item.status != RecordStatus.ACTIVE for item in workshops.values()
        ):
            raise CommandError("数据库必须先存在且仅存在四个启用的固定车间。")

        with transaction.atomic():
            Craft.objects.bulk_create(
                [
                    Craft(
                        craft_type=(
                            CraftType.INTERNAL
                            if row["类型"] == "厂内"
                            else CraftType.EXTERNAL
                        ),
                        workshop=(workshops[row["车间"]] if row["类型"] == "厂内" else None),
                        name=row["工艺"],
                        status=RecordStatus.ACTIVE,
                    )
                    for row in plan.crafts
                ]
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"工艺正式导入完成：{len(plan.crafts)} 条，排除 {len(plan.excluded_crafts)} 条。"
            )
        )
