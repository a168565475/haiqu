"""2026-11-02规则迁移：默认只预览，按明确数据库和版本摘要应用。"""
import hashlib
import json
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from rest_framework.exceptions import ValidationError

from apps.access_control.management_permissions import can_manage
from apps.wecom.models import NotificationRule
from apps.wecom.notification_catalog import get_event
from apps.wecom.notification_role_policy import ROLE_POLICIES, enabled
from apps.wecom.notification_selectors import default_rule_payload, rule_payload
from apps.wecom.notification_services import RULE_FIELDS, _lock_key, _validate_rule, update_rule


def notification_plan():
    saved = {row.event_code: row for row in NotificationRule.objects.all()}
    rows = []
    for code in ROLE_POLICIES:
        event = get_event(code)
        before = rule_payload(saved[code]) if code in saved else None
        source = before or default_rule_payload(event)
        after = {field: source[field] for field in RULE_FIELDS}
        after.update(recipient_scope='ROLE_POLICY', recipient_role_codes=sorted(ROLE_POLICIES[code]),
                     enabled=bool(ROLE_POLICIES[code]))
        try:
            _validate_rule(event, after)
        except ValidationError as exc:
            raise CommandError(f'{code}规则无效，整批未写入：{exc.detail}') from exc
        changed = before is None or any(before[field] != after[field] for field in RULE_FIELDS)
        rows.append({'event_code': code, 'before': before, 'after': after,
                     'change': 'CREATE' if before is None else 'UPDATE' if changed else 'PRESERVE'})
    plan = {'database': connection.settings_dict['NAME'], 'rules': rows,
            'will_send': False, 'will_create_business_events': False,
            'create_count': sum(row['change'] == 'CREATE' for row in rows),
            'update_count': sum(row['change'] == 'UPDATE' for row in rows)}
    plan['digest'] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return plan


class Command(BaseCommand):
    help = '预览已确认岗位通知规则；apply只改规则，不补发历史事件、不发送消息。'

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
        if not enabled():
            raise CommandError('确认岗位策略闸门尚未启用，没有写入。')
        if options['database_name'] != connection.settings_dict['NAME']:
            raise CommandError('须指定目标数据库完整名称，没有写入。')
        user = get_user_model().objects.filter(username=options['actor_username'], is_active=True).first()
        if user is None or not can_manage(user, 'access_control.manage_notifications'):
            raise CommandError('须为有效通知管理员，没有写入。')
        for code in sorted(ROLE_POLICIES):
            _lock_key('notification-rule:' + code)
        plan = notification_plan()
        if options['expected_digest'] != plan['digest']:
            raise CommandError('预览摘要已变化，重新审阅后再应用；没有写入。')
        for row in plan['rules']:
            if row['change'] == 'PRESERVE':
                continue
            request = SimpleNamespace(user=user, META={'HTTP_USER_AGENT': 'configure_confirmed_notifications'},
                headers={'If-Match': row['before']['etag'] if row['before'] else '"notification-rule-unsaved"'})
            update_rule(request, row['event_code'], row['after'])
        self.stdout.write(json.dumps({'applied': True, 'before_digest': plan['digest'],
            'created': plan['create_count'], 'updated': plan['update_count'], 'will_send': False}, ensure_ascii=False))
