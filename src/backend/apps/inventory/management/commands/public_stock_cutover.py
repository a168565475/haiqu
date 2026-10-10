import json

from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import APIException

from apps.organizations.models import Employee
from apps.inventory.public_stock_cutover import begin_cutover_maintenance, current_cutover_target, get_cutover_control


class Command(BaseCommand):
    help = "只读查看库存切换状态；显式 --begin-maintenance 才进入持久停写状态。"

    def add_arguments(self, parser):
        parser.add_argument("--begin-maintenance", action="store_true")
        parser.add_argument("--actor")
        parser.add_argument("--reason")
        parser.add_argument("--expected-host")
        parser.add_argument("--expected-database")
        parser.add_argument("--expected-system-identifier")

    def handle(self, *args, **options):
        try:
            if options["begin_maintenance"]:
                required = ["actor", "reason", "expected_host", "expected_database", "expected_system_identifier"]
                if any(not options[key] for key in required):
                    raise CommandError("进入停写须提供操作员工、原因以及明确的数据库主机、库名、实例标识。")
                actor = Employee.objects.filter(pk=options["actor"]).first()
                control = begin_cutover_maintenance(actor_employee=actor, reason=options["reason"], expected_target={
                    "host": options["expected_host"], "database": options["expected_database"],
                    "system_identifier": options["expected_system_identifier"],
                })
            else:
                control = get_cutover_control()
            self.stdout.write(json.dumps({"target": current_cutover_target(),
                "state": control.state if control else "NOT_STARTED",
                "control_id": str(control.pk) if control else None}, ensure_ascii=False))
        except APIException as exc:
            raise CommandError(f"{getattr(exc, 'api_error_code', 'INVALID')}: {exc.detail}") from exc
