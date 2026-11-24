from decimal import Decimal, InvalidOperation
from math import ceil

from django.conf import settings
from django.db.models import Q
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.access_control import module_policy, sales_policy
from apps.core.api.permissions import HasActiveEmployee
from apps.production_tasks.models import ProductionTask

from ..models import PurchaseScope
from ..purchase_scope import PACKAGING_PERMISSION
from ..tracking_permissions import (
    VIEW_PERMISSION, accessible_packaging_tracking_task_ids, accessible_tracking_task_ids, can_read_packaging_as_pmc,
)
from ..tracking_selectors import arrival_rows, coverage_rows
from .group_serializers import PurchaseGroupFilterOptionsSerializer
from .tracking_serializers import (
    ArrivalTrackingResponseSerializer, ArrivalTrackingRowSerializer,
    CoverageTrackingResponseSerializer, CoverageTrackingRowSerializer, TrackingFilterSerializer,
)


class TrackingViewPermission(BasePermission):
    message = '当前账号没有采购查看权限。'

    def has_permission(self, request, view):
        return any(module_policy.has_permission(request, code) for code in (VIEW_PERMISSION, PACKAGING_PERMISSION))


def _decimal_value(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _arrival_is_incomplete(row):
    """只保留未到齐或退货待处理行；数量无法核对时不能当作已到齐。"""
    unreceived = _decimal_value(row.get('unreceived_quantity'))
    return (
        unreceived is None
        or unreceived > 0
        or row.get('return_pending')
        or (_decimal_value(row.get('return_quantity')) or Decimal('0')) > 0
    )


def _coverage_is_incomplete(row):
    """采购覆盖量为零的行不展示；需求量未知时保留待核对提醒。"""
    remaining = _decimal_value(row.get('remaining_quantity'))
    if remaining is not None:
        return remaining > 0
    return not row.get('source_reliable') or any(
        risk['code'] in {'DEMAND_UNKNOWN', 'DEMAND_CHANGED'} for risk in row.get('risks', [])
    )


def _sort_coverage_rows(rows):
    if not settings.PURCHASE_TRACKING_POLICY_ENABLED:
        rows.sort(key=lambda row: (row['task_number'], row.get('material_inbound_date') or '9999-12-31',
            row.get('material_name') or '', row['row_key']))
        return
    # 先按订单最急的一行排序，订单内再按期限排序，保持同一订单连续以便合并。
    group_priority = {}
    for row in rows:
        deadline_known = row.get('scheduled') and row.get('source_reliable') and row.get('latest_purchase_date')
        # 已排产且期限可靠时，BOM超时继续提示，但不压过更近的采购期限；缺数据警告仍保留优先级。
        rank = max((item['rank'] for item in row['risks']
            if not (deadline_known and item.get('code') == 'BOM_PURCHASE_TIMEOUT')), default=0)
        due = row.get('latest_purchase_date') or row.get('bom_purchase_due_at') or '9999-12-31'
        key = (-rank, due)
        task_id = row['production_task_id']
        group_priority[task_id] = min(group_priority.get(task_id, key), key)
    rows.sort(key=lambda row: (*group_priority[row['production_task_id']], row['task_number'],
        row['production_task_id'], row.get('latest_purchase_date') or row.get('bom_purchase_due_at') or '9999-12-31',
        row.get('material_name') or '', row['row_key']))


class PurchaseTrackingViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, TrackingViewPermission]
    serializer_class = ArrivalTrackingRowSerializer
    pagination_class = None

    def _filters(self):
        serializer = TrackingFilterSerializer(data=self.request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _task_scopes(self, filters):
        request = self.request
        can_standard = module_policy.has_permission(request, VIEW_PERMISSION)
        can_packaging = module_policy.has_permission(request, PACKAGING_PERMISSION) or (
            can_standard and can_read_packaging_as_pmc(sales_policy.access_for(request)))
        selected = filters.get('purchase_scope', PurchaseScope.STANDARD if can_standard else PurchaseScope.PACKAGING)
        scopes = {}
        if can_standard and selected in (PurchaseScope.STANDARD, 'ALL'):
            scopes[PurchaseScope.STANDARD] = accessible_tracking_task_ids(request)
        if can_packaging and selected in (PurchaseScope.PACKAGING, 'ALL'):
            scopes[PurchaseScope.PACKAGING] = accessible_packaging_tracking_task_ids(request)
        if not scopes:
            raise PermissionDenied('当前账号无权查看所选采购范围。')
        task_id = filters.get('production_task_id')
        return {scope: tasks.filter(pk=task_id) if task_id else tasks for scope, tasks in scopes.items()}

    def _rows(self, selector, serializer_class, *, mode):
        filters = self._filters()
        # 必须先在数据库限定可见任务，再进行批量事实计算；分页不会影响权限边界。
        rows = [row for scope, tasks in self._task_scopes(filters).items()
                for row in selector(task_ids=tasks, include_history=filters['include_history'], purchase_scope=scope)]
        rows = [row for row in rows if _arrival_is_incomplete(row)] if mode == 'arrival' else [row for row in rows if _coverage_is_incomplete(row)]
        if filters.get('risk'):
            rows = [row for row in rows if any(risk['code'] == filters['risk'] for risk in row['risks'])]
        if filters.get('row_key'):
            rows = [row for row in rows if row['row_key'] == filters['row_key']]
        if mode == 'arrival':
            rows.sort(key=lambda row: (
                row['task_number'],
                row['production_task_id'],
                row.get('purchase_order_no') or '9999',
                row.get('delivery_date') or '9999-12-31',
                row.get('supplier_name') or '',
                row['row_key'],
            ))
        else:
            _sort_coverage_rows(rows)
        total = len(rows)
        start = (filters['page'] - 1) * filters['page_size']
        page = rows[start:start + filters['page_size']]
        self._filter_actions(page)
        return Response({'data': serializer_class(page, many=True).data, 'meta': {
            'page': filters['page'], 'page_size': filters['page_size'], 'total': total,
            'total_pages': ceil(total / filters['page_size']),
        }})

    def _filter_actions(self, rows):
        visible_task_ids = {row['production_task_id'] for row in rows}
        required = {
            PurchaseScope.STANDARD: dict.fromkeys(('create_group', 'create_batch'), 'procurement.add_purchaseorder'),
            PurchaseScope.PACKAGING: dict.fromkeys(('create_group', 'create_batch', 'view_group', 'view_return'), PACKAGING_PERMISSION),
        }
        for permissions in required.values():
            permissions['view_bom'] = 'boms.view_bom'
        wanted = {required[row['purchase_scope']][action['kind']] for row in rows for action in row['actions']
                  if action['kind'] in required[row['purchase_scope']]}
        allowed = {permission: {str(pk) for pk in accessible_tracking_task_ids(self.request, permission=permission)
                               .filter(pk__in=visible_task_ids)} for permission in wanted}
        for row in rows:
            actions = row['actions']
            permissions = required[row['purchase_scope']]
            row['actions'] = [action for action in actions if action['kind'] not in permissions
                              or row['production_task_id'] in allowed[permissions[action['kind']]]]
            if any(action['kind'].startswith('create_') for action in actions) and not any(
                    action['kind'].startswith('create_') for action in row['actions']):
                row['action_blocked_reason'] = '当前账号没有该任务的新增采购权限'

    @extend_schema(parameters=[TrackingFilterSerializer], responses=ArrivalTrackingResponseSerializer)
    @action(detail=False, methods=['get'])
    def arrivals(self, request):
        return self._rows(arrival_rows, ArrivalTrackingRowSerializer, mode='arrival')

    @extend_schema(parameters=[TrackingFilterSerializer], responses=CoverageTrackingResponseSerializer)
    @action(detail=False, methods=['get'])
    def coverage(self, request):
        return self._rows(coverage_rows, CoverageTrackingRowSerializer, mode='coverage')

    @extend_schema(responses=inline_serializer(name='PurchaseTrackingFilterOptionsResponse',
        fields={'data': PurchaseGroupFilterOptionsSerializer()}))
    @action(detail=False, methods=['get'], url_path='filter-options')
    def filter_options(self, request):
        task_filter = Q(pk__in=[])
        for task_ids in self._task_scopes(self._filters()).values():
            task_filter |= Q(pk__in=task_ids)
        tasks = ProductionTask.objects.filter(task_filter).filter(
            Q(status__in=['READY', 'IN_PRODUCTION', 'PAUSED', 'COMPLETED', 'CANCELLED'])
            | Q(purchase_orders__isnull=False)).order_by('task_number', 'id').values('id', 'task_number', 'order_number').distinct()
        return Response({'data': PurchaseGroupFilterOptionsSerializer({'production_tasks': list(tasks)}).data})
