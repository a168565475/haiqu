import json

from django.core.management.base import BaseCommand, CommandError

from ...workbook_import import analyze_employee_workbook, read_additional_employees, read_supervisor_keys


class Command(BaseCommand):
    help = "预检旧车间员工工作簿；员工须从统一主档选择，不再按姓名导入。"

    def add_arguments(self, parser):
        parser.add_argument("--employees", required=True, help="车间员工工作簿路径")
        parser.add_argument("--expect-employees", type=int, default=81)
        parser.add_argument("--apply", action="store_true", help="历史兼容参数；此命令已禁止员工写入")
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
            "can_apply": False,
            "apply_blocker": "员工须从统一员工主档选择，此命令仅支持预检。",
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
        raise CommandError("员工已改为从统一员工主档选择，旧姓名工作簿仅支持 dry-run；请在车间员工配置中分配员工。")
