"""只将明确成功的审计动作转换为通知；不发送消息，不读取任意审计记录。"""
from .notification_role_policy import enabled


AUDIT_EVENTS = {
    ('PRODUCTION_TASK', 'CREATED'): 'PRODUCTION_TASK_UPDATED',
    ('PRODUCTION_TASK', 'CREATED_FROM_SALES_ORDER'): 'PRODUCTION_TASK_UPDATED',
    ('PRODUCTION_TASK', 'UPDATED'): 'PRODUCTION_TASK_UPDATED',
    ('PRODUCTION_TASK', 'CANCELLED'): 'PRODUCTION_TASK_STATUS_CHANGED',
    ('PRODUCTION_TASK', 'COMPLETED'): 'PRODUCTION_TASK_STATUS_CHANGED',
    ('PRODUCTION_TASK', 'COMPLETED_EXCEPTION'): 'PRODUCTION_TASK_STATUS_CHANGED',
    ('BOM', 'UPDATE'): 'BOM_UPDATED', ('BOM', 'VERIFY'): 'BOM_CONFIRMED',
    ('PRODUCTION_SCHEDULE', 'UPDATED'): 'PRODUCTION_PLAN_UPDATED',
    ('PRODUCTION_SCHEDULE', 'VOIDED'): 'PRODUCTION_PLAN_VOIDED',
    ('OUTSOURCING_ORDER', 'CANCELLED'): 'OUTSOURCING_ORDER_CANCELLED',
    ('OUTSOURCING_ORDER', 'DISPATCH_CONFIRMED'): 'OUTSOURCING_DISPATCH_CONFIRMED',
    ('OUTSOURCING_ORDER', 'DIRECT_HANDOFF_CONFIRMED'): 'OUTSOURCING_DISPATCH_CONFIRMED',
    ('OUTSOURCING_ORDER', 'RETURN_CONFIRMED'): 'OUTSOURCING_RETURN_CONFIRMED',
    ('OUTSOURCING_ORDER', 'DIRECT_GOOD_RETURN_CONFIRMED'): 'OUTSOURCING_RETURN_CONFIRMED',
    ('OUTSOURCING_ORDER', 'DIRECT_UNSPRAYED_RETURN_CONFIRMED'): 'COATING_UNSPRAYED_RETURNED',
    ('OUTSOURCING_ORDER', 'RECONCILIATION_CONFIRMED'): 'OUTSOURCING_RECONCILED',
    ('OUTSOURCING_ORDER', 'COMPLETED'): 'OUTSOURCING_RECONCILED',
    ('TUBE_OUTSOURCING_ORDER', 'CANCELLED'): 'OUTSOURCING_ORDER_CANCELLED',
    ('TUBE_OUTSOURCING_ORDER', 'DISPATCH_CONFIRMED'): 'OUTSOURCING_DISPATCH_CONFIRMED',
    ('TUBE_OUTSOURCING_ORDER', 'RETURN_COMPLETED'): 'OUTSOURCING_RETURN_CONFIRMED',
    ('TUBE_OUTSOURCING_ORDER', 'PLAN_RECEIVED'): 'OUTSOURCING_RETURN_CONFIRMED',
    ('OUTSOURCING_FACTORY', 'DISABLED'): 'OUTSOURCING_FACTORY_DISABLED',
    **{('RECEIVABLE_STATEMENT', action): 'FINANCE_STATEMENT_CHANGED' for action in ('CREATE', 'UPDATE', 'VOID', 'DELETE')},
    **{('FINANCE_RECEIPT', action): 'FINANCE_RECEIPT_CHANGED' for action in ('CREATE', 'UPDATE', 'VOID', 'DELETE')},
    **{('PRODUCTION_TASK_EXPENSE', action): 'PRODUCTION_EXPENSE_CHANGED' for action in ('CREATED', 'UPDATED')},
}

ACTION_NAMES = {'CREATE': '新增', 'CREATED': '新增', 'UPDATE': '修改', 'UPDATED': '修改',
                'CREATED_FROM_SALES_ORDER': '新增跟单分配',
                'VOID': '作废', 'VOIDED': '作废', 'DELETE': '已删除（仅保留操作摘要）',
                'CANCELLED': '取消', 'COMPLETED': '完成／结清', 'COMPLETED_EXCEPTION': '异常完成',
                'VERIFY': '确认', 'DISABLED': '停用', 'DISPATCH_CONFIRMED': '实际外发完成',
                'DIRECT_HANDOFF_CONFIRMED': '实际交接完成', 'RETURN_CONFIRMED': '实际回货完成',
                'DIRECT_GOOD_RETURN_CONFIRMED': '合格回货完成', 'RETURN_COMPLETED': '回货结束',
                'PLAN_RECEIVED': '分批回货完成', 'RECONCILIATION_CONFIRMED': '对账完成',
                'DIRECT_UNSPRAYED_RETURN_CONFIRMED': '未喷塑退回暂存'}


def register_audit_notification(log):
    code = AUDIT_EVENTS.get((log.object_type, log.action))
    if not enabled() or not code or not log.actor_employee_id:
        return None
    from .models import NotificationEvent
    key = f'ROLE_POLICY_AUDIT:{log.pk}'
    existing = NotificationEvent.objects.filter(idempotency_key=key).first()
    if existing is not None:
        return existing
    from .notification_objects import audit_subject, document_number
    from .notification_services import register_business_event
    subject = audit_subject(log)
    snapshot = log.after_data or log.before_data or {}
    number = document_number(subject) if subject is not None else str(snapshot.get('number') or log.object_id)
    status = ACTION_NAMES[log.action]
    quantity = quantity_summary(log, subject)
    if quantity:
        status += f'；本次数量：{quantity}'
    # 实际回货与是否结清放在同一条消息，未回差额不误写成损耗。
    if code == 'OUTSOURCING_RETURN_CONFIRMED' and subject is not None:
        status += f"；当前状态：{subject.get_status_display() if hasattr(subject, 'get_status_display') else subject.status}"
        if log.action == 'PLAN_RECEIVED':
            reached = subject.status == 'COMPLETED'
            status += ('；本次新达到入库目标' if reached and snapshot.get('previous_status') != 'COMPLETED'
                       else '；已达到入库目标' if reached else '；尚未达到入库目标')
            status += '（入库达标不代表差异核清或财务结算）'
    if code == 'PRODUCTION_TASK_STATUS_CHANGED' and snapshot.get('status_reason'):
        status += f"；原因：{str(snapshot['status_reason'])[:160]}"
    extra = {'product_name': subject.product_name_snapshot} if code == 'BOM_CONFIRMED' and subject else {}
    version = str(subject.version_number) if code == 'BOM_CONFIRMED' and subject else str(log.pk)
    return register_business_event(event_code=code, idempotency_key=key,
        object_type='audit.AuditLog', object_id=log.pk, object_version=version,
        actor_employee=log.actor_employee,
        context={'audit_id': str(log.pk), 'document_no': number, 'status': status,
                 'operator': log.actor_name_snapshot or log.actor_employee.display_name,
                 'occurred_at': log.occurred_at.isoformat(), **extra})


def quantity_summary(log, subject):
    """不同单位分别汇总；只读明确关联的本次成功凭证。"""
    from decimal import Decimal
    snapshot = log.after_data
    if log.object_type == 'TUBE_OUTSOURCING_ORDER':
        from apps.outsourcing.tube_kinds import output_unit
        value = snapshot.get('quantity', snapshot.get('total_received_quantity'))
        return f'{value} {output_unit(subject.source_kind)}' if value is not None and subject else ''
    if log.object_type != 'OUTSOURCING_ORDER' or subject is None:
        return ''
    if snapshot.get('quantity') is not None:
        return f"{snapshot['quantity']} 支"
    totals = {}
    if log.action == 'DISPATCH_CONFIRMED':
        from apps.outsourcing.models import OutsourcingDispatchLine
        for line in OutsourcingDispatchLine.objects.filter(dispatch__order=subject).select_related('unit'):
            unit = '支' if line.issued_piece_count is not None else line.unit.unit_name
            amount = line.issued_piece_count if line.issued_piece_count is not None else line.issued_quantity
            totals[unit] = totals.get(unit, Decimal('0')) + amount
    elif log.action == 'RETURN_CONFIRMED' and snapshot.get('notification_return_id'):
        from apps.outsourcing.models import OutsourcingReturnLine
        for line in OutsourcingReturnLine.objects.filter(return_record_id=snapshot['notification_return_id'], return_record__order=subject):
            unit = line.snapshot.get('unit', '')
            quality = '合格' if line.quality == 'AVAILABLE' else '不良隔离'
            key = f'{unit}（{quality}）'
            totals[key] = totals.get(key, Decimal('0')) + line.returned_quantity
    return '；'.join(f'{amount} {unit}' for unit, amount in sorted(totals.items()))
