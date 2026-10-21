"""Per-operation resource selections. Disabled until the forward migration is deployed."""
from django.conf import settings
from rest_framework.exceptions import PermissionDenied, ValidationError


def configured():
    return bool(getattr(settings, 'ACCESS_RESOURCE_SCOPES_ENABLED', False))


def enabled():
    return configured() and bool(getattr(settings, 'MODULE_ACCESS_ENABLED', False))


def enforcing(request, code):
    if enabled():
        return True
    from .sales_policy import access_for
    # 回退开关不能把已配置的资源角色升级成全模块；关闭资源开关时不读取资源表。
    return bool(set(access_for(request)['actions'].get(code, {}).get('scopes', [])) & {'MODULE', 'ALL', 'WORKSHOP', 'CRAFT', 'STOCK'})


def scope_kind(code):
    if code.startswith('production_scheduling.') and '.view_all_' not in code:
        return 'WORKSHOP'
    if code.startswith('material_issues.') and code.endswith('materialissue') and '.view_all_' not in code:
        return 'WORKSHOP'
    if code.startswith('workshop_reporting.') and '.view_all_' not in code:
        return 'WORKSHOP'
    if code.startswith('outsourcing.') and 'outsourcingorder' in code:
        return 'CRAFT'
    if code.startswith('material_issues.') and 'metalprocessing' in code and code not in {
        'material_issues.register_metalprocessingcompletion',
        'material_issues.close_metalprocessingsource',
    }:
        return 'CRAFT'
    return None


def current_permission(request, default):
    from .module_policy import action_permission
    view = (getattr(request, 'parser_context', None) or {}).get('view')
    permission = action_permission(request, view) if view is not None else None
    return permission if isinstance(permission, str) and scope_kind(permission) == scope_kind(default) else default


def resource_ids(request, code, kind, *, include_legacy=True):
    """None = unrestricted, empty = no access. Never union different operations."""
    from .sales_policy import access_for
    from .module_operations import LEGACY_ALIASES
    if not enforcing(request, code):
        return None
    access = access_for(request)
    if not access['active']:
        return set()
    entry = access['actions'].get(code, {})
    if access['is_superuser'] or set(entry.get('scopes', [])) & {'MODULE', 'ALL'}:
        return None
    if kind == 'CRAFT' and code.startswith('outsourcing.') and (
        'STOCK' in entry.get('scopes', []) or any(
            source.get('scope') == 'WORKSHOP' and source.get('resource_ids')
            for source in entry.get('sources', [])
        )
    ):
        # 来源范围还须由source_access检查实际库存/车间，不能仅凭此处放行对象。
        return None
    legacy = {row['permission'] for row in access['legacy_sources']}
    if include_legacy and (code in legacy or LEGACY_ALIASES.get(code) in legacy):
        return None
    return {str(pk) for source in entry.get('sources', []) if source.get('scope') == kind
            for pk in source.get('resource_ids', [])}


def filter_crafts(queryset, request, permission, field='craft_id', *, include_legacy=True):
    ids = resource_ids(request, permission, 'CRAFT', include_legacy=include_legacy)
    return queryset if ids is None else queryset.filter(**{f'{field}__in': ids})


def has_legacy_permission(request, permission):
    from .sales_policy import access_for
    from .module_operations import LEGACY_ALIASES
    access = access_for(request)
    legacy = {row['permission'] for row in access['legacy_sources']}
    return access['active'] and bool({permission, LEGACY_ALIASES.get(permission)} & legacy)


def craft_access_union(queryset, legacy_queryset, request, permission, field='craft_id'):
    """Union sources without combining a legacy scope with new contextual visibility."""
    if not enforcing(request, permission):
        return legacy_queryset
    selected = filter_crafts(queryset, request, permission, field, include_legacy=False)
    if has_legacy_permission(request, permission):
        return selected.distinct() | legacy_queryset.distinct()
    return selected


def require_craft(request, permission, craft_id):
    ids = resource_ids(request, permission, 'CRAFT')
    if ids is not None and str(craft_id) not in ids:
        raise PermissionDenied('当前操作未授权此外协工艺。')


def can_craft(request, permission, craft_id):
    if request is None or not request.user.has_perm(permission):
        return False
    ids = resource_ids(request, permission, 'CRAFT')
    return ids is None or str(craft_id) in ids


def can_order(request, permission, order):
    if not can_craft(request, permission, order.craft_id):
        return False
    from .sales_policy import access_for
    if enforcing(request, permission) and set(access_for(request)['actions'].get(permission, {}).get('scopes', [])) & {'STOCK', 'WORKSHOP'}:
        from apps.outsourcing.selectors import accessible_outsourcing_orders
        return accessible_outsourcing_orders(request, permission=permission).filter(pk=order.pk).exists()
    if not enabled():
        return True
    ids = resource_ids(request, permission, 'CRAFT', include_legacy=False)
    if ids is None or str(order.craft_id) in ids:
        return True
    from apps.production_scheduling.selectors import accessible_production_schedules
    cache = getattr(request, '_legacy_outsourcing_schedules', None)
    if cache is None:
        cache = request._legacy_outsourcing_schedules = {}
    if order.schedule_id not in cache:
        cache[order.schedule_id] = accessible_production_schedules(request).filter(pk=order.schedule_id).exists()
    return has_legacy_permission(request, permission) and cache[order.schedule_id]


def require_order_craft(request, permission, order_id):
    if not enforcing(request, permission):
        return
    from django.shortcuts import get_object_or_404
    from apps.outsourcing.selectors import accessible_outsourcing_orders
    get_object_or_404(accessible_outsourcing_orders(request, permission=permission), pk=order_id)


def has_resource_grant(request, permission, kind):
    if not enabled():
        return False
    from .sales_policy import access_for
    access = access_for(request)
    return access['active'] and kind in access['actions'].get(permission, {}).get('scopes', [])


def require_workshop(request, permission, workshop_id):
    if not enforcing(request, permission):
        return
    if permission.startswith('workshop_reporting.'):
        from apps.workshop_reporting.selectors import allowed_workshop_ids
        ids = allowed_workshop_ids(request, permission=permission,
                                  for_work_reports=permission.endswith('workreport'))
    else:
        ids = resource_ids(request, permission, 'WORKSHOP')
    if ids is not None and str(workshop_id) not in {str(pk) for pk in ids}:
        raise PermissionDenied('当前操作未授权该车间。')


def scope_options():
    if not configured():
        return {'enabled': False, 'workshops': [], 'crafts': []}
    from apps.workshop_config.models import Workshop, Craft
    # Include inactive historical selections for honest display; no business activation implied.
    def rows(queryset):
        return [{'id': str(obj.pk), 'name': obj.name, 'active': obj.status == 'ACTIVE'} for obj in queryset.order_by('name', 'id')]
    return {'enabled': True, 'workshops': rows(Workshop.objects.all()),
            'crafts': rows(Craft.objects.filter(craft_type='EXTERNAL'))}


def validate_resources(rows):
    from apps.workshop_config.models import Workshop, Craft
    result = {}
    for row in rows:
        ids = [str(pk) for pk in row.get('resource_ids', [])]
        scope = row['scope']
        if scope not in {'WORKSHOP', 'CRAFT'}:
            if ids:
                raise ValidationError({'grants': '只有指定车间或工艺范围可以选择资源。'})
            continue
        supported = scope_kind(row['permission']) == scope or (
            scope == 'WORKSHOP' and row['permission'].startswith('outsourcing.')
            and 'outsourcingorder' in row['permission'])
        if not configured() or not supported:
            raise ValidationError({'grants': '当前操作不支持该资源范围。'})
        if len(ids) != len(set(ids)):
            raise ValidationError({'grants': '所选资源不能重复。'})
        model = Workshop if scope == 'WORKSHOP' else Craft
        qs = model.objects.filter(pk__in=ids)
        if scope == 'CRAFT':
            qs = qs.filter(craft_type='EXTERNAL')
        if qs.count() != len(ids):
            raise ValidationError({'grants': '所选车间或外协工艺不存在。'})
        # Empty selections intentionally grant no resources.
        result[(row['permission'], scope)] = sorted(ids)
    return result


def save_resources(role, selections):
    if not configured():
        return
    from .models import RoleGrantResource
    from .selectors import role_grants
    from .catalog import permission_code
    resources = []
    for grant in role_grants(role):
        field = 'workshop_id' if grant.scope == 'WORKSHOP' else 'craft_id'
        resources.extend(RoleGrantResource(grant=grant, **{field: pk})
                         for pk in selections.get((permission_code(grant.permission), grant.scope), []))
    RoleGrantResource.objects.bulk_create(resources)


def selected_ids(grant):
    if not configured() or grant.scope not in {'WORKSHOP', 'CRAFT'}:
        return []
    return sorted(str(row.workshop_id or row.craft_id) for row in grant.resource_selections.all())
