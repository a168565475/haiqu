import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ...constants import FIXED_WORKSHOP_NAMES
from ...models import RecordStatus, Workshop, WorkshopEmployee, WorkshopEmployeeStatus
from ...workbook_import import analyze_employee_workbook, read_additional_employees, read_supervisor_keys


class Command(BaseCommand):
    help = "预检或单独导入车间员工工作簿；默认只执行 dry-run。"

    def add_arguments(self, parser):
        parser.add_argument("--employees", required=True, help="车间员工工作簿路径")
        parser.add_argument("--expect-employees", type=int, default=81)
        parser.add_argument("--apply", action="store_true", help="通过全部校验后写入数据库")
        parser.add_argument("--supervisor-file", help="主管名单 JSON，内容为车间、岗位、姓名对象数组")
        parser.add_argument("--additional-employees-file", help="经业务确认、但不在原表中的新增员工 JSON")
        parser.add_argument("--expect-additional-employees", type=int, default=0)
        parser.add_argument("--expect-existing-employees", type=int)

    def handle(self, *args, **options):
        try:
            plan = analyze_employee_workbook(
                employee_path=options["employees"],
                expected_employees=options["expect_employees"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        try:
            additional_employees = read_additional_employees(
                options.get("additional_employees_file"),
                plan.employees,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        if len(additional_employees) != options["expect_additional_employees"]:
            raise CommandError(
                "新增员工行数变化，"
                f"预期 {options['expect_additional_employees']}，实际 {len(additional_employees)}。"
            )
        all_employees = [*plan.employees, *additional_employees]
        supervisor_keys = None
        if options.get("supervisor_file"):
            try:
                supervisor_keys = read_supervisor_keys(options["supervisor_file"], all_employees)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            inconsistent_additional = [
                row["姓名"]
                for row in additional_employees
                if row["是否为主管"]
                != ((row["车间"], row["岗位"], row["姓名"]) in supervisor_keys)
            ]
            if inconsistent_additional:
                raise CommandError(f"新增员工的主管值与主管名单不一致：{inconsistent_additional}")
        report = {
            **plan.report,
            "counts": {
                **plan.report["counts"],
                "additional_employees": len(additional_employees),
                "total_employees_to_import": len(all_employees),
                "supervisors_to_import": len(supervisor_keys) if supervisor_keys is not None else None,
            },
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS("员工 dry-run 完成：未写入数据库。"))
            return
        if not plan.report["can_apply"]:
            raise CommandError("员工工作簿存在阻断项，禁止写入数据库。")

        expected_existing = options.get("expect_existing_employees")
        if expected_existing is None:
            raise CommandError("--apply 必须提供 --expect-existing-employees 参数。")
        if supervisor_keys is None:
            raise CommandError("--apply 必须提供 --supervisor-file，不能推断主管。")

        actual_existing = WorkshopEmployee.objects.count()
        if actual_existing != expected_existing:
            raise CommandError(f"数据库现有员工数变化，预期 {expected_existing}，实际 {actual_existing}。")
        if actual_existing:
            raise CommandError("初始员工导入只允许写入空员工表，禁止覆盖现有配置。")

        workshops = {item.name: item for item in Workshop.objects.all()}
        if set(workshops) != set(FIXED_WORKSHOP_NAMES) or any(
            item.status != RecordStatus.ACTIVE for item in workshops.values()
        ):
            raise CommandError("数据库必须先存在且仅存在四个启用的固定车间。")

        with transaction.atomic():
            WorkshopEmployee.objects.bulk_create(
                [
                    WorkshopEmployee(
                        workshop=workshops[row["车间"]],
                        position=row["岗位"],
                        name=row["姓名"],
                        is_supervisor=(row["车间"], row["岗位"], row["姓名"]) in supervisor_keys,
                        status=(
                            WorkshopEmployeeStatus.ACTIVE
                            if row["状态"] == "在职"
                            else WorkshopEmployeeStatus.LEFT
                        ),
                    )
                    for row in all_employees
                ]
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"员工正式导入完成：{len(all_employees)} 人，其中主管 {len(supervisor_keys)} 人。"
            )
        )
