import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test import RequestFactory
from rest_framework.exceptions import APIException

from apps.access_control.department_baseline import apply_baseline, baseline_plan


class Command(BaseCommand):
    help = "预览12部门/20角色差异；仅--apply且明确数据库和操作者时执行，不改员工或业务授权。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--database-name")
        parser.add_argument("--actor-username")

    def handle(self, *args, **options):
        if not options["apply"]:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                result = baseline_plan()
        else:
            if options["database_name"] != connection.settings_dict["NAME"] or not options["actor_username"]:
                raise CommandError("必须明确匹配当前数据库的--database-name与--actor-username。")
            user = get_user_model().objects.filter(username=options["actor_username"]).first()
            if user is None:
                raise CommandError("操作者不存在。")
            request = RequestFactory().post("/management/initialize-departments/")
            request.user = user
            try:
                result = apply_baseline(request)
            except APIException as exc:
                raise CommandError(str(exc.detail)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
