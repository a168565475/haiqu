import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.wecom import directory_snapshots
from apps.wecom.directory_services import employee_source
from apps.wecom.employee_department_snapshots import department_snapshot
from apps.wecom.models import WeComBinding, WeComConfig, WeComDirectorySnapshot
from apps.wecom.selectors import get_config


class Command(BaseCommand):
    help = "从有效受信通讯录补齐空白企业微信部门副本，默认只预览数量。"

    def add_arguments(self, parser):
        parser.add_argument("--corp-id", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                config = get_config()
                if config.corp_id != options["corp_id"]:
                    raise CommandError("指定企业与当前配置不一致。")
                if config._state.adding:
                    directory_snapshots.lock_read_only_import()
                    if WeComConfig.objects.exists():
                        raise CommandError("配置已变化，请重新执行。")
                else:
                    config = WeComConfig.objects.select_for_update().get(pk=config.pk)
                if config.corp_id != options["corp_id"]:
                    raise CommandError("指定企业与当前配置不一致。")
                snapshot = WeComDirectorySnapshot.objects.select_for_update().filter(corp_id=config.corp_id).first()
                loaded, directory, metadata, _ = employee_source(config)
                if snapshot is None or loaded.pk != snapshot.pk or not metadata["can_submit"]:
                    raise CommandError("来源副本缺失、过期或不受信，未执行补齐。")
                if directory.get("corp_id") != config.corp_id or not isinstance(directory.get("members"), list):
                    raise CommandError("来源企业或成员列表无效。")
                members = {}
                for member in directory["members"]:
                    if not isinstance(member, dict) or not isinstance(member.get("userid"), str) or not member["userid"].strip():
                        raise CommandError("来源成员标识缺失。")
                    key = member["userid"].lower()
                    if key in members:
                        raise CommandError("来源成员标识重复。")
                    members[key] = member
                bindings = list(WeComBinding.objects.select_for_update().filter(
                    corp_id=config.corp_id, department_snapshot__isnull=True).order_by("pk"))
                plans = []
                for binding in bindings:
                    member = members.get(binding.user_id.lower())
                    if member is None:
                        raise CommandError("绑定未唯一匹配来源成员，整批未执行。")
                    departments = department_snapshot(directory, member)
                    if departments is None:
                        raise CommandError("来源成员部门缺失，整批未执行。")
                    plans.append((binding, departments))
                if snapshot.expires_at <= timezone.now():
                    raise CommandError("等待期间来源副本过期，整批未执行。")
                if options["apply"]:
                    for binding, departments in plans:
                        binding.department_snapshot = departments
                        binding.save(update_fields=["department_snapshot", "updated_at"])
                result = {"applied": options["apply"], "eligible_count": len(plans),
                          "multiple_department_count": sum(len(rows) > 1 for _, rows in plans)}
        except APIException as exc:
            raise CommandError("来源部门数据无效，整批未执行。") from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False))
