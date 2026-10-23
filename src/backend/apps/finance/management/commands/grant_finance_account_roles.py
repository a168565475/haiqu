import json
from types import SimpleNamespace
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from rest_framework.exceptions import APIException

from apps.access_control.models import RoleActionGrant
from apps.access_control.services import add_module_grant, require_manager
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, RoleProfile

ROLES = ("FINANCE", "CASHIER", "FACTORY_MANAGER", "GENERAL_MANAGER")
PERMISSIONS = tuple(f"finance.{action}_financeaccount" for action in ("view", "add", "change", "delete"))


class Command(BaseCommand):
    help = "仅对四角色增补四个公司账户 MODULE 权限；默认预检，不重置其他授权。"
    permissions = PERMISSIONS

    def add_arguments(self, parser):
        parser.add_argument("--database-name", required=True)
        parser.add_argument("--actor-employee-id", type=UUID)
        parser.add_argument("--apply", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        permissions = self.permissions
        if connection.settings_dict["NAME"] != options["database_name"]:
            raise CommandError("目标数据库名不匹配。")
        roles = list(RoleProfile.objects.filter(role_code__in=ROLES).order_by("role_code"))
        if {role.role_code for role in roles} != set(ROLES):
            raise CommandError("四个目标角色不完整。")
        plan = []
        for role in roles:
            grants = RoleActionGrant.objects.filter(role=role, permission__content_type__app_label="finance")
            existing = {f"finance.{item.permission.codename}": item.scope for item in grants.select_related("permission")}
            if role.archived_at or any(existing.get(code) not in (None, "MODULE") for code in permissions):
                raise CommandError("目标角色已归档或现有权限范围冲突，请审阅。")
            plan.append({"role": role.role_code, "add": [code for code in permissions if code not in existing],
                         "unchanged": [code for code in permissions if code in existing]})
        self.stdout.write(json.dumps({"database": connection.settings_dict["NAME"], "plan": plan,
                                     "mode": "APPLY" if options["apply"] else "READ_ONLY"}, ensure_ascii=False))
        if not options["apply"]:
            return
        actor = Employee.objects.select_related("user").filter(pk=options["actor_employee_id"]).first()
        if not actor or not actor.user:
            raise CommandError("缺少有效授权操作者。")
        request = SimpleNamespace(user=actor.user, META={}, headers={})
        try:
            require_manager(request)
            for role in roles:
                for code in permissions:
                    role.refresh_from_db()
                    request.headers = {"If-Match": etag_for_instance(role)}
                    add_module_grant(request, role.pk, code)
            actual = RoleActionGrant.objects.filter(role__in=roles, scope="MODULE",
                permission__content_type__app_label="finance", permission__codename__in=[code.split(".")[1] for code in permissions]).count()
            expected_count = len(ROLES) * len(self.permissions)
            if actual != expected_count:
                raise CommandError("四角色权限回读不完整，事务回滚。")
        except APIException as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"APPLIED_AND_READ_BACK: {expected_count} MODULE grants; employee assignments unchanged")
