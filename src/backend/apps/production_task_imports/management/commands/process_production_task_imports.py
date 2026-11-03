import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.production_task_imports.worker import enqueue_next, expire_once, preprocess_once, recover_media_once
from apps.production_task_imports.readiness import require_schema


class Command(BaseCommand):
    help = '处理用户提交的生产任务导入，清理未保存的过期资料；模型操作由 Codex worker 领取。'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true')

    def handle(self, *args, **options):
        require_schema()
        next_recovery = 0
        try:
            while True:
                close_old_connections()
                if time.monotonic() >= next_recovery:
                    recover_media_once()
                    next_recovery = time.monotonic() + 60
                processed = preprocess_once()
                processed = enqueue_next() or processed
                processed = expire_once() or processed
                if not options['watch']:
                    self.stdout.write('PROCESSED' if processed else 'IDLE')
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write('STOPPED')
        finally:
            close_old_connections()
