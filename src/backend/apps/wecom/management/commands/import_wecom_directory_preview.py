import json
import sys

from django.core.management.base import BaseCommand, CommandError
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import ValidationError

from apps.wecom.directory_imports import import_directory_copy


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("封套包含重复JSON字段。")
        result[key] = value
    return result


class Command(BaseCommand):
    help = "从stdin校验线上目录封套；显式--apply只保存本地只读来源副本，不创建员工或企微配置。"

    def add_arguments(self, parser):
        parser.add_argument("--database-name", required=True)
        parser.add_argument("--corp-id", required=True)
        parser.add_argument("--source-origin", required=True)
        parser.add_argument("--apply", action="store_true")

    @sensitive_variables()
    def handle(self, *args, **options):
        try:
            raw = sys.stdin.read(10 * 1024 * 1024 + 1)
            if len(raw.encode("utf-8")) > 10 * 1024 * 1024:
                raise CommandError("目录封套超过10MiB，未保存。")
            envelope = json.loads(raw.lstrip("\ufeff"), object_pairs_hook=unique_fields)
        except (ValueError, UnicodeError) as exc:
            raise CommandError("stdin不是有效的UTF-8 JSON封套，未保存。") from exc
        try:
            summary = import_directory_copy(envelope, database_name=options["database_name"],
                expected_corp_id=options["corp_id"], expected_source_origin=options["source_origin"],
                apply=options["apply"])
        except ValidationError as exc:
            raise CommandError(str(exc.detail)) from exc
        self.stdout.write(json.dumps(summary, ensure_ascii=False))
