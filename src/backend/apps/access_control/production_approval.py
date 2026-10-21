from .module_policy import prohibit_audit_self_approval


def check_production_approval(actor, task):
    from .selectors import current_assignments
    # 仅有效行政角色且持有任务确认动作时允许此流程自确认。
    if actor is not None and actor.status == 'ACTIVE' and actor.archived_at is None and current_assignments(actor).filter(
        role_profile__role_code='ADMINISTRATION',
        role_profile__action_grants__permission__content_type__app_label='production_tasks',
        role_profile__action_grants__permission__codename='confirm_productiontask',
        role_profile__action_grants__scope='MODULE',
    ).exists():
        return
    prohibit_audit_self_approval(actor, 'PRODUCTION_TASK', task.pk, ['SUBMITTED'])
