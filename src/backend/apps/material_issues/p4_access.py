"""Authorization for craft-bearing metal flow records, including request replays."""
from django.shortcuts import get_object_or_404
from apps.access_control.resource_scopes import enabled, require_craft, craft_access_union, resource_ids, has_legacy_permission
from .processing_selectors import processing_lines


def can_record(request, permission, kind, pk):
    if request is None or not request.user.has_perm(permission):
        return False
    from django.http import Http404
    from rest_framework.exceptions import PermissionDenied
    try:
        require_record(request, permission, kind, pk)
        return True
    except (Http404, PermissionDenied):
        return False


def scoped_records(queryset, request, permission, craft_field='craft_id', source_field='source__issue_line'):
    legacy = queryset.filter(**{source_field + '__in': processing_lines(request, scoped=False, permission=permission)})
    candidates = queryset.filter(**{source_field + '__in': processing_lines(request, permission=permission)})
    return craft_access_union(candidates, legacy, request, permission, craft_field)


def require_external_destination(request, rework_id, craft_id):
    if not enabled():
        return
    from .models import MetalProcessingRework
    from rest_framework.exceptions import PermissionDenied
    permission = 'material_issues.create_metalprocessingexternalorder'
    ids = resource_ids(request, permission, 'CRAFT', include_legacy=False)
    if ids is None or str(craft_id) in ids:
        return
    if has_legacy_permission(request, permission) and MetalProcessingRework.objects.filter(
        pk=rework_id, source__issue_line__in=processing_lines(request, scoped=False, permission=permission)
    ).exists():
        return
    raise PermissionDenied('当前来源不允许创建该工艺的外发单。')


def require_record(request, permission, kind, pk):
    if not enabled():
        return
    from .models import (MetalProcessingOriginalHandoff, MetalProcessingUnsprayedReturn,
                         MetalProcessingRework, MetalProcessingExternalOrder)
    from apps.outsourcing.models import OutsourcingOrder
    from apps.outsourcing.selectors import accessible_outsourcing_orders
    if kind == 'original':
        order = get_object_or_404(accessible_outsourcing_orders(request, permission=permission), pk=pk)
        require_craft(request, permission, order.craft_id)
        return
    model, source_path, craft_path = {
        'handoff': (MetalProcessingOriginalHandoff, 'source', 'original_order'),
        'return': (MetalProcessingUnsprayedReturn, 'original_handoff__source', 'original_handoff__original_order'),
        'rework': (MetalProcessingRework, 'source', 'unsprayed_return__original_handoff__original_order'),
        'external': (MetalProcessingExternalOrder, 'source', ''),
    }[kind]
    field = craft_path + '__craft_id' if craft_path else 'craft_id'
    get_object_or_404(scoped_records(model.objects.all(), request, permission, field,
        source_path + '__issue_line'), pk=pk)
