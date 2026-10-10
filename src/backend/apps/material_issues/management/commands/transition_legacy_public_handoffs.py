import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from rest_framework.exceptions import APIException

from apps.material_issues.legacy_public_transition import apply_legacy_public_transition, preview_legacy_public_transition
from apps.organizations.models import Employee


class Command(BaseCommand):
    help = "默认只读预检旧金工交接接续；仅显式 --apply 且维护期、目标白名单、有效授权员工及摘要匹配才写接续凭证。"

    def add_arguments(self, parser):
        parser.add_argument("manifest", help="已确认颜色及历史证据候选 JSON 文件")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--actor-employee-id")
        parser.add_argument("--request-id")
        parser.add_argument("--expected-manifest-hash")

    def handle(self, *args, **options):
        try:
            manifest = json.loads(Path(options["manifest"]).read_text(encoding="utf-8-sig"))
            if options["apply"]:
                if any(not options[key] for key in ("actor_employee_id", "request_id", "expected_manifest_hash")):
                    raise CommandError("应用必须提供 --actor-employee-id、--request-id 和只读预检返回的 --expected-manifest-hash。")
                actor = Employee.objects.filter(pk=options["actor_employee_id"]).first()
                result = apply_legacy_public_transition(manifest=manifest, actor=actor,
                    request_id=options["request_id"], expected_manifest_hash=options["expected_manifest_hash"])
            else:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    result = preview_legacy_public_transition(manifest)
        except (OSError, ValueError, TypeError, APIException) as exc:
            raise CommandError(str(getattr(exc, "detail", exc))) from exc
        self.stdout.write(json.dumps(result, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2))
