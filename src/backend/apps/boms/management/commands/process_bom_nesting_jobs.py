import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.boms.nesting_worker import process_once


class Command(BaseCommand):
    help = "提交并跟踪 Codex DXF 任务；ERP 不执行解析、排料或单耗计算。"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--watch", action="store_true")
        mode.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=1.0)

    def handle(self, *args, **options):
        interval = options["interval"]
        if not 0.1 <= interval <= 60:
            from django.core.management.base import CommandError
            raise CommandError("轮询间隔须在 0.1 到 60 秒之间。")
        try:
            while True:
                close_old_connections()
                processed = process_once()
                if not options["watch"]:
                    self.stdout.write("PROCESSED" if processed else "IDLE")
                    break
                if not processed:
                    time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("STOPPED")
        finally:
            close_old_connections()
