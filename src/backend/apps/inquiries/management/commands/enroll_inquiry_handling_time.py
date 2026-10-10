import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.inquiries.handling_time import stages_for_enrollment
from apps.inquiries.models import Inquiry
from apps.inquiries.services import _start_sla
from apps.workflow.models import SlaPolicy


class Command(BaseCommand):
    help = '预检或为历史在途询盘接入当前阶段计时，不追溯超时。'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--output', help='执行时必须提供新的备份及结果文件路径')

    def handle(self, *args, **options):
        output = Path(options['output']) if options['output'] else None
        if options['apply'] and (output is None or output.exists() or output.with_name(output.stem + '-result' + output.suffix).exists()):
            raise CommandError('执行前必须指定尚不存在的 --output 备份文件。')
        with transaction.atomic():
            policy = SlaPolicy.objects.filter(target_type='INQUIRY', is_enabled=True, archived_at__isnull=True).order_by('policy_code').first()
            if options['apply'] and (not policy or not policy.config_data.get('stage_minutes')):
                raise CommandError('须先启用完整阶段时限规则。')
            rows = list(Inquiry.objects.select_for_update().filter(archived_at__isnull=True).exclude(status__in=['DRAFT','CONVERTED','LOST','CLOSED','CANCELLED']).order_by('id'))
            now = timezone.now()
            report = {'started_at': now.isoformat(), 'applied': False, 'rows': []}
            for inquiry in rows:
                active = list(inquiry.sla_links.filter(is_current=True).values_list('stage_code', flat=True))
                report['rows'].append({'id': str(inquiry.pk), 'number': inquiry.inquiry_number, 'status': inquiry.status,
                    'before': list(inquiry.sla_links.values('id','stage_code','is_current','sla_tracking__started_at','sla_tracking__next_deadline_at','sla_tracking__status','sla_tracking__tracking_data')),
                    'add_stages': [stage for stage in stages_for_enrollment(inquiry) if stage not in active]})
            if options['apply']:
                output.parent.mkdir(parents=True, exist_ok=True)
                # 在任何业务写入之前保存可核对的原记录快照。
                output.write_text(json.dumps(report, default=str, ensure_ascii=False, indent=2), encoding='utf-8')
                for inquiry, item in zip(rows, report['rows']):
                    for stage in item['add_stages']:
                        link = _start_sla(inquiry, now, stage, context={'entry_reason':'启用时接入，不追溯历史超时', 'event_key':f'ENROLLED:{inquiry.pk}:{stage}'})
                        if link is None:
                            raise CommandError(f'{stage} 未配置目标时长，已回滚。')
                report['applied'] = True
            summary = {'applied': options['apply'], 'started_at': now.isoformat(), 'inquiries':len(rows),
                       'new_stages': sum(len(row['add_stages']) for row in report['rows']),
                       'stages': [{'number': row['number'], 'stages':row['add_stages']} for row in report['rows']]}
        if options['apply']:
            output.with_name(output.stem + '-result' + output.suffix).write_text(json.dumps(report, default=str, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(json.dumps(summary, ensure_ascii=False))
