"""仓库外发待办按单显示，实办汇总按每次发出或回货凭证计数。"""
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.access_control.module_policy import has_permission
from apps.outsourcing.warehouse_access import (
    DISPATCH_PERMISSION, RETURN_PERMISSION, REWORK_HANDOFF_PERMISSION, REWORK_RETURN_PERMISSION,
)
from .warehouse_workbench_external_legacy import legacy_events, original_documents, regular_documents, rework_documents
from .warehouse_workbench_external_tubes import tube_documents, tube_events


SOURCES = {'tube': tube_documents, 'outsourcing': regular_documents, 'metal_original': original_documents,
           'rework': rework_documents}
ACTIONS = {'dispatch': (DISPATCH_PERMISSION, REWORK_HANDOFF_PERMISSION),
           'returns': (RETURN_PERMISSION, REWORK_RETURN_PERMISSION)}


def _available(request, key):
    return any(has_permission(request, code) for code in ACTIONS[key])


def _rows(request, key):
    rows = [row for source in SOURCES.values() for row, _ in source(request, key, None)]
    return sorted(rows, key=lambda r: (r['date'] is None, r['date'], r['number'], r['kind'], r['id']))


def overview(request, key, today):
    if not _available(request, key):
        return {'available': False, 'count': None, 'breakdown': {}, 'preview': None, 'priority': []}
    rows = _rows(request,key)
    as_of = today.isoformat()
    dates = [row['date'] for row in rows if row['date']]
    counts = {'partial': sum(row['status'] in {'分批发出','部分回货'} for row in rows),
              'overdue': sum(day < as_of for day in dates), 'today': dates.count(as_of)}
    return {'available': True, 'count': len(rows), 'breakdown': counts, 'preview': rows[0] if rows else None,
            'priority': [r for r in rows if r['date'] and r['date'] <= as_of][:4]}


def items(request, key, params):
    if not _available(request, key):
        raise PermissionDenied('无此仓库收发权限。')
    rows = _rows(request,key)
    offset = (params['page'] - 1) * params['page_size']
    return len(rows), rows[offset:offset + params['page_size']]


def detail(request, key, kind, id):
    if not _available(request, key):
        raise PermissionDenied('无此仓库收发权限。')
    if kind not in SOURCES:
        raise NotFound()
    record = next(SOURCES[kind](request,key,id), None)
    if record is None:
        raise NotFound('单据已处理或不在可查看范围。')
    row, lines = record
    related, movements = None, []
    for side in ACTIONS:
        if not _available(request,side):
            continue
        if side != key and next(SOURCES[kind](request,side,id), None):
            related = {'queue': side, 'kind': kind, 'id': str(id)}
        if kind == 'tube':
            _, logs = tube_events(request,side,None,None,id)
        else:
            _, logs = legacy_events(request,side,None,None,kind,id)
        for log in logs:
            movements.append({'date': log['date'], 'action': '仓库发出' if side=='dispatch' else '仓库收回',
                              'number': log['number'], 'description': log['description']})
    movements.sort(key=lambda r: (r['date'],r['number']), reverse=True)
    return {'row': row, 'lines': lines, 'movements': movements, 'related': related}


def activity(request, key, start, end, limit, offset):
    if not _available(request,key):
        return None, []
    maximum = offset+limit if limit else 0
    tube_total, tubes = tube_events(request,key,(start,end),maximum,None)
    legacy_total, legacy = legacy_events(request,key,(start,end),maximum,None,None)
    rows = sorted(tubes+legacy, key=lambda row: (row['date'], row['id']), reverse=True)
    return tube_total+legacy_total, rows[offset:offset+limit]
