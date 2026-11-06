"""采购风险通知：按员工/渠道认领，正文版本仅追加，外发前重新核实。"""
import hashlib
import json
from collections import Counter
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.organizations.models import Employee, EmployeeRoleAssignment
from apps.production_tasks.models import ProductionTask
from apps.wecom.models import NotificationDelivery, NotificationEvent, NotificationRecipient, NotificationRule, WeComBinding, WeComConfig
from .tracking_models import PurchaseTrackingContent, PurchaseTrackingDigest, PurchaseTrackingIssue, PurchaseTrackingNotice


TRACKING_EVENTS = frozenset({"PURCHASE_TRACKING_RISK", "PURCHASE_TRACKING_DIGEST"})
TRACKING_ROLES = ("PURCHASING", "PMC", "MERCHANDISER")
BEIJING = ZoneInfo("Asia/Shanghai")


def tracking_wecom_enabled():
    return bool(getattr(settings, "PURCHASE_TRACKING_WECOM_ENABLED", False))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def semantic_snapshot(snapshot):
    return {key: value for key, value in snapshot.items() if key not in {"evaluated_at", "actions", "action_blocked_reason"}}


def issue_transition(previous, candidate):
    if previous is None:
        return {"cycle": 1, "transition": 1, "revision": 1, "notify": True}
    recurring = not previous.active
    changed_rank = previous.rank != candidate["rank"]
    return {"cycle": previous.cycle + int(recurring),
            "transition": previous.transition + int(recurring or changed_rank),
            "revision": previous.revision + int(recurring or previous.fingerprint != candidate["fingerprint"]),
            "notify": recurring or candidate["rank"] > previous.rank}


def candidate_employees(now):
    assignments = EmployeeRoleAssignment.objects.filter(
        role_profile__role_code__in=TRACKING_ROLES[:2], role_profile__archived_at__isnull=True,
        effective_from__lte=now,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now)).values("employee_id")
    return Employee.objects.filter(status="ACTIVE", archived_at__isnull=True, user__is_active=True).filter(
        Q(pk__in=assignments) | Q(followed_production_tasks__isnull=False),
    ).select_related("user").distinct().order_by("pk")


def recipient_roles(employee, task_id, now=None, event_code=None, cache=None):
    from .tracking_permissions import employee_can_view_task
    now = now or timezone.now()
    key = ('purchase-tracking-roles', str(employee.pk), str(task_id), event_code)
    if cache is not None and key in cache:
        return cache[key]
    if not employee_can_view_task(employee, task_id):
        if cache is not None:
            cache[key] = []
        return []
    roles = set(EmployeeRoleAssignment.objects.filter(
        employee=employee, role_profile__role_code__in=TRACKING_ROLES[:2],
        role_profile__archived_at__isnull=True, effective_from__lte=now,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now)).values_list("role_profile__role_code", flat=True))
    if ProductionTask.objects.filter(pk=task_id, followers=employee).exists():
        roles.add("MERCHANDISER")
    if event_code:
        configured = NotificationRule.objects.filter(event_code=event_code).values_list('recipient_role_codes', flat=True).first()
        roles &= set(configured or [])
    result = sorted(roles)
    if cache is not None:
        cache[key] = result
    return result


def issue_item(issue):
    return {"issue_id": str(issue.pk), "source_key": issue.source_key, "kind": issue.kind,
            "cycle": issue.cycle, "transition": issue.transition, "revision": issue.revision,
            "code": issue.code, "rank": issue.rank, "production_task_id": str(issue.production_task_id),
            "row_key": issue.row_key, "snapshot": issue.snapshot}


def content_target(items, *, object_id):
    query = {}
    kinds = {item['kind'] for item in items}
    if len(kinds) == 1:
        query['tab'] = 'coverage' if 'coverage' in kinds else 'arrival'
    if any(item.get('historical_state') or item['snapshot'].get('is_history') for item in items):
        query['include_history'] = 'true'
    if len(items) == 1:
        item = items[0]
        query.update(production_task_id=item['production_task_id'], row_key=item['row_key'])
    return {"target_key": "purchase-tracking", "route_name": "purchase-tracking", 'object_id': str(object_id),
        "params": {}, "query": query}


def render_content(items, *, digest=False, templates=None):
    title = "采购跟踪每日汇总" if digest else "采购跟踪提醒"
    lines = []
    ordered_items = sorted(items, key=lambda item: (-item.get('rank', 0), item['code'],
        item.get('production_task_id', ''), item.get('row_key', '')))
    for item in ordered_items:
        row = item["snapshot"]
        labels = [risk['label'] for risk in row.get('risks', []) if
            (risk['code'] == 'RETURN_PENDING') == (item['code'] == 'RETURN_PENDING')]
        label = '；'.join(labels) or item['code']
        text = f"{row.get('task_number', '任务待核对')} / {row.get('product_name', '产品待核对')} / {row.get('material_name', '材料待核对')}\n{label}"
        if item.get('historical_state'):
            text += f"（{item['historical_state']}，请查看当前状态）"
        unit = row.get("unit") or "单位待核对"
        if item["kind"] == "coverage":
            text += f"；需求 {row.get('required_quantity') or '待核对'}；已确认采购 {row.get('purchased_quantity') or '待核对'}；待采购 {row.get('remaining_quantity') or '待核对'} {unit}"
            if row.get("material_inbound_date"):
                text += f"；计划材料入库 {row['material_inbound_date']}"
            if row.get('latest_purchase_date'):
                text += f"；最晚采购日 {row['latest_purchase_date']}"
            if row.get('bom_purchase_due_at'):
                deadline = timezone.datetime.fromisoformat(row['bom_purchase_due_at']).astimezone(BEIJING)
                text += f"；BOM采购提醒起点 {deadline:%Y-%m-%d %H:%M}"
        else:
            text += f"；采购 {row.get('purchase_order_no', '待核对')}；供应商 {row.get('supplier_name') or '待核对'}"
            if row.get("batch_number") is not None:
                text += f"；第 {row['batch_number']} 批"
            publication = row.get('publication_status')
            if publication:
                text += f"；采购表{publication}" + ('（待发出）' if publication != '已发布' else '')
            if item["code"] == "RETURN_PENDING":
                text += "；退货待处理，不代表供应商需要补交"
            else:
                text += f"；交期 {row.get('delivery_date') or '待核对'}；未到 {row.get('unreceived_quantity') if row.get('unreceived_quantity') is not None else '待核对'} {unit}"
        if row.get("verification_notes"):
            text += "\n待核对：" + "；".join(row["verification_notes"])
        lines.append(text)
    body = f"{len(items)} 项需处理\n\n" + "\n\n".join(lines)
    if digest:
        counts = Counter(item['code'] for item in ordered_items)
        labels = {item['code']: next((risk['label'] for risk in item['snapshot'].get('risks', [])
            if risk['code'] == item['code']), item['code']) for item in ordered_items}
        task_count = len({item['production_task_id'] for item in ordered_items})
        summary = '；'.join(f'{labels[code]} {count}项' for code, count in counts.items())
        body = f'{task_count} 个任务 / {len(items)} 项需处理\n{summary}\n\n' + '\n\n'.join(lines)
    if templates:
        from apps.wecom.notification_services import _render
        context = {'reason_summary': body}
        title = _render(templates['title'], ['reason_summary'], context)
        body = _render(templates['body'], ['reason_summary'], context)
    if len(title.encode()) > 600:
        raise ValueError('采购提醒标题超出发送限制。')
    # 网关限完整卡片2048字节。逐字符分段保留全部正文，不截掉材料；每段有序号。
    chunks, chunk = [], ""
    for character in body:
        if len((chunk + character).encode()) > 1350:
            chunks.append(chunk)
            chunk = ""
        chunk += character
    if chunk:
        chunks.append(chunk)
    parts = [f"（{index + 1}/{len(chunks)}）\n{part}" for index, part in enumerate(chunks)]
    return title, body, parts


def saved_content(delivery):
    return delivery.tracking_contents.order_by("-revision").first()


def append_content(delivery, items, *, digest=False):
    current = saved_content(delivery)
    if current and (delivery.attempt_count or delivery.status != "PENDING"):
        return current
    if current and current.items == items:
        return current
    title, body, parts = render_content(items, digest=digest, templates=delivery.recipient.event.context.get('templates'))
    return PurchaseTrackingContent.objects.create(delivery=delivery, revision=(current.revision + 1 if current else 1),
        items=items, title=title, body=body, parts=parts,
        target=content_target(items, object_id=delivery.recipient.event.object_id))


def rule_enabled(code):
    return NotificationRule.objects.filter(event_code=code, enabled=True).exists()


def create_event(owner, employee, items, *, now, digest=False, channels=('IN_APP', 'WECOM'), roles_cache=None):
    """仅内部可信来源调用；通用业务事件注册入口拒绝这些系统代码。"""
    code = "PURCHASE_TRACKING_DIGEST" if digest else "PURCHASE_TRACKING_RISK"
    rule = NotificationRule.objects.filter(event_code=code, enabled=True).first()
    if rule is None or not items:
        return None
    model = PurchaseTrackingDigest if digest else PurchaseTrackingIssue
    if not isinstance(owner, model) or not model.objects.filter(pk=owner.pk).exists():
        raise ValueError("采购系统事件必须引用已持久化的可信跟踪对象。")
    version = str(owner.business_date) if digest else f"{owner.cycle}:{owner.transition}"
    key = f"purchase-tracking:{'digest' if digest else 'risk'}:{owner.pk}:{employee.pk}:{version}"
    existing = NotificationEvent.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    templates = {'title': rule.title_template, 'body': rule.body_template}
    title, body, _ = render_content(items, digest=digest, templates=templates)
    event = NotificationEvent.objects.create(event_code=code, idempotency_key=key,
        object_type=owner._meta.label, object_id=str(owner.pk), object_version=version,
        context={"source": "PURCHASE_TRACKING_SCANNER", "owner_id": str(owner.pk), 'templates': templates},
        rule_version=rule.version, template_name=rule.name, rendered_title=title, rendered_body=body,
        target=content_target(items, object_id=owner.pk), status="CREATED")
    config = WeComConfig.objects.first()
    roles = sorted({role for item in items for role in recipient_roles(employee, item["production_task_id"],
        now, event_code=code, cache=roles_cache)})
    recipient = NotificationRecipient.objects.create(event=event, employee=employee, employee_name=employee.display_name,
        role_codes=roles, scope="ROLE_POLICY", eligibility_snapshot={"tracking": True,
            "corp_id": config.corp_id if config else "", "agent_id": config.agent_id if config else ""})
    binding = WeComBinding.objects.filter(employee=employee).first()
    for channel in channels:
        wecom_disabled = channel == "WECOM" and not tracking_wecom_enabled()
        delivery = NotificationDelivery.objects.create(recipient=recipient, channel=channel,
            idempotency_key=f"{event.pk}:{employee.pk}:{channel}", status="SKIPPED" if wecom_disabled else "PENDING",
            error_code="TRACKING_WECOM_DISABLED" if wecom_disabled else "", finished_at=now if wecom_disabled else None,
            user_id_snapshot=binding.user_id if binding and channel == "WECOM" else "")
        append_content(delivery, items, digest=digest)
        if channel == "IN_APP":
            delivery.status, delivery.finished_at = "ACCEPTED", now
            delivery.save(update_fields=["status", "finished_at", "updated_at"])
    return event


def skip_pending(delivery, reason, now):
    if delivery.status == "PENDING" and delivery.attempt_count == 0:
        delivery.status, delivery.error_code, delivery.finished_at = "SKIPPED", reason, now
        delivery.save(update_fields=["status", "error_code", "finished_at", "updated_at"])


def current_content_items(delivery, *, now, live=True, candidates=None, roles_cache=None):
    """逐条复核；站内历史仅做权限过滤，外发还需当前业务事实与生命周期一致。"""
    from .tracking_runner import collect_candidates
    content = saved_content(delivery)
    roles_cache = {} if roles_cache is None else roles_cache
    if content is None:
        return []
    if live and delivery.recipient.event.event_code == 'PURCHASE_TRACKING_DIGEST':
        if not PurchaseTrackingDigest.objects.filter(event_id=delivery.recipient.event_id,
                business_date=now.astimezone(BEIJING).date()).exists():
            return []
    employee = Employee.objects.select_related("user").filter(pk=delivery.recipient.employee_id,
        status="ACTIVE", archived_at__isnull=True, user__is_active=True).first()
    if employee is None:
        return []
    if live and candidates is None:
        task_ids = {item["production_task_id"] for item in content.items}
        candidates = {item["source_key"]: item for item in collect_candidates(task_ids=task_ids, now=now)}
    issues = {str(issue.pk): issue for issue in PurchaseTrackingIssue.objects.filter(pk__in=[item["issue_id"] for item in content.items])}
    permitted = {}
    result = []
    for item in content.items:
        task_id = item["production_task_id"]
        if task_id not in permitted:
            permitted[task_id] = bool(recipient_roles(employee, task_id, now,
                event_code=delivery.recipient.event.event_code, cache=roles_cache))
        if not permitted[task_id]:
            continue
        issue = issues.get(item["issue_id"])
        if live:
            candidate = candidates.get(item["source_key"])
            if (not issue or not issue.active or not candidate or issue.cycle != item["cycle"]
                    or issue.transition != item["transition"] or candidate["rank"] != item["rank"]):
                continue
            result.append({**item, 'revision': issue.revision,
                "snapshot": semantic_snapshot(candidate["snapshot"]), "code": candidate["code"]})
        else:
            history_state = ('已解除' if not issue or not issue.active else '状态已更新'
                if issue.cycle != item['cycle'] or issue.transition != item['transition'] else '')
            result.append({**item, 'historical_state': history_state})
    return result


def refresh_pending_delivery(delivery, *, now, candidates=None, roles_cache=None):
    if delivery.status != "PENDING" or delivery.attempt_count:
        return
    if delivery.channel == "WECOM" and not tracking_wecom_enabled():
        # 关闭期间的机会留痕后结束；未来开启不能把旧正文当作积压队列补发。
        skip_pending(delivery, "TRACKING_WECOM_DISABLED", now)
        return
    items = current_content_items(delivery, now=now, candidates=candidates, roles_cache=roles_cache)
    if not items:
        skip_pending(delivery, empty_content_reason(delivery, now=now, candidates=candidates, roles_cache=roles_cache), now)
    else:
        append_content(delivery, items, digest=delivery.recipient.event.event_code == "PURCHASE_TRACKING_DIGEST")


def empty_content_reason(delivery, *, now, candidates=None, roles_cache=None):
    """单项即时机会的纯失权单独留痕；解除/降级/摘要覆盖不允许被恢复资格顺带复活。"""
    if delivery.recipient.event.event_code != 'PURCHASE_TRACKING_RISK':
        return 'TRACKING_NO_CURRENT_ITEMS'
    content = saved_content(delivery)
    if not content or len(content.items) != 1:
        return 'TRACKING_NO_CURRENT_ITEMS'
    item = content.items[0]
    if candidates is None:
        from .tracking_runner import collect_candidates
        candidates = {row['source_key']: row for row in collect_candidates(task_ids=[item['production_task_id']], now=now)}
    candidate = candidates.get(item['source_key'])
    current = PurchaseTrackingIssue.objects.filter(pk=item['issue_id'], active=True,
        cycle=item['cycle'], transition=item['transition'], rank=item['rank']).exists()
    if current and candidate and candidate['rank'] == item['rank'] and not recipient_roles(
            delivery.recipient.employee, item['production_task_id'], now,
            event_code=delivery.recipient.event.event_code, cache=roles_cache):
        return 'TRACKING_RECIPIENT_INELIGIBLE'
    return 'TRACKING_NO_CURRENT_ITEMS'


def tracking_recipient_payload(recipient, user, *, qualification_cache=None):
    from apps.wecom.notification_selectors import delivery_statuses
    delivery = recipient.deliveries.filter(channel="IN_APP").first()
    items = current_content_items(delivery, now=timezone.now(), live=False, roles_cache=qualification_cache
        ) if delivery and recipient.employee.user_id == user.pk else []
    accessible = bool(items)
    if accessible:
        title, body, _ = render_content(items, digest=recipient.event.event_code == "PURCHASE_TRACKING_DIGEST",
            templates=recipient.event.context.get('templates'))
        if not PurchaseTrackingIssue.objects.filter(pk__in=[item["issue_id"] for item in items], active=True).exists():
            body += "\n\n这些提醒已解除，请以采购跟踪当前状态为准。"
        target = content_target(items, object_id=recipient.event.object_id)
    else:
        title, body, target = "通知内容不可访问", "该业务内容当前不可访问。", None
    return {"id": recipient.pk, "event_code": recipient.event.event_code,
        "event_name": "采购跟踪每日汇总" if recipient.event.event_code.endswith("DIGEST") else "采购跟踪提醒",
        "title": title, "body": body, "created_at": recipient.created_at, "read_at": recipient.read_at,
        "target": target, "target_accessible": accessible, "channel_status": delivery_statuses(recipient)}


def process_tracking_delivery(delivery, *, allow_uncertain=False, allow_failed=False, defer_unconfigured=False):
    from apps.wecom.client import WeComClient, WeComError, WeComSendUncertain
    from apps.wecom.notification_services import _lock_key
    from apps.wecom.selectors import configuration_complete
    if connection.in_atomic_block:
        raise RuntimeError("外部通知只能在业务事务提交后执行。")
    allowed = {"PENDING"} | ({"UNCERTAIN"} if allow_uncertain else set()) | ({"FAILED"} if allow_failed else set())
    with transaction.atomic():
        _lock_key("purchase-tracking:recompute")
        locked = NotificationDelivery.objects.select_for_update(of=('self',)).select_related("recipient__event", "recipient__employee__user").get(pk=delivery.pk)
        if locked.channel != "WECOM" or locked.status not in allowed or locked.attempt_count != delivery.attempt_count:
            return locked
        if not tracking_wecom_enabled():
            # 人工重试也受开关约束；FAILED/UNCERTAIN 的既有尝试事实不得覆盖。
            skip_pending(locked, "TRACKING_WECOM_DISABLED", timezone.now())
            return locked
        if not getattr(settings, "PURCHASE_TRACKING_ENABLED", False) or not rule_enabled(locked.recipient.event.event_code):
            return locked
        now = timezone.now()
        content = saved_content(locked)
        if content:
            from .tracking_runner import collect_candidates, recompute_tracking
            task_ids = {item['production_task_id'] for item in content.items}
            current_candidates = {item['source_key']: item for item in collect_candidates(task_ids=task_ids, now=now)}
            current_issues = PurchaseTrackingIssue.objects.filter(pk__in=[item['issue_id'] for item in content.items])
            changed = False
            for issue in current_issues:
                candidate = current_candidates.get(issue.source_key)
                if issue.active and not candidate:
                    changed = True
                    break
                if candidate and (not issue.active or issue.fingerprint != fingerprint({'code': candidate['code'],
                        'rank': candidate['rank'], 'snapshot': semantic_snapshot(candidate['snapshot'])})):
                    changed = True
                    break
            if changed:
                # 提交回调漏执行时，先落当前修订号再形成发送子版本，不能把新数量挂在旧风险版本上。
                recompute_tracking(task_ids=task_ids, now=now)
                locked.refresh_from_db()
                if locked.status not in allowed or locked.attempt_count != delivery.attempt_count:
                    return locked
        items = current_content_items(locked, now=now)
        if not items:
            locked.status, locked.error_code, locked.finished_at = "SKIPPED", empty_content_reason(locked, now=now), now
            locked.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
            return locked
        content = saved_content(locked)
        # 人工重试也使用已尝试的冻结正文；已过期或失权的旧正文不能重放。
        unattempted_manual_retry = (allow_failed and locked.status == 'FAILED' and locked.attempt_count == 0
            and locked.error_code in {'CONFIGURATION_ERROR', 'NO_WECOM_BINDING'})
        if (locked.attempt_count or locked.status != 'PENDING' and not unattempted_manual_retry) and content.items != items:
            locked.status, locked.error_code = "SKIPPED", "TRACKING_RETRY_CONTENT_STALE"
            locked.save(update_fields=["status", "error_code", "updated_at"])
            return locked
        if unattempted_manual_retry:
            # 仅人工指定的本地前置失败：从未调用网关，允许原渠道追加当前正文，站内不重发。
            locked.status = 'PENDING'
        content = append_content(locked, items, digest=locked.recipient.event.event_code.endswith("DIGEST"))
        config = WeComConfig.objects.first()
        binding = WeComBinding.objects.filter(employee_id=locked.recipient.employee_id).first()
        reason = ""
        if config is None or not config.enabled or not configuration_complete(config):
            if defer_unconfigured and locked.status == "PENDING":
                return locked
            reason = "CONFIGURATION_ERROR"
        elif binding is None:
            reason = "NO_WECOM_BINDING"
        elif binding.corp_id != config.corp_id:
            reason = "CORPORATION_MISMATCH"
        else:
            original = locked.recipient.eligibility_snapshot
            if (original.get("corp_id") and original["corp_id"] != config.corp_id
                    or original.get("agent_id") and str(original["agent_id"]) != str(config.agent_id)
                    or locked.user_id_snapshot and locked.user_id_snapshot != binding.user_id):
                reason = "BINDING_OR_APPLICATION_CHANGED"
        if reason:
            locked.status, locked.error_code, locked.finished_at = "FAILED", reason, now
            locked.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
            return locked
        locked.status, locked.error_code = "PROCESSING", ""
        locked.attempt_count += 1
        attempt = locked.attempt_count
        locked.last_attempt_at, locked.user_id_snapshot = now, binding.user_id
        locked.save(update_fields=["status", "error_code", "attempt_count", "last_attempt_at", "user_id_snapshot", "updated_at"])
        accepted_parts = list(locked.tracking_part_results)
    status, error_code = "ACCEPTED", ""
    try:
        for index in range(len(accepted_parts), len(content.parts)):
            if index or not tracking_wecom_enabled():
                # 长摘要分段之间也重验，不能在撤权或问题解除后继续外发余下旧正文。
                with transaction.atomic():
                    _lock_key('purchase-tracking:recompute')
                    current = NotificationDelivery.objects.select_for_update().select_related(
                        'recipient__event', 'recipient__employee').get(pk=locked.pk)
                    if current.status != 'PROCESSING' or current.attempt_count != attempt:
                        return current
                    if not tracking_wecom_enabled():
                        current.status, current.error_code, current.finished_at = 'SKIPPED', 'TRACKING_WECOM_DISABLED', timezone.now()
                        current.save(update_fields=['status', 'error_code', 'finished_at', 'updated_at'])
                        return current
                    current_config = WeComConfig.objects.filter(pk=config.pk).first()
                    same_config = bool(current_config and current_config.enabled
                        and current_config.corp_id == config.corp_id and current_config.agent_id == config.agent_id
                        and current_config.erp_origin == config.erp_origin
                        and current_config.secret_ciphertext == config.secret_ciphertext)
                    if (not getattr(settings, 'PURCHASE_TRACKING_ENABLED', False)
                            or not same_config
                            or not rule_enabled(current.recipient.event.event_code)
                            or current_content_items(current, now=timezone.now()) != content.items
                            or not WeComBinding.objects.filter(employee_id=current.recipient.employee_id,
                                corp_id=binding.corp_id, user_id=binding.user_id).exists()):
                        current.status, current.error_code, current.finished_at = 'SKIPPED', 'TRACKING_CHANGED_DURING_SEND', timezone.now()
                        current.save(update_fields=['status', 'error_code', 'finished_at', 'updated_at'])
                        return current
            result = WeComClient(config).send_text_notice(binding.user_id, title=content.title,
                body=content.parts[index], url=f"{config.erp_origin}/?notification={locked.recipient_id}", preview=False)
            accepted_parts.append({"part": index + 1, "msgid": result["msgid"], "content_id": str(content.pk)})
            # 成功分段立即留痕；之后失败的人工重试不能再发已受理段。
            with transaction.atomic():
                row = NotificationDelivery.objects.select_for_update().get(pk=locked.pk)
                if row.status != "PROCESSING" or row.attempt_count != attempt:
                    return row
                row.tracking_part_results = accepted_parts
                row.msgid = result["msgid"]
                row.save(update_fields=["tracking_part_results", "msgid", "updated_at"])
    except WeComSendUncertain:
        status, error_code = "UNCERTAIN", "SEND_UNCERTAIN"
    except WeComError as exc:
        status, error_code = "FAILED", exc.code
    with transaction.atomic():
        locked = NotificationDelivery.objects.select_for_update().get(pk=locked.pk)
        if locked.status == "PROCESSING" and locked.attempt_count == attempt:
            locked.status, locked.error_code, locked.finished_at = status, error_code, timezone.now()
            locked.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
    return locked
