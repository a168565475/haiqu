import hashlib
import json
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test import override_settings

from apps.access_control.catalog import catalog
from apps.access_control.production_role_templates import DIRECTORS, PENDING, templates
from apps.access_control.selectors import grant_rows
from apps.access_control.services import assert_managed_projection, replace_grants
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import RoleProfile
from apps.workshop_config.models import Workshop


def role_plan(*, lock=False):
    workshops = {name: str(Workshop.objects.get(name=name, status='ACTIVE').pk) for name in DIRECTORS.values()}
    with override_settings(ACCESS_RESOURCE_SCOPES_ENABLED=True):
        desired = templates(workshops)
        entries = catalog()
        roles = RoleProfile.objects.select_related('auth_group').order_by('role_code')
        if lock:
            roles = roles.select_for_update(of=('self',))
        output = []
        for role in roles:
            before = grant_rows(role)
            wanted = desired.get(role.role_code, [])
            if wanted and role.archived_at:
                raise CommandError(f'{role.role_code}已停用，停止整批配置。')
            assert_managed_projection(role)
            by_key = {(row['permission'], row['scope']): row for row in before}
            added = []
            for row in wanted:
                key = (row['permission'], row['scope'])
                if key not in by_key:
                    added.append(row)
                    by_key[key] = row
                elif sorted(row.get('resource_ids', [])) != sorted(by_key[key].get('resource_ids', [])):
                    raise CommandError(f'{role.role_code}的{key[0]}资源与基线冲突，请先审阅。')
            output.append({'id': str(role.pk), 'role_code': role.role_code, 'name': role.display_name,
                'etag': etag_for_instance(role), 'status': PENDING.get(role.role_code,
                    '材料需求/领料职责已确定；裁剪参数与报工对应关系待确认' if role.role_code == 'FABRIC_SAMPLING' else '已确定职责'),
                'before': before, 'added': added, 'retained': before, 'revoked': [],
                'after': sorted(by_key.values(), key=lambda row: (row['permission'], row['scope'])),
                'active_assignments': current_assignments_for_role(role),
                'native_group_members': role.auth_group.user_set.count()})
    actual = {row['role_code'] for row in output}
    if set(desired) - actual:
        raise CommandError('缺少既有角色：' + ','.join(sorted(set(desired) - actual)))
    payload = {'database': connection.settings_dict['NAME'], 'roles': output,
        'missing_permissions': [row['code'] for row in entries if not row['available']],
        'catalog_codes': [row['code'] for row in entries]}
    payload['digest'] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload


def current_assignments_for_role(role):
    from django.utils import timezone
    from django.db.models import Q
    from apps.organizations.models import EmployeeRoleAssignment
    now = timezone.now()
    return EmployeeRoleAssignment.objects.filter(role_profile=role, employee__status='ACTIVE',
        employee__archived_at__isnull=True, effective_from__lte=now).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gt=now)).count()


class Command(BaseCommand):
    help = '预览生产角色新增/保留/撤销差异；显式apply复用授权服务、ETag及审计，不分配员工。'

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
            self.stdout.write(json.dumps(role_plan(), ensure_ascii=False))
            return
        if options['database_name'] != connection.settings_dict['NAME']:
            raise CommandError('须明确指定当前目标数据库完整名称。')
        if not (settings.MODULE_ACCESS_ENABLED and settings.ACCESS_RESOURCE_SCOPES_ENABLED):
            raise CommandError('先完成权限及资源开关启用确认，不能在不生效的环境写入角色配置。')
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(20261020, 3)')
        plan = role_plan(lock=True)
        if options['expected_digest'] != plan['digest']:
            raise CommandError('预览已变化，请重新审阅最新差异；没有写入。')
        if plan['missing_permissions']:
            raise CommandError('权限记录尚缺失，请先应用已确认迁移。')
        user = get_user_model().objects.get(username=options['actor_username'], is_active=True)
        request = SimpleNamespace(user=user, META={}, headers={})
        from apps.access_control.services import require_manager
        require_manager(request)
        for row in plan['roles']:
            if not row['added']:
                continue
            request.headers = {'If-Match': row['etag']}
            request.META = {'HTTP_IF_MATCH': row['etag']}
            replace_grants(request, row['id'], row['after'])
        result = role_plan()
        result['applied'] = True
        result['before_digest'] = plan['digest']
        self.stdout.write(json.dumps(result, ensure_ascii=False))
