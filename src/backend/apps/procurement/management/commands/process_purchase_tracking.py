"""采购风险producer：只登记通知队列，企微投递仍由通知worker负责。"""
import json
import time
from contextlib import closing

from psycopg import sql
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.procurement.tracking_hooks import SUPPLIER_TRACKING_CHANNEL
from apps.procurement.tracking_runner import recompute_tracking


class Command(BaseCommand):
    help = '重算采购风险及北京时间09点每日摘要；默认只读预览。'

    def add_arguments(self, parser):
        modes = parser.add_mutually_exclusive_group()
        modes.add_argument('--once', action='store_true')
        modes.add_argument('--loop', action='store_true')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--interval', type=int, default=60)

    def handle(self, *args, **options):
        if options['interval'] < 1 or options['interval'] > 3600:
            raise CommandError('--interval 必须在1至3600秒之间。')
        if options['loop'] and options['dry_run']:
            raise CommandError('只读预览不使用持续循环。')
        dry_run = options['dry_run'] or not (options['once'] or options['loop'])
        try:
            if options['loop']:
                self._watch(options['interval'])
            else:
                self._scan(dry_run=dry_run)
        except KeyboardInterrupt:
            self.stdout.write('采购风险扫描已停止。')
        finally:
            if options['loop']:
                close_old_connections()

    def _scan(self, *, task_ids=None, dry_run=False):
        result = recompute_tracking(task_ids=task_ids, dry_run=dry_run)
        result['finished_at'] = timezone.now().isoformat()
        result['outcome'] = 'preview' if dry_run else 'success' if result['enabled'] else 'disabled'
        self.stdout.write(json.dumps(result, ensure_ascii=False))

    def _watch(self, interval):
        with closing(connection.copy()) as listener:
            with listener.cursor() as cursor:
                cursor.execute(sql.SQL("LISTEN {}").format(sql.Identifier(SUPPLIER_TRACKING_CHANNEL)))
            task_ids = None
            while True:
                close_old_connections()
                self._scan(task_ids=task_ids)
                if task_ids is None:
                    next_full_scan = time.monotonic() + interval
                # Keep the periodic full scan even when submissions keep arriving.
                timeout = max(0, next_full_scan - time.monotonic())
                notices = list(listener.connection.notifies(timeout=timeout, stop_after=1))
                task_ids = sorted({notice.payload for notice in notices}) if notices and time.monotonic() < next_full_scan else None
