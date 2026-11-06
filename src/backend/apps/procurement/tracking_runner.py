"""事务后与常驻扫描共用入口；所有覆盖认领在同一数据库事务锁内完成。"""
from collections import Counter
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.wecom.models import NotificationDelivery, WeComBinding, WeComConfig
from apps.wecom.notification_services import _lock_key
from .tracking_models import PurchaseTrackingDigest, PurchaseTrackingIssue, PurchaseTrackingNotice
from .tracking_notifications import (
    BEIJING, TRACKING_EVENTS, candidate_employees, create_event, fingerprint, issue_item,
    issue_transition, recipient_roles, refresh_pending_delivery, rule_enabled, semantic_snapshot,
    skip_pending, tracking_wecom_enabled,
)


def collect_candidates(*, task_ids=None, now=None):
    from .tracking_rules import issue_candidates
    from .tracking_selectors import arrival_rows, coverage_rows
    now = now or timezone.now()
    today = now.astimezone(BEIJING).date()
    return (issue_candidates(arrival_rows(task_ids=task_ids, today=today), 'arrival')
            + issue_candidates(coverage_rows(task_ids=task_ids, today=today, now=now), 'coverage'))


def preview_candidates(candidates, now):
    """启用前核对潜在合法收件范围；只返回内部员工标识，不含姓名、微信号或凭据。"""
    from apps.wecom.selectors import configuration_complete
    config = WeComConfig.objects.first()
    wecom_enabled = tracking_wecom_enabled()
    config_ready = bool(wecom_enabled and config and config.enabled and configuration_complete(config))
    recipients = []
    roles_cache = {}
    for employee in candidate_employees(now):
        roles_by_task = {task_id: recipient_roles(employee, task_id, now, cache=roles_cache)
                        for task_id in {item['production_task_id'] for item in candidates}}
        visible = [item for item in candidates if roles_by_task[item['production_task_id']]]
        if not visible:
            continue
        binding = WeComBinding.objects.filter(employee=employee).first()
        recipients.append({'employee_id': str(employee.pk),
            'role_codes': sorted({role for roles in roles_by_task.values() for role in roles}),
            'task_count': len({item['production_task_id'] for item in visible}), 'issue_count': len(visible),
            'channels': {'IN_APP': True, 'WECOM': bool(config_ready and binding and binding.corp_id == config.corp_id)}})
    return {'task_count': len({item['production_task_id'] for item in candidates}),
        'wecom_enabled': wecom_enabled,
        'risk_counts': dict(sorted(Counter(item['code'] for item in candidates).items())),
        'rules_enabled': {code: rule_enabled(code) for code in sorted(TRACKING_EVENTS)},
        'recipients': recipients}


def _sync_issues(candidates, task_ids, now, result):
    queryset = PurchaseTrackingIssue.objects.all()
    if task_ids is not None:
        queryset = queryset.filter(production_task_id__in=task_ids)
    previous = {issue.source_key: issue for issue in queryset.select_for_update()}
    seen = set()
    for candidate in candidates:
        candidate = {**candidate, 'snapshot': semantic_snapshot(candidate['snapshot'])}
        candidate['fingerprint'] = fingerprint({key: candidate[key] for key in ('code', 'rank', 'snapshot')})
        source_key = candidate['source_key']
        if source_key in seen:
            raise ValueError(f'采购风险身份重复：{source_key}')
        seen.add(source_key)
        issue = previous.get(source_key)
        change = issue_transition(issue, candidate)
        if issue is None:
            issue = PurchaseTrackingIssue(source_key=source_key, first_seen_at=now)
            result['created_issues'] += 1
        elif change['revision'] != issue.revision or not issue.active:
            result['updated_issues'] += 1
        for field in ('kind', 'code', 'rank', 'production_task_id', 'row_key', 'snapshot', 'fingerprint'):
            setattr(issue, field, candidate[field])
        for field in ('cycle', 'transition', 'revision'):
            setattr(issue, field, change[field])
        if change['notify']:
            issue.notify_transition = issue.transition
        issue.active, issue.resolved_at, issue.resolution_reason = True, None, ''
        issue.evaluated_at = now
        issue.save()
    for key, issue in previous.items():
        if key not in seen and issue.active:
            issue.active, issue.resolved_at, issue.evaluated_at = False, now, now
            issue.resolution_reason = 'CURRENT_FACTS_NO_ACTIVE_RISK'
            issue.save(update_fields=['active', 'resolved_at', 'evaluated_at', 'resolution_reason', 'updated_at'])
            result['resolved_issues'] += 1
    return list(PurchaseTrackingIssue.objects.filter(source_key__in=seen, active=True).order_by('source_key'))


def _notice(issue, employee, channel):
    return PurchaseTrackingNotice.objects.filter(issue=issue, cycle=issue.cycle,
        transition=issue.transition, employee=employee, channel=channel, digest__isnull=True).first()


def _record_notice(issue, employee, delivery, digest=None):
    return PurchaseTrackingNotice.objects.get_or_create(issue=issue, cycle=issue.cycle,
        transition=issue.transition, employee=employee, channel=delivery.channel, digest=digest,
        defaults={'delivery': delivery})[0]


def _produce_digest(employee, issues, now, result, roles_cache):
    today = now.astimezone(BEIJING).date()
    digest, created = PurchaseTrackingDigest.objects.get_or_create(employee=employee, business_date=today,
        defaults={'evaluated_at': now, 'item_count': len(issues)})
    if not created:
        return
    result['digests_created'] += 1
    event = create_event(digest, employee, [issue_item(issue) for issue in issues], now=now, digest=True, roles_cache=roles_cache)
    if event is None:  # 空摘要也保存日期评估事实，后续新风险走即时入口。
        return
    digest.event = event
    digest.save(update_fields=['event', 'updated_at'])
    for delivery in NotificationDelivery.objects.filter(recipient__event=event):
        for issue in issues:
            _record_notice(issue, employee, delivery, digest)
            instant = _notice(issue, employee, delivery.channel)
            if instant is None:
                _record_notice(issue, employee, delivery)
            elif instant.delivery.status == 'PENDING' and instant.delivery.attempt_count == 0:
                # 同一天09点时，尚未尝试的即时渠道并入这次摘要；已发送的站内历史保留。
                skip_pending(instant.delivery, 'TRACKING_COVERED_BY_DIGEST', now)
                instant.delivery = delivery
                instant.save(update_fields=['delivery', 'updated_at'])


def _produce_immediate(employee, issues, now, roles_cache):
    for issue in issues:
        notices = {channel: _notice(issue, employee, channel) for channel in ('IN_APP', 'WECOM')}
        for notice in notices.values():
            if notice is None:
                continue
            delivery = notice.delivery
            if (delivery.status == 'SKIPPED' and delivery.attempt_count == 0
                    and delivery.error_code == 'TRACKING_RECIPIENT_INELIGIBLE'
                    and delivery.recipient.event.event_code == 'PURCHASE_TRACKING_RISK'):
                delivery.status, delivery.error_code, delivery.finished_at = 'PENDING', '', None
                delivery.save(update_fields=['status', 'error_code', 'finished_at', 'updated_at'])
                refresh_pending_delivery(delivery, now=now, roles_cache=roles_cache)
        # 降级不向旧收件人追加即时消息；新加入的合法接收人仍可收到当前未解决问题。
        if (issue.notify_transition != issue.transition and PurchaseTrackingNotice.objects.filter(
                issue=issue, cycle=issue.cycle, employee=employee, digest__isnull=True).exists()):
            continue
        missing = [channel for channel, notice in notices.items() if notice is None]
        if not missing:
            continue
        event = create_event(issue, employee, [issue_item(issue)], now=now, channels=missing, roles_cache=roles_cache)
        if event:
            for delivery in NotificationDelivery.objects.filter(recipient__event=event, channel__in=missing):
                _record_notice(issue, employee, delivery)


def recompute_tracking(*, task_ids=None, now=None, dry_run=False):
    now = now or timezone.now()
    if timezone.is_naive(now):
        raise ValueError('采购扫描时钟必须包含时区。')
    enabled = bool(getattr(settings, 'PURCHASE_TRACKING_ENABLED', False))
    result = dict(enabled=enabled, dry_run=dry_run, candidate_count=0, active_issue_count=0,
        created_issues=0, updated_issues=0, resolved_issues=0, digests_created=0, deliveries_created=0)
    if not enabled and not dry_run:
        return result
    # 日摘要必须基于全量，局部提交回调不能提前消耗员工当天的评估机会。
    after_nine = now.astimezone(BEIJING).hour >= 9
    effective_task_ids = None if after_nine else task_ids
    if dry_run:
        candidates = collect_candidates(task_ids=effective_task_ids, now=now)
        result['candidate_count'] = len(candidates)
        result['active_issue_count'] = result['candidate_count']
        result.update(preview_candidates(candidates, now))
        return result
    with transaction.atomic():
        _lock_key('purchase-tracking:recompute')
        candidates = collect_candidates(task_ids=effective_task_ids, now=now)
        result['candidate_count'] = len(candidates)
        before_deliveries = NotificationDelivery.objects.filter(recipient__event__event_code__in=TRACKING_EVENTS).count()
        issues = _sync_issues(candidates, effective_task_ids, now, result)
        roles_cache = {}
        pending = NotificationDelivery.objects.filter(recipient__event__event_code__in=TRACKING_EVENTS,
            status='PENDING', attempt_count=0).select_related('recipient__event', 'recipient__employee')
        if effective_task_ids is not None:
            pending = pending.filter(tracking_notices__issue__production_task_id__in=effective_task_ids).distinct()
        for delivery in pending:
            refresh_pending_delivery(delivery, now=now, candidates={item['source_key']: item for item in candidates}, roles_cache=roles_cache)
        for employee in candidate_employees(now):
            if after_nine and rule_enabled('PURCHASE_TRACKING_DIGEST'):
                visible = [issue for issue in issues if recipient_roles(employee, issue.production_task_id, now,
                    event_code='PURCHASE_TRACKING_DIGEST', cache=roles_cache)]
                _produce_digest(employee, visible, now, result, roles_cache)
            if rule_enabled('PURCHASE_TRACKING_RISK'):
                visible = [issue for issue in issues if recipient_roles(employee, issue.production_task_id, now,
                    event_code='PURCHASE_TRACKING_RISK', cache=roles_cache)]
                _produce_immediate(employee, visible, now, roles_cache)
        result['active_issue_count'] = PurchaseTrackingIssue.objects.filter(active=True).count()
        result['deliveries_created'] = NotificationDelivery.objects.filter(
            recipient__event__event_code__in=TRACKING_EVENTS).count() - before_deliveries
    return result
