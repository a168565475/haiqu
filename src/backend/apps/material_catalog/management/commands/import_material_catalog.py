import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from ...importing import import_catalog_payload


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 存在重复字段：{key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"JSON 不支持数值：{value}")


class Command(BaseCommand):
    help = "预检已人工确认的原料 JSON；只有显式指定 --apply 才写入新原料管理。"

    def add_arguments(self, parser):
        parser.add_argument("source_json", help="已确认的规范化 JSON 文件路径")
        parser.add_argument("--apply", action="store_true", help="执行受授权导入；缺省只读预检")

    def handle(self, *args, **options):
        try:
            payload = json.loads(
                Path(options["source_json"]).read_text(encoding="utf-8-sig"),
                object_pairs_hook=_unique_keys, parse_constant=_invalid_constant,
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise CommandError(f"无法读取规范化 JSON：{exc}") from exc
        try:
            result = import_catalog_payload(payload, apply=options["apply"])
        except ValidationError as exc:
            raise CommandError(json.dumps({"errors": exc.detail}, ensure_ascii=False)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
