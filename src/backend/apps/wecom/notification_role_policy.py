"""2026-11-02确认的逐岗位收件规则。授权与收件资格分开，兼岗取合法来源并集。"""
from django.conf import settings
from apps.access_control.superuser_services import SUPERUSER_ROLE_CODES


POLICY_SCOPE = 'ROLE_POLICY'
POLICY_VERSION = '20261102'
DIRECTORS = ('METAL_DIRECTOR', 'SEWING_DIRECTOR', 'ASSEMBLY_DIRECTOR')
SAMPLERS = ('METAL_SAMPLING', 'FABRIC_SAMPLING')
SILENT_ROLES = SUPERUSER_ROLE_CODES | frozenset({
    'SALESPERSON', 'ACCOUNT_MANAGER',
    'ROLE_A0D541A3E36E414890125AB40D10DCF4', 'ROLE_2993D2B2A09045BC9CE667142051C15C',
    'ROLE_92229791A0E04A9C8067ED7D2AC2ED77', 'ROLE_5EE76DEC357247968ECC1B252B68DD1C',
})


def enabled():
    return bool(getattr(settings, 'CONFIRMED_ROLE_POLICY_ENABLED', False))


def _rule(permission, scope='MODULE', *, exclude_actor=False, fields=(), actor_role=None):
    return {'permissions': (permission,) if isinstance(permission, str) else tuple(permission),
            'scope': scope, 'exclude_actor': exclude_actor, 'fields': frozenset(fields), 'actor_role': actor_role}


def _follow(permission):
    return _rule(permission, 'FOLLOWED', exclude_actor=True)


def _coating(permission='outsourcing.view_outsourcingorder'):
    return _rule(permission, 'COATING', exclude_actor=True)


def _directors(permission, scope='WORKSHOP'):
    return {role: _rule(permission, scope) for role in DIRECTORS}


TASK_FIELDS = ('delivery_date', 'quantity', 'planned_start_date', 'planned_end_date',
               'production_priority', 'followers')
READ_TASK = 'production_tasks.view_productiontask'
READ_PLAN = 'production_scheduling.view_productionschedule'
READ_PURCHASE = 'procurement.view_purchaseorder'
READ_OUTSIDE = 'outsourcing.view_outsourcingorder'
SAMPLE_EXECUTE = ('access_control.metalwork_sample', 'access_control.cutting_sample',
                  'access_control.metalreport_sample', 'access_control.cuttingreport_sample')

ROLE_POLICIES = {
    'PRODUCTION_TASK_CONFIRMED': {
        'TECHNICAL': _rule(READ_TASK), 'ADMINISTRATION': _rule(READ_TASK, exclude_actor=True),
        'FACTORY_MANAGER': _rule(READ_TASK, actor_role='ADMINISTRATION'),
        'FINANCE': _rule(READ_TASK, exclude_actor=True), 'CASHIER': _rule(READ_TASK, exclude_actor=True),
        'PMC': _rule(READ_TASK, exclude_actor=True), 'MERCHANDISER': _follow(READ_TASK),
    },
    'PRODUCTION_TASK_UPDATED': {
        'TECHNICAL': _rule(READ_TASK, exclude_actor=True, fields=('products', 'quantity', 'delivery_date')),
        'ADMINISTRATION': _rule(READ_TASK, fields=('quantity', 'delivery_date')),
        'PMC': _rule(READ_TASK, exclude_actor=True, fields=TASK_FIELDS),
        'MERCHANDISER': _rule(READ_TASK, 'FOLLOWED', exclude_actor=True, fields=TASK_FIELDS),
    },
    'PRODUCTION_TASK_STATUS_CHANGED': {
        'TECHNICAL': _rule(READ_TASK), 'PMC': _rule(READ_TASK, exclude_actor=True),
        'MERCHANDISER': _follow(READ_TASK),
    },
    'BOM_CONFIRMED': {'TECHNICAL': _rule('boms.view_bom', exclude_actor=True)},
    'BOM_UPDATED': {'TECHNICAL': _rule('boms.view_bom', exclude_actor=True)},
    'PRODUCTION_TASK_BOMS_CONFIRMED': {
        'PURCHASING': _rule('procurement.add_purchaseorder'), 'ADMINISTRATION': _rule(READ_TASK),
        'PMC': _rule('boms.view_bom', exclude_actor=True), 'MERCHANDISER': _follow('boms.view_bom'),
    },
    'MATERIAL_RECEIPT_RECORDED': {
        'QUALITY': _rule('inventory.quality_confirm_material'), 'PURCHASING': _rule(READ_PURCHASE),
        'PMC': _rule(READ_PURCHASE, exclude_actor=True), 'MERCHANDISER': _follow(READ_PURCHASE),
    },
    'MATERIAL_INSPECTION_CONFIRMED': {
        'PURCHASING': _rule(READ_PURCHASE), 'PMC': _rule(READ_PURCHASE, exclude_actor=True),
        'MERCHANDISER': _follow(READ_PURCHASE),
    },
    'PURCHASE_ORDER_COMPLETED': {
        'FACTORY_MANAGER': _rule(READ_PURCHASE), 'ADMINISTRATION': _rule(READ_PURCHASE),
        'PMC': _rule(READ_PURCHASE, exclude_actor=True), 'MERCHANDISER': _follow(READ_PURCHASE),
    },
    'PRODUCTION_PLAN_CREATED': {
        **_directors(READ_PLAN), 'PMC': _rule(READ_PLAN, exclude_actor=True),
        'MERCHANDISER': _follow(READ_PLAN),
    },
    'PRODUCTION_PLAN_UPDATED': {
        **_directors(READ_PLAN), 'ADMINISTRATION': _rule(READ_PLAN, exclude_actor=True),
        'PMC': _rule(READ_PLAN, exclude_actor=True), 'MERCHANDISER': _follow(READ_PLAN),
    },
    'PRODUCTION_PLAN_VOIDED': {
        **_directors(READ_PLAN), 'ADMINISTRATION': _rule(READ_PLAN, exclude_actor=True),
        'PMC': _rule(READ_PLAN, exclude_actor=True), 'MERCHANDISER': _follow(READ_PLAN),
    },
    'MATERIAL_ISSUE_SUBMITTED': {'WAREHOUSE_KEEPER': _rule('material_issues.review_materialissue')},
    'MATERIAL_ISSUE_ISSUED': {
        **_directors('material_issues.view_materialissue', 'SUBMITTER'),
        'MERCHANDISER': _follow('material_issues.view_materialissue'),
    },
    'SEMI_FINISHED_RECEIPT_SUBMITTED': {'WAREHOUSE_KEEPER': _rule('inventory.view_internalsemifinishedreceipt')},
    'ASSEMBLY_FINISHED_RECEIPT_SUBMITTED': {'WAREHOUSE_KEEPER': _rule('inventory.view_finishedgoodsreceipt')},
    'INTERNAL_SEMI_RECEIPT_CONFIRMED': {
        'FACTORY_MANAGER': _rule('inventory.view_internalsemifinishedreceipt'),
        **{role: _rule('inventory.view_internalsemifinishedreceipt', 'SUBMITTER') for role in DIRECTORS[:2]},
        'MERCHANDISER': _follow('inventory.view_internalsemifinishedreceipt'),
    },
    'ASSEMBLY_FINISHED_RECEIPT_CONFIRMED': {
        'FACTORY_MANAGER': _rule('inventory.view_finishedgoodsreceipt'),
        'ASSEMBLY_DIRECTOR': _rule('inventory.view_finishedgoodsreceipt', 'SUBMITTER'),
        'MERCHANDISER': _follow('inventory.view_finishedgoodsreceipt'),
    },
    'FINISHED_GOODS_OUTBOUND_CONFIRMED': {
        'FACTORY_MANAGER': _rule('inventory.view_finishedgoodsoutbound'),
        'MERCHANDISER': _follow('inventory.view_finishedgoodsoutbound'),
    },
    'WAGE_SCHEME_SUBMITTED': {'FACTORY_MANAGER': _rule('workshop_reporting.approve_wagescheme')},
    'WAGE_SCHEME_DECIDED': _directors('workshop_reporting.view_wagescheme'),
    'WORK_REPORT_SAVED': {'FACTORY_MANAGER': _rule('workshop_reporting.view_workreport')},
    'WORK_REPORT_CORRECTED': {
        'FACTORY_MANAGER': _rule('workshop_reporting.view_workreport'),
        'MERCHANDISER': _follow('workshop_reporting.view_workreport'),
    },
    'WORK_REPORT_DELETED': {
        'FACTORY_MANAGER': _rule('workshop_reporting.view_workreport'),
        'MERCHANDISER': _follow('workshop_reporting.view_workreport'),
    },
    'OUTSOURCING_ORDER_CREATED': {
        'WAREHOUSE_KEEPER': _rule('outsourcing.confirm_dispatch_outsourcingorder'),
        'OUTSOURCING': _rule(READ_OUTSIDE, exclude_actor=True), 'COATING_MATERIALS': _coating(),
    },
    'TUBE_OUTSOURCING_ORDER_CREATED': {
        'WAREHOUSE_KEEPER': _rule('outsourcing.confirm_dispatch_outsourcingorder'),
        'OUTSOURCING': _rule(READ_OUTSIDE, exclude_actor=True), 'COATING_MATERIALS': _coating(),
    },
    'OUTSOURCING_ORDER_CANCELLED': {
        'OUTSOURCING': _rule(READ_OUTSIDE, exclude_actor=True), 'COATING_MATERIALS': _coating(),
    },
    'OUTSOURCING_DISPATCH_CONFIRMED': {
        'OUTSOURCING': _rule(READ_OUTSIDE, exclude_actor=True), 'MERCHANDISER': _follow(READ_OUTSIDE),
        'COATING_MATERIALS': _coating(),
    },
    'OUTSOURCING_RETURN_CONFIRMED': {
        'FACTORY_MANAGER': _rule(READ_OUTSIDE), 'OUTSOURCING': _rule(READ_OUTSIDE, exclude_actor=True),
        'MERCHANDISER': _follow(READ_OUTSIDE), 'COATING_MATERIALS': _coating(),
    },
    'OUTSOURCING_LOSS_RECORDED': {
        'FACTORY_MANAGER': _rule(READ_OUTSIDE), 'OUTSOURCING': _rule(READ_OUTSIDE, exclude_actor=True),
        'MERCHANDISER': _follow(READ_OUTSIDE), 'COATING_MATERIALS': _coating(),
    },
    'TUBE_OUTSOURCING_SHORTAGE_RECORDED': {
        'FACTORY_MANAGER': _rule(READ_OUTSIDE), 'OUTSOURCING': _rule(READ_OUTSIDE, exclude_actor=True),
        'MERCHANDISER': _follow(READ_OUTSIDE), 'COATING_MATERIALS': _coating(),
    },
    'OUTSOURCING_RECONCILED': {'OUTSOURCING': _rule(READ_OUTSIDE, exclude_actor=True)},
    'OUTSOURCING_FACTORY_DISABLED': {
        'OUTSOURCING': _rule('outsourcing.view_outsourcingfactory', exclude_actor=True),
        'COATING_MATERIALS': _coating(),
    },
    'COATING_UNSPRAYED_RETURNED': {'COATING_MATERIALS': _coating('material_issues.register_metalprocessingunsprayedreturn')},
    'COATING_REWORK_READY': {'COATING_MATERIALS': _coating('material_issues.confirm_metalprocessingexternalhandoff')},
    'COATING_REWORK_DISPATCHED': {'COATING_MATERIALS': _coating('material_issues.confirm_metalprocessingexternalhandoff')},
    'COATING_REWORK_RECEIVED': {'COATING_MATERIALS': _coating('material_issues.confirm_metalprocessingexternalreturn')},
    'SAMPLE_SUBMITTED': {'FACTORY_MANAGER': _rule('samples.review_sample_application', exclude_actor=True)},
    'SAMPLE_EFFECTIVE': {role: _rule('samples.complete_sample_requirements') for role in SAMPLERS},
    'SAMPLE_REQUIREMENTS_COMPLETED': {role: _rule('samples.edit_sample_materials') for role in SAMPLERS},
    'SAMPLE_MATERIALS_SUBMITTED': {'WAREHOUSE_KEEPER': _rule('samples.review_sample_materials')},
    'SAMPLE_MATERIAL_SHORTAGE': {'PURCHASING': _rule('samples.view_sample_procurement')},
    'SAMPLE_MATERIALS_AVAILABLE': {role: _rule('samples.edit_sample_materials') for role in SAMPLERS},
    'SAMPLE_MATERIAL_ISSUE_SUBMITTED': {'WAREHOUSE_KEEPER': _rule('samples.review_sample_materials')},
    'SAMPLE_MATERIAL_ISSUED': {role: _rule(SAMPLE_EXECUTE) for role in SAMPLERS},
    'SAMPLE_PRODUCTION_READY': {role: _rule(SAMPLE_EXECUTE) for role in SAMPLERS},
    'SAMPLE_COMPLETED': {
        'FACTORY_MANAGER': _rule('samples.view_samplerequest'),
        'WAREHOUSE_KEEPER': _rule('samples.add_sampleinventoryreceipt'),
    },
    'FINANCE_STATEMENT_CHANGED': {role: _rule('finance.view_receivablestatement', exclude_actor=True) for role in ('FINANCE', 'CASHIER')},
    'FINANCE_RECEIPT_CHANGED': {role: _rule('finance.view_receipt', exclude_actor=True) for role in ('FINANCE', 'CASHIER')},
    'PRODUCTION_EXPENSE_CHANGED': {role: _rule('production_tasks.view_productiontaskcost', exclude_actor=True) for role in ('FINANCE', 'CASHIER')},
    'SAMPLE_RETURNED': {}, 'SAMPLE_INVENTORY_RECEIVED': {}, 'SUPPLIER_PURCHASE_SHEET_PUBLISHED': {},
}


def matching_roles(event_code, employee, role_codes, facts):
    """只返回实际命中的接收岗位；一个岗位的本人过滤不影响另一兼任岗位。"""
    from apps.access_control.models import RoleActionGrant
    from apps.access_control.resource_scopes import selected_ids
    from apps.production_tasks.models import ProductionTask
    roles = []
    policies = ROLE_POLICIES.get(event_code, {})
    tasks = ProductionTask.objects.filter(pk__in=facts['task_ids'], archived_at__isnull=True)
    for role_code in role_codes:
        policy = policies.get(role_code)
        if policy is None or role_code in SILENT_ROLES:
            continue
        if policy['exclude_actor'] and str(employee.pk) == facts['actor_id']:
            continue
        if policy['actor_role'] and policy['actor_role'] not in facts['actor_roles']:
            continue
        if event_code == 'PRODUCTION_TASK_STATUS_CHANGED' and role_code == 'TECHNICAL' and facts['action'] != 'CANCELLED':
            continue
        if policy['fields'] and not policy['fields'].intersection(facts['changed_fields']):
            continue
        if facts['action'] in {'CREATED', 'CREATED_FROM_SALES_ORDER'} and event_code == 'PRODUCTION_TASK_UPDATED' and role_code != 'MERCHANDISER':
            continue
        if policy['scope'] == 'FOLLOWED':
            # 一张多任务单的完整摘要不能因为只跟其中一个任务就全部泄露。
            if not facts['task_ids'] or tasks.filter(followers=employee).distinct().count() != len(facts['task_ids']):
                continue
            if event_code == 'PRODUCTION_TASK_UPDATED' and facts['changed_fields'] == {'followers'} and str(employee.pk) not in facts['new_follower_ids']:
                continue
        if policy['scope'] == 'SUBMITTER' and str(employee.pk) != facts['submitter_id']:
            continue
        if policy['scope'] == 'COATING' and not facts['coating']:
            continue
        for permission in policy['permissions']:
            app_label, codename = permission.split('.', 1)
            grants = RoleActionGrant.objects.filter(role__role_code=role_code,
                permission__content_type__app_label=app_label, permission__codename=codename).prefetch_related('resource_selections')
            for grant in grants:
                # 只使用这一岗位的授权来源，超管或另一兼岗不扩大它的收件范围。
                if grant.scope in {'MODULE', 'ALL'}:
                    allowed = True
                elif grant.scope == 'FOLLOWED':
                    allowed = bool(facts['task_ids']) and tasks.filter(followers=employee).distinct().count() == len(facts['task_ids'])
                elif grant.scope == 'WORKSHOP':
                    allowed = bool(facts['workshop_ids'].intersection(str(pk) for pk in selected_ids(grant)))
                elif grant.scope == 'CRAFT':
                    allowed = bool(facts['craft_ids']) and facts['craft_ids'].issubset(str(pk) for pk in selected_ids(grant))
                elif grant.scope == 'STOCK':
                    allowed = role_code == 'WAREHOUSE_KEEPER'
                else:
                    allowed = False
                if allowed:
                    roles.append(role_code)
                    break
            if role_code in roles:
                break
    return sorted(set(roles))
