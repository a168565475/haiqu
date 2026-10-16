import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import PermissionDenied, ValidationError

from ...importing import import_product_catalog, verify_product_catalog_import
from ...models import ProductCatalogImport


class Command(BaseCommand):
    help = "预检产品 xlsx；仅 --apply --actor 现有用户名 写入；--verify 只读核验保存的来源批次。"

    def add_arguments(self, parser):
        parser.add_argument("path", help="xlsx 路径；--verify 时只按其文件名定位保存批次")
        parser.add_argument("--sheet", default="产品信息", help="来源工作表名，默认产品信息")
        parser.add_argument("--apply", action="store_true", help="明确授权后实际写入数据库")
        parser.add_argument("--actor", help="执行写入的现有用户登录名")
        parser.add_argument("--verify", action="store_true", help="从保存的原始文件逐行核验，不写入")

    def handle(self, *args, **options):
        if options["apply"] and options["verify"]:
            raise CommandError("--apply 和 --verify 不能同时使用。")
        path = Path(options["path"])
        if options["verify"]:
            batches = ProductCatalogImport.objects.filter(filename=path.name, sheet=options["sheet"])
            if batches.count() != 1:
                raise CommandError("未找到唯一的已保存来源批次，请核对文件名、工作表和已有来源冲突。")
            result = verify_product_catalog_import(batch=batches.get())
            self.stdout.write(json.dumps(result, ensure_ascii=False))
            if not result["valid"]:
                raise CommandError("来源逐行核验发现差异，未修改任何记录。")
            return
        actor = None
        if options["apply"]:
            if not options.get("actor"):
                raise CommandError("--apply 必须指定 --actor 现有用户名。")
            actor = get_user_model().objects.filter(**{get_user_model().USERNAME_FIELD: options["actor"]}).first()
            if actor is None:
                raise CommandError("指定的执行用户不存在。")
        try:
            source_bytes = path.read_bytes()
        except OSError as exc:
            raise CommandError(f"无法读取来源文件：{exc}") from exc
        try:
            result = import_product_catalog(source_bytes, filename=path.name, sheet=options["sheet"], apply=options["apply"], actor=actor)
        except (ValidationError, PermissionDenied) as exc:
            raise CommandError(str(exc.detail)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False))
