"""采购风险producer：只登记通知队列，企微投递仍由通知worker负责。"""
import json
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

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
            while True:
                if options['loop']:
                    close_old_connections()
                result = recompute_tracking(dry_run=dry_run)
                result['finished_at'] = timezone.now().isoformat()
                result['outcome'] = 'preview' if dry_run else 'success' if result['enabled'] else 'disabled'
                self.stdout.write(json.dumps(result, ensure_ascii=False))
                if not options['loop']:
                    break
                time.sleep(options['interval'])
        except KeyboardInterrupt:
            self.stdout.write('采购风险扫描已停止。')
        finally:
            if options['loop']:
                close_old_connections()
