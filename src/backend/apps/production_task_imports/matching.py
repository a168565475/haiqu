"""仅查询真实候选；唯一匹配仍由用户在原产品编辑器确认，不建主档。"""
from django.db.models import Q

from apps.organizations.selectors import active_department_employees, active_role_employees
from apps.product_catalog.models import ProductCatalog
from apps.reference_data.models import ProductionUnit
from .validation import extracted


def match_result(result):
    matched = {'products': {}, 'salespersons': [], 'followers': []}
    for line in result['products']:
        fields = line['fields']
        name = extracted(fields['product_name']) or ''
        code = extracted(fields['product_identifier_original']) or ''
        spec = extracted(fields['specification']) or ''
        candidates = ProductCatalog.objects.filter(archived_at__isnull=True,
            name__archived_at__isnull=True, name__category__archived_at__isnull=True).select_related('name__category')
        identity = Q(name__name=name) if name else Q(pk__in=[])
        if code:
            identity |= Q(product_code=code) | Q(item_number=code)
        candidates = candidates.filter(identity)
        if spec:
            candidates = candidates.filter(specification=spec)
        products = list(candidates.order_by('pk')[:21])
        unit_text = extracted(fields['unit_text'])
        units = ProductionUnit.objects.filter(archived_at__isnull=True, status='ACTIVE')
        units = units.filter(Q(unit_name=unit_text) | Q(unit_code=unit_text)) if unit_text else units.none()
        matched['products'][line['line_key']] = {
            'status': 'MATCHED' if len(products) == 1 else 'AMBIGUOUS' if products else 'UNMATCHED',
            'has_more': len(products) > 20,
            'candidates': [{'id': str(item.pk), 'name': item.name.name, 'category': item.name.category.name,
                            'specification': item.specification, 'product_code': item.product_code,
                            'item_number': item.item_number, 'version': item.updated_at.isoformat()}
                           for item in products[:20]],
            'units': [{'id': str(item.pk), 'name': item.unit_name, 'code': item.unit_code} for item in units[:20]],
        }
    for target, field, candidates in (
        ('salespersons', 'salesperson_text', active_department_employees('DEPT_BUSINESS')),
        ('followers', 'followers_text', active_role_employees('MERCHANDISER')),
    ):
        text = extracted(result['fields'][field])
        if text:
            matched[target] = [{'id': str(item.pk), 'name': item.display_name} for item in
                               candidates.filter(display_name=text).order_by('pk')[:20]]
    return matched
