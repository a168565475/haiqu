import json

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.inventory.public_stock_transition import preview_public_stock_transition


class Command(BaseCommand):
    help = "只读列出公共库存正式切换前需要核验的旧未结单，不修改单据和库存。"

    def handle(self, *args, **options):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            self.stdout.write(json.dumps(preview_public_stock_transition(), ensure_ascii=False, indent=2))
