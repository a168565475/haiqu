"""从后端已保存对象解析收件范围；上下文中的展示文字不是授权依据。"""
from django.apps import apps
from django.db.models import Q
from django.utils import timezone

AUDIT_MODELS = {
    'PRODUCTION_TASK': ('production_tasks', 'ProductionTask'),
    'BOM': ('boms', 'Bom'), 'PRODUCTION_SCHEDULE': ('production_scheduling', 'ProductionSchedule'),
    'OUTSOURCING_ORDER': ('outsourcing', 'OutsourcingOrder'),
    'TUBE_OUTSOURCING_ORDER': ('outsourcing', 'TubeOutsourcingOrder'),
    'OUTSOURCING_FACTORY': ('outsourcing', 'OutsourcingFactory'),
    'RECEIVABLE_STATEMENT': ('finance', 'ReceivableStatement'),
    'FINANCE_RECEIPT': ('finance', 'Receipt'),
    'PRODUCTION_TASK_EXPENSE': ('production_tasks', 'ProductionTaskExpense'),
}


def audit_subject(log):
    model = AUDIT_MODELS.get(log.object_type)
    return apps.get_model(*model).objects.filter(pk=log.object_id).first() if model else None


def document_number(obj):
    for field in ('task_number', 'bom_number', 'schedule_number', 'order_number', 'issue_number', 'number', 'name'):
        if getattr(obj, field, None):
            return str(getattr(obj, field))
    return str(obj.pk)


def active_role_codes(employee_id):
    from apps.organizations.models import EmployeeRoleAssignment
    now = timezone.now()
    return set(EmployeeRoleAssignment.objects.filter(employee_id=employee_id,
        role_profile__archived_at__isnull=True, effective_from__lte=now).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gt=now)).values_list('role_profile__role_code', flat=True))


def _subject(event_code, object_id, context):
    """返回真正业务对象和可选的不可变成功审计。"""
    if context.get('audit_id'):
        from apps.audit.models import AuditLog
        from .notification_audit_events import AUDIT_EVENTS
        log = AuditLog.objects.filter(pk=object_id).first()
        if (log is None or str(log.pk) != context['audit_id']
                or AUDIT_EVENTS.get((log.object_type, log.action)) != event_code
                or str(log.actor_employee_id) != context.get('actor_employee_id')):
            return None, None
        subject = audit_subject(log)
        expected = str(subject.version_number) if event_code == 'BOM_CONFIRMED' and subject else str(log.pk)
        return (subject, log) if expected == context.get('object_version') else (None, None)
    from apps.samples.notification_events import SAMPLE_EVENTS, current_sample_object
    from apps.inventory.notification_events import INVENTORY_EVENTS, current_inventory_object
    from .workshop_notifications import WORKSHOP_EVENTS, current_workshop_object
    from .workshop_change_notifications import CHANGE_EVENTS, current_change_object
    version = context.get('object_version')
    for codes, resolver in ((SAMPLE_EVENTS, current_sample_object), (INVENTORY_EVENTS, current_inventory_object),
                            (WORKSHOP_EVENTS, current_workshop_object), (CHANGE_EVENTS, current_change_object)):
        if event_code in codes:
            # 每次保存是独立知悉事实，后一次保存不合并掉厂长尚未收到的前一条。
            return resolver(event_code, object_id, None if event_code == 'WORK_REPORT_SAVED' else version), None
    models = {
        'PRODUCTION_TASK_CONFIRMED': ('production_tasks', 'ProductionTask'),
        'PRODUCTION_TASK_BOMS_CONFIRMED': ('production_tasks', 'ProductionTask'),
        'BOM_CONFIRMED': ('boms', 'Bom'), 'PRODUCTION_PLAN_CREATED': ('production_scheduling', 'ProductionSchedule'),
        'MATERIAL_RECEIPT_RECORDED': ('inventory', 'MaterialInbound'),
        'MATERIAL_INSPECTION_CONFIRMED': ('inventory', 'MaterialInbound'),
        'PURCHASE_ORDER_COMPLETED': ('procurement', 'PurchaseOrder'),
        'MATERIAL_ISSUE_ISSUED': ('material_issues', 'MaterialIssue'),
        'COATING_REWORK_READY': ('material_issues', 'MetalProcessingExternalOrder'),
        'COATING_REWORK_DISPATCHED': ('material_issues', 'MetalProcessingExternalHandoff'),
        'COATING_REWORK_RECEIVED': ('material_issues', 'MetalProcessingExternalGoodReturn'),
    }
    if event_code == 'PRODUCTION_TASK_BOMS_CONFIRMED':
        from apps.boms.notification_events import current_task_bom_snapshot, snapshot_version
        current = current_task_bom_snapshot(object_id)
        if current is None or snapshot_version(current) != version:
            return None, None
    model = models.get(event_code)
    obj = apps.get_model(*model).objects.filter(pk=object_id).first() if model else None
    if event_code == 'MATERIAL_ISSUE_ISSUED' and obj is not None:
        if obj.status != 'ISSUED' or str(obj.version) != version:
            return None, None
    if event_code.startswith('COATING_REWORK_') and obj is not None:
        if str(obj.pk) != version or event_code == 'COATING_REWORK_READY' and obj.status != 'PENDING_HANDOFF':
            return None, None
    return obj, None


def object_facts(event_code, object_id, context):
    obj, log = _subject(event_code, object_id, context)
    deleted_finance = log is not None and log.action == 'DELETE' and log.object_type in {'RECEIVABLE_STATEMENT', 'FINANCE_RECEIPT'}
    if obj is None and not deleted_finance:
        return None
    actor_id = str(log.actor_employee_id) if log else context.get('actor_employee_id', '')
    if not actor_id:
        return None
    facts = {'task_ids': set(), 'workshop_ids': set(), 'craft_ids': set(), 'actor_id': actor_id,
             'actor_roles': set(context.get('actor_role_codes', '').split(',')), 'submitter_id': '', 'coating': False,
             'action': log.action if log else '', 'changed_fields': set(), 'new_follower_ids': set(),
             'subject': obj, 'deleted': deleted_finance, 'audit': log}
    if deleted_finance:
        return facts
    model = obj._meta.model_name
    if model == 'workreporthistory':
        snapshot = obj.deletion_snapshot
        product = apps.get_model('production_tasks', 'ProductionTaskProduct').objects.filter(pk=snapshot['product_line_id']).first()
        facts['task_ids'] = {str(product.production_task_id)} if product else set()
        facts['workshop_ids'] = {str(snapshot['workshop_id'])}
        facts['deleted'] = True
        return facts
    if model == 'outsourcingreconciliationentry':
        obj = obj.record.order
    elif model == 'tubeoutsourcingreceiptline':
        obj = obj.receipt.order
    elif model in {'metalprocessingexternalhandoff', 'metalprocessingexternalgoodreturn'}:
        obj = obj.order
    facts['subject'] = obj
    model = obj._meta.model_name
    if model == 'productiontask':
        facts['task_ids'] = {str(obj.pk)}
    elif model == 'materialinbound':
        if obj.purchase_order_id and obj.purchase_order.production_task_id:
            facts['task_ids'] = {str(obj.purchase_order.production_task_id)}
    elif model == 'internalsemifinishedreceipt':
        facts['task_ids'] = {str(obj.schedule_product.schedule.production_task_id)}
        facts['workshop_ids'] = {str(obj.completed_craft.workshop_id)} if obj.completed_craft.workshop_id else set()
        facts['submitter_id'] = str(getattr(obj, 'submitted_by_employee_id', None) or obj.actor_employee_id)
    elif model == 'finishedgoodsreceipt':
        facts['task_ids'] = {str(obj.production_task_product.production_task_id)}
        facts['submitter_id'] = str(getattr(obj, 'submitted_by_employee_id', None) or obj.received_by_employee_id)
        facts['workshop_ids'] = set(str(pk) for pk in apps.get_model('workshop_config', 'Workshop').objects.filter(name='装配车间').values_list('pk', flat=True))
    elif model == 'finishedgoodsoutbound':
        facts['task_ids'] = set(str(pk) for pk in obj.lines.values_list('receipt__production_task_product__production_task_id', flat=True) if pk)
    elif model == 'outsourcingorder':
        facts['task_ids'] = {str(obj.schedule.production_task_id)}
    elif model == 'metalprocessingexternalorder':
        issue = obj.source.issue_line.issue
        facts['task_ids'] = {str(issue.production_task_id)} if issue.production_task_id else set()
    elif model == 'receipt':
        facts['task_ids'] = {str(obj.statement.production_task_id)}
    elif getattr(obj, 'production_task_id', None):
        facts['task_ids'] = {str(obj.production_task_id)}
    elif getattr(obj, 'product_line_id', None):
        facts['task_ids'] = {str(obj.product_line.production_task_id)}
    if model == 'productionschedule':
        from .notification_access import plan_workshop_ids
        facts['workshop_ids'] = plan_workshop_ids(obj.pk)
    if getattr(obj, 'workshop_id', None):
        facts['workshop_ids'].add(str(obj.workshop_id))
    if model == 'materialissue':
        facts['submitter_id'] = str(obj.submitted_by_employee_id or '')
    if getattr(obj, 'craft_id', None):
        facts['craft_ids'] = {str(obj.craft_id)}
        facts['coating'] = obj.craft.outsourcing_code == 'POWDER_COATING'
    if model == 'outsourcingfactory':
        related = []
        related.extend(apps.get_model('outsourcing', 'OutsourcingFactoryAllocation').objects.filter(factory=obj,
            processing_item__order_product__order__craft__outsourcing_code='POWDER_COATING').values_list('processing_item__order_product__order__craft_id', flat=True))
        related.extend(apps.get_model('outsourcing', 'TubeOutsourcingLine').objects.filter(factory=obj,
            order__craft__outsourcing_code='POWDER_COATING').values_list('order__craft_id', flat=True))
        related.extend(apps.get_model('material_issues', 'MetalProcessingExternalOrder').objects.filter(factory=obj,
            craft__outsourcing_code='POWDER_COATING').values_list('craft_id', flat=True))
        facts['craft_ids'] = {str(pk) for pk in related}
        facts['coating'] = bool(facts['craft_ids'])
    if facts['task_ids'] and apps.get_model('production_tasks', 'ProductionTask').objects.filter(
            pk__in=facts['task_ids'], archived_at__isnull=True).count() != len(facts['task_ids']):
        return None
    if log and log.object_type == 'PRODUCTION_TASK' and log.action in {'UPDATED', 'CREATED', 'CREATED_FROM_SALES_ORDER'}:
        before, after = log.before_data, log.after_data
        facts['changed_fields'] = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        if 'follower_ids' in facts['changed_fields']:
            facts['changed_fields'].remove('follower_ids')
            if set(before.get('follower_ids', [])) != set(after.get('follower_ids', [])):
                facts['changed_fields'].add('followers')
        if 'products' in facts['changed_fields']:
            old = {p['id']: p.get('quantity') for p in before.get('products', [])}
            new = {p['id']: p.get('quantity') for p in after.get('products', [])}
            if old != new:
                facts['changed_fields'].add('quantity')
        facts['new_follower_ids'] = set(after.get('follower_ids', [])) - set(before.get('follower_ids', []))
        if log.action != 'UPDATED':
            facts['changed_fields'] = {'followers'} if facts['new_follower_ids'] else set()
    return facts


def target_for_roles(event_code, object_id, roles, facts):
    from .notification_catalog import target_for
    if facts['deleted'] or event_code == 'OUTSOURCING_FACTORY_DISABLED':
        return None
    obj = facts['subject']
    model = obj._meta.model_name
    name, params = None, {}
    if event_code == 'PRODUCTION_TASK_BOMS_CONFIRMED':
        if 'PURCHASING' in roles:
            name = 'purchase-order-create'
        elif 'ADMINISTRATION' in roles:
            name, params = 'production-task-detail', {'taskId': str(obj.pk)}
        else:
            name = 'boms'
    if roles == ['MERCHANDISER'] and model in {'materialissue', 'internalsemifinishedreceipt', 'finishedgoodsreceipt', 'finishedgoodsoutbound'}:
        if len(facts['task_ids']) == 1:
            name, params = 'production-task-detail', {'taskId': next(iter(facts['task_ids']))}
        else:
            return None
    if name is None and model == 'productiontask':
        name, params = 'production-task-detail', {'taskId': str(obj.pk)}
    elif name is None and model == 'bom':
        name, params = 'bom-preview', {'bomId': str(obj.pk)}
    elif name is None and model == 'productionschedule':
        name, params = 'workshop-scheduling-detail', {'scheduleId': str(obj.pk)}
    elif name is None and model == 'materialissue':
        name, params = 'material-issue-detail', {'issueId': str(obj.pk)}
    elif name is None and model in {'outsourcingorder', 'tubeoutsourcingorder', 'metalprocessingexternalorder'}:
        prefix = 'warehouse' if set(roles) & {'WAREHOUSE_KEEPER', 'COATING_MATERIALS'} else 'workshop'
        suffix, parameter = {'outsourcingorder': ('detail', 'orderId'), 'tubeoutsourcingorder': ('tube-detail', 'id'),
                             'metalprocessingexternalorder': ('rework-detail', 'orderId')}[model]
        name, params = f'{prefix}-outsourcing-{suffix}', {parameter: str(obj.pk)}
    elif name is None and model in {'receivablestatement', 'receipt'}:
        name = 'finance-statements' if model == 'receivablestatement' else 'finance-receipts'
    elif name is None and model == 'productiontaskexpense':
        name, params = 'production-task-detail', {'taskId': str(obj.production_task_id)}
    elif name is None and model == 'materialinbound' and 'QUALITY' not in roles:
        if obj.purchase_order_id:
            name, params = 'purchase-order-detail', {'id': str(obj.purchase_order_id)}
        else:
            return None
    elif name is None and model == 'workreport' and roles == ['MERCHANDISER']:
        name, params = 'production-task-detail', {'taskId': str(obj.product_line.production_task_id)}
    if name:
        return {'target_key': 'role-policy', 'object_id': str(obj.pk), 'route_name': name, 'params': params}
    return target_for(event_code, object_id)
