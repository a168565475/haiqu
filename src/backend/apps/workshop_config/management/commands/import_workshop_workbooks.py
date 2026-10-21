import json

from django.core.management.base import BaseCommand, CommandError

from ...workbook_import import analyze_workbooks


class Command(BaseCommand):
    help = "预检旧车间员工、工艺、工序工作簿；员工须从统一主档选择，不再支持联合写入。"

    def add_arguments(self, parser):
        parser.add_argument("--employees", required=True, help="车间员工工作簿路径")
        parser.add_argument("--crafts", required=True, help="工艺工作簿路径")
        parser.add_argument("--operations", required=True, help="工序工作簿路径")
        parser.add_argument("--expect-employees", type=int, default=81)
        parser.add_argument("--expect-crafts", type=int, default=11)
        parser.add_argument("--expect-operations", type=int, default=947)
        parser.add_argument("--apply", action="store_true", help="历史兼容参数；此命令已禁止员工写入")
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

        report = {**plan.report, "can_apply": False, "apply_blocker": "员工须从统一员工主档选择，此命令仅支持预检。"}
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS("dry-run 完成：未写入数据库。"))
            return
        raise CommandError("员工已改为从统一员工主档选择，旧姓名工作簿仅支持 dry-run；请在车间员工配置中分配员工。")
