"""全任务最新BOM的确认快照；不改变采购建单和数量规则。"""
import hashlib
import json
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from .models import Bom, BomStatus


EVENT_CODE = "PRODUCTION_TASK_BOMS_CONFIRMED"
SNAPSHOT_FIELDS = {"product_line_id", "product_quantity", "bom_id", "version_number", "confirmed_at"}


def validated_bom_snapshot(value):
    """仅接受本事件的固定关系结构，不把关系快照当模板文本或任意JSON。"""
    if not isinstance(value, list) or not value:
        raise ValidationError({"bom_versions": "必须提供完整BOM版本组合。"})
    rows = []
    for item in value:
        if not isinstance(item, dict) or set(item) != SNAPSHOT_FIELDS:
            raise ValidationError({"bom_versions": "BOM版本快照字段无效。"})
        try:
            product_id, bom_id = str(UUID(str(item["product_line_id"]))), str(UUID(str(item["bom_id"])))
        except (ValueError, TypeError):
            raise ValidationError({"bom_versions": "BOM关系必须使用有效UUID。"}) from None
        version = item["version_number"]
        quantity = item["product_quantity"]
        confirmed_at = item["confirmed_at"]
        if (not isinstance(version, int) or isinstance(version, bool) or version < 1
                or not isinstance(quantity, str) or len(quantity) > 19
                or not quantity.isascii() or not quantity.isdigit() or int(quantity) < 1):
            raise ValidationError({"bom_versions": "版本和任务产品数量无效。"})
        if confirmed_at is not None:
            try:
                valid_time = isinstance(confirmed_at, str) and len(confirmed_at) <= 80 and parse_datetime(confirmed_at) is not None
            except ValueError:
                valid_time = False
            if not valid_time:
                raise ValidationError({"bom_versions": "BOM确认时间无效。"})
        rows.append({"product_line_id": product_id, "product_quantity": str(int(quantity)),
                     "bom_id": bom_id, "version_number": version, "confirmed_at": confirmed_at})
    if len({row["product_line_id"] for row in rows}) != len(rows):
        raise ValidationError({"bom_versions": "同一任务产品不能重复。"})
    return sorted(rows, key=lambda row: row["product_line_id"])


def snapshot_version(snapshot):
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def current_task_bom_snapshot(task_id):
    if not ProductionTask.objects.filter(pk=task_id, archived_at__isnull=True).exists():
        return None
    products = list(ProductionTaskProduct.objects.filter(production_task_id=task_id).order_by("id").values_list("id", "quantity"))
    if not products:
        return None
    latest = {}
    for bom in Bom.objects.filter(production_task_id=task_id, product_line_id__in=[pk for pk, _ in products],
                                  archived_at__isnull=True).order_by("product_line_id", "-version_number", "-id"):
        latest.setdefault(bom.product_line_id, bom)
    if any(pk not in latest or latest[pk].status != BomStatus.VERIFIED for pk, _ in products):
        return None
    return [{"product_line_id": str(pk), "product_quantity": str(quantity), "bom_id": str(latest[pk].pk),
             "version_number": latest[pk].version_number,
             "confirmed_at": latest[pk].confirmed_at.isoformat() if latest[pk].confirmed_at else None}
            for pk, quantity in products]


def bom_event_is_current(event):
    if event.status == "STALE":
        return False
    snapshot = current_task_bom_snapshot(event.object_id)
    return snapshot is not None and snapshot_version(snapshot) == event.object_version


@transaction.atomic
def expire_task_bom_events(task_id, *, force=False):
    """仅更新事件有效状态，历史文案、版本组合及收件快照保持原样。"""
    from apps.wecom.models import NotificationEvent

    ProductionTask.objects.select_for_update().get(pk=task_id)
    events = NotificationEvent.objects.filter(event_code=EVENT_CODE, object_id=str(task_id), status="CREATED")
    snapshot = current_task_bom_snapshot(task_id)
    if snapshot is not None and not force:
        events = events.exclude(object_version=snapshot_version(snapshot))
    events.update(status="STALE", updated_at=timezone.now())


@transaction.atomic
def register_task_boms_confirmed(*, task_id, actor_employee, confirmed_at):
    from apps.wecom.models import NotificationEvent
    from apps.wecom.notification_services import register_business_event

    task = ProductionTask.objects.select_for_update().get(pk=task_id)
    snapshot = current_task_bom_snapshot(task_id)
    if snapshot is None:
        return None
    version = snapshot_version(snapshot)
    key = f"{EVENT_CODE}:{task.pk}:{version}"
    # 同一组合返回原事件；不因操作者、模板或角色变化追发历史事件。
    existing = NotificationEvent.objects.filter(idempotency_key=key).first()
    if existing is not None:
        return existing
    expire_task_bom_events(task_id)
    return register_business_event(
        event_code=EVENT_CODE, idempotency_key=key, object_type="production_tasks.ProductionTask",
        object_id=task.pk, object_version=version,
        context={"document_no": task.task_number, "product_count": len(snapshot),
                 "operator": actor_employee.display_name, "occurred_at": confirmed_at.isoformat(),
                 "bom_versions": snapshot},
    )
