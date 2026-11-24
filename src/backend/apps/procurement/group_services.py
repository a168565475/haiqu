from .catalog_materials import purchase_catalog_selection, physical_pipe_quantity, priced_quantity
from apps.material_catalog.saved_selection import validate_saved_material
"""生产采购总单：冻结来源，原 PurchaseOrder 继续承担批次履约。"""
import hashlib
import json
from collections import defaultdict
from copy import copy
from decimal import Decimal
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.boms.models import Bom, BomLine, BomStatus
from apps.boms.material_flow_calculations import MaterialFlowValueError, decimal_quantity
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.products.material_identity import lock_bom_line_material_identities
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import Currency, ReferenceStatus

from .material_receipt_identity import build_purchase_material_snapshot, resolve_purchase_material
from .group_selectors import (
    purchase_group_batch_numbers, purchase_group_completion_summary, purchase_group_deletion_summary,
    purchase_group_progress, purchase_groups_with_context,
)
from .models import PurchaseGroup, PurchaseGroupBomSource, PurchaseGroupLine, PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus, PurchaseScope, Supplier
from .multi_bom_sources import matches_combined_source, merge_purchase_snapshots, purchase_merge_key
from .pipe_purchase import pipe_source_snapshot, purchase_pipe_values
from .purchase_scope import is_packaging_snapshot, validate_source_scope
from .selectors import production_tasks_with_purchase_sources, purchase_orders_with_context
from .set_pricing import apply_set_pricing, material_calculation_snapshot, validate_set_members
from .services import (
    PURCHASABLE_TASK_STATUSES, PurchaseSourceChanged, PurchaseSourceUnavailable, _money, evaluate_purchase_source,
    _validate_hardware_actual_weight, confirm_purchase_order, is_hardware_weight_snapshot, next_purchase_order_number, purchase_order_snapshot,
)


SOURCE_FIELDS = (
    "material_catalog_id", "material_selection_snapshot",
    "bom_id", "bom_line_id", "source_bom_line_id_snapshot", "product_line_id_snapshot",
    "bom_number_snapshot", "product_number_snapshot", "product_code_snapshot", "product_name_snapshot",
    "product_specification_snapshot", "section_type_snapshot", "section_title_snapshot",
    "category_snapshot", "material_snapshot", "part_name_snapshot", "specification_snapshot",
    "raw_material_snapshot", "material_attributes_snapshot", "required_quantity",
    "source_quantity_field", "source_quantity_text", "source_unit_text", "quantity_parse_status",
    "raw_bar_length_m", "raw_bar_weight_kg", "suggested_bar_count", "suggested_purchase_meters",
    "suggested_purchase_weight_kg", "calculation_snapshot",
)


@transaction.atomic
def complete_purchase_group(*, group_id, remark, allowed_task_ids, actor_employee, request):
    task_id = PurchaseGroup.objects.filter(
        pk=group_id, production_task_id__in=allowed_task_ids, archived_at__isnull=True,
    ).values_list("production_task_id", flat=True).first()
    if task_id is None:
        raise NotFound("采购需求不存在或不在当前账号的数据范围内。")
    task = ProductionTask.objects.select_for_update().get(pk=task_id)
    group = PurchaseGroup.objects.select_for_update().filter(pk=group_id, archived_at__isnull=True).first()
    if task.archived_at or group is None:
        raise NotFound("采购需求不存在、已删除或生产订单已归档。")
    require_matching_etag(request, group)
    # 入库先锁采购单；锁完当前所有批次后重新读取流程，不能依赖页面预取或总单版本代替重核。
    list(PurchaseOrder.objects.select_for_update().filter(
        purchase_group=group, archived_at__isnull=True,
    ).order_by("id"))
    current = purchase_groups_with_context().get(pk=group.pk)
    summary = purchase_group_completion_summary(current)
    if not summary["can_complete"]:
        raise Conflict(summary["blocked_reason"])
    remark = remark.strip()
    if len(remark) > 2000:
        raise ValidationError({"remark": "完成备注不能超过2000字。"})
    group.manual_completed_at = timezone.now()
    group.manual_completed_by_employee = actor_employee
    group.manual_completion_remark = remark
    group.save(update_fields=["manual_completed_at", "manual_completed_by_employee", "manual_completion_remark", "updated_at"])
    write_audit_log(
        object_type="PURCHASE_GROUP", object_id=group.pk, action="MANUALLY_COMPLETED",
        context_type="PRODUCTION_TASK", context_id=group.production_task_id, actor_employee=actor_employee,
        before_data={"manual_completed_at": None},
        after_data={"manual_completed_at": group.manual_completed_at,
                    "manual_completed_by_employee_id": actor_employee.pk, "manual_completion_remark": remark},
        request=request,
    )
    return purchase_groups_with_context().get(pk=group.pk)


@transaction.atomic
def delete_purchase_group(*, group_id, allowed_task_ids, actor_employee, request):
    task_id = PurchaseGroup.objects.filter(
        pk=group_id, production_task_id__in=allowed_task_ids, archived_at__isnull=True,
    ).values_list("production_task_id", flat=True).first()
    if task_id is None:
        raise NotFound("采购需求不存在或不在当前账号的数据范围内。")
    # 与新建总单、批次及确认采购统一锁顺序；等待期间对象可能已被删除。
    task = ProductionTask.objects.select_for_update().get(pk=task_id)
    group = PurchaseGroup.objects.select_for_update().filter(
        pk=group_id, production_task_id__in=allowed_task_ids, archived_at__isnull=True,
    ).first()
    if group is None or task.archived_at:
        raise NotFound("采购需求不存在或不在当前账号的数据范围内。")
    require_matching_etag(request, group)
    batches = list(PurchaseOrder.objects.select_for_update().filter(purchase_group=group).order_by("id"))
    batch_ids = [batch.pk for batch in batches]
    list(PurchaseOrderLine.objects.select_for_update().filter(purchase_order_id__in=batch_ids).order_by("id"))
    list(PurchaseGroupLine.objects.select_for_update().filter(purchase_group=group).order_by("id"))
    summary = purchase_group_deletion_summary(purchase_groups_with_context().get(pk=group.pk))
    if not summary["can_delete"]:
        raise Conflict(summary["blocked_reason"])
    before = {
        "group_number": group.group_number, "source_revision": group.source_revision,
        "deleted_draft_batches": [{"id": batch.pk, "order_number": batch.order_number} for batch in batches],
    }
    try:
        PurchaseOrder.objects.filter(pk__in=batch_ids).delete()
        PurchaseGroupLine.objects.filter(purchase_group=group).delete()
        group.delete()
    except ProtectedError as error:
        raise Conflict("采购需求已有其他业务记录引用，不能删除；请刷新后核对。") from error
    write_audit_log(
        object_type="PURCHASE_GROUP", object_id=group_id, action="DELETED",
        context_type="PRODUCTION_TASK", context_id=task_id, actor_employee=actor_employee,
        before_data=before, request=request,
    )


def _json_value(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def source_issues(snapshot):
    issues = []
    if not snapshot.get("source_bom_line_id_snapshot") or not snapshot.get("product_line_id_snapshot"):
        issues.append("SOURCE_ID_MISSING")
    if snapshot.get("required_quantity") is None or Decimal(str(snapshot["required_quantity"])) <= 0:
        issues.append("SUGGESTED_QUANTITY_MISSING")
    if snapshot.get("quantity_parse_status") != "READY":
        issues.append("SUGGESTED_QUANTITY_UNRESOLVED")
    if not str(snapshot.get("source_unit_text") or "").strip():
        issues.append("UNIT_MISSING")
    if snapshot.get("material_catalog_id"):
        try:
            selected = validate_saved_material(snapshot.get("material_selection_snapshot"), material_catalog_id=snapshot["material_catalog_id"])
            pipe = snapshot.get("section_type_snapshot") == "PROFILE"
            hardware = is_hardware_weight_snapshot(snapshot.get("calculation_snapshot"))
            expected_unit = "KG" if (pipe and (snapshot.get("calculation_snapshot") or {}).get("measurement_unit") == "kg") or hardware else ("米" if pipe else selected["unit_name"])
            if expected_unit != snapshot.get("source_unit_text") or (pipe and selected["unit_name"] != "根"):
                issues.append("UNIT_MISMATCH")
            if pipe and not snapshot.get("raw_bar_length_m"):
                issues.append("PIPE_PARAMETERS_MISSING")
        except ValidationError:
            issues.append("MATERIAL_SNAPSHOT_INVALID")
        return issues
    identity = snapshot.get("calculation_snapshot") or {}
    if not isinstance(identity, dict):
        identity = {}
        issues.append("MATERIAL_SNAPSHOT_INVALID")
    try:
        material_id = UUID(str(identity.get("raw_material_id")))
    except (ValueError, TypeError):
        issues.append("MATERIAL_IDENTITY_MISSING")
    else:
        material = RawMaterialInformation.objects.select_related("unit").filter(
            pk=material_id, item_type="MATERIAL", archived_at__isnull=True,
        ).first()
        if material is None:
            issues.append("MATERIAL_IDENTITY_MISSING")
        elif snapshot.get("section_type_snapshot") != "PROFILE" and (
            (not is_hardware_weight_snapshot(identity)
             and snapshot.get("source_unit_text") not in {material.unit.unit_name, material.unit.unit_code})
            or str(identity.get("unit_id") or material.unit_id) != str(material.unit_id)
        ):
            issues.append("UNIT_MISMATCH")
    if snapshot.get("section_type_snapshot") == "PROFILE":
        if not snapshot.get("raw_bar_length_m"):
            issues.append("PIPE_PARAMETERS_MISSING")
        if snapshot.get("source_unit_text") == "KG" and not snapshot.get("raw_bar_weight_kg"):
            issues.append("PIPE_WEIGHT_MISSING")
    return issues


def _save_group_line(group, number, snapshot):
    # 历史采购允许凭已保存的原料编号精确唯一识别；绝不按品名或当前BOM猜配。
    identity = snapshot.get("calculation_snapshot") or {}
    if not isinstance(identity, dict):
        identity = {}
    if "raw_material_id" not in identity and snapshot.get("raw_material_snapshot"):
        matches = list(RawMaterialInformation.objects.filter(
            material_number=snapshot["raw_material_snapshot"],
        ).values("id", "item_type", "archived_at", "unit_id")[:2])
        if len(matches) == 1 and matches[0]["item_type"] == "MATERIAL" and matches[0]["archived_at"] is None:
            snapshot["calculation_snapshot"] = {**identity, "raw_material_id": str(matches[0]["id"]),
                                                 "unit_id": str(matches[0]["unit_id"])}
    return PurchaseGroupLine.objects.create(
        purchase_group=group, line_number=number,
        source_bom_line_id_snapshot=snapshot.get("source_bom_line_id_snapshot"),
        product_line_id_snapshot=snapshot.get("product_line_id_snapshot"),
        required_quantity=snapshot.get("required_quantity"),
        source_unit_text=snapshot.get("source_unit_text", ""),
        source_snapshot=snapshot, compatibility_issues=source_issues(snapshot),
    )


def attach_purchase_order_group(order):
    """兼容旧创建入口；只增加归属，保留订单和所有明细的主键。调用方持任务锁。"""
    if order.source_type != "PRODUCTION" or order.purchase_group_id:
        return order.purchase_group if order.purchase_group_id else None
    lines = list(order.lines.order_by("line_number", "id"))
    product_ids = {line.product_line_id_snapshot for line in lines}
    bom_ids = {line.bom_id for line in lines}
    issues = [] if lines else ["SOURCE_LINES_MISSING"]
    if lines and (len(product_ids) != 1 or None in product_ids):
        issues.append("SOURCE_PRODUCT_AMBIGUOUS")
    if lines and (len(bom_ids) != 1 or None in bom_ids):
        issues.append("SOURCE_BOM_AMBIGUOUS")
    existing = PurchaseGroup.objects.select_for_update().filter(
        production_task=order.production_task,
        product_line_id_snapshot__in=product_ids, archived_at__isnull=True,
        purchase_scope=PurchaseScope.STANDARD,
    ).first()
    if existing is not None:
        if (issues or existing.compatibility_issues or existing.batches.exists()
                or existing.source_bom_id_snapshot not in bom_ids or existing.source_revision != order.source_revision):
            raise Conflict("该产品已有采购需求，不能重建不同来源的采购单。")
        saved_lines = {line.source_bom_line_id_snapshot: line for line in existing.lines.all()}
        if set(saved_lines) != {line.source_bom_line_id_snapshot for line in lines}:
            raise Conflict("原采购需求材料范围已变化，请沿用采购需求快照新增批次。")
        for line in lines:
            saved = saved_lines[line.source_bom_line_id_snapshot]
            snapshot = _json_value({field: getattr(line, field) for field in SOURCE_FIELDS})
            if saved.compatibility_issues or any(snapshot.get(key) != saved.source_snapshot.get(key) for key in SOURCE_FIELDS):
                raise Conflict("原采购需求来源快照已变化，请沿用采购需求快照新增批次。")
            line.purchase_group_line = saved
            line.save(update_fields=["purchase_group_line"])
        order.purchase_group = existing
        order.batch_number = 1
        order.save(update_fields=["purchase_group", "batch_number"])
        existing.save(update_fields=["updated_at"])
        return existing
    group = PurchaseGroup.objects.create(
        group_number="CGZD" + order.order_number[4:], production_task=order.production_task,
        product_line_id_snapshot=next(iter(product_ids)) if len(product_ids) == 1 else None,
        source_bom_id_snapshot=next(iter(bom_ids)) if len(bom_ids) == 1 else None,
        production_task_number_snapshot=order.production_task_number_snapshot,
        sales_order_number_snapshot=order.sales_order_number_snapshot,
        customer_name_snapshot=order.customer_name_snapshot, source_revision=order.source_revision,
        created_by_employee=order.created_by_employee,
        compatibility_issues=issues,
    )
    for line in lines:
        snapshot = _json_value({field: getattr(line, field) for field in SOURCE_FIELDS})
        line.purchase_group_line = _save_group_line(group, line.line_number, snapshot)
        # 兼容归属不改原明细时间戳及履约字段。
        line.save(update_fields=["purchase_group_line"])
    order.purchase_group = group
    order.batch_number = 1
    order.save(update_fields=["purchase_group", "batch_number"])
    return group


def _selected_group_sources(task, revisions, purchase_scope):
    groups = list(PurchaseGroup.objects.filter(
        production_task=task, archived_at__isnull=True, purchase_scope=purchase_scope,
    ).prefetch_related("bom_sources"))
    product_for_bom = {str(p.purchase_source_boms[0].pk): p.pk for p in task.purchase_source_products if p.purchase_source_boms}
    single_groups = defaultdict(list)
    combined_groups = []
    for group in groups:
        if group.product_line_id_snapshot:
            if group.source_bom_id_snapshot:
                product_for_bom[str(group.source_bom_id_snapshot)] = group.product_line_id_snapshot
            single_groups[group.product_line_id_snapshot].append(group)
        else:
            members = {row.product_line_id_snapshot: row for row in group.bom_sources.all()}
            product_for_bom.update({str(row.bom_id_snapshot): pk for pk, row in members.items()})
            combined_groups.append((group, members))
    if revisions.keys() - product_for_bom.keys():
        raise ValidationError({"bom_id": "所选 BOM 不属于该生产订单，或不是当前可用的采购来源。"})
    requested = {product_for_bom[bom_id]: (bom_id, revision) for bom_id, revision in revisions.items()}
    if len(requested) != len(revisions):
        raise ValidationError({"sources": "同一产品只能选择一份采购来源。"})
    for group, members in combined_groups:
        if not requested.keys() & members.keys():
            continue
        if requested.keys() == members.keys() and all(revision == members[pk].source_revision for pk, (_, revision) in requested.items()):
            return group, []
        raise Conflict(f"所选产品已在合并采购需求 {group.group_number} 中，请在该需求中新增批次。")
    selected = []
    for product in task.purchase_source_products:
        if product.pk not in requested:
            continue
        bom_id, revision = requested[product.pk]
        previous_groups = single_groups[product.pk]
        if len(previous_groups) > 1:
            raise Conflict("同一产品存在多份采购需求，请先核对原需求归属。")
        previous = previous_groups[0] if previous_groups else None
        if previous:
            if not previous.source_bom_id_snapshot:
                raise Conflict("已有采购需求缺少已保存的 BOM 归属，请核对原需求。")
            if revision != previous.source_revision:
                raise Conflict("该产品已保存采购需求，请重新读取原需求。")
            if len(requested) == 1:
                return previous, []
            if not product.purchase_source_boms or product.purchase_source_boms[0].status != BomStatus.VERIFIED:
                raise Conflict("请先确认所选产品的最新 BOM，再合并采购需求。")
            bom_id = str(previous.source_bom_id_snapshot)
        selected.append((product, bom_id, revision, previous))
    if len(selected) != len(requested):
        raise Conflict("采购来源的产品已不存在，请核对原采购需求。")
    return None, selected


def _previous_group_snapshots(group, product, components):
    group = purchase_groups_with_context().get(pk=group.pk)
    progress = purchase_group_progress(group)
    if group.manual_completed_at or progress["status"] == "UNKNOWN" or not progress["lines"]:
        raise Conflict(f"采购需求 {group.group_number} 已手动完成或缺少可核实的采购明细。")
    snapshots = []
    for row in progress["lines"]:
        snapshot = dict(row["source_snapshot"])
        if (not snapshot.get("bom_id") or not row["source_bom_line_id_snapshot"]
                or row["product_line_id_snapshot"] != product.pk or source_issues(snapshot)):
            raise Conflict(f"采购需求 {group.group_number} 第 {row['line_number']} 行的原 BOM 或物料身份待核对，无法合并。")
        snapshot.update(bom_line_id=str(row["source_bom_line_id_snapshot"]),
                        previous_group_line_id=str(row["id"]), required_quantity=format(row["required_quantity"], "f"))
        snapshot.setdefault("material_selection_snapshot", {})
        snapshot["material_attributes_snapshot"] = snapshot.get("material_attributes_snapshot") or {}
        snapshot.setdefault("component_identity", components.get(row["source_bom_line_id_snapshot"]))
        snapshot.setdefault("product_color", product.color_name_snapshot)
        if not (snapshot.get("material_attributes_snapshot") or {}).get("fields") and not snapshot["material_selection_snapshot"]:
            raise Conflict(f"采购需求 {group.group_number} 第 {row['line_number']} 行缺少冻结的物料属性，无法核对合并。")
        if snapshot["section_type_snapshot"] == "PROFILE" and snapshot["source_unit_text"] != "KG":
            raise Conflict(f"采购需求 {group.group_number} 仍是旧米制管材，请核对重量采购来源。")
        snapshots.append(snapshot)
    return snapshots


@transaction.atomic
def create_purchase_group(*, validated_data, allowed_task_ids, actor_employee, request=None, purchase_scope=PurchaseScope.STANDARD):
    task = ProductionTask.objects.select_for_update().filter(
        pk=validated_data["production_task_id"], pk__in=allowed_task_ids, archived_at__isnull=True,
    ).first()
    if task is None:
        raise NotFound("生产订单不存在或不在当前账号的数据范围内。")
    list(ProductionTaskProduct.objects.select_for_update().filter(production_task=task).order_by("id"))
    list(Bom.objects.select_for_update().filter(production_task=task).order_by("id"))
    bom_lines = list(BomLine.objects.select_for_update().filter(section__bom__production_task=task).order_by("id"))
    lock_bom_line_material_identities(bom_lines)
    entries = validated_data.get("sources") or [validated_data]
    revisions = {str(entry["bom_id"]): entry["source_revision"] for entry in entries}
    task = production_tasks_with_purchase_sources(ProductionTask.objects.filter(pk=task.pk)).get()
    existing, selected = _selected_group_sources(task, revisions, purchase_scope)
    if existing:
        return existing
    if all(previous for _, _, _, previous in selected) and task.status not in PURCHASABLE_TASK_STATUSES:
        raise Conflict("生产任务当前状态不允许新建采购需求。")
    snapshots = []
    components = {line.pk: str(line.component_identity) for line in bom_lines}
    for product, bom_id, revision, previous in selected:
        if previous:
            snapshots.extend(_previous_group_snapshots(previous, product, components))
            continue
        product_source = copy(task)
        product_source.purchase_source_products = [product]
        source = evaluate_purchase_source(product_source, bom_id=bom_id, purchase_scope=purchase_scope)
        if not source["can_create"]:
            raise PurchaseSourceUnavailable(source["blockers"])
        if revision != source["source_revision"]:
            raise PurchaseSourceChanged(source["source_revision"])
        snapshots.extend(bom_group_line_snapshot(item) for item in source["lines"])
    combined = len(selected) > 1
    group = PurchaseGroup.objects.create(
        group_number="CGZD" + next_purchase_order_number()[4:], production_task=task,
        purchase_scope=purchase_scope,
        product_line_id_snapshot=None if combined else selected[0][0].pk,
        source_bom_id_snapshot=None if combined else selected[0][1],
        production_task_number_snapshot=task.task_number, sales_order_number_snapshot=task.order_number,
        customer_name_snapshot=task.customer_account.account_name if task.customer_account_id else "",
        source_revision=(hashlib.sha256(json.dumps(revisions, sort_keys=True).encode()).hexdigest()
                         if combined else selected[0][2]), created_by_employee=actor_employee,
    )
    PurchaseGroupBomSource.objects.bulk_create([
        PurchaseGroupBomSource(purchase_group=group, product_line_id_snapshot=product.pk,
                               bom_id_snapshot=bom_id, source_revision=revision, previous_group=previous)
        for product, bom_id, revision, previous in selected
    ])
    if combined:
        materials = defaultdict(list)
        for snapshot in snapshots:
            materials[purchase_merge_key(snapshot)].append(snapshot)
        snapshots = [merge_purchase_snapshots(rows) for rows in materials.values()]
    for number, snapshot in enumerate(snapshots, 1):
        _save_bom_snapshot(group, number, snapshot)
    write_audit_log(object_type="PURCHASE_GROUP", object_id=group.pk, context_type="PRODUCTION_TASK",
                    context_id=task.pk, action="CREATED", actor_employee=actor_employee,
                    after_data={"group_number": group.group_number, "source_revision": group.source_revision}, request=request)
    return group


def bom_group_line_snapshot(item):
    snapshot = {key: item[key] for key in (
        "material_catalog_id", "material_selection_snapshot",
        "source_bom_line_id_snapshot", "required_quantity", "source_quantity_field", "source_quantity_text",
        "source_unit_text", "quantity_parse_status", "material_attributes_snapshot",
    )}
    for key in ("bom_number", "product_number", "product_code", "product_name", "product_specification",
                "section_type", "section_title", "category", "material", "part_name", "specification", "raw_material"):
        snapshot[key + "_snapshot"] = item[key]
    snapshot.update(bom_id=item["bom_id"], bom_line_id=item["bom_line_id"], product_line_id_snapshot=item["product_line_id"])
    if "purchase_required" in item["_bom_line"].raw_values:
        snapshot["purchase_required"] = item["_bom_line"].purchase_required
    if item["section_type"] == "PROFILE":
        calculation = pipe_source_snapshot(item["_bom_line"])
        snapshot.update({key: calculation[key] for key in ("raw_bar_length_m", "raw_bar_weight_kg", "suggested_bar_count", "suggested_purchase_meters", "suggested_purchase_weight_kg") if key in calculation})
    else:
        calculation = item.get("calculation_snapshot") or build_purchase_material_snapshot(item["_bom_line"])
    snapshot["calculation_snapshot"] = calculation
    snapshot.update(component_identity=str(item["_bom_line"].component_identity), product_color=item["product_color"])
    return _json_value(snapshot)


def _save_bom_snapshot(group, number, snapshot):
    validate_source_scope(is_packaging_snapshot(snapshot), group.purchase_scope, number)
    line = _save_group_line(group, number, snapshot)
    if line.compatibility_issues:
        raise ValidationError({"lines": f"第{number}行来源建议量、单位或材料身份不完整，请先核对BOM。"})
    return line


def save_bom_group_line(group, number, item):
    return _save_bom_snapshot(group, number, bom_group_line_snapshot(item))


def validate_group_line_source(line):
    """分批采用已保存的总单身份；BOM版本变化不能改写历史采购来源。"""
    source = line.purchase_group_line
    if source.purchase_group_id != line.purchase_order.purchase_group_id:
        raise Conflict("采购批次明细不属于当前采购需求。")
    if source.compatibility_issues:
        raise Conflict("采购需求来源存在待核对项，不能沿用未知来源。")
    combined = bool(line.calculation_snapshot.get("group_source_contributions"))
    if combined:
        if not matches_combined_source(line, source):
            raise Conflict("合并采购的物料、单位或建议量与保存的来源不一致。")
    else:
        if line.source_unit_text != source.source_unit_text or line.required_quantity != source.required_quantity:
            raise Conflict("采购批次单位或建议量与保存的采购需求快照不一致。")
        if material_calculation_snapshot(line.calculation_snapshot) != source.source_snapshot.get("calculation_snapshot", {}):
            raise Conflict("采购批次材料身份或计算参数与采购需求快照不一致。")
    if line.material_catalog_id:
        purchase_catalog_selection(line)
        if not combined and (str(line.material_catalog_id) != str(source.source_snapshot.get("material_catalog_id")) or line.material_selection_snapshot != source.source_snapshot.get("material_selection_snapshot")):
            raise Conflict("采购批次材料与采购需求保存内容不一致。")
        return
    material = resolve_purchase_material(line)
    if line.section_type_snapshot == "PROFILE" and (
        material.unit.unit_name != "根" or material.unit.status != "ACTIVE" or material.unit.archived_at
        or material.category.category_name != "管材" or material.category.status != "ACTIVE" or material.category.archived_at
    ):
        raise Conflict("管材采购缺少有效的根制材料身份。")


def _batch_request_fingerprint(validated_data):
    return hashlib.sha256(json.dumps(validated_data, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()


def _lock_group_for_batch(group_id, allowed_task_ids):
    task_id = PurchaseGroup.objects.filter(pk=group_id, production_task_id__in=allowed_task_ids,
                                           archived_at__isnull=True).values_list("production_task_id", flat=True).first()
    if task_id is None:
        raise NotFound("采购需求不存在或不在当前账号的数据范围内。")
    # 与原采购编辑保持任务→总单→明细的锁顺序；批次序号和幂等键在同一事务产生。
    task = ProductionTask.objects.select_for_update().get(pk=task_id)
    if task.archived_at:
        raise NotFound("生产订单已归档。")
    group = PurchaseGroup.objects.select_for_update().filter(pk=group_id, archived_at__isnull=True).first()
    if group is None:
        raise NotFound("采购需求不存在或已删除，请重新选择。")
    return task, group


@transaction.atomic
def create_purchase_batch(*, group_id, validated_data, allowed_task_ids, actor_employee, request=None, group_version_checked=False):
    task, group = _lock_group_for_batch(group_id, allowed_task_ids)
    fingerprint = _batch_request_fingerprint(validated_data)
    existing = group.batches.filter(batch_request_id=validated_data["request_id"]).first()
    if existing:
        if existing.batch_request_fingerprint != fingerprint:
            raise Conflict("同一请求编号不能用于不同的采购批次内容。")
        if existing.archived_at:
            raise Conflict("该请求创建的采购批次已归档，请使用新的请求编号。")
        return purchase_orders_with_context().get(pk=existing.pk), False
    destination = group.combined_into_sources.filter(purchase_group__archived_at__isnull=True).select_related("purchase_group").first()
    if destination:
        raise Conflict(f"该产品已合并采购，请在采购需求 {destination.purchase_group.group_number} 中新增批次。")
    if task.status not in PURCHASABLE_TASK_STATUSES:
        raise Conflict("生产任务当前状态不允许新增采购批次。")
    if group.compatibility_issues:
        raise Conflict("采购需求来源归属存在待核对项，不能新增批次。")
    if not group_version_checked:
        require_matching_etag(request, group)
    source_lines = {str(line.pk): line for line in group.lines.select_for_update().order_by("id")}
    inputs = validated_data["lines"]
    ids = [str(item["purchase_group_line_id"]) for item in inputs]
    if len(ids) != len(set(ids)) or not set(ids).issubset(source_lines):
        raise ValidationError({"lines": "批次材料必须属于当前采购需求，且不能重复。"})
    inputs = [item for item in inputs if item.get("set_pricing")
              or (item.get("actual_purchase_quantity") != 0 and item.get("unit_price") != 0)]
    ids = [str(item["purchase_group_line_id"]) for item in inputs]
    if not inputs:
        raise ValidationError({"lines": "采购批次至少选择一项材料。"})
    for identifier in ids:
        source = source_lines[identifier]
        snapshot = source.source_snapshot
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("calculation_snapshot", {}), dict):
            raise Conflict(f"第{source.line_number}项历史来源待核对，不能创建批次。")
        if snapshot.get("purchase_required") is False:
            raise ValidationError({"lines": "所选材料已改为外供，请重新读取采购需求。"})
        validate_source_scope(is_packaging_snapshot(snapshot), group.purchase_scope, source.line_number)
        if snapshot.get("section_type_snapshot") != "PROFILE":
            continue
        calculation = snapshot.get("calculation_snapshot") or {}
        if source.source_unit_text != "KG" or not isinstance(calculation, dict) or calculation.get("measurement_unit") != "kg":
            raise Conflict("旧米制管材采购需求不能新建采购批次，请先补齐 BOM 长料单重并建立重量采购来源。")
        try:
            weight = decimal_quantity(snapshot.get("raw_bar_weight_kg"), "raw_bar_weight_kg")
            saved_weight = decimal_quantity(calculation.get("raw_bar_weight_kg"), "raw_bar_weight_kg")
        except MaterialFlowValueError as error:
            raise Conflict("管材采购需求缺少有效长料单重，不能新建采购批次。") from error
        if weight != saved_weight:
            raise Conflict("管材采购需求长料单重与保存的计算依据不一致，请先核对来源。")
    lock_bom_line_material_identities([], extra_raw_material_ids=[
        source_lines[key].source_snapshot.get("calculation_snapshot", {}).get("raw_material_id") for key in ids
    ])
    currency = Currency.objects.select_for_update().filter(pk=validated_data["currency_id"],
        status=ReferenceStatus.ACTIVE, archived_at__isnull=True).first()
    if currency is None:
        raise ValidationError({"currency_id": "采购币种不存在或已停用。"})
    supplier_ids = {item.get("supplier_id") for item in inputs if item.get("supplier_id")}
    suppliers = {str(row.pk): row for row in Supplier.objects.select_for_update(no_key=True).filter(
        pk__in=supplier_ids, archived_at__isnull=True, is_disabled=False)}
    if {str(pk) for pk in supplier_ids} - set(suppliers):
        raise ValidationError({"lines": "采购明细包含不存在、禁用或归档的供应商。"})
    batch_session_id = validated_data.get("batch_session_id")
    current_batch, next_batch = purchase_group_batch_numbers(group.pk, batch_session_id)
    order = PurchaseOrder.objects.create(
        purchase_group=group, batch_number=current_batch or next_batch, batch_session_id=batch_session_id,
        batch_type=validated_data["batch_type"], batch_request_id=validated_data["request_id"],
        batch_request_fingerprint=fingerprint, order_number=next_purchase_order_number(),
        production_task=task, production_task_number_snapshot=group.production_task_number_snapshot,
        sales_order_number_snapshot=group.sales_order_number_snapshot, customer_name_snapshot=group.customer_name_snapshot,
        source_revision=group.source_revision, currency=currency, currency_code_snapshot=currency.code,
        currency_name_snapshot=currency.chinese_name, currency_symbol_snapshot=currency.symbol,
        created_by_employee=actor_employee,
    )
    created_lines = []
    for number, item in enumerate(inputs, 1):
        source = source_lines[str(item["purchase_group_line_id"])]
        if source.compatibility_issues:
            raise Conflict(f"第{source.line_number}项历史来源待核对，不能创建批次。")
        values = {key: value for key, value in source.source_snapshot.items() if key in SOURCE_FIELDS}
        # BOM编辑可删除旧行；稳定来源ID及材料身份仍取保存快照，不重绑新BOM行。
        if values.get("bom_line_id") and not BomLine.objects.filter(pk=values["bom_line_id"]).exists():
            values["bom_line_id"] = None
        quantity = item.get("actual_purchase_quantity")
        if values.get("raw_bar_length_m"):
            values.update(purchase_pipe_values(values["calculation_snapshot"], item))
            quantity = physical_pipe_quantity(values["calculation_snapshot"], item, values)
        _validate_hardware_actual_weight(values.get("calculation_snapshot"), item, quantity)
        if quantity is None or quantity <= 0:
            raise ValidationError({"lines": "所选材料必须填写正数采购数量；管材填写根数。"})
        supplier = suppliers.get(str(item.get("supplier_id")))
        price = item.get("unit_price")
        price_quantity = priced_quantity(section_type=values["section_type_snapshot"], material_catalog_id=values.get("material_catalog_id"), physical_quantity=quantity, pipe_values=values)
        amount = _money(price_quantity * price) if price is not None and price_quantity is not None else None
        line = PurchaseOrderLine(purchase_order=order, purchase_group_line=source, line_number=number,
            **values, supplier=supplier, supplier_number_snapshot=supplier.supplier_number if supplier else "",
            supplier_name_snapshot=supplier.supplier_name if supplier else "",
            supplier_type_snapshot=supplier.supplier_type if supplier else "",
            supplier_categories_snapshot=list(supplier.supplier_categories) if supplier else [],
            delivery_date=item.get("delivery_date"), actual_purchase_quantity=quantity, unit_price=price, amount=amount)
        # Decimal/UUID字段在JSON中为字符串，加载模型字段转换后进行一致性校验。
        line.required_quantity = source.required_quantity
        validate_group_line_source(line)
        if contributions := source.source_snapshot.get("source_contributions"):
            line.calculation_snapshot = {**line.calculation_snapshot, "group_source_contributions": [
                {key: value for key, value in row.items() if key != "source_snapshot"} for row in contributions
            ]}
        apply_set_pricing(line, item)
        line.save()
        created_lines.append(line)
    validate_set_members(created_lines)
    amounts = [line.amount for line in created_lines]
    if all(amount is not None for amount in amounts):
        order.total_amount = _money(sum(amounts, Decimal("0")))
        order.save(update_fields=["total_amount", "updated_at"])
    group.save(update_fields=["updated_at"])
    order = purchase_orders_with_context().get(pk=order.pk)
    write_audit_log(object_type="PURCHASE_ORDER", object_id=order.pk, context_type="PRODUCTION_TASK",
                    context_id=task.pk, action="CREATED", actor_employee=actor_employee,
                    after_data=purchase_order_snapshot(order), request=request)
    return order, True


def _confirm_orders_with_default_sheets(order_ids, allowed_task_ids, actor_employee, request):
    from .purchase_sheet_services import (
        active_purchase_sheet_template_versions, generate_supplier_purchase_sheets, recommended_purchase_sheet_template,
    )

    versions = active_purchase_sheet_template_versions()
    if not versions:
        raise ValidationError({"template": "暂无可用采购合同模板，请先在合同模板管理中启用模板。"})
    confirmed = []
    for order_id in order_ids:
        order = confirm_purchase_order(
            order_id=order_id, allowed_task_ids=allowed_task_ids, actor_employee=actor_employee, request=request,
        )
        suppliers = {line.supplier_id: line.supplier_categories_snapshot for line in order.lines.all()}
        assignments = [{
            "supplier_id": supplier_id,
            "template_version_id": (recommended_purchase_sheet_template(versions, categories) or versions[0]).pk,
        } for supplier_id, categories in suppliers.items()]
        generate_supplier_purchase_sheets(
            order_id=order.pk, assignments=assignments,
            allowed_task_ids=allowed_task_ids, actor_employee=actor_employee, request=request,
        )
        confirmed.append(order)
    return confirmed


@transaction.atomic
def submit_supplier_purchase_batch(*, group_id, validated_data, allowed_task_ids, actor_employee, request):
    order, created = create_purchase_batch(
        group_id=group_id, validated_data={**validated_data, "supplier_submission": True},
        allowed_task_ids=allowed_task_ids, actor_employee=actor_employee, request=request,
    )
    if created and not validated_data.get("save_as_draft"):
        order, = _confirm_orders_with_default_sheets([order.pk], allowed_task_ids, actor_employee, request)
    return order, purchase_groups_with_context().get(pk=group_id), created


@transaction.atomic
def confirm_purchase_batch_page(*, group_id, validated_data, allowed_task_ids, actor_employee, request):
    _, group = _lock_group_for_batch(group_id, allowed_task_ids)
    session_id = validated_data["batch_session_id"]
    additional = validated_data.get("additional")
    if additional:
        additional = {**additional, "batch_session_id": session_id}
    orders = group.batches.filter(batch_session_id=session_id, archived_at__isnull=True)
    pending_ids = list(orders.filter(status=PurchaseOrderStatus.DRAFT).order_by("id").values_list("pk", flat=True))
    confirmed = orders.exclude(status=PurchaseOrderStatus.DRAFT)
    if not pending_ids and not additional and confirmed.exists():
        return purchase_groups_with_context().get(pk=group_id)
    if not pending_ids and additional:
        previous = confirmed.filter(batch_request_id=additional["request_id"]).first()
        if previous:
            if previous.batch_request_fingerprint != _batch_request_fingerprint(additional):
                raise Conflict("同一请求编号不能用于不同的采购批次内容。")
            return purchase_groups_with_context().get(pk=group_id)

    require_matching_etag(request, group)
    if additional:
        order, _ = create_purchase_batch(
            group_id=group_id, validated_data=additional,
            allowed_task_ids=allowed_task_ids, actor_employee=actor_employee, request=request,
        )
        if order.status == PurchaseOrderStatus.DRAFT and order.pk not in pending_ids:
            pending_ids.append(order.pk)
    if not pending_ids:
        raise Conflict("本批暂无待确认采购，请先按供应商保存。")
    _confirm_orders_with_default_sheets(pending_ids, allowed_task_ids, actor_employee, request)
    group.save(update_fields=["updated_at"])
    return purchase_groups_with_context().get(pk=group_id)
