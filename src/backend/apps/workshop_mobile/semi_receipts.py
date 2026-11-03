from copy import copy

from apps.inventory.api.internal_receipts import InternalReceiptViewSet
from apps.inventory.receipt_permissions import receipt_plans_for_category


SEMI_RECEIPT_VIEW = 'inventory.view_internalsemifinishedreceipt'
SEMI_RECEIPT_ADD = 'inventory.add_internalsemifinishedreceipt'


def semi_receipt_products(request, category):
    # ERP 预览需查看权，提交仍需新增权；两种动作的来源必须同时可访问。
    sources = []
    for action in ('preview', 'create'):
        scoped = copy(request)
        scoped.__dict__.pop('_sales_access_snapshot', None)
        view = InternalReceiptViewSet()
        view.action = action
        view.request = scoped
        scoped.parser_context = {**(getattr(request, 'parser_context', None) or {}), 'view': view}
        sources.append(receipt_plans_for_category(scoped, category))
    return sources[1].filter(pk__in=sources[0].values('pk'))
