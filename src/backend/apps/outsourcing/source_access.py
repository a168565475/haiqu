"""同一外发动作的来源范围；不同角色取并集，不拼接不同动作的范围。"""
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from apps.access_control.resource_scopes import enforcing, has_legacy_permission
from apps.access_control.sales_policy import access_for

STOCK_SOURCES = {'RAW_PIPE', 'PUBLIC_SEMI', 'PUBLIC_CUTTING'}
DIRECT_WORKSHOPS = {'METAL': '金工车间', 'SEWING': '车缝车间'}


def source_grants(request, permission):
    access = access_for(request)
    if not access['active']:
        return []
    return access['actions'].get(permission, {}).get('sources', [])


def workshop_sources(ids):
    from apps.workshop_config.models import Workshop
    names = set(Workshop.objects.filter(pk__in=ids, status='ACTIVE').values_list('name', flat=True))
    return {kind for kind, name in DIRECT_WORKSHOPS.items() if name in names}


def allowed_source_kinds(request, permission):
    if not enforcing(request, permission):
        return STOCK_SOURCES | set(DIRECT_WORKSHOPS)
    access = access_for(request)
    result = set()
    if access['is_superuser'] or has_legacy_permission(request, permission):
        return STOCK_SOURCES | set(DIRECT_WORKSHOPS)
    for source in source_grants(request, permission):
        if source.get('scope') in {'MODULE', 'ALL'} or (source.get('scope') == 'CRAFT' and source.get('resource_ids')):
            return STOCK_SOURCES | set(DIRECT_WORKSHOPS)
        if source.get('scope') == 'STOCK':
            result.update(STOCK_SOURCES)
        if source.get('scope') == 'WORKSHOP':
            result.update(workshop_sources(source.get('resource_ids', [])))
    return result


def require_source(request, permission, source_kind):
    if source_kind not in allowed_source_kinds(request, permission):
        raise PermissionDenied('当前动作未授权此库存或车间来源。')


def require_source_product(request, permission, source_kind, product):
    require_source(request, permission, source_kind)
    if not enforcing(request, permission) or source_kind not in DIRECT_WORKSHOPS:
        return
    access = access_for(request)
    sources = source_grants(request, permission)
    if access['is_superuser'] or has_legacy_permission(request, permission) or any(
        source.get('scope') in {'MODULE', 'ALL', 'CRAFT'} for source in sources
    ):
        return
    ids = {pk for source in sources if source.get('scope') == 'WORKSHOP' for pk in source.get('resource_ids', [])}
    if not product.crafts.filter(removed_at__isnull=True, craft_type_snapshot='INTERNAL',
        plan_category=source_kind, craft__workshop_id__in=ids,
        craft__workshop__name=DIRECT_WORKSHOPS[source_kind]).exists():
        raise PermissionDenied('所选产品的实际工艺车间不在当前来源授权内。')


def filter_source_products(queryset, request, permission):
    if not enforcing(request, permission):
        return queryset
    access = access_for(request)
    sources = source_grants(request, permission)
    if not access['active']:
        return queryset.none()
    if access['is_superuser'] or has_legacy_permission(request, permission) or any(
        source.get('scope') in {'MODULE', 'ALL', 'STOCK'} or
        (source.get('scope') == 'CRAFT' and source.get('resource_ids')) for source in sources
    ):
        return queryset
    ids = {pk for source in sources if source.get('scope') == 'WORKSHOP' for pk in source.get('resource_ids', [])}
    return queryset.filter(crafts__removed_at__isnull=True, crafts__craft_type_snapshot='INTERNAL',
        crafts__plan_category__in=workshop_sources(ids), crafts__craft__workshop_id__in=ids).distinct()


def scoped_tube_orders(queryset, request, permission, legacy_queryset):
    if not enforcing(request, permission):
        return legacy_queryset
    access = access_for(request)
    if not access['active']:
        return queryset.none()
    if access['is_superuser']:
        return queryset
    allowed = Q(pk__in=[])
    for source in source_grants(request, permission):
        scope = source.get('scope')
        if scope in {'MODULE', 'ALL'}:
            return queryset
        if scope == 'CRAFT':
            allowed |= Q(craft_id__in=source.get('resource_ids', []))
        elif scope == 'STOCK':
            allowed |= Q(source_kind__in=STOCK_SOURCES)
        elif scope == 'WORKSHOP':
            allowed |= Q(source_kind__in=workshop_sources(source.get('resource_ids', [])))
    if has_legacy_permission(request, permission):
        allowed |= Q(pk__in=legacy_queryset.values('pk'))
    return queryset.filter(allowed).distinct()


def scoped_regular_orders(queryset, request, permission, legacy_queryset):
    if not enforcing(request, permission):
        return legacy_queryset
    access = access_for(request)
    if not access['active']:
        return queryset.none()
    if access['is_superuser']:
        return queryset
    allowed = Q(pk__in=[])
    for source in source_grants(request, permission):
        scope = source.get('scope')
        if scope in {'MODULE', 'ALL'}:
            return queryset
        if scope == 'CRAFT':
            allowed |= Q(craft_id__in=source.get('resource_ids', []))
        elif scope == 'STOCK':
            allowed |= Q(metal_processing_original_handoffs__isnull=True)
        elif scope == 'WORKSHOP':
            allowed |= Q(metal_processing_original_handoffs__source__issue_line__issue__workshop_id__in=source.get('resource_ids', []))
    if has_legacy_permission(request, permission):
        allowed |= Q(pk__in=legacy_queryset.values('pk'))
    return queryset.filter(allowed).distinct()
