"""业务聚合根保存后刷新采购风险；事务回滚时不产生提醒。

既有服务在同一事务内保存总单/批次/BOM/排产等主记录及其批量子行。
只监听主记录，提交后才读取完整结果，避免逐材料保存时反复读取半成品。
没有经过这些服务的批量维护和日期变化由 60 秒扫描兜底。
"""
from functools import partial

from django.conf import settings
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save


def _enabled():
    return getattr(settings, "PURCHASE_TRACKING_ENABLED", False)


def _recompute(task_ids):
    from .tracking_runner import recompute_tracking

    return recompute_tracking(task_ids=task_ids)


def refresh_tracking_after_commit(task_ids, *, using="default"):
    if not _enabled():
        return
    ids = tuple(sorted({str(task_id) for task_id in task_ids if task_id}))
    if ids:
        # robust=True 会记录异常及堆栈；已提交业务不返回假失败，扫描进程负责补算。
        transaction.on_commit(partial(_recompute, ids), using=using, robust=True)


def _direct_task_changed(sender, instance, *, raw=False, using="default", **kwargs):
    if raw or not _enabled():
        return
    task_id = instance.pk if sender._meta.label_lower == "production_tasks.productiontask" else instance.production_task_id
    refresh_tracking_after_commit([task_id], using=using)


def _return_changed(sender, instance, *, raw=False, using="default", **kwargs):
    if raw or not _enabled():
        return
    refresh_tracking_after_commit([instance.purchase_order.production_task_id], using=using)


def _refresh_inbound(inbound_id, task_id):
    from apps.inventory.models import MaterialInboundLine

    # 同次到货允许引用不同采购批次，不能只看可空的主记录 purchase_order。
    task_ids = set(MaterialInboundLine.objects.filter(inbound_id=inbound_id).values_list(
        "purchase_order_line__purchase_order__production_task_id", flat=True,
    ))
    if task_id:
        task_ids.add(task_id)
    task_ids.discard(None)
    if task_ids:
        _recompute(tuple(sorted(str(value) for value in task_ids)))


def _inbound_changed(sender, instance, *, raw=False, using="default", **kwargs):
    if raw or not _enabled():
        return
    task_id = instance.purchase_order.production_task_id if instance.purchase_order_id else None
    transaction.on_commit(partial(_refresh_inbound, instance.pk, task_id), using=using, robust=True)


def _followers_changed(sender, instance, action, reverse, pk_set, using="default", **kwargs):
    if not _enabled():
        return
    if reverse and action == "pre_clear":
        instance._tracking_cleared_task_ids = tuple(instance.followed_production_tasks.values_list("pk", flat=True))
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    if not reverse:
        task_ids = [instance.pk]
    elif action == "post_clear":
        task_ids = getattr(instance, "_tracking_cleared_task_ids", ())
        if hasattr(instance, "_tracking_cleared_task_ids"):
            del instance._tracking_cleared_task_ids
    else:
        task_ids = pk_set or ()
    refresh_tracking_after_commit(task_ids, using=using)


def connect_tracking_hooks():
    from apps.boms.models import Bom
    from apps.inventory.models import MaterialInbound
    from apps.production_scheduling.models import ProductionSchedule
    from apps.production_tasks.models import ProductionTask, ProductionTaskFollower
    from .models import PurchaseGroup, PurchaseOrder, PurchaseReturn

    for model in (ProductionTask, Bom, PurchaseGroup, PurchaseOrder, ProductionSchedule, ProductionTaskFollower):
        for signal in (post_save, post_delete):
            signal.connect(_direct_task_changed, sender=model, weak=False,
                           dispatch_uid=f"purchase_tracking:{model._meta.label_lower}:{id(signal)}")
    for model, receiver in ((MaterialInbound, _inbound_changed), (PurchaseReturn, _return_changed)):
        post_save.connect(receiver, sender=model, weak=False, dispatch_uid=f"purchase_tracking:{model._meta.label_lower}")
    m2m_changed.connect(_followers_changed, sender=ProductionTask.followers.through, weak=False,
                        dispatch_uid="purchase_tracking:followers")
