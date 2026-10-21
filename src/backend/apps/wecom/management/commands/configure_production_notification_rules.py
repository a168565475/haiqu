"""按已确认的生产通知基线首次保存规则；保留所有既有配置。"""
import hashlib
import json
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from rest_framework.exceptions import ValidationError

from apps.access_control.management_permissions import can_manage
from apps.wecom.models import NotificationRule
from apps.wecom.notification_catalog import all_events
from apps.wecom.notification_selectors import default_rule_payload, rule_payload
from apps.wecom.notification_services import RULE_FIELDS, _lock_key, _validate_rule, update_rule


DISABLED_REASONS = {
    'BOM_CONFIRMED': '旧单BOM事件仅兼容；当前生产链采用任务BOM全部确认。',
    'SUPPLIER_PURCHASE_SHEET_PUBLISHED': '用户明确要求此节点不通知。',
    'SEMI_FINISHED_RECEIPT_SUBMITTED': '申请对象NOT_READY；用户暂缓新增流程。',
    'SAMPLE_INVENTORY_RECEIVED': '入库后通知为未确认建议，未新增业务触发。',
}


def notification_plan():
    saved = {row.event_code: row for row in NotificationRule.objects.order_by('event_code')}
    rows = []
    for event in all_events():
        code = event['event_code']
        before = rule_payload(saved[code]) if code in saved else None
        default = default_rule_payload(event) if before is None else None
        desired = {field: (default or before)[field] for field in RULE_FIELDS}
        desired['enabled'] = event['enabled_by_default'] and code not in DISABLED_REASONS
        # 首次初始化不覆盖人工保存的模板、角色、范围或启停状态。
        after = {field: before[field] for field in RULE_FIELDS} if before else desired
        try:
            _validate_rule(event, after)
        except ValidationError as error:
            raise CommandError(f'{code}配置无效，整批未写入：{error.detail}') from error
        if code in DISABLED_REASONS and after['enabled']:
            raise CommandError(f'{code}现有配置与本期停用边界冲突，请先审阅，整批未写入。')
        rows.append({'event_code': code, 'change': 'PRESERVE' if before else 'CREATE',
            'before': before, 'after': after, 'allowed_variables': event['allowed_variables'],
            'required_variables': event['required_variables'], 'channels': ['IN_APP', 'WECOM'],
            'disabled_reason': DISABLED_REASONS.get(code),
            'warnings': (before or default)['warnings']})
    plan = {'database': connection.settings_dict['NAME'], 'rules': rows,
        'create_count': sum(row['change'] == 'CREATE' for row in rows),
        'preserve_count': sum(row['change'] == 'PRESERVE' for row in rows),
        'will_send': False, 'will_create_business_events': False}
    plan['digest'] = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    return plan


class Command(BaseCommand):
    help = '只读预览生产通知首次配置；显式apply经原配置服务和审计保存，不分配员工、不创建事件、不发送消息。'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--database-name')
        parser.add_argument('--expected-digest')
        parser.add_argument('--actor-username')

    @transaction.atomic
    def handle(self, *args, **options):
        if not options['apply']:
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
            self.stdout.write(json.dumps(notification_plan(), ensure_ascii=False, default=str))
            return
        if options['database_name'] != connection.settings_dict['NAME']:
            raise CommandError('须明确指定当前目标数据库完整名称；没有写入。')
        user = get_user_model().objects.filter(username=options['actor_username'], is_active=True).first()
        if user is None or not can_manage(user, 'access_control.manage_notifications'):
            raise CommandError('操作者须为有效员工并具备业务通知规则管理权限；没有写入。')
        for event in sorted(all_events(), key=lambda item: item['event_code']):
            _lock_key('notification-rule:' + event['event_code'])
        plan = notification_plan()
        if options['expected_digest'] != plan['digest']:
            raise CommandError('预览已变化，请重新审阅最新差异；没有写入。')
        request = SimpleNamespace(user=user, META={'HTTP_USER_AGENT': 'configure_production_notification_rules'},
            headers={'If-Match': '"notification-rule-unsaved"'})
        for row in plan['rules']:
            if row['change'] == 'CREATE':
                update_rule(request, row['event_code'], row['after'])
        result = notification_plan()
        result.update(applied=True, before_digest=plan['digest'], created_count=plan['create_count'])
        self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
