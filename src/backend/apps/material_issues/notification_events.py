"""实际发料及喷塑重加工成功节点；只保存同事务通知。"""
from apps.wecom.notification_role_policy import enabled


def issue_issued(issue, actor_employee):
    if not enabled():
        return None
    from apps.wecom.notification_services import register_business_event
    return register_business_event(event_code='MATERIAL_ISSUE_ISSUED',
        idempotency_key=f'MATERIAL_ISSUE_ISSUED:{issue.pk}:{issue.version}', object_type=issue._meta.label,
        object_id=issue.pk, object_version=issue.version, actor_employee=actor_employee,
        context={'document_no': issue.issue_number, 'status': '实际发料完成',
                 'operator': actor_employee.display_name, 'occurred_at': issue.issued_at.isoformat()})


def coating_event(event_code, obj, actor_employee):
    """obj依次为ExternalOrder、ExternalHandoff、ExternalGoodReturn真实成功对象。"""
    if event_code not in {'COATING_REWORK_READY', 'COATING_REWORK_DISPATCHED', 'COATING_REWORK_RECEIVED'}:
        raise ValueError('未登记的喷塑重加工通知节点。')
    if not enabled():
        return None
    from apps.wecom.notification_services import register_business_event
    from apps.wecom.notification_plan_catalog import PLAN_EVENTS
    order = obj if event_code == 'COATING_REWORK_READY' else obj.order
    quantity = order.allocated_pieces if event_code == 'COATING_REWORK_READY' else (
        obj.handoff_pieces if event_code == 'COATING_REWORK_DISPATCHED' else obj.good_pieces)
    status = f'{PLAN_EVENTS[event_code][0]}；本次数量：{quantity} 支'
    if event_code == 'COATING_REWORK_RECEIVED':
        status += f'；当前状态：{order.get_status_display()}'
    return register_business_event(event_code=event_code, idempotency_key=f'{event_code}:{obj.pk}',
        object_type=obj._meta.label, object_id=obj.pk, object_version=str(obj.pk), actor_employee=actor_employee,
        context={'document_no': order.order_number, 'status': status,
                 'operator': actor_employee.display_name, 'occurred_at': obj.created_at.isoformat()})
