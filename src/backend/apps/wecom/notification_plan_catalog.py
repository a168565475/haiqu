"""已确认方案新增事件；只登记事件契约，不改变现存规则。"""

PLAN_EVENTS = {
    'PRODUCTION_TASK_UPDATED': ('生产任务资料变更', 'production_tasks.view_productiontask'),
    'PRODUCTION_TASK_STATUS_CHANGED': ('生产任务状态变更', 'production_tasks.view_productiontask'),
    'BOM_UPDATED': ('BOM资料变更', 'boms.view_bom'),
    'PRODUCTION_PLAN_UPDATED': ('作业计划变更', 'production_scheduling.view_productionschedule'),
    'PRODUCTION_PLAN_VOIDED': ('作业计划作废', 'production_scheduling.view_productionschedule'),
    'MATERIAL_ISSUE_ISSUED': ('生产领料实际发料完成', 'material_issues.view_materialissue'),
    'OUTSOURCING_ORDER_CANCELLED': ('委外单取消', 'outsourcing.view_outsourcingorder'),
    'OUTSOURCING_DISPATCH_CONFIRMED': ('委外实际外发完成', 'outsourcing.view_outsourcingorder'),
    'OUTSOURCING_RETURN_CONFIRMED': ('委外实际回货完成', 'outsourcing.view_outsourcingorder'),
    'OUTSOURCING_RECONCILED': ('委外对账或结清完成', 'outsourcing.view_outsourcingorder'),
    'OUTSOURCING_FACTORY_DISABLED': ('外协工厂停用', 'outsourcing.view_outsourcingfactory'),
    'COATING_UNSPRAYED_RETURNED': ('未喷塑件退回暂存', 'material_issues.register_metalprocessingunsprayedreturn'),
    'COATING_REWORK_READY': ('重加工喷塑单待交接', 'material_issues.confirm_metalprocessingexternalhandoff'),
    'COATING_REWORK_DISPATCHED': ('重加工喷塑交接完成', 'material_issues.confirm_metalprocessingexternalhandoff'),
    'COATING_REWORK_RECEIVED': ('重加工喷塑合格回货完成', 'material_issues.confirm_metalprocessingexternalreturn'),
    'FINANCE_STATEMENT_CHANGED': ('应收对账单变更', 'finance.view_receivablestatement'),
    'FINANCE_RECEIPT_CHANGED': ('收款记录变更', 'finance.view_receipt'),
    'PRODUCTION_EXPENSE_CHANGED': ('生产任务费用变更', 'production_tasks.view_productiontaskcost'),
}

PLAN_BODY = '单据编号：{{document_no}}\n业务结果：{{status}}\n操作人：{{operator}}\n操作时间：{{occurred_at}}'


def definitions():
    from .notification_role_policy import ROLE_POLICIES
    return {code: {
        'event_code': code, 'display_name': title, 'default_title': title,
        'default_body': PLAN_BODY, 'legacy_default_body': PLAN_BODY,
        'allowed_variables': ['document_no', 'status', 'operator', 'occurred_at', 'object_version'],
        'required_variables': ['document_no', 'status', 'operator', 'occurred_at'],
        'default_role_codes': sorted(ROLE_POLICIES[code]), 'supported_scopes': ['ROLE_POLICY'],
        'required_permission': permission, 'target_key': 'role-policy', 'enabled_by_default': False,
    } for code, (title, permission) in PLAN_EVENTS.items()}
