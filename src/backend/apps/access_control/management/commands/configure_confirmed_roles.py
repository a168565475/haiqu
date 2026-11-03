"""只预览为默认；明确数据库、摘要及操作者后才精确替换选定角色。"""
import hashlib
import json
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test import override_settings

from apps.access_control.catalog import catalog, permission_code, projected_permission_ids, validate_grants
from apps.access_control.production_role_templates import DIRECTORS, PENDING, templates
from apps.access_control.resource_scopes import validate_resources
from apps.access_control.selectors import grant_rows
from apps.access_control.services import replace_grants, require_manager
from apps.access_control.superuser_services import sync_role_superuser, superuser_plan
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import RoleProfile
from apps.workshop_config.models import Craft, Workshop


def role_plan(role_codes=None, *, lock=False):
    workshops = dict(Workshop.objects.filter(name__in=DIRECTORS.values(), status='ACTIVE').values_list('name', 'pk'))
    missing_workshops = sorted(set(DIRECTORS.values()) - set(workshops))
    # 缺资源时仍可预览阻断原因；空资源绝不转成全模块授权。
    workshop_ids = {name: str(workshops[name]) if name in workshops else '' for name in DIRECTORS.values()}
    craft_ids = list(Craft.objects.filter(craft_type='EXTERNAL', outsourcing_code='POWDER_COATING',
                                         status='ACTIVE').values_list('pk', flat=True))
    with override_settings(ACCESS_RESOURCE_SCOPES_ENABLED=True):
        desired = templates(workshop_ids, craft_ids)
        requested = set(role_codes) if role_codes else set(desired) - set(PENDING)
        invalid = requested - (set(desired) - set(PENDING))
        if invalid:
            raise CommandError('未确认或暂缓角色不能精确配置：' + ','.join(sorted(invalid)))
        roles = RoleProfile.objects.filter(role_code__in=requested).select_related('auth_group').order_by('role_code')
        if lock:
            roles = roles.select_for_update(of=('self',))
        output, blockers = [], []
        entries = catalog()
        available = {entry['code'] for entry in entries if entry['available']}
        for role in roles:
            wanted = desired[role.role_code]
            before = grant_rows(role)
            group_permissions = list(role.auth_group.permissions.select_related('content_type').order_by('pk'))
            target_codes = {row['permission'] for row in wanted}
            missing = sorted(target_codes - available)
            if missing:
                blockers.append({'role': role.role_code, 'missing_permissions': missing})
                target_group_ids = set()
            else:
                target_group_ids = projected_permission_ids(validate_grants(wanted))
            before_keys = {(row['permission'], row['scope'], tuple(row.get('resource_ids', []))) for row in before}
            wanted_keys = {(row['permission'], row['scope'], tuple(row.get('resource_ids', []))) for row in wanted}
            native_members = role.auth_group.user_set.count()
            if native_members:
                blockers.append({'role': role.role_code, 'native_group_members': native_members})
            if role.archived_at and wanted:
                blockers.append({'role': role.role_code, 'reason': '角色已停用，不能自动恢复'})
            assignments = [{'employee_id': str(row.employee_id), 'effective_from': row.effective_from.isoformat(),
                            'effective_to': row.effective_to.isoformat() if row.effective_to else None}
                           for row in role.employee_assignments.order_by('employee_id', 'effective_from')]
            output.append({
                'id': str(role.pk), 'role_code': role.role_code, 'etag': etag_for_instance(role),
                'before': before, 'after': wanted, 'assignments': assignments,
                'added': [row for row in wanted if (row['permission'], row['scope'], tuple(row.get('resource_ids', []))) not in before_keys],
                'revoked': [row for row in before if (row['permission'], row['scope'], tuple(row.get('resource_ids', []))) not in wanted_keys],
                'group_permission_ids': [p.pk for p in group_permissions],
                'removed_group_permissions': [permission_code(p) for p in group_permissions if p.pk not in target_group_ids],
                'group_projection_changed': {p.pk for p in group_permissions} != target_group_ids,
            })
        missing_roles = sorted(requested - {row['role_code'] for row in output})
        if missing_roles:
            blockers.append({'missing_roles': missing_roles})
        if requested & set(DIRECTORS) and missing_workshops:
            blockers.append({'missing_workshops': missing_workshops})
        if 'COATING_MATERIALS' in requested and not craft_ids:
            blockers.append({'reason': '缺少有效POWDER_COATING喷塑委外工艺'})
    payload = {'database': connection.settings_dict['NAME'], 'roles': output, 'blockers': blockers,
               'superuser_changes_on_policy_enable': superuser_plan(),
               'preserved_roles': sorted(set(PENDING)), 'schema_version': '20261102'}
    payload['digest'] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload


class Command(BaseCommand):
    help = '预览已确认角色精确新增/撤销及旧组清理；显式apply，不分配员工、不修改暂缓销售角色。'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--role-code', action='append')
        parser.add_argument('--database-name')
        parser.add_argument('--expected-digest')
        parser.add_argument('--actor-username')

    @transaction.atomic
    def handle(self, *args, **options):
        if not options['apply']:
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION READ ONLY')
            self.stdout.write(json.dumps(role_plan(options['role_code']), ensure_ascii=False))
            return
        if options['database_name'] != connection.settings_dict['NAME']:
            raise CommandError('须明确指定当前目标数据库完整名称。')
        if not (settings.MODULE_ACCESS_ENABLED and settings.ACCESS_RESOURCE_SCOPES_ENABLED
                and getattr(settings, 'CONFIRMED_ROLE_POLICY_ENABLED', False)):
            raise CommandError('须先确认启用模块、资源范围和本轮角色策略开关。')
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(20261102, 1)')
        plan = role_plan(options['role_code'], lock=True)
        if options['expected_digest'] != plan['digest']:
            raise CommandError('预览摘要已变化，须重新审阅；没有写入。')
        if plan['blockers']:
            raise CommandError('预览存在阻断项，不能应用：' + json.dumps(plan['blockers'], ensure_ascii=False))
        try:
            user = get_user_model().objects.get(username=options['actor_username'], is_active=True)
        except get_user_model().DoesNotExist as exc:
            raise CommandError('操作者不存在或未启用。') from exc
        request = SimpleNamespace(user=user, META={}, headers={})
        require_manager(request)
        for row in plan['roles']:
            validate_resources(row['after'])
            if not row['added'] and not row['revoked'] and not row['group_projection_changed']:
                continue
            request.headers = {'If-Match': row['etag']}
            request.META = {'HTTP_IF_MATCH': row['etag']}
            replace_grants(request, row['id'], row['after'],
                           reviewed_group_permission_ids=row['group_permission_ids'])
        employee_ids = {assignment['employee_id'] for row in plan['roles'] for assignment in row['assignments']}
        for account in get_user_model().objects.filter(employee_profile__pk__in=employee_ids).order_by('pk'):
            sync_role_superuser(account, request=request)
        result = role_plan(options['role_code'])
        result.update(applied=True, before_digest=plan['digest'])
        self.stdout.write(json.dumps(result, ensure_ascii=False))
