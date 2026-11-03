import time
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from apps.codex_connection.runtime_client import RuntimeClient
from apps.codex_connection.selectors import schema_is_ready
from apps.codex_connection.worker import process_tick


class Command(BaseCommand):
    help = '处理管理员已明确提交的 Codex 操作；默认单轮，--watch 常驻。不会自动登录或调用模型。'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true')
        parser.add_argument('--interval', type=int, default=1)

    def handle(self, *args, **options):
        if not 1 <= options['interval'] <= 60:
            raise CommandError('--interval 必须在 1..60 秒之间。')
        if not schema_is_ready():
            raise CommandError('CODEX_SCHEMA_UNAVAILABLE')
        owner_id = uuid4()
        runtime = RuntimeClient()
        try:
            while True:
                close_old_connections()
                processed = process_tick(runtime, owner_id=owner_id)
                if not options['watch']:
                    self.stdout.write('PROCESSED' if processed else 'IDLE')
                    break
                time.sleep(options['interval'])
        except KeyboardInterrupt:
            self.stdout.write('STOPPED')
        finally:
            close_old_connections()
