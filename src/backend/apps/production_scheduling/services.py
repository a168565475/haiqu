import hashlib
import json

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.boms.models import Bom, BomStatus
from apps.procurement.models import PurchaseOrder, PurchaseOrderStatus
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from apps.workshop_config.models import Craft, RecordStatus

from .models import (
    ProductionSchedule,
    ProductionScheduleProduct,
    ProductionScheduleProductCraft,
    ScheduleStatus,
)
from .selectors import schedule_product_image


def _json_hash(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def task_source_snapshot(task):
    followers = [
        {"id": str(employee.pk), "code": employee.employee_code, "name": employee.display_name}
        for employee in task.followers.all().order_by("id")
    ]
    return {
        "task_number": task.task_number,
        "contract_number": task.contract_number,
        "order_number": task.order_number,
        "sales_order_id": str(task.sales_order_id) if task.sales_order_id else None,
        "sales_order_number": task.sales_order.order_number if task.sales_order_id else None,
        "customer_account_id": str(task.customer_account_id) if task.customer_account_id else None,
        "customer_name": task.customer_account.account_name if task.customer_account_id else "",
        "salesperson": {
            "id": str(task.salesperson_id),
            "code": task.salesperson.employee_code,
            "name": task.salesperson.display_name,
        },
        "followers": followers,
        "order_date": task.order_date.isoformat(),
        "delivery_date": task.delivery_date.isoformat(),
        "planned_start_date": task.planned_start_date.isoformat() if task.planned_start_date else None,
        "planned_end_date": task.planned_end_date.isoformat() if task.planned_end_date else None,
    }


def product_source_snapshot(product_line):
    return {
        "product_id": str(product_line.product_id),
        "product_number": product_line.product_number_snapshot,
        "product_code": product_line.product_code_snapshot,
        "item_number": product_line.item_number_snapshot,
        "product_name": product_line.product_name_snapshot,
        "specification": product_line.specification_snapshot,
        "product_color_id": str(product_line.product_color_id) if product_line.product_color_id else None,
        "color_card": product_line.color_card_snapshot,
        "color_name": product_line.color_name_snapshot,
        "color_code": product_line.color_code_snapshot,
        "special_requirements": product_line.special_requirements,
        "packaging_method": product_line.packaging_method,
    }


def source_revision(task, product_lines):
    data = {
        "task_id": str(task.pk),
        "status": task.status,
        "archived": task.archived_at is not None,
        "source": task_source_snapshot(task),
        "products": [
            {
                "id": str(line.pk), "product_id": str(line.product_id), "quantity": line.quantity,
                "unit_id": str(line.unit_id), "snapshot": product_source_snapshot(line),
            }
            for line in sorted(product_lines, key=lambda item: str(item.pk))
        ],
    }
    return _json_hash(data)


def schedule_audit_snapshot(schedule):
    products = schedule.products.filter(removed_at__isnull=True).order_by("line_number", "id").prefetch_related("crafts")
    return {
        "version": schedule.version,
        "record_status": schedule.record_status,
        "source_revision_hash": schedule.source_revision_hash,
        "products": [
            {
                "product_line_id": str(row.product_line_id),
                "line_number": row.line_number,
                "planned_quantity": row.planned_quantity,
                "material_inbound_date": row.material_inbound_date.isoformat(),
                "metal_return_date": row.metal_return_date.isoformat(),
                "sewing_return_date": row.sewing_return_date.isoformat(),
                "finished_inbound_date": row.finished_inbound_date.isoformat(),
                "crafts": [
                    {
                        "craft_id": str(link.craft_id),
                        "name": link.craft_name_snapshot,
                        "craft_type": link.craft_type_snapshot,
                        "plan_category": link.plan_category,
                    }
                    for link in row.crafts.all() if link.removed_at is None
                ],
            }
            for row in products
        ],
    }


def _validated_source(production_task_id, items, expected_revision="", allowed_statuses=None):
    try:
        task = ProductionTask.objects.select_for_update(of=("self",)).select_related(
            "customer_account", "salesperson", "sales_order"
        ).prefetch_related("followers").get(pk=production_task_id)
    except ProductionTask.DoesNotExist as exc:
        raise ValidationError({"production_task_id": "生产任务单不存在或不可访问。"}) from exc
    allowed_statuses = set(allowed_statuses or {ProductionTaskStatus.READY})
    if task.archived_at is not None or task.status not in allowed_statuses:
        raise Conflict("仅当前状态为已接单（READY）且未归档的生产任务单可以排产。")
    line_ids = [item["product_line_id"] for item in items]
    if len(line_ids) != len(set(line_ids)):
        raise ValidationError({"items": "同一任务产品不能重复加入排产。"})
    all_lines = list(
        ProductionTaskProduct.objects.select_for_update(of=("self",)).select_related(
            "unit", "image_file", "product_color", "production_task",
            "sales_order_delivery_batch_line__sales_order_line__product_image",
        ).filter(production_task=task).prefetch_related("images__image_file")
    )
    all_line_map = {line.pk: line for line in all_lines}
    if any(line_id not in all_line_map for line_id in line_ids):
        raise ValidationError({"items": "存在不属于所选生产任务单的产品。"})
    latest_bom_by_line = {}
    active_boms = (
        Bom.objects.select_for_update(of=("self",))
        .filter(production_task=task, archived_at__isnull=True)
        .order_by("product_line_id", "-version_number", "-created_at", "-id")
    )
    for bom in active_boms:
        latest_bom_by_line.setdefault(bom.product_line_id, bom)
    unverified_lines = [
        line for line in all_lines
        if latest_bom_by_line.get(line.pk) is None
        or latest_bom_by_line[line.pk].status != BomStatus.VERIFIED
    ]
    if unverified_lines:
        raise Conflict("生产任务单内所有产品的 BOM 必须已确认后才能排产。")
    purchase_order = (
        PurchaseOrder.objects.select_for_update(of=("self",))
        .filter(production_task=task, archived_at__isnull=True)
        .first()
    )
    if purchase_order is None or purchase_order.status != PurchaseOrderStatus.COMPLETED:
        raise Conflict("采购订单必须为“已完成采购”后才能排产。")
    current_revision = source_revision(task, all_lines)
    accepted_revisions = {current_revision}
    if task.status == ProductionTaskStatus.IN_PRODUCTION:
        task.status = ProductionTaskStatus.READY
        accepted_revisions.add(source_revision(task, all_lines))
        task.status = ProductionTaskStatus.IN_PRODUCTION
    if expected_revision and expected_revision not in accepted_revisions:
        raise Conflict("生产任务单或产品资料已变化，请刷新后重新填写。")
    return task, {line_id: all_line_map[line_id] for line_id in line_ids}, current_revision, all_lines


def _validated_crafts(items):
    craft_ids = {craft_id for item in items for craft_id in item["craft_ids"]}
    crafts = list(Craft.objects.select_for_update().filter(pk__in=craft_ids))
    craft_map = {craft.pk: craft for craft in crafts}
    if len(craft_map) != len(craft_ids):
        raise ValidationError({"items": "存在无效工艺。"})
    for craft in crafts:
        if craft.status != RecordStatus.ACTIVE:
            raise ValidationError({"items": f"工艺“{craft.name}”已停用，不能选择。"})
    return craft_map


def _payload_hash(data):
    normalized = {
        "production_task_id": str(data["production_task_id"]),
        "source_revision_hash": data.get("source_revision_hash", ""),
        "items": [
            {
                **{key: str(value) for key, value in item.items() if key != "craft_ids"},
                "craft_ids": sorted(str(value) for value in item["craft_ids"]),
            }
            for item in data["items"]
        ],
    }
    return _json_hash(normalized)


def _set_product_fields(row, item, line, line_number, revision):
    row.product_line = line
    row.line_number = line_number
    row.planned_quantity = item["planned_quantity"]
    row.source_quantity_snapshot = line.quantity
    row.unit = line.unit
    row.unit_name_snapshot = line.unit.unit_name
    row.image_file = schedule_product_image(line)
    row.material_inbound_date = item["material_inbound_date"]
    row.metal_return_date = item["metal_return_date"]
    row.sewing_return_date = item["sewing_return_date"]
    row.finished_inbound_date = item["finished_inbound_date"]
    row.product_snapshot = product_source_snapshot(line)
    row.source_revision_hash = revision
    row.removed_at = None
    row.removed_by_employee = None
    row.full_clean()
    row.save()


def _sync_crafts(row, craft_ids, craft_map, actor_employee, now):
    active = {link.craft_id: link for link in row.crafts.select_for_update().filter(removed_at__isnull=True)}
    for craft_id, link in active.items():
        if craft_id not in craft_ids:
            link.removed_at = now
            link.removed_by_employee = actor_employee
            link.save(update_fields=["removed_at", "removed_by_employee", "updated_at"])
    for craft_id in craft_ids:
        if craft_id in active:
            continue
        craft = craft_map[craft_id]
        old = row.crafts.select_for_update().filter(craft_id=craft_id).order_by("-created_at").first()
        link = old or ProductionScheduleProductCraft(schedule_product=row, craft=craft)
        link.craft_type_snapshot = craft.craft_type
        link.craft_name_snapshot = craft.name
        link.plan_category = craft.plan_category
        link.removed_at = None
        link.removed_by_employee = None
        link.full_clean()
        link.save()


@transaction.atomic
def create_schedule(*, validated_data, actor_employee, request=None):
    from apps.access_control.workshop_scopes import require_schedule_write
    require_schedule_write(request, 'production_scheduling.add_productionschedule',
                           {pk for item in validated_data['items'] for pk in item['craft_ids']},
                           task_id=validated_data['production_task_id'])
    request_id = validated_data["client_request_id"]
    payload_hash = _payload_hash(validated_data)
    existing = ProductionSchedule.objects.select_for_update().filter(client_request_id=request_id).first()
    if existing:
        if existing.request_payload_hash != payload_hash:
            raise Conflict("相同请求标识已用于不同的排产内容。")
        return existing
    items = validated_data["items"]
    try:
        task, line_map, revision, all_lines = _validated_source(
            validated_data["production_task_id"], items, validated_data.get("source_revision_hash", "")
        )
    except Conflict:
        # 并发的同一幂等请求可能已在等待任务锁期间完成，并把任务推进到生产中。
        existing = ProductionSchedule.objects.filter(client_request_id=request_id).first()
        if existing and existing.request_payload_hash == payload_hash:
            return existing
        raise
    existing = ProductionSchedule.objects.select_for_update().filter(client_request_id=request_id).first()
    if existing:
        if existing.request_payload_hash != payload_hash:
            raise Conflict("相同请求标识已用于不同的排产内容。")
        return existing
    duplicate = ProductionSchedule.objects.filter(
        production_task=task, record_status=ScheduleStatus.ACTIVE
    ).first()
    if duplicate:
        raise Conflict({"detail": "该生产任务单已有有效排产计划。", "existing_schedule_id": str(duplicate.pk)})
    craft_map = _validated_crafts(items)
    try:
        with transaction.atomic():
            schedule = ProductionSchedule.objects.create(
                schedule_number=next_business_number("PRODUCTION_SCHEDULE", timezone.localdate()),
                production_task=task,
                source_snapshot=task_source_snapshot(task),
                source_revision_hash=revision,
                client_request_id=request_id,
                request_payload_hash=payload_hash,
                created_by_employee=actor_employee,
                updated_by_employee=actor_employee,
            )
            for index, item in enumerate(items, start=1):
                line = line_map[item["product_line_id"]]
                if item["planned_quantity"] > line.quantity:
                    raise ValidationError({"items": {index - 1: {"planned_quantity": "排产数量不能超过任务产品数量。"}}})
                row = ProductionScheduleProduct(schedule=schedule)
                _set_product_fields(row, item, line, index, revision)
                _sync_crafts(row, set(item["craft_ids"]), craft_map, actor_employee, timezone.now())
            task_status_before = task.status
            task.status = ProductionTaskStatus.IN_PRODUCTION
            task.save(update_fields=["status", "updated_at"])
            revision = source_revision(task, all_lines)
            ProductionScheduleProduct.objects.filter(schedule=schedule, removed_at__isnull=True).update(
                source_revision_hash=revision, updated_at=timezone.now()
            )
            ProductionSchedule.objects.filter(pk=schedule.pk).update(
                version=1, source_revision_hash=revision, updated_at=timezone.now()
            )
            schedule.refresh_from_db(fields=["version", "source_revision_hash", "updated_at"])
    except IntegrityError as exc:
        existing = ProductionSchedule.objects.filter(client_request_id=request_id).first()
        if existing and existing.request_payload_hash == payload_hash:
            return existing
        raise Conflict("该生产任务单已被其他请求排产，请刷新后查看原计划。") from exc
    write_audit_log(
        object_type="PRODUCTION_SCHEDULE", object_id=schedule.pk, action="CREATED",
        actor_employee=actor_employee, after_data={"schedule_number": schedule.schedule_number, **schedule_audit_snapshot(schedule)},
        context_type="PRODUCTION_TASK", context_id=task.pk, request=request,
    )
    write_audit_log(
        object_type="PRODUCTION_TASK", object_id=task.pk, action="SCHEDULED",
        actor_employee=actor_employee,
        before_data={"status": task_status_before},
        after_data={"status": task.status, "schedule_id": str(schedule.pk)},
        context_type="SALES_ORDER" if task.sales_order_id else "CUSTOMER_ACCOUNT",
        context_id=task.sales_order_id or task.customer_account_id,
        request=request,
    )
    from apps.wecom.notification_services import register_business_event
    # 一张计划一个创建事件；多车间关系由通知权限层从已保存工艺解析并按员工去重。
    register_business_event(
        event_code="PRODUCTION_PLAN_CREATED", idempotency_key=f"PRODUCTION_PLAN_CREATED:{schedule.pk}:1",
        object_type="production_scheduling.ProductionSchedule", object_id=schedule.pk, object_version=1,
        context={"document_no": schedule.schedule_number, "operator": actor_employee.display_name,
                 "occurred_at": schedule.created_at.isoformat()},
    )
    return schedule


@transaction.atomic
def create_schedule_batch(*, validated_data, actor_employee, request=None):
    """在同一事务中为多张生产任务单分别生成排产计划。"""
    schedules = validated_data["schedules"]
    request_ids = {item["client_request_id"] for item in schedules}
    # 与编辑路径保持“排产计划 -> 来源任务”的锁顺序，避免批量幂等重试和编辑互相等待。
    existing_request_ids = set(
        ProductionSchedule.objects.select_for_update()
        .filter(client_request_id__in=request_ids)
        .order_by("client_request_id")
        .values_list("client_request_id", flat=True)
    )
    pending = [item for item in schedules if item["client_request_id"] not in existing_request_ids]
    task_ids = {item["production_task_id"] for item in pending}
    craft_ids = {craft_id for item in pending for row in item["items"] for craft_id in row["craft_ids"]}
    # 只锁定真正待创建项目的来源与工艺，且始终按稳定顺序获取。
    list(ProductionTask.objects.select_for_update().filter(pk__in=task_ids).order_by("pk"))
    list(
        ProductionTaskProduct.objects.select_for_update()
        .filter(production_task_id__in=task_ids)
        .order_by("production_task_id", "pk")
    )
    list(Craft.objects.select_for_update().filter(pk__in=craft_ids).order_by("pk"))
    return [
        create_schedule(validated_data=item, actor_employee=actor_employee, request=request)
        for item in schedules
    ]


@transaction.atomic
def update_schedule(*, schedule_id, validated_data, actor_employee, request):
    schedule = ProductionSchedule.objects.select_for_update().get(pk=schedule_id)
    from apps.access_control.workshop_scopes import require_schedule_write
    require_schedule_write(request, 'production_scheduling.change_productionschedule',
                           {pk for item in validated_data['items'] for pk in item['craft_ids']}, schedule)
    require_matching_etag(request, schedule)
    if schedule.record_status != ScheduleStatus.ACTIVE:
        raise Conflict("已作废排产不能编辑。")
    items = validated_data["items"]
    task, line_map, revision, _ = _validated_source(
        schedule.production_task_id,
        items,
        validated_data.get("source_revision_hash", ""),
        allowed_statuses={ProductionTaskStatus.READY, ProductionTaskStatus.IN_PRODUCTION},
    )
    craft_map = _validated_crafts(items)
    before_state = schedule_audit_snapshot(schedule)
    original_version = schedule.version
    now = timezone.now()
    active_rows = list(schedule.products.select_for_update().filter(removed_at__isnull=True).prefetch_related("crafts"))
    active_by_line = {row.product_line_id: row for row in active_rows}
    incoming_ids = {item["product_line_id"] for item in items}
    for offset, row in enumerate(active_rows, start=1):
        row.line_number = 1_000_000 + offset
        row.save(update_fields=["line_number", "updated_at"])
    for row in active_rows:
        if row.product_line_id not in incoming_ids:
            row.crafts.filter(removed_at__isnull=True).update(removed_at=now, removed_by_employee=actor_employee, updated_at=now)
            row.removed_at = now
            row.removed_by_employee = actor_employee
            row.save(update_fields=["removed_at", "removed_by_employee", "updated_at"])
    for index, item in enumerate(items, start=1):
        line = line_map[item["product_line_id"]]
        if item["planned_quantity"] > line.quantity:
            raise ValidationError({"items": {index - 1: {"planned_quantity": "排产数量不能超过任务产品数量。"}}})
        row = active_by_line.get(line.pk) or ProductionScheduleProduct(schedule=schedule)
        _set_product_fields(row, item, line, index, revision)
        _sync_crafts(row, set(item["craft_ids"]), craft_map, actor_employee, now)
    schedule.version = original_version + 1
    schedule.source_snapshot = task_source_snapshot(task)
    schedule.source_revision_hash = revision
    schedule.updated_by_employee = actor_employee
    schedule.updated_at = timezone.now()
    schedule.save(update_fields=["version", "source_snapshot", "source_revision_hash", "updated_by_employee", "updated_at"])
    write_audit_log(
        object_type="PRODUCTION_SCHEDULE", object_id=schedule.pk, action="UPDATED", actor_employee=actor_employee,
        before_data=before_state, after_data=schedule_audit_snapshot(schedule),
        context_type="PRODUCTION_TASK", context_id=task.pk, request=request,
    )
    return schedule


@transaction.atomic
def void_schedule(*, schedule_id, reason, actor_employee, request):
    schedule = ProductionSchedule.objects.select_for_update().get(pk=schedule_id)
    from apps.access_control.workshop_scopes import require_schedule_write
    require_schedule_write(request, 'production_scheduling.void_productionschedule', set(), schedule)
    require_matching_etag(request, schedule)
    if schedule.record_status != ScheduleStatus.ACTIVE:
        raise Conflict("该排产计划已经作废。")
    before_state = schedule_audit_snapshot(schedule)
    now = timezone.now()
    schedule.record_status = ScheduleStatus.VOID
    schedule.version += 1
    schedule.void_reason = reason.strip()
    schedule.voided_at = now
    schedule.voided_by_employee = actor_employee
    schedule.updated_by_employee = actor_employee
    schedule.updated_at = now
    schedule.full_clean()
    schedule.save()
    task = ProductionTask.objects.select_for_update().get(pk=schedule.production_task_id)
    task_status_before = task.status
    if task.status == ProductionTaskStatus.IN_PRODUCTION:
        task.status = ProductionTaskStatus.READY
        task.save(update_fields=["status", "updated_at"])
    write_audit_log(
        object_type="PRODUCTION_SCHEDULE", object_id=schedule.pk, action="VOIDED", actor_employee=actor_employee,
        before_data=before_state,
        after_data={**schedule_audit_snapshot(schedule), "void_reason": schedule.void_reason},
        context_type="PRODUCTION_TASK", context_id=schedule.production_task_id, request=request,
    )
    if task.status != task_status_before:
        write_audit_log(
            object_type="PRODUCTION_TASK", object_id=task.pk, action="SCHEDULE_VOIDED",
            actor_employee=actor_employee,
            before_data={"status": task_status_before, "schedule_id": str(schedule.pk)},
            after_data={"status": task.status},
            context_type="SALES_ORDER" if task.sales_order_id else "CUSTOMER_ACCOUNT",
            context_id=task.sales_order_id or task.customer_account_id,
            request=request,
        )
    return schedule
