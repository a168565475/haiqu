import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ...constants import FIXED_WORKSHOP_NAMES
from ...models import Craft, CraftType, Operation, RecordStatus, Workshop, WorkshopEmployee, WorkshopEmployeeStatus
from ...workbook_import import analyze_workbooks, read_supervisor_keys


class Command(BaseCommand):
    help = "预检或导入车间员工、工艺、工序工作簿；默认只执行 dry-run。"

    def add_arguments(self, parser):
        parser.add_argument("--employees", required=True, help="车间员工工作簿路径")
        parser.add_argument("--crafts", required=True, help="工艺工作簿路径")
        parser.add_argument("--operations", required=True, help="工序工作簿路径")
        parser.add_argument("--expect-employees", type=int, default=81)
        parser.add_argument("--expect-crafts", type=int, default=11)
        parser.add_argument("--expect-operations", type=int, default=947)
        parser.add_argument("--apply", action="store_true", help="通过全部校验后写入数据库")
        parser.add_argument("--supervisor-file", help="主管名单 JSON，内容为车间、岗位、姓名对象数组")
        parser.add_argument("--expect-existing-workshops", type=int)
        parser.add_argument("--expect-existing-employees", type=int)
        parser.add_argument("--expect-existing-crafts", type=int)
        parser.add_argument("--expect-existing-operations", type=int)

    def handle(self, *args, **options):
        try:
            plan = analyze_workbooks(
                employee_path=options["employees"],
                craft_path=options["crafts"],
                operation_path=options["operations"],
                expected_employees=options["expect_employees"],
                expected_crafts=options["expect_crafts"],
                expected_operations=options["expect_operations"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(plan.report, ensure_ascii=False, indent=2))
        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS("dry-run 完成：未写入数据库。"))
            return
        if not plan.report["can_apply"]:
            raise CommandError("存在阻断项，禁止写入数据库。")

        try:
            supervisor_keys = read_supervisor_keys(options.get("supervisor_file"), plan.employees)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        expected_existing = {
            "workshops": options.get("expect_existing_workshops"),
            "employees": options.get("expect_existing_employees"),
            "crafts": options.get("expect_existing_crafts"),
            "operations": options.get("expect_existing_operations"),
        }
        if any(value is None for value in expected_existing.values()):
            raise CommandError("--apply 必须同时提供四个 --expect-existing-* 参数。")
        actual_existing = {
            "workshops": Workshop.objects.count(),
            "employees": WorkshopEmployee.objects.count(),
            "crafts": Craft.objects.count(),
            "operations": Operation.objects.count(),
        }
        if actual_existing != expected_existing:
            raise CommandError(f"数据库现有行数变化，预期 {expected_existing}，实际 {actual_existing}。")
        if actual_existing["workshops"] != len(FIXED_WORKSHOP_NAMES) or any(
            actual_existing[key] for key in ("employees", "crafts", "operations")
        ):
            raise CommandError("初始导入要求四个固定车间已建立，员工、工艺和工序表为空。")

        with transaction.atomic():
            workshops = {item.name: item for item in Workshop.objects.all()}
            if set(workshops) != set(FIXED_WORKSHOP_NAMES):
                raise CommandError("数据库固定车间与系统配置不一致，禁止导入。")
            WorkshopEmployee.objects.bulk_create(
                [
                    WorkshopEmployee(
                        workshop=workshops[row["车间"]],
                        position=row["岗位"],
                        name=row["姓名"],
                        is_supervisor=(row["车间"], row["岗位"], row["姓名"]) in supervisor_keys,
                        status=WorkshopEmployeeStatus.ACTIVE if row["状态"] == "在职" else WorkshopEmployeeStatus.LEFT,
                    )
                    for row in plan.employees
                ]
            )
            crafts = {}
            for row in plan.crafts:
                craft_type = CraftType.INTERNAL if row["类型"] == "厂内" else CraftType.EXTERNAL
                craft = Craft.objects.create(
                    craft_type=craft_type,
                    workshop=workshops.get(row["车间"]),
                    name=row["工艺"],
                    status=RecordStatus.ACTIVE,
                )
                crafts[(row["类型"], row["工艺"])] = craft
            Operation.objects.bulk_create(
                [
                    Operation(
                        operation_number=row["工序编号"].upper(),
                        product_name=row["品名"],
                        craft=crafts[(row["类型"], row["工艺"])],
                        name=row["工序"],
                        status=RecordStatus.ACTIVE,
                    )
                    for row in plan.operations
                ]
            )
        self.stdout.write(self.style.SUCCESS("正式导入完成。"))
